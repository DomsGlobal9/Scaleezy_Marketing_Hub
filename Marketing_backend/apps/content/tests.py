"""Phase 3 + 4 — content persistence and the review gate."""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.content.models import ContentItem
from apps.marketing.models import MarketingAsset
from apps.social_accounts.models import SocialConnection
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()


class ContentReviewTests(APITestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.other = MarketingWorkspace.objects.create(customer_id='b', workspace_name='Beta')

        self.manager = User.objects.create_user(username='mgr', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.manager, role=WorkspaceMember.Role.MANAGER
        )
        self.editor = User.objects.create_user(username='ed', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.editor, role=WorkspaceMember.Role.EDITOR
        )
        self.outsider = User.objects.create_user(username='out', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.other, user=self.outsider, role=WorkspaceMember.Role.OWNER
        )

        self.item = ContentItem.objects.create(
            workspace=self.ws, headline='Festive drop', status=ContentItem.Status.PENDING_REVIEW
        )
        self.asset = MarketingAsset.objects.create(
            workspace=self.ws, file_name='draft.jpg', source='MANUAL_UPLOAD'
        )

    def as_(self, user, ws=None):
        self.client.force_authenticate(user=user)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str((ws or self.ws).id))

    # ── persistence & tenancy ────────────────────────────────────────────
    def test_anonymous_rejected(self):
        self.client.credentials()
        self.assertEqual(
            self.client.get('/api/marketing/content/').status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_list_is_workspace_scoped(self):
        ContentItem.objects.create(workspace=self.other, headline='Theirs')
        self.as_(self.editor)
        res = self.client.get('/api/marketing/content/')
        self.assertEqual([c['headline'] for c in res.data], ['Festive drop'])

    def test_workspace_cannot_be_chosen_by_client(self):
        self.as_(self.outsider, self.other)
        self.client.post(
            '/api/marketing/content/',
            {'headline': 'Planted', 'workspace': str(self.ws.id)},
            format='json',
        )
        self.assertEqual(ContentItem.objects.get(headline='Planted').workspace, self.other)

    def test_status_cannot_be_set_by_a_direct_patch(self):
        """Status only moves through the review actions."""
        self.as_(self.editor)
        self.client.patch(
            f'/api/marketing/content/{self.item.id}/',
            {'status': ContentItem.Status.APPROVED},
            format='json',
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ContentItem.Status.PENDING_REVIEW)

    def test_filter_by_status(self):
        ContentItem.objects.create(
            workspace=self.ws, headline='Done', status=ContentItem.Status.APPROVED
        )
        self.as_(self.editor)
        res = self.client.get('/api/marketing/content/?status=APPROVED')
        self.assertEqual([c['headline'] for c in res.data], ['Done'])

    # ── review workflow ──────────────────────────────────────────────────
    def test_manager_can_approve(self):
        self.as_(self.manager)
        res = self.client.post(f'/api/marketing/content/{self.item.id}/approve/', {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ContentItem.Status.APPROVED)
        self.assertEqual(self.item.reviewed_by, self.manager)
        self.assertIsNotNone(self.item.reviewed_at)

    def test_editor_cannot_approve(self):
        self.as_(self.editor)
        res = self.client.post(f'/api/marketing/content/{self.item.id}/approve/', {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ContentItem.Status.PENDING_REVIEW)

    def test_editor_can_submit_for_review(self):
        draft = ContentItem.objects.create(
            workspace=self.ws, headline='Draft', asset=self.asset
        )
        self.as_(self.editor)
        res = self.client.post(f'/api/marketing/content/{draft.id}/submit/', {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ContentItem.Status.PENDING_REVIEW)

    def test_draft_without_media_cannot_be_submitted(self):
        draft = ContentItem.objects.create(workspace=self.ws, headline='No media')
        self.as_(self.editor)

        res = self.client.post(f'/api/marketing/content/{draft.id}/submit/', {}, format='json')

        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['error']['code'], 'CONTENT_MEDIA_REQUIRED')

    def test_submitted_content_cannot_be_edited(self):
        self.as_(self.editor)

        res = self.client.patch(
            f'/api/marketing/content/{self.item.id}/', {'headline': 'Changed'}, format='json'
        )

        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.item.refresh_from_db()
        self.assertEqual(self.item.headline, 'Festive drop')

    def test_reject_records_the_note(self):
        self.as_(self.manager)
        self.client.post(
            f'/api/marketing/content/{self.item.id}/reject/',
            {'note': 'Off-brand colours'}, format='json',
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ContentItem.Status.REJECTED)
        self.assertEqual(self.item.review_note, 'Off-brand colours')

    def test_request_edits_opens_a_linked_revision(self):
        self.as_(self.manager)
        res = self.client.post(
            f'/api/marketing/content/{self.item.id}/request-edits/',
            {'note': 'Tighten the headline'}, format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ContentItem.Status.NEEDS_EDITS)

        revision = ContentItem.objects.get(parent=self.item)
        self.assertEqual(revision.version, 2)
        self.assertEqual(revision.status, ContentItem.Status.DRAFT)
        self.assertEqual(revision.headline, 'Festive drop')

    def test_published_content_cannot_be_re_reviewed(self):
        self.item.status = ContentItem.Status.PUBLISHED
        self.item.save()
        self.as_(self.manager)
        res = self.client.post(f'/api/marketing/content/{self.item.id}/approve/', {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)

    def test_cannot_review_another_workspaces_content(self):
        self.as_(self.outsider, self.other)
        res = self.client.post(f'/api/marketing/content/{self.item.id}/approve/', {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class PublishingGateTests(APITestCase):
    """Phase 4's point: unapproved content must not reach a platform."""

    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.user = User.objects.create_user(username='mgr', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.user, role=WorkspaceMember.Role.MANAGER
        )
        self.asset = MarketingAsset.objects.create(
            workspace=self.ws, file_name='a.jpg', source='MANUAL_UPLOAD'
        )
        self.conn = SocialConnection.objects.create(
            workspace=self.ws, platform='X', external_account_id='x1',
            account_name='X', status=SocialConnection.Status.CONNECTED,
        )
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str(self.ws.id))

    def _publish(self, content_item):
        if content_item.workspace_id == self.ws.id:
            content_item.asset = self.asset
            content_item.save(update_fields=['asset'])
        return self.client.post(
            '/api/marketing/publishing/jobs/',
            {
                'workspace_id': str(self.ws.id),
                'asset_id': str(self.asset.id),
                'publish_mode': 'NOW',
                'social_connection_ids': [str(self.conn.id)],
                'content_item_id': str(content_item.id),
            },
            format='json',
        )

    def test_unapproved_content_cannot_be_published(self):
        draft = ContentItem.objects.create(
            workspace=self.ws, headline='Draft', status=ContentItem.Status.PENDING_REVIEW
        )
        res = self._publish(draft)
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['error']['code'], 'NOT_APPROVED')

    def test_publish_without_a_content_item_is_rejected(self):
        res = self.client.post(
            '/api/marketing/publishing/jobs/',
            {
                'workspace_id': str(self.ws.id),
                'asset_id': str(self.asset.id),
                'publish_mode': 'NOW',
                'social_connection_ids': [str(self.conn.id)],
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_approved_content_cannot_publish_a_different_asset(self):
        approved = ContentItem.objects.create(
            workspace=self.ws, headline='Yes', status=ContentItem.Status.APPROVED,
            asset=self.asset,
        )
        other_asset = MarketingAsset.objects.create(
            workspace=self.ws, file_name='other.jpg', source='MANUAL_UPLOAD'
        )
        res = self.client.post(
            '/api/marketing/publishing/jobs/',
            {
                'workspace_id': str(self.ws.id),
                'asset_id': str(other_asset.id),
                'content_item_id': str(approved.id),
                'publish_mode': 'NOW',
                'social_connection_ids': [str(self.conn.id)],
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['error']['code'], 'CONTENT_ASSET_MISMATCH')

    def test_rejected_content_cannot_be_published(self):
        rejected = ContentItem.objects.create(
            workspace=self.ws, headline='No', status=ContentItem.Status.REJECTED
        )
        self.assertEqual(self._publish(rejected).status_code, status.HTTP_409_CONFLICT)

    def test_approved_content_passes_the_gate(self):
        approved = ContentItem.objects.create(
            workspace=self.ws, headline='Yes', status=ContentItem.Status.APPROVED
        )
        # The publish itself will fail on a fake token; what matters is that
        # the gate did not block it.
        self.assertNotEqual(self._publish(approved).status_code, status.HTTP_409_CONFLICT)

    def test_content_from_another_workspace_is_not_found(self):
        other = MarketingWorkspace.objects.create(customer_id='b', workspace_name='Beta')
        foreign = ContentItem.objects.create(
            workspace=other, headline='Theirs', status=ContentItem.Status.APPROVED
        )
        self.assertEqual(self._publish(foreign).status_code, status.HTTP_404_NOT_FOUND)
