"""
The compile-status route: after queueing a compile, the console can watch that
one task — and nothing else. Any other task_path is Not Found, and the usual
boundary holds (workspace owner and anonymous callers get nothing).
"""
import uuid

from django.contrib.auth import get_user_model
from django.tasks import TaskResultStatus
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import PlatformAuditLog
from apps.audit.services import grant_platform_admin
from apps.common.testing import TenantFixtureMixin
from apps.jobs.models import TaskRun
from apps.workspaces.models import WorkspaceMember

User = get_user_model()

COMPILE = '/api/platform/patterns/compile/'


class PatternCompileStatusTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.owner, self.owner_api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner@acme.test'
        )
        self.staff = User.objects.create_user(username='staff@scaleezy.test', password='pw')
        grant_platform_admin(self.staff, note='test')
        self.staff_api = APIClient()
        self.staff_api.force_authenticate(user=self.staff)

    def queue_compile(self):
        """POST the real compile route; the database task backend only stores."""
        response = self.staff_api.post(COMPILE, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.content)
        return response.json()['data']['task_id']

    def test_status_reports_the_queued_compile_then_its_failure(self):
        task_id = self.queue_compile()

        response = self.staff_api.get(f'{COMPILE}{task_id}/')
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual(data['task_id'], task_id)
        self.assertEqual(data['status'], TaskResultStatus.READY)
        self.assertEqual(data['attempts'], 0)
        self.assertIsNotNone(data['enqueued_at'])
        self.assertIsNone(data['finished_at'])
        self.assertEqual(data['error'], '')
        # A non-terminal poll writes no audit row; the terminal one does.
        self.assertFalse(
            PlatformAuditLog.objects.filter(
                action='LEARNED_PATTERN_COMPILE_STATUS_VIEWED'
            ).exists()
        )

        TaskRun.objects.filter(pk=task_id).update(
            status=TaskResultStatus.FAILED,
            attempts=3,
            finished_at=timezone.now(),
            errors=[
                {'exception_class_path': 'builtins.ValueError', 'traceback': 'old'},
                {
                    'exception_class_path': 'builtins.RuntimeError',
                    'traceback': 'Traceback (most recent call last):\n'
                                 + ('  frame\n' * 200)
                                 + 'RuntimeError: boom',
                },
            ],
        )
        response = self.staff_api.get(f'{COMPILE}{task_id}/')
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual(data['status'], TaskResultStatus.FAILED)
        self.assertEqual(data['attempts'], 3)
        self.assertIsNotNone(data['finished_at'])
        # The short tail of the LAST error, bounded, ending in the message.
        self.assertTrue(data['error'].endswith('RuntimeError: boom'), data['error'])
        self.assertLessEqual(len(data['error']), 500)
        entry = PlatformAuditLog.objects.get(action='LEARNED_PATTERN_COMPILE_STATUS_VIEWED')
        self.assertEqual(entry.detail['status'], TaskResultStatus.FAILED)

    def test_success_reports_no_error(self):
        task_id = self.queue_compile()
        TaskRun.objects.filter(pk=task_id).update(
            status=TaskResultStatus.SUCCESSFUL,
            attempts=1,
            finished_at=timezone.now(),
            errors=[{'exception_class_path': 'builtins.ValueError', 'traceback': 'retried'}],
        )
        data = self.staff_api.get(f'{COMPILE}{task_id}/').json()['data']
        self.assertEqual(data['status'], TaskResultStatus.SUCCESSFUL)
        # A run that failed once then succeeded is a success: no error text.
        self.assertEqual(data['error'], '')

    def test_refuses_task_ids_that_are_not_the_compile_task(self):
        foreign = TaskRun.objects.create(
            id=uuid.uuid4().hex,
            task_path='apps.knowledge.tasks.process_source_task',
        )
        response = self.staff_api.get(f'{COMPILE}{foreign.pk}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        missing = self.staff_api.get(f'{COMPILE}{uuid.uuid4().hex}/')
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_platform_admins_get_nothing(self):
        task_id = self.queue_compile()
        url = f'{COMPILE}{task_id}/'
        self.assertEqual(self.owner_api.get(url).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(APIClient().get(url).status_code, status.HTTP_401_UNAUTHORIZED)
