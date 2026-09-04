import uuid
from unittest.mock import patch, MagicMock

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from django.contrib.auth import get_user_model
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember
from apps.social_accounts.integrations.meta.exceptions import MetaConfigurationError
from apps.social_accounts.oauth_authority import bind_authority

User = get_user_model()


class MetaViewsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.workspace = MarketingWorkspace.objects.create(
            customer_id='c123',
            workspace_name='Test Workspace'
        )
        self.user = User.objects.create_user(username='tester', password='p')
        WorkspaceMember.objects.create(
            workspace=self.workspace,
            user=self.user,
            role=WorkspaceMember.Role.ADMIN
        )
        self.client.force_authenticate(user=self.user)

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_connect_handles_meta_api_error(self, mock_get_adapter):
        """
        Verify that if the Meta adapter raises a MetaAPIError (like MetaConfigurationError)
        during connect(), the view catches it and returns a 400 Bad Request
        with the correct error structure.
        """
        mock_adapter = MagicMock()
        # Make the adapter's get_authorization_url raise the exception
        mock_adapter.get_authorization_url.side_effect = MetaConfigurationError("Missing Meta credentials")
        mock_get_adapter.return_value = mock_adapter

        url = '/api/marketing/social-accounts/connect/'
        data = {
            'workspace_id': str(self.workspace.id),
            'platform': 'FACEBOOK'
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        resp_data = response.json()
        self.assertFalse(resp_data.get('success'))
        self.assertIn('error', resp_data)
        self.assertEqual(resp_data['error'].get('code'), 'META_NOT_CONFIGURED')
        self.assertEqual(resp_data['error'].get('message'), "Missing Meta credentials")

    @patch('apps.social_accounts.views.SocialConnectionViewSet.get_adapter')
    def test_oauth_callback_handles_meta_api_error(self, mock_get_adapter):
        """
        Verify that if the Meta adapter raises a MetaAPIError during oauth_callback(),
        the view catches it and returns a 400 Bad Request.
        """
        mock_adapter = MagicMock()
        mock_adapter.exchange_code_for_token.side_effect = MetaConfigurationError("Invalid state")
        mock_get_adapter.return_value = mock_adapter

        url = '/api/marketing/social-accounts/oauth_callback/'
        # Use HTTP_X_WORKSPACE_ID to pass workspace scope correctly as required by views
        data = {
            'platform': 'FACEBOOK',
            'code': 'testcode123',
            'state': f'{self.workspace.id}:somestate'
        }
        bind_authority(authorization_url=f"https://example.test/oauth?state={data['state']}", workspace=self.workspace, user=self.user, platform='FACEBOOK')

        response = self.client.post(url, data, format='json', HTTP_X_WORKSPACE_ID=str(self.workspace.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        resp_data = response.json()
        self.assertFalse(resp_data.get('success'))
        self.assertIn('error', resp_data)
        self.assertEqual(resp_data['error'].get('code'), 'META_NOT_CONFIGURED')
        self.assertEqual(resp_data['error'].get('message'), "Invalid state")
