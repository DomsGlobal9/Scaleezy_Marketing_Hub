from rest_framework import viewsets, status
from rest_framework.decorators import action, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import SocialConnection
from apps.workspaces.models import MarketingWorkspace
from .serializers import SocialConnectionSerializer, ConnectPlatformSerializer
from apps.common.responses import APIResponse
from .integrations.meta.facebook import FacebookAdapter
from .integrations.meta.instagram import InstagramAdapter
from .integrations.linkedin import LinkedInAdapter
from .integrations.x import XAdapter
from .utils.encryption import encrypt_token, decrypt_token
from .models import SocialAccountAuditLog
from django.utils import timezone

class SocialConnectionViewSet(viewsets.ModelViewSet):
    queryset = SocialConnection.objects.all()
    serializer_class = SocialConnectionSerializer
    permission_classes = [AllowAny] # Changed to AllowAny for MVP since frontend auth is mocked

    def get_adapter(self, platform):
        adapters = {
            SocialConnection.Platform.FACEBOOK: FacebookAdapter(),
            SocialConnection.Platform.INSTAGRAM: InstagramAdapter(),
            SocialConnection.Platform.LINKEDIN: LinkedInAdapter(),
            SocialConnection.Platform.X: XAdapter(),
        }
        return adapters.get(platform)

    @action(detail=False, methods=['post'])
    def connect(self, request):
        serializer = ConnectPlatformSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(success=False, error=serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        workspace_id = serializer.validated_data['workspace_id']
        platform = serializer.validated_data['platform']
        
        adapter = self.get_adapter(platform)
        if not adapter:
            return APIResponse(success=False, message="Platform not supported yet.", status=status.HTTP_400_BAD_REQUEST)

        try:
            auth_url = adapter.get_authorization_url(workspace_id=str(workspace_id))
            return APIResponse(success=True, data={"authorization_url": auth_url})
        except Exception as e:
            if str(e) == "NOT_CONFIGURED":
                return APIResponse(success=False, error={"code": "NOT_CONFIGURED", "message": f"{platform} integration is not configured yet."})
            import traceback
            traceback.print_exc()
            return APIResponse(success=False, message=str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def oauth_callback(self, request):
        # In a real app, you would exchange the code for a token and save the SocialConnection.
        # This is a stub for the MVP callback handler.
        platform = request.data.get('platform')
        code = request.data.get('code')
        state = request.data.get('state')

        adapter = self.get_adapter(platform)
        if not adapter:
            return APIResponse(success=False, message="Platform not supported", status=400)
            
        try:
            # Exchange code for token. The state handles getting the workspace_id for us if PKCE.
            if platform == 'X':
                token_data = adapter.exchange_code_for_token(code, state)
                workspace_id = token_data.get('workspace_id')
            else:
                workspace_id = request.data.get('workspace_id')
                token_data = adapter.exchange_code_for_token(code, "http://localhost:8000")
                
            account_info = adapter.get_account_info(token_data['access_token'])
            
            workspace = MarketingWorkspace.objects.get(id=workspace_id)
            
            # Create or update connection
            connection, created = SocialConnection.objects.update_or_create(
                workspace=workspace,
                platform=platform,
                external_account_id=account_info['id'],
                defaults={
                    'account_name': account_info.get('name', 'Unknown'),
                    'username': account_info.get('username'),
                    'profile_image_url': account_info.get('profile_image_url'),
                    'status': SocialConnection.Status.CONNECTED,
                    'access_token_encrypted': encrypt_token(token_data.get('access_token')),
                    'refresh_token_encrypted': encrypt_token(token_data.get('refresh_token')),
                    'scopes': token_data.get('scopes', ''),
                    'last_verified_at': timezone.now()
                }
            )
            
            # Audit Log
            SocialAccountAuditLog.objects.create(
                workspace=workspace,
                social_connection=connection,
                user=request.user if request.user.is_authenticated else None,
                action=SocialAccountAuditLog.Action.ACCOUNT_CONNECTION if created else SocialAccountAuditLog.Action.ACCOUNT_RECONNECTION
            )
            
            return APIResponse(success=True, data=SocialConnectionSerializer(connection).data)
        except Exception as e:
            if str(e) == "NOT_CONFIGURED":
                return APIResponse(success=False, error={"code": "NOT_CONFIGURED", "message": f"{platform} integration is not configured yet."})
            return APIResponse(success=False, message=str(e), status=500)

    @action(detail=True, methods=['post'])
    def disconnect(self, request, pk=None):
        connection = self.get_object()
        connection.status = SocialConnection.Status.DISCONNECTED
        connection.disconnected_at = timezone.now()
        connection.save()
        
        SocialAccountAuditLog.objects.create(
            workspace=connection.workspace,
            social_connection=connection,
            user=request.user if request.user.is_authenticated else None,
            action=SocialAccountAuditLog.Action.ACCOUNT_DISCONNECTION
        )
        return APIResponse(success=True, message="Account disconnected")

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        connection = self.get_object()
        adapter = self.get_adapter(connection.platform)
        if not adapter:
            return APIResponse(success=False, message="Adapter missing", status=400)
            
        try:
            access_token = decrypt_token(connection.access_token_encrypted)
            account_info = adapter.get_account_info(access_token)
            connection.status = SocialConnection.Status.CONNECTED
            connection.last_verified_at = timezone.now()
            connection.save()
            return APIResponse(success=True, message="Connection verified")
        except Exception as e:
            connection.status = SocialConnection.Status.TOKEN_EXPIRED
            connection.last_error = str(e)
            connection.save()
            return APIResponse(success=False, message="Verification failed, reauthorization required", status=401)
