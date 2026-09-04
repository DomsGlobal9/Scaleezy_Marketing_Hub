from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from apps.knowledge.models import BrandMemory
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.workspaces.models import WorkspaceMember
from apps.onboarding.models import BrandOnboarding
from apps.onboarding.services import onboarding_summary
from apps.context.views import build_brand_master_overview
from .models import Brand
from .services.brand_brain import rebuild_brand_brain


class BrandReadBoundaryTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Read boundaries', 'read-boundaries')
        self.viewer, self.client = self.authenticate_as(self.workspace, WorkspaceMember.Role.VIEWER, 'read-viewer')
        self.headers = workspace_header(self.workspace)

    def test_viewer_cannot_provision_a_brand_through_either_read_alias(self):
        for url in ('/api/marketing/brands/current/', '/api/marketing/brand-master/current/'):
            response = self.client.get(url, **self.headers)
            self.assertEqual(response.status_code, 403, response.content)
        self.assertFalse(Brand.objects.filter(workspace=self.workspace).exists())

    def test_read_only_onboarding_derives_progress_without_writes(self):
        brand = Brand.objects.create(workspace=self.workspace, name='Brand', industry='Software')
        summary = onboarding_summary(brand)
        self.assertEqual(summary['onboarding']['current_stage'], 'KNOWLEDGE')
        self.assertIsNone(summary['onboarding']['started_at'])
        self.assertFalse(BrandOnboarding.objects.filter(brand=brand).exists())
        saved = BrandOnboarding.objects.create(workspace=self.workspace, brand=brand)
        summary = onboarding_summary(brand)
        self.assertEqual(summary['onboarding']['current_stage'], 'KNOWLEDGE')
        saved.refresh_from_db()
        self.assertEqual(saved.current_stage, 'BASICS')

    def test_old_snapshot_is_not_reported_as_current_after_compile_failure(self):
        brand = Brand.objects.create(workspace=self.workspace, name='Brand')
        rebuild_brand_brain(brand)
        brand.brain_last_error = 'internal failure detail'
        brand.save(update_fields=['brain_last_error'])
        overview = build_brand_master_overview(brand)
        self.assertTrue(overview['brain']['compiled'])
        self.assertTrue(overview['brain']['needs_refresh'])
        self.assertNotIn('internal failure detail', str(overview))

    def test_compile_excludes_expired_and_future_confirmed_memories(self):
        brand = Brand.objects.create(workspace=self.workspace, name='Brand')
        now = timezone.now()
        for content, dates in (
            ('Expired fact', {'valid_until': now - timedelta(seconds=1)}),
            ('Future fact', {'valid_from': now + timedelta(days=1)}),
            ('Current fact', {}),
        ):
            BrandMemory.objects.create(
                workspace=self.workspace, brand=brand, memory_type='BRAND_CANON',
                status='CONFIRMED', content=content, **dates,
            )
        rebuild_brand_brain(brand)
        brand.refresh_from_db()
        compiled = str(brand.creative_brain)
        self.assertIn('Current fact', compiled)
        self.assertNotIn('Expired fact', compiled)
        self.assertNotIn('Future fact', compiled)
