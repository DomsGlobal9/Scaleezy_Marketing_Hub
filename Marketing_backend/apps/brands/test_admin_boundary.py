"""
Django admin is not platform authority.

`is_staff` grants Django admin; `PlatformAdmin` grants the console. They are
different decisions, and the first must not be able to make the second's
calls — approve or reject a customer, or edit approval state directly.
"""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.brands.admin import BrandAdmin
from apps.brands.models import Brand
from apps.workspaces.admin import MarketingWorkspaceAdmin
from apps.workspaces.models import MarketingWorkspace

User = get_user_model()


class AdminBoundaryTests(TestCase):
    def setUp(self):
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='c', workspace_name='Pending Co',
            approval_status=MarketingWorkspace.Approval.PENDING,
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Pending Co', status=Brand.Status.PENDING
        )
        # Ordinary staff: may open Django admin, holds no platform authority.
        self.staff = User.objects.create_user(
            username='staff@x.test', password='pw', is_staff=True
        )
        from django.contrib.auth.models import Permission

        self.staff.user_permissions.add(
            *Permission.objects.filter(content_type__app_label__in=['brands', 'workspaces'])
        )
        self.client.force_login(self.staff)

    def test_brand_admin_offers_no_approve_or_reject_action(self):
        self.assertFalse(BrandAdmin.actions)
        self.assertFalse(hasattr(BrandAdmin, 'approve_brands'))
        self.assertFalse(hasattr(BrandAdmin, 'reject_brands'))

    def test_approval_fields_are_read_only_in_both_admins(self):
        for field in ('status', 'reviewed_at', 'reviewed_by'):
            self.assertIn(field, BrandAdmin.readonly_fields, field)
        for field in ('approval_status', 'status', 'client_code'):
            self.assertIn(field, MarketingWorkspaceAdmin.readonly_fields, field)

    def test_staff_cannot_flip_brand_status_through_the_admin_change_form(self):
        url = reverse('admin:brands_brand_change', args=[self.brand.pk])
        response = self.client.post(url, {
            'workspace': str(self.workspace.pk), 'name': 'Pending Co', 'industry': '',
            'status': 'ACTIVE', 'is_default': 'on',
            'palette': '{}', 'fonts': '{}', 'layout_preference': 'agency_column',
            'logo_file_name': '', 'tagline': '', 'cta_keyword': '', 'brand_tone': '',
            'contact_phone': '', 'instagram_handle': '', 'competitors': '[]',
            'creative_brain': '{}', 'created_by': '',
            '_save': 'Save',
        })
        # Whatever the form did with the rest, the read-only field was ignored.
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.status, Brand.Status.PENDING)
        self.assertIn(response.status_code, (200, 302))

    def test_staff_cannot_flip_workspace_approval_through_the_admin_change_form(self):
        url = reverse('admin:workspaces_marketingworkspace_change', args=[self.workspace.pk])
        response = self.client.post(url, {
            'customer_id': 'c', 'workspace_name': 'Pending Co', 'timezone': 'UTC',
            'default_language': 'en', 'approval_status': 'APPROVED', 'status': 'ACTIVE',
            'members-TOTAL_FORMS': '0', 'members-INITIAL_FORMS': '0',
            'members-MIN_NUM_FORMS': '0', 'members-MAX_NUM_FORMS': '1000',
            '_save': 'Save',
        })
        self.workspace.refresh_from_db()
        self.assertEqual(self.workspace.approval_status, MarketingWorkspace.Approval.PENDING)
        self.assertIn(response.status_code, (200, 302))
