from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.brands.models import Brand
from apps.content.models import ContentItem
from apps.gemini.models import GeminiGenerationRequest, GeminiGenerationResult
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

from .models import AutopilotPolicy, AutopilotRun
from .admin import AutopilotPolicyAdmin
from .services import (
    QUEUED_STALE_AFTER,
    RUNNING_STALE_AFTER,
    WAITING_GENERATION_DEADLINE,
    create_run,
    emergency_stop,
    enqueue_due_autopilot_runs,
    execute_run,
    sweep_stalled_autopilot_runs,
)

User = get_user_model()


class AutopilotTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='auto-1', workspace_name='One'
        )
        self.other = MarketingWorkspace.objects.create(
            customer_id='auto-2', workspace_name='Two'
        )
        self.user = User.objects.create_user(username='auto-admin', password='p')
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=self.user, role=WorkspaceMember.Role.ADMIN
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Brand', is_default=True,
            audience='Founders', brand_tone='Clear',
        )
        self.policy = AutopilotPolicy.objects.create(
            workspace=self.workspace,
            brand=self.brand,
            name='Weekly authority',
            objective='Explain one useful operating principle',
            mode=AutopilotPolicy.Mode.APPROVAL_REQUIRED,
            allowed_formats=['POSTER', 'VIDEO'],
            daily_generation_limit=2,
            enabled=True,
            created_by=self.user,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.pk)}

    def test_admin_can_trigger_an_enabled_policy(self):
        response = self.client.post(
            f'/api/marketing/autopilot/policies/{self.policy.pk}/trigger/',
            {}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 202, response.json())
        run = AutopilotRun.objects.get()
        self.assertEqual(run.workspace, self.workspace)
        self.assertTrue(run.task_id)
        self.assertEqual(run.policy_snapshot['objective'], self.policy.objective)

    def test_admin_can_create_then_trigger_a_guided_policy(self):
        created = self.client.post(
            '/api/marketing/autopilot/policies/',
            {
                'brand': str(self.brand.pk),
                'name': 'Brand guided growth',
                'objective': 'Create useful content for founders',
                'campaign_brief': 'Use Brand Master facts and keep the work original.',
                'mode': AutopilotPolicy.Mode.APPROVAL_REQUIRED,
                'allowed_formats': ['POSTER'],
                'daily_generation_limit': 1,
                'monthly_spend_cap': '0',
                'enabled': True,
            },
            format='json', **self.headers,
        )
        self.assertEqual(created.status_code, 201, created.json())

        triggered = self.client.post(
            f"/api/marketing/autopilot/policies/{created.json()['id']}/trigger/",
            {}, format='json', **self.headers,
        )
        self.assertEqual(triggered.status_code, 202, triggered.json())
        run = AutopilotRun.objects.get(policy_id=created.json()['id'])
        self.assertEqual(run.workspace, self.workspace)
        self.assertEqual(run.policy.brand, self.brand)
        self.assertTrue(run.task_id)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_trigger_records_queue_enqueue_failure_honestly(self, task):
        self.policy.daily_generation_limit = 1
        self.policy.save(update_fields=['daily_generation_limit', 'updated_at'])
        task.enqueue.side_effect = RuntimeError('queue unavailable')
        response = self.client.post(
            f'/api/marketing/autopilot/policies/{self.policy.pk}/trigger/',
            {}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 503, response.json())
        self.assertEqual(response.json()['error']['code'], 'QUEUE_ENQUEUE_FAILED')
        run = AutopilotRun.objects.get()
        self.assertEqual(run.status, AutopilotRun.Status.FAILED)
        self.assertEqual(run.error_code, 'QUEUE_ENQUEUE_FAILED')
        self.assertTrue(run.completed_at)
        self.assertEqual(run.task_id, '')
        self.assertEqual(run.steps.get(key='finish').status, 'FAILED')

        task.enqueue.side_effect = None
        task.enqueue.return_value.id = 'retry-task-id'
        retried = self.client.post(
            f'/api/marketing/autopilot/policies/{self.policy.pk}/trigger/',
            {}, format='json', **self.headers,
        )
        self.assertEqual(retried.status_code, 202, retried.json())
        retry_run = AutopilotRun.objects.exclude(pk=run.pk).get()
        self.assertEqual(retry_run.task_id, 'retry-task-id')

    def test_viewer_cannot_create_or_trigger_policy(self):
        membership = WorkspaceMember.objects.get(workspace=self.workspace, user=self.user)
        membership.role = WorkspaceMember.Role.VIEWER
        membership.save(update_fields=['role'])
        response = self.client.post(
            f'/api/marketing/autopilot/policies/{self.policy.pk}/trigger/',
            {}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_cross_tenant_brand_and_channel_are_rejected(self):
        other_brand = Brand.objects.create(workspace=self.other, name='Other')
        other_connection = SocialConnection.objects.create(
            workspace=self.other,
            platform=SocialConnection.Platform.X,
            external_account_id='other-x',
            account_name='Other X',
        )
        response = self.client.post(
            '/api/marketing/autopilot/policies/',
            {
                'brand': str(other_brand.pk),
                'name': 'Bad', 'objective': 'Bad', 'enabled': True,
                'allowed_formats': ['POSTER'],
                'social_connections': [str(other_connection.pk)],
            },
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AutopilotPolicy.objects.count(), 1)

    def test_cross_tenant_channel_is_rejected_on_direct_orm_path(self):
        other_connection = SocialConnection.objects.create(
            workspace=self.other,
            platform=SocialConnection.Platform.X,
            external_account_id='other-direct-x',
            account_name='Other direct X',
        )
        with self.assertRaises(ValidationError), transaction.atomic():
            self.policy.social_connections.add(other_connection)
        self.assertFalse(self.policy.social_connections.exists())

    def test_django_admin_is_observability_only(self):
        model_admin = AutopilotPolicyAdmin(AutopilotPolicy, admin.site)
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None, self.policy))
        self.assertFalse(model_admin.has_delete_permission(None, self.policy))

    def test_auto_publish_is_not_an_available_mode(self):
        response = self.client.post(
            '/api/marketing/autopilot/policies/',
            {
                'brand': str(self.brand.pk),
                'name': 'Unsafe', 'objective': 'Publish without review',
                'mode': 'AUTO_PUBLISH', 'enabled': True,
                'allowed_formats': ['POSTER'],
            },
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_run_queues_existing_generation_then_waits_for_review(self):
        run = create_run(self.policy, initiated_by=self.user)

        first = execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(first['status'], AutopilotRun.Status.WAITING_GENERATION)
        self.assertEqual(run.generation_request.workspace, self.workspace)
        self.assertIn('autopilot', run.generation_request.prompt_data)

        content = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand, status=ContentItem.Status.DRAFT
        )
        generation = run.generation_request
        generation.status = GeminiGenerationRequest.Status.COMPLETED
        generation.save(update_fields=['status'])
        GeminiGenerationResult.objects.create(
            generation_request=generation,
            metadata={'contentItemId': str(content.pk)},
        )
        second = execute_run(run.pk)
        run.refresh_from_db()
        content.refresh_from_db()
        self.assertEqual(second['status'], AutopilotRun.Status.WAITING_REVIEW)
        self.assertEqual(content.status, ContentItem.Status.PENDING_REVIEW)
        self.assertIsNone(run.completed_at)

    def test_emergency_stop_stops_pending_work(self):
        run = create_run(self.policy, initiated_by=self.user)
        policy = emergency_stop(self.policy, by=self.user)
        run.refresh_from_db()
        self.assertTrue(policy.emergency_stop)
        self.assertTrue(policy.paused)
        self.assertEqual(run.status, AutopilotRun.Status.STOPPED)
        self.assertEqual(run.error_code, 'EMERGENCY_STOP')

    def test_run_is_linked_and_waiting_before_generation_enqueues(self):
        """The follow-up race: a generation finishing before the run row
        carries its FK and WAITING_GENERATION status loses the follow-up
        forever. The link must therefore be durable before enqueue."""
        run = create_run(self.policy, initiated_by=self.user)
        seen = {}

        def capture(generation_id):
            row = AutopilotRun.objects.get(pk=run.pk)
            seen['status'] = row.status
            seen['generation_id'] = str(row.generation_request_id)

            class _Result:
                id = 'task-under-test'

            return _Result()

        with patch('apps.gemini.tasks.generate_content') as task:
            task.enqueue.side_effect = capture
            execute_run(run.pk)

        self.assertEqual(seen['status'], AutopilotRun.Status.WAITING_GENERATION)
        run.refresh_from_db()
        self.assertEqual(seen['generation_id'], str(run.generation_request_id))
        self.assertEqual(run.task_id, 'task-under-test')


class AutopilotSweepTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='sweep-1', workspace_name='Sweep'
        )
        self.user = User.objects.create_user(username='sweep-admin', password='p')
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=self.user, role=WorkspaceMember.Role.ADMIN
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Brand', is_default=True,
            audience='Founders', brand_tone='Clear',
        )
        self.policy = AutopilotPolicy.objects.create(
            workspace=self.workspace, brand=self.brand, name='Sweep policy',
            objective='Objective', enabled=True, created_by=self.user,
            allowed_formats=['POSTER'],
        )

    def _waiting_run(self, *, checked_ago_seconds=120, started_ago_seconds=300):
        now = timezone.now()
        generation = GeminiGenerationRequest.objects.create(
            workspace=self.workspace, user=self.user, prompt_data='{}',
            status=GeminiGenerationRequest.Status.GENERATING,
        )
        run = create_run(self.policy, initiated_by=self.user)
        AutopilotRun.objects.filter(pk=run.pk).update(
            status=AutopilotRun.Status.WAITING_GENERATION,
            generation_request=generation,
            started_at=now - timedelta(seconds=started_ago_seconds),
            next_check_at=now - timedelta(seconds=checked_ago_seconds),
        )
        run.refresh_from_db()
        return run

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_sweep_redrives_a_due_waiting_run_exactly_once(self, task):
        run = self._waiting_run()
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        task.enqueue.assert_called_once_with(str(run.pk))
        run.refresh_from_db()
        # Still WAITING_GENERATION — the sweep re-drives, it never advances
        # state itself — with next_check_at pushed into the future as the claim.
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_GENERATION)
        self.assertGreater(run.next_check_at, timezone.now())
        # The pushed next_check_at is the CAS: an immediate second sweep
        # (a second worker on the same tick) claims nothing.
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        task.enqueue.assert_called_once()

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_sweep_ignores_runs_not_yet_due(self, task):
        run = self._waiting_run(checked_ago_seconds=-300)
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        task.enqueue.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_GENERATION)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_deadline_never_discards_a_finished_generation(self, task):
        """A >2h wait whose generation actually COMPLETED (worker outage ate
        the follow-up) must be re-driven so the paid draft lands — failing it
        would tell the user to buy the same work twice."""
        run = self._waiting_run(
            started_ago_seconds=int(WAITING_GENERATION_DEADLINE.total_seconds()) + 60
        )
        generation = run.generation_request
        generation.status = GeminiGenerationRequest.Status.COMPLETED
        generation.save(update_fields=['status'])
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        task.enqueue.assert_called_once_with(str(run.pk))
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_GENERATION)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_redrive_advances_even_when_a_cap_was_crossed_mid_wait(self, task):
        """Caps gate new spend. A re-driven run whose generation is already
        paid for must link its draft even if the daily limit filled up while
        it waited."""
        run = self._waiting_run()
        self.policy.daily_generation_limit = 1
        self.policy.save(update_fields=['daily_generation_limit', 'updated_at'])
        # A sibling run consumes the whole daily limit while run #1 waits.
        create_run(self.policy, initiated_by=self.user)
        generation = run.generation_request
        content = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand,
            status=ContentItem.Status.DRAFT,
        )
        generation.status = GeminiGenerationRequest.Status.COMPLETED
        generation.save(update_fields=['status'])
        GeminiGenerationResult.objects.create(
            generation_request=generation,
            metadata={'contentItemId': str(content.pk)},
        )
        execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_REVIEW)
        self.assertEqual(run.content_item, content)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_sweep_fails_a_wait_past_the_deadline_without_respend(self, task):
        run = self._waiting_run(
            started_ago_seconds=int(WAITING_GENERATION_DEADLINE.total_seconds()) + 60
        )
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        task.enqueue.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.FAILED)
        self.assertEqual(run.error_code, 'GENERATION_STUCK')
        self.assertTrue(run.completed_at)
        self.assertEqual(run.steps.get(key='finish').status, 'FAILED')

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_lost_enqueue_leaves_the_retry_timer_armed(self, task):
        run = self._waiting_run()
        task.enqueue.side_effect = RuntimeError('queue unavailable')
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_GENERATION)
        # next_check_at was pushed by the claim, so the next pass retries.
        self.assertGreater(run.next_check_at, timezone.now())

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_sweep_redrives_a_queued_run_whose_task_died(self, task):
        """The stranding found live in production: the durable task crashed
        out of all its attempts (a Postgres-only locking bug) leaving the run
        QUEUED forever. QUEUED proves nothing was spent, so re-driving is
        free; the CAS on updated_at re-drives once per interval."""
        run = create_run(self.policy, initiated_by=self.user)
        stale = timezone.now() - QUEUED_STALE_AFTER - timedelta(minutes=1)
        AutopilotRun.objects.filter(pk=run.pk).update(updated_at=stale)
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        task.enqueue.assert_called_once_with(str(run.pk))
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.QUEUED)
        # Claimed: updated_at moved, so an immediate second sweep is a no-op.
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        task.enqueue.assert_called_once()

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_sweep_leaves_a_fresh_queued_run_alone(self, task):
        create_run(self.policy, initiated_by=self.user)
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        task.enqueue.assert_not_called()

    def test_sweep_fails_a_run_abandoned_mid_execute(self):
        run = create_run(self.policy, initiated_by=self.user)
        stale = timezone.now() - RUNNING_STALE_AFTER - timedelta(minutes=1)
        AutopilotRun.objects.filter(pk=run.pk).update(
            status=AutopilotRun.Status.RUNNING, started_at=stale, updated_at=stale
        )
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.FAILED)
        self.assertEqual(run.error_code, 'RUN_INTERRUPTED')
        self.assertIsNone(run.next_check_at)

    def test_sweep_leaves_a_live_running_run_alone(self):
        run = create_run(self.policy, initiated_by=self.user)
        AutopilotRun.objects.filter(pk=run.pk).update(
            status=AutopilotRun.Status.RUNNING
        )
        self.assertEqual(sweep_stalled_autopilot_runs(), 0)
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.RUNNING)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_swept_run_advances_when_its_generation_actually_finished(self, task):
        """End to end: follow-up lost, sweep re-drives, execute advances."""
        run = self._waiting_run()
        generation = run.generation_request
        content = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand,
            status=ContentItem.Status.DRAFT,
        )
        generation.status = GeminiGenerationRequest.Status.COMPLETED
        generation.save(update_fields=['status'])
        GeminiGenerationResult.objects.create(
            generation_request=generation,
            metadata={'contentItemId': str(content.pk)},
        )
        self.assertEqual(sweep_stalled_autopilot_runs(), 1)
        # The sweep only enqueues; running the queued work is execute_run.
        execute_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, AutopilotRun.Status.WAITING_REVIEW)
        self.assertEqual(run.content_item, content)

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_generation_sweep_terminal_branches_queue_the_followup(self, task):
        """A generation completed or finally failed by gemini's own sweep must
        still wake the run waiting on it."""
        from apps.gemini.tasks import sweep_stuck_generations

        run = self._waiting_run()
        generation = run.generation_request
        GeminiGenerationResult.objects.create(
            generation_request=generation, metadata={}
        )
        stale = timezone.now() - timedelta(hours=1)
        GeminiGenerationRequest.objects.filter(pk=generation.pk).update(updated_at=stale)
        self.assertEqual(sweep_stuck_generations(), 1)
        task.enqueue.assert_called_once_with(str(run.pk))


class AutopilotScheduleTests(TestCase):
    """The due-policy sweep: cadence, slot math, CAS claims and honesty."""

    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='sched-1', workspace_name='Sched'
        )
        self.user = User.objects.create_user(username='sched-admin', password='p')
        WorkspaceMember.objects.create(
            workspace=self.workspace, user=self.user, role=WorkspaceMember.Role.ADMIN
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Brand', is_default=True,
            audience='Founders', brand_tone='Clear',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.headers = {'HTTP_X_WORKSPACE_ID': str(self.workspace.pk)}

    def _policy(self, *, name, cadence=AutopilotPolicy.Cadence.DAILY, due=None,
                enabled=True, **overrides):
        policy = AutopilotPolicy.objects.create(
            workspace=self.workspace, brand=self.brand, name=name,
            objective='Objective', enabled=enabled, created_by=self.user,
            allowed_formats=['POSTER'], cadence=cadence, **overrides,
        )
        if due is not None:
            # Backdate through the queryset: save() would re-arm a past slot.
            AutopilotPolicy.objects.filter(pk=policy.pk).update(next_run_at=due)
            policy.refresh_from_db()
        return policy

    def test_saving_a_scheduled_policy_arms_next_run_one_interval_out(self):
        before = timezone.now()
        policy = self._policy(name='Armed daily')
        after = timezone.now()
        self.assertIsNotNone(policy.next_run_at)
        self.assertGreaterEqual(policy.next_run_at, before + timedelta(days=1))
        self.assertLessEqual(policy.next_run_at, after + timedelta(days=1))
        # Creating a schedule never creates a run by itself.
        self.assertEqual(AutopilotRun.objects.count(), 0)

    def test_switching_back_to_manual_disarms_the_schedule(self):
        policy = self._policy(name='Back to manual')
        policy.cadence = AutopilotPolicy.Cadence.MANUAL
        # update_fields without next_run_at is the repo's save idiom; save()
        # must widen it or the disarm would silently not persist.
        policy.save(update_fields=['cadence', 'updated_at'])
        policy.refresh_from_db()
        self.assertIsNone(policy.next_run_at)

    def test_due_daily_policy_creates_exactly_one_scheduled_run(self):
        due = timezone.now() - timedelta(hours=1)
        policy = self._policy(name='Due daily', due=due)
        self.assertEqual(enqueue_due_autopilot_runs(), 1)
        run = AutopilotRun.objects.get(policy=policy)
        self.assertEqual(run.dedupe_key, f'sched:{policy.pk}:{due.isoformat()}')
        self.assertEqual(run.scheduled_for, due)
        self.assertEqual(run.status, AutopilotRun.Status.QUEUED)
        self.assertTrue(run.task_id)
        self.assertIsNone(run.initiated_by)
        policy.refresh_from_db()
        self.assertEqual(policy.next_run_at, due + timedelta(days=1))
        self.assertGreater(policy.next_run_at, timezone.now())

    def test_overdue_policy_catches_up_without_a_backfill_burst(self):
        due = timezone.now() - timedelta(days=3, hours=1)
        policy = self._policy(name='Overdue daily', due=due)
        self.assertEqual(enqueue_due_autopilot_runs(), 1)
        self.assertEqual(AutopilotRun.objects.filter(policy=policy).count(), 1)
        policy.refresh_from_db()
        # Missed slots are skipped, never replayed: the schedule lands on the
        # first slot in the future.
        self.assertEqual(policy.next_run_at, due + 4 * timedelta(days=1))
        self.assertGreater(policy.next_run_at, timezone.now())

    def test_weekly_interval_math(self):
        due = timezone.now() - timedelta(hours=2)
        policy = self._policy(
            name='Due weekly', cadence=AutopilotPolicy.Cadence.WEEKLY, due=due
        )
        self.assertEqual(enqueue_due_autopilot_runs(), 1)
        policy.refresh_from_db()
        self.assertEqual(policy.next_run_at, due + timedelta(days=7))
        run = AutopilotRun.objects.get(policy=policy)
        self.assertEqual(run.dedupe_key, f'sched:{policy.pk}:{due.isoformat()}')

    def test_manual_disabled_paused_and_stopped_policies_are_untouched(self):
        due = timezone.now() - timedelta(hours=1)
        untouched = [
            self._policy(name='Manual', cadence=AutopilotPolicy.Cadence.MANUAL, due=due),
            self._policy(name='Disabled', enabled=False, due=due),
            self._policy(name='Paused', paused=True, due=due),
            self._policy(name='Stopped', emergency_stop=True, due=due),
        ]
        self.assertEqual(enqueue_due_autopilot_runs(), 0)
        self.assertEqual(AutopilotRun.objects.count(), 0)
        for policy in untouched:
            policy.refresh_from_db()
            self.assertEqual(policy.next_run_at, due, policy.name)

    def test_double_sweep_same_instant_creates_one_run(self):
        due = timezone.now() - timedelta(minutes=30)
        policy = self._policy(name='Raced daily', due=due)
        now = timezone.now()
        self.assertEqual(enqueue_due_autopilot_runs(now=now), 1)
        self.assertEqual(enqueue_due_autopilot_runs(now=now), 0)
        self.assertEqual(AutopilotRun.objects.filter(policy=policy).count(), 1)

    def test_cas_claim_blocks_a_stale_worker(self):
        """Pins the PRODUCTION claim, not a reimplementation: _claim_due_slot
        must refuse a slot whose next_run_at another worker already moved.
        Losing the conditional filter fails this test even though the dedupe
        constraint would still protect the money."""
        from .services import _claim_due_slot

        due = timezone.now() - timedelta(minutes=30)
        policy = self._policy(name='CAS daily', due=due)
        now = timezone.now()
        # Winner claims with the value it read.
        self.assertEqual(
            _claim_due_slot(policy.pk, due, due + timedelta(days=1), now), 1
        )
        # Loser read the same due slot but the row has moved on: zero rows.
        self.assertEqual(
            _claim_due_slot(policy.pk, due, due + timedelta(days=1), now), 0
        )
        policy.refresh_from_db()
        self.assertEqual(policy.next_run_at, due + timedelta(days=1))

    def test_a_crash_after_the_claim_rolls_the_slot_back(self):
        """Claim and create commit together: a failure between them must not
        advance the schedule with no run to show for it — the next tick
        retries the slot instead of losing it silently."""
        due = timezone.now() - timedelta(minutes=30)
        policy = self._policy(name='Crashy daily', due=due)
        with patch(
            'apps.autopilot.services.create_run',
            side_effect=RuntimeError('db blip'),
        ):
            self.assertEqual(enqueue_due_autopilot_runs(), 0)
        policy.refresh_from_db()
        self.assertEqual(policy.next_run_at, due)  # claim rolled back
        self.assertEqual(AutopilotRun.objects.count(), 0)
        # The next pass succeeds normally.
        self.assertEqual(enqueue_due_autopilot_runs(), 1)

    def test_changing_cadence_rearms_a_future_slot(self):
        """DAILY→WEEKLY must not leave tomorrow's daily slot armed to buy a
        generation on the schedule the user just slowed down."""
        policy = self._policy(name='Slowed down')
        daily_slot = policy.next_run_at
        policy.cadence = AutopilotPolicy.Cadence.WEEKLY
        policy.save(update_fields=['cadence', 'updated_at'])
        policy.refresh_from_db()
        self.assertGreater(policy.next_run_at, daily_slot + timedelta(days=5))

    def test_unrelated_edit_rearms_a_past_due_slot_by_design(self):
        """Accepted semantics, pinned: any save of a policy whose slot is
        already past re-arms one interval out — editing a policy never spends
        immediately, even when the edit was only a rename during a worker
        outage. The missed slot is skipped, not queued."""
        due = timezone.now() - timedelta(hours=2)
        policy = self._policy(name='Renamed while due', due=due)
        policy.name = 'Renamed while due (v2)'
        policy.save(update_fields=['name', 'updated_at'])
        policy.refresh_from_db()
        self.assertGreater(policy.next_run_at, timezone.now())
        self.assertEqual(AutopilotRun.objects.count(), 0)

    def test_duplicate_dedupe_key_is_treated_as_already_created(self):
        due = timezone.now() - timedelta(minutes=30)
        policy = self._policy(name='Deduped daily', due=due)
        AutopilotRun.objects.create(
            workspace=self.workspace, policy=policy, scheduled_for=due,
            dedupe_key=f'sched:{policy.pk}:{due.isoformat()}',
        )
        # No exception, nothing new created, and the schedule still advances
        # so the slot is not retried forever.
        self.assertEqual(enqueue_due_autopilot_runs(), 0)
        self.assertEqual(AutopilotRun.objects.filter(policy=policy).count(), 1)
        policy.refresh_from_db()
        self.assertEqual(policy.next_run_at, due + timedelta(days=1))

    @patch('apps.autopilot.tasks.execute_autopilot_run')
    def test_enqueue_failure_marks_scheduled_run_failed_honestly(self, task):
        task.enqueue.side_effect = RuntimeError('queue unavailable')
        due = timezone.now() - timedelta(minutes=30)
        policy = self._policy(name='Queueless daily', due=due)
        self.assertEqual(enqueue_due_autopilot_runs(), 1)
        run = AutopilotRun.objects.get(policy=policy)
        self.assertEqual(run.status, AutopilotRun.Status.FAILED)
        self.assertEqual(run.error_code, 'QUEUE_ENQUEUE_FAILED')
        self.assertTrue(run.completed_at)
        self.assertEqual(run.task_id, '')
        self.assertEqual(run.steps.get(key='finish').status, 'FAILED')
        # The schedule advanced regardless: no unbounded retry storm against
        # a queue that is down.
        self.assertEqual(enqueue_due_autopilot_runs(), 0)

    def test_api_sets_cadence_but_never_next_run_at(self):
        before = timezone.now()
        created = self.client.post(
            '/api/marketing/autopilot/policies/',
            {
                'brand': str(self.brand.pk),
                'name': 'API daily', 'objective': 'Ship one useful draft',
                'allowed_formats': ['POSTER'], 'enabled': True,
                'cadence': 'DAILY',
                # A client must not be able to schedule immediate spend.
                'next_run_at': before.isoformat(),
            },
            format='json', **self.headers,
        )
        self.assertEqual(created.status_code, 201, created.json())
        payload = created.json()
        self.assertEqual(payload['cadence'], 'DAILY')
        policy = AutopilotPolicy.objects.get(pk=payload['id'])
        self.assertGreaterEqual(policy.next_run_at, before + timedelta(days=1))

        patched = self.client.patch(
            f'/api/marketing/autopilot/policies/{policy.pk}/',
            {'cadence': 'MANUAL'}, format='json', **self.headers,
        )
        self.assertEqual(patched.status_code, 200, patched.json())
        self.assertIsNone(patched.json()['next_run_at'])

        rejected = self.client.patch(
            f'/api/marketing/autopilot/policies/{policy.pk}/',
            {'cadence': 'HOURLY'}, format='json', **self.headers,
        )
        self.assertEqual(rejected.status_code, 400)
