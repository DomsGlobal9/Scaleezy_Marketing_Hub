"""Compare-and-pick: one decision closes both halves of an A/B pair.

The winner is approved, the twin is rejected with a note naming the pick —
the loss becomes a learning signal instead of an orphaned draft.
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.content.models import ContentItem
from apps.feedback.models import Feedback
from apps.marketing.models import MarketingAsset
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()

GROUP = 'f0000000-0000-0000-0000-000000000001'


class PickTwinTests(APITestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='ab', workspace_name='AB')
        self.manager = User.objects.create_user(username='abmgr', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.manager, role=WorkspaceMember.Role.MANAGER
        )
        self.editor = User.objects.create_user(username='abed', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.editor, role=WorkspaceMember.Role.EDITOR
        )
        asset = MarketingAsset.objects.create(
            workspace=self.ws, file_name='a.jpg', source='AI_GENERATED',
            file_url='https://storage.test/a.jpg',
        )
        self.a = ContentItem.objects.create(
            workspace=self.ws, headline='Variant A', asset=asset,
            preview_url='https://storage.test/a.jpg',
            status=ContentItem.Status.DRAFT,
            layout_config={'ab_group': GROUP, 'ab_slot': 'A'},
        )
        self.b = ContentItem.objects.create(
            workspace=self.ws, headline='Variant B', asset=asset,
            preview_url='https://storage.test/b.jpg',
            status=ContentItem.Status.DRAFT,
            layout_config={'ab_group': GROUP, 'ab_slot': 'B'},
        )

    def as_(self, user):
        self.client.force_authenticate(user=user)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str(self.ws.id))

    def pick(self, item, note=''):
        return self.client.post(
            f'/api/marketing/content/{item.pk}/pick-twin/', {'note': note},
            format='json',
        )

    def test_one_pick_decides_both_halves_and_both_teach(self):
        self.as_(self.manager)
        res = self.pick(self.a, note='The motion pose sells it.')
        self.assertEqual(res.status_code, 200, res.data)
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual(self.a.status, ContentItem.Status.APPROVED)
        self.assertEqual(self.b.status, ContentItem.Status.REJECTED)
        self.assertIn('A/B pick', self.b.review_note)
        verdicts = {
            (f.content_item_id, f.verdict) for f in Feedback.objects.all()
        }
        self.assertIn((self.a.pk, Feedback.Verdict.APPROVE), verdicts)
        self.assertIn((self.b.pk, Feedback.Verdict.REJECT), verdicts)
        # The loser's rejection is VERDICT-ONLY: the machine note (and the
        # reviewer's praise of the winner) must never reach the NL parser as
        # if a reviewer had criticised this creative.
        loser_row = Feedback.objects.get(content_item=self.b)
        self.assertEqual(loser_row.feedback_text, '')
        self.assertEqual(loser_row.element_keys, [])

    def test_the_pairing_authority_is_not_client_writable(self):
        # An editor PATCHing ab_group onto arbitrary items could weaponise a
        # pick into auto-rejection — layout_config is the engine's ledger.
        self.as_(self.editor)
        res = self.client.patch(
            f'/api/marketing/content/{self.a.pk}/',
            {'layout_config': {'ab_group': 'spoofed', 'ab_slot': 'A'}},
            format='json',
        )
        self.a.refresh_from_db()
        self.assertEqual(self.a.layout_config.get('ab_group'), GROUP, res.data)

    def test_a_group_that_is_not_exactly_two_is_refused(self):
        ContentItem.objects.create(
            workspace=self.ws, headline='Variant C',
            status=ContentItem.Status.DRAFT,
            layout_config={'ab_group': GROUP, 'ab_slot': 'C'},
        )
        self.as_(self.manager)
        res = self.pick(self.a)
        self.assertEqual(res.status_code, 409)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, ContentItem.Status.DRAFT)

    def test_a_decided_pair_refuses_a_pick(self):
        self.b.status = ContentItem.Status.APPROVED
        self.b.save(update_fields=['status'])
        self.as_(self.manager)
        res = self.pick(self.a)
        self.assertEqual(res.status_code, 409)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, ContentItem.Status.DRAFT)

    def test_only_a_manager_picks_and_only_twins_qualify(self):
        self.as_(self.editor)
        self.assertEqual(self.pick(self.a).status_code, 403)
        solo = ContentItem.objects.create(
            workspace=self.ws, headline='Solo', status=ContentItem.Status.DRAFT,
        )
        self.as_(self.manager)
        self.assertEqual(self.pick(solo).status_code, 409)
