"""Phase 8 — the durable task queue and scheduled publishing."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.tasks import TaskResultStatus, task
from django.tasks.exceptions import TaskResultDoesNotExist
from django.test import TestCase
from django.utils import timezone

from apps.jobs import runner
from apps.jobs.models import TaskRun
from apps.marketing.models import MarketingAsset
from apps.publishing.models import PublishingJob
from apps.publishing.scheduler import due_jobs, enqueue_due_jobs
from apps.workspaces.models import MarketingWorkspace

User = get_user_model()

#: Module-level so the backend can import it back by path, which is exactly
#: what a real task has to survive.
_calls = []


@task
def record_call(value):
    _calls.append(value)
    return {'got': value}


@task
def always_fails():
    raise RuntimeError("nope")


class QueueTests(TestCase):
    def setUp(self):
        _calls.clear()

    def test_enqueue_stores_rather_than_running(self):
        result = record_call.enqueue('hello')
        self.assertEqual(_calls, [])
        self.assertEqual(result.status, TaskResultStatus.READY)

        run = TaskRun.objects.get(pk=result.id)
        self.assertEqual(run.task_path, 'apps.jobs.tests.record_call')
        self.assertEqual(run.args, ['hello'])

    def test_worker_runs_it(self):
        record_call.enqueue('hello')
        self.assertEqual(runner.run_once(), 1)
        self.assertEqual(_calls, ['hello'])

        run = TaskRun.objects.get()
        self.assertEqual(run.status, TaskResultStatus.SUCCESSFUL)
        self.assertEqual(run.return_value, {'got': 'hello'})
        self.assertIsNotNone(run.finished_at)

    def test_kwargs_survive_the_round_trip(self):
        record_call.enqueue(value='keyword')
        runner.run_once()
        self.assertEqual(_calls, ['keyword'])

    def test_a_task_is_only_run_once(self):
        record_call.enqueue('once')
        runner.run_once()
        runner.run_once()
        self.assertEqual(_calls, ['once'])

    def test_deferred_work_waits_for_its_time(self):
        record_call.using(run_after=timezone.now() + timedelta(hours=1)).enqueue('later')
        self.assertEqual(runner.run_once(), 0)
        self.assertEqual(_calls, [])

        TaskRun.objects.update(run_after=timezone.now() - timedelta(seconds=1))
        self.assertEqual(runner.run_once(), 1)
        self.assertEqual(_calls, ['later'])

    def test_priority_order(self):
        record_call.using(priority=0).enqueue('low')
        record_call.using(priority=50).enqueue('high')
        runner.run_once()
        self.assertEqual(_calls, ['high', 'low'])

    def test_a_failing_task_is_retried_then_given_up_on(self):
        always_fails.enqueue()
        run = TaskRun.objects.get()
        run.max_attempts = 2
        run.save(update_fields=['max_attempts'])

        runner.run_once()
        run.refresh_from_db()
        self.assertEqual(run.status, TaskResultStatus.READY)
        self.assertEqual(run.attempts, 1)
        # Backed off rather than retried in the same pass.
        self.assertIsNotNone(run.run_after)
        self.assertGreater(run.run_after, timezone.now())

        TaskRun.objects.update(run_after=None)
        runner.run_once()
        run.refresh_from_db()
        self.assertEqual(run.status, TaskResultStatus.FAILED)
        self.assertEqual(len(run.errors), 2)
        self.assertIn('RuntimeError', run.errors[0]['exception_class_path'])

    def test_a_failing_task_does_not_stop_the_worker(self):
        always_fails.enqueue()
        record_call.enqueue('still runs')
        runner.run_once()
        self.assertEqual(_calls, ['still runs'])

    def test_an_unimportable_task_fails_without_retrying(self):
        record_call.enqueue('x')
        TaskRun.objects.update(task_path='apps.jobs.tests.no_such_task')
        runner.run_once()
        run = TaskRun.objects.get()
        self.assertEqual(run.status, TaskResultStatus.FAILED)
        self.assertEqual(run.attempts, 1)

    def test_results_can_be_fetched_back(self):
        result = record_call.enqueue('fetch me')
        runner.run_once()
        refreshed = record_call.get_result(result.id)
        self.assertEqual(refreshed.status, TaskResultStatus.SUCCESSFUL)
        self.assertEqual(refreshed.return_value, {'got': 'fetch me'})

    def test_a_missing_result_raises(self):
        with self.assertRaises(TaskResultDoesNotExist):
            record_call.get_result('0' * 32)

    def test_a_crashed_workers_task_is_reclaimed(self):
        record_call.enqueue('orphan')
        TaskRun.objects.update(
            status=TaskResultStatus.RUNNING,
            claimed_at=timezone.now() - runner.STALE_AFTER - timedelta(minutes=1),
        )
        self.assertEqual(runner.run_once(), 1)
        self.assertEqual(_calls, ['orphan'])

    def test_a_recently_claimed_task_is_left_alone(self):
        record_call.enqueue('in flight')
        TaskRun.objects.update(status=TaskResultStatus.RUNNING, claimed_at=timezone.now())
        self.assertEqual(runner.run_once(), 0)
        self.assertEqual(_calls, [])

    def test_limit_caps_a_pass(self):
        for i in range(3):
            record_call.enqueue(str(i))
        self.assertEqual(runner.run_once(limit=2), 2)
        self.assertEqual(len(_calls), 2)


class ScheduledPublishingTests(TestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.asset = MarketingAsset.objects.create(
            workspace=self.ws, file_name='poster.jpg', source='MANUAL_UPLOAD'
        )

    def job(self, *, when, status=PublishingJob.Status.SCHEDULED):
        return PublishingJob.objects.create(
            workspace=self.ws,
            asset=self.asset,
            publish_mode=PublishingJob.PublishMode.SCHEDULED,
            scheduled_at=when,
            status=status,
        )

    def test_a_future_job_is_not_due(self):
        self.job(when=timezone.now() + timedelta(hours=2))
        self.assertEqual(due_jobs().count(), 0)
        self.assertEqual(enqueue_due_jobs(), 0)

    def test_a_past_job_is_queued_and_executed(self):
        job = self.job(when=timezone.now() - timedelta(minutes=1))

        with patch('apps.publishing.services.execute_publishing_job') as execute:
            self.assertEqual(enqueue_due_jobs(), 1)
            job.refresh_from_db()
            self.assertEqual(job.status, PublishingJob.Status.QUEUED)

            # The queued task is what actually publishes.
            self.assertEqual(TaskRun.objects.count(), 1)
            runner.run_once()
            execute.assert_called_once_with(str(job.id))

    def test_a_job_is_never_queued_twice(self):
        self.job(when=timezone.now() - timedelta(minutes=1))
        enqueue_due_jobs()
        self.assertEqual(enqueue_due_jobs(), 0)
        self.assertEqual(TaskRun.objects.count(), 1)

    def test_already_published_jobs_are_ignored(self):
        self.job(
            when=timezone.now() - timedelta(days=1),
            status=PublishingJob.Status.PUBLISHED,
        )
        self.assertEqual(enqueue_due_jobs(), 0)

    def test_a_job_with_no_time_is_never_due(self):
        PublishingJob.objects.create(
            workspace=self.ws, asset=self.asset,
            publish_mode=PublishingJob.PublishMode.SCHEDULED,
            status=PublishingJob.Status.SCHEDULED,
        )
        self.assertEqual(enqueue_due_jobs(), 0)

    def test_the_worker_pass_sweeps_the_schedule(self):
        """A single `run_tasks --once` is a complete tick."""
        job = self.job(when=timezone.now() - timedelta(minutes=1))
        with patch('apps.publishing.services.execute_publishing_job') as execute:
            runner.run_once()
            execute.assert_called_once_with(str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.status, PublishingJob.Status.QUEUED)

    def test_one_bad_job_does_not_block_the_rest(self):
        good = self.job(when=timezone.now() - timedelta(minutes=1))
        self.job(when=timezone.now() - timedelta(minutes=2))

        import apps.publishing.tasks as publishing_tasks

        real_enqueue = publishing_tasks.publish_job.enqueue
        calls = {'n': 0}

        def flaky(*args, **kwargs):
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError("queue is down")
            return real_enqueue(*args, **kwargs)

        # Task is a frozen dataclass, so the module attribute is the seam —
        # its own attributes cannot be patched.
        with patch.object(publishing_tasks, 'publish_job') as stub:
            stub.enqueue.side_effect = flaky
            self.assertEqual(enqueue_due_jobs(), 1)

        # The failed one is rolled back to SCHEDULED and will be retried on the
        # next sweep, rather than being lost as QUEUED with nothing queued.
        self.assertEqual(
            PublishingJob.objects.filter(status=PublishingJob.Status.SCHEDULED).count(), 1
        )
        self.assertTrue(
            PublishingJob.objects.filter(
                pk=good.pk, status=PublishingJob.Status.QUEUED
            ).exists()
            or PublishingJob.objects.filter(status=PublishingJob.Status.QUEUED).exists()
        )
