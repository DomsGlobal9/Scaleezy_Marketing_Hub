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
from .services import create_run, emergency_stop, execute_run

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
