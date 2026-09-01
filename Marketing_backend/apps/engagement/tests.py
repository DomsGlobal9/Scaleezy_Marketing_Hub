from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status

from apps.ai.models import Capability
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.learning.models import LearningEvent
from apps.social_accounts.models import SocialConnection
from apps.social_accounts.utils.encryption import encrypt_token
from apps.workspaces.models import WorkspaceMember

from .models import EngagementItem, EngagementSyncRun
from .services import draft_reply, sync_inbox


class EngagementClosureTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.ws1 = self.make_workspace('One', 'engagement-one')
        self.user1, self.client1 = self.authenticate_as(
            self.ws1, WorkspaceMember.Role.ADMIN, 'engagement-admin-1'
        )
        self.editor, self.editor_client = self.authenticate_as(
            self.ws1, WorkspaceMember.Role.EDITOR, 'engagement-editor'
        )
        self.viewer, self.viewer_client = self.authenticate_as(
            self.ws1, WorkspaceMember.Role.VIEWER, 'engagement-viewer'
        )
        self.brand1 = Brand.objects.create(workspace=self.ws1, name='One Brand')
        self.connection1 = SocialConnection.objects.create(
            workspace=self.ws1,
            platform=SocialConnection.Platform.X,
            external_account_id='x-user-1',
            account_name='One on X',
            status=SocialConnection.Status.CONNECTED,
            access_token_encrypted=encrypt_token('token-one'),
            connected_by=self.user1,
        )

        self.ws2 = self.make_workspace('Two', 'engagement-two')
        self.user2, self.client2 = self.authenticate_as(
            self.ws2, WorkspaceMember.Role.ADMIN, 'engagement-admin-2'
        )
        self.brand2 = Brand.objects.create(workspace=self.ws2, name='Two Brand')
        self.connection2 = SocialConnection.objects.create(
            workspace=self.ws2,
            platform=SocialConnection.Platform.X,
            external_account_id='x-user-2',
            account_name='Two on X',
            status=SocialConnection.Status.CONNECTED,
            access_token_encrypted=encrypt_token('token-two'),
            connected_by=self.user2,
        )

    def header(self, workspace=None):
        return workspace_header(workspace or self.ws1)

    def item(self, **overrides):
        data = {
            'workspace': self.ws1,
            'brand': self.brand1,
            'social_connection': self.connection1,
            'platform': SocialConnection.Platform.X,
            'kind': EngagementItem.Kind.MENTION,
            'external_id': f'x-{EngagementItem.objects.count() + 1}',
            'author_name': 'Customer',
            'author_handle': 'customer',
            'body': 'Can you help?',
            'occurred_at': timezone.now(),
        }
        data.update(overrides)
        return EngagementItem.objects.create(**data)

    def test_sync_run_is_queued_and_relations_are_tenant_scoped(self):
        response = self.client1.post(
            '/api/marketing/engagement/sync-runs/',
            {'brand': str(self.brand1.pk), 'social_connection': str(self.connection1.pk)},
            format='json', **self.header(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        run = EngagementSyncRun.objects.get(pk=response.json()['id'])
        self.assertTrue(run.task_id)

        leaked = self.client1.post(
            '/api/marketing/engagement/sync-runs/',
            {'brand': str(self.brand1.pk), 'social_connection': str(self.connection2.pk)},
            format='json', **self.header(),
        )
        self.assertEqual(leaked.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('apps.engagement.services._adapter_for')
    def test_platform_sync_is_bounded_normalized_and_idempotent(self, adapter_for):
        adapter = Mock()
        adapter.fetch_mentions.return_value = {
            'items': [{
                'external_id': 'mention-1', 'thread_id': 'thread-1',
                'kind': 'MENTION', 'author_name': 'A', 'author_handle': 'a',
                'body': 'Hello', 'source_url': 'https://x.com/a/status/mention-1',
                'occurred_at': '2026-09-01T10:00:00Z',
                'source_payload': {'author_id': 'author-1'},
            }],
            'cursor': 'next',
        }
        adapter_for.return_value = adapter
        run = EngagementSyncRun.objects.create(
            workspace=self.ws1, brand=self.brand1,
            social_connection=self.connection1, initiated_by=self.user1,
        )
        first = sync_inbox(run.pk)
        run.status = EngagementSyncRun.Status.QUEUED
        run.save(update_fields=['status', 'updated_at'])
        second = sync_inbox(run.pk)
        self.assertEqual(first['imported'], 1)
        self.assertEqual(second['imported'], 0)
        self.assertEqual(EngagementItem.objects.count(), 1)
        adapter.fetch_mentions.assert_called_with('token-one', 'x-user-1', cursor='next')

    def test_viewer_cannot_claim_or_create_sync(self):
        item = self.item()
        claim = self.viewer_client.post(
            f'/api/marketing/engagement/items/{item.pk}/claim/',
            format='json', **self.header(),
        )
        sync = self.viewer_client.post(
            '/api/marketing/engagement/sync-runs/',
            {'brand': str(self.brand1.pk), 'social_connection': str(self.connection1.pk)},
            format='json', **self.header(),
        )
        self.assertEqual(claim.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(sync.status_code, status.HTTP_403_FORBIDDEN)

    def test_collision_lock_blocks_a_second_operator(self):
        item = self.item()
        first = self.client1.post(
            f'/api/marketing/engagement/items/{item.pk}/claim/',
            format='json', **self.header(),
        )
        second = self.editor_client.post(
            f'/api/marketing/engagement/items/{item.pk}/claim/',
            format='json', **self.header(),
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        item.refresh_from_db()
        self.assertEqual(item.locked_by, self.user1)

    def test_sending_or_closed_item_cannot_be_claimed_or_reapproved(self):
        sending = self.item(
            status=EngagementItem.Status.SENDING,
            approved_response='Already in flight',
        )
        claim = self.client1.post(
            f'/api/marketing/engagement/items/{sending.pk}/claim/',
            format='json', **self.header(),
        )
        approve = self.client1.post(
            f'/api/marketing/engagement/items/{sending.pk}/approve/',
            {'response': 'Try to reopen'}, format='json', **self.header(),
        )
        self.assertEqual(claim.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(approve.status_code, status.HTTP_409_CONFLICT)
        sending.refresh_from_db()
        self.assertEqual(sending.status, EngagementItem.Status.SENDING)

    @patch('apps.engagement.services.AIRouter.dispatch')
    def test_ai_draft_uses_dedicated_route_and_never_sends(self, dispatch):
        dispatch.return_value = {
            'reply': 'Thanks — we can help.', 'sentiment': 'NEUTRAL',
            'urgency': 'NORMAL', 'risk_flags': [],
            'provider': 'chosen-by-admin', 'provider_name': 'Chosen by admin',
        }
        item = self.item()
        result = draft_reply(item.pk)
        item.refresh_from_db()
        self.assertEqual(result['status'], EngagementItem.DraftStatus.READY)
        self.assertEqual(dispatch.call_args.args[0], Capability.ENGAGEMENT_RESPONSE)
        self.assertEqual(item.status, EngagementItem.Status.AWAITING_APPROVAL)
        self.assertEqual(item.external_response_id, '')
        self.assertIsNone(item.responded_at)

    def test_approval_is_human_evidence_but_does_not_send(self):
        item = self.item(ai_draft='Suggested reply')
        response = self.client1.post(
            f'/api/marketing/engagement/items/{item.pk}/approve/',
            {'response': 'Approved reply'}, format='json', **self.header(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        item.refresh_from_db()
        self.assertEqual(item.status, EngagementItem.Status.APPROVED)
        self.assertIsNone(item.responded_at)
        self.assertTrue(LearningEvent.objects.filter(
            workspace=self.ws1, dedupe_key=f'engagement-response-approved:{item.pk}'
        ).exists())

    @patch('apps.engagement.views.send_approved_reply', return_value={'id': 'reply-1'})
    def test_send_is_single_claim_and_marks_resolved_only_after_platform_success(self, send):
        item = self.item(
            status=EngagementItem.Status.APPROVED,
            approved_response='Approved response', approved_by=self.user1,
            approved_at=timezone.now(),
        )
        url = f'/api/marketing/engagement/items/{item.pk}/send/'
        first = self.client1.post(url, format='json', **self.header())
        second = self.client1.post(url, format='json', **self.header())
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.content)
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(send.call_count, 1)
        item.refresh_from_db()
        self.assertEqual(item.status, EngagementItem.Status.RESOLVED)
        self.assertEqual(item.external_response_id, 'reply-1')
        self.assertIsNotNone(item.responded_at)

    @patch('apps.engagement.views.send_approved_reply', side_effect=RuntimeError('private'))
    def test_failed_platform_reply_stays_approved_and_never_claims_sent(self, _send):
        item = self.item(
            status=EngagementItem.Status.APPROVED,
            approved_response='Approved response', approved_by=self.user1,
            approved_at=timezone.now(),
        )
        response = self.client1.post(
            f'/api/marketing/engagement/items/{item.pk}/send/',
            format='json', **self.header(),
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        item.refresh_from_db()
        self.assertEqual(item.status, EngagementItem.Status.APPROVED)
        self.assertEqual(item.external_response_id, '')
        self.assertIsNone(item.responded_at)

    @patch('apps.engagement.services.XAdapter.reply_to_post', return_value={'id': ''})
    def test_missing_platform_confirmation_is_not_sent(self, _reply):
        item = self.item(
            status=EngagementItem.Status.APPROVED,
            approved_response='Approved response', approved_by=self.user1,
            approved_at=timezone.now(),
        )
        response = self.client1.post(
            f'/api/marketing/engagement/items/{item.pk}/send/',
            format='json', **self.header(),
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        item.refresh_from_db()
        self.assertEqual(item.status, EngagementItem.Status.APPROVED)
        self.assertEqual(item.external_response_id, '')

    def test_other_tenant_cannot_see_or_act_on_an_item(self):
        item = self.item()
        detail = self.client2.get(
            f'/api/marketing/engagement/items/{item.pk}/', **self.header(self.ws2)
        )
        claim = self.client2.post(
            f'/api/marketing/engagement/items/{item.pk}/claim/',
            format='json', **self.header(self.ws2),
        )
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(claim.status_code, status.HTTP_404_NOT_FOUND)
