import logging

from rest_framework import mixins, viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.utils import timezone

from .models import SocialConnection, SocialAccountAuditLog
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember
from .serializers import SocialConnectionSerializer, ConnectPlatformSerializer
from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import HasWorkspaceRole, IsWorkspaceMember, authorize_workspace
from apps.common.responses import APIResponse
from .integrations.meta.facebook import FacebookAdapter
from .integrations.meta.instagram import InstagramAdapter
from .integrations.linkedin import LinkedInAdapter
from .integrations.x import XAdapter
from .integrations.youtube.youtube import YouTubeAdapter
from .integrations.exceptions import (
    SocialPlatformError,
    LinkedInAPIError,
    LinkedInConfigurationError,
    LinkedInOAuthError,
    LinkedInStateValidationError,
)
from .integrations.meta.exceptions import MetaAPIError
from .integrations.meta.exceptions import MetaOAuthError
from .integrations.youtube.exceptions import YouTubeOAuthError
from .utils.encryption import encrypt_token, decrypt_token
from .oauth_authority import bind_authority, consume_authority, current_authority

logger = logging.getLogger(__name__)


class SocialConnectionViewSet(
    WorkspaceScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = SocialConnection.objects.all()
    serializer_class = SocialConnectionSerializer
    # OAuth owns creation and disconnect preserves the publishing history.
    # Ordinary resource writes are limited to the serializer's PATCH toggles;
    # custom POST actions remain available, but raw POST/PUT/DELETE do not.
    http_method_names = ['get', 'patch', 'post', 'head', 'options']
    required_role = WorkspaceMember.Role.ADMIN
    required_read_role = WorkspaceMember.Role.VIEWER

    def get_permissions(self):
        # The OAuth callback is reached straight after an external redirect and
        # must not 401 — it carries a single-use authorization code that cannot
        # be replayed. Its state originates in the ADMIN-gated connect action.
        # Every other mutation is account configuration and requires ADMIN;
        # safe reads remain available to every active workspace member.
        if self.action == 'oauth_callback':
            return [AllowAny()]
        return [IsAuthenticated(), IsWorkspaceMember(), HasWorkspaceRole()]

    def get_adapter(self, platform):
        adapters = {
            SocialConnection.Platform.FACEBOOK: FacebookAdapter(),
            SocialConnection.Platform.INSTAGRAM: InstagramAdapter(),
            SocialConnection.Platform.LINKEDIN: LinkedInAdapter(),
            SocialConnection.Platform.X: XAdapter(),
            SocialConnection.Platform.YOUTUBE: YouTubeAdapter(),
        }
        return adapters.get(platform)

    @action(detail=False, methods=['post'])
    def connect(self, request):
        serializer = ConnectPlatformSerializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse(success=False, error=serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        workspace_id = serializer.validated_data['workspace_id']
        platform = serializer.validated_data['platform']

        # This id is bound into the OAuth state and decides which workspace the
        # resulting connection lands in. Authorise it explicitly.
        _m, denied = authorize_workspace(request, workspace_id)
        if denied:
            return denied

        adapter = self.get_adapter(platform)
        if not adapter:
            return APIResponse(success=False, message="Platform not supported yet.", status=status.HTTP_400_BAD_REQUEST)

        try:
            auth_url = adapter.get_authorization_url(workspace_id=str(workspace_id))
            bind_authority(authorization_url=auth_url, workspace=_m.workspace, user=request.user, platform=platform)
            logger.info(f"OAuth connect initiated for platform={platform}")
            return APIResponse(success=True, data={"authorization_url": auth_url})
        except LinkedInConfigurationError as e:
            return APIResponse(
                success=False,
                error={"code": "NOT_CONFIGURED", "message": e.safe_message},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SocialPlatformError as e:
            return APIResponse(
                success=False,
                error={"code": e.error_code, "message": e.safe_message},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MetaAPIError as e:
            return APIResponse(
                success=False,
                error={"code": e.error_code, "message": e.safe_message},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            if str(e) == "NOT_CONFIGURED":
                return APIResponse(
                    success=False,
                    error={"code": "NOT_CONFIGURED", "message": f"{platform} integration is not configured yet."},
                )
            logger.exception(f"Unexpected error during OAuth connect for {platform}")
            return APIResponse(success=False, message="An unexpected error occurred.", status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def oauth_callback(self, request):
        """
        Handle OAuth callback — exchange code for token, fetch account info,
        save connection.
        """
        platform = request.data.get('platform')
        code = request.data.get('code')
        state = request.data.get('state')
        error = request.data.get('error')

        # Handle OAuth errors from the platform
        if error:
            logger.warning(f"OAuth callback received error from {platform}: {error}")
            error_desc = request.data.get('error_description', 'Authorization was not granted.')
            return APIResponse(
                success=False,
                message=error_desc,
                error={"code": "OAUTH_DENIED", "message": error_desc},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not code:
            return APIResponse(
                success=False,
                message="No authorization code received.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        adapter = self.get_adapter(platform)
        if not adapter:
            return APIResponse(success=False, message="Platform not supported", status=400)

        try:
            request.oauth_authority = consume_authority(state=state, platform=platform)
            # ── Platform-specific token exchange ──────────────────────────
            if platform == 'LINKEDIN':
                return self._handle_linkedin_callback(adapter, code, state, request)
            elif platform in ('FACEBOOK', 'INSTAGRAM'):
                return self._handle_meta_callback(adapter, code, state, request)
            elif platform == 'YOUTUBE':
                return self._handle_youtube_callback(adapter, code, state, request)
            elif platform == 'X':
                token_data = adapter.exchange_code_for_token(code, state)
                workspace_id = token_data.get('workspace_id')
            else:
                workspace_id = request.data.get('workspace_id')
                token_data = adapter.exchange_code_for_token(code, "http://localhost:8000")

            if not token_data.get('access_token'):
                raise SocialPlatformError('Missing OAuth access token')
            account_info = adapter.get_account_info(token_data['access_token'])
            if not account_info.get('id'):
                raise SocialPlatformError('Missing account identity')

            workspace = current_authority(request.oauth_authority, workspace_id)

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
                    'last_verified_at': timezone.now(),
                    'token_created_at': timezone.now(),
                    'token_expires_at': (timezone.now() + timezone.timedelta(seconds=int(token_data['expires_in']))) if token_data.get('expires_in') else None,
                    'reauthorization_required': False,
                    'last_error': None,
                    'disconnected_at': None,
                    'publishing_enabled': True,
                    'connected_by_id': request.oauth_authority.user_id,
                }
            )

            # Audit Log
            SocialAccountAuditLog.objects.create(
                workspace=workspace,
                social_connection=connection,
                user_id=request.oauth_authority.user_id,
                action=SocialAccountAuditLog.Action.ACCOUNT_CONNECTION if created else SocialAccountAuditLog.Action.ACCOUNT_RECONNECTION
            )

            logger.info(f"OAuth callback completed for {platform} — connection {'created' if created else 'updated'}")
            return APIResponse(success=True, data=SocialConnectionSerializer(connection).data)

        except SocialPlatformError as e:
            logger.warning(f"OAuth callback failed for {platform}: {e}")
            return APIResponse(
                success=False,
                message=e.safe_message,
                error={"code": e.error_code, "message": e.safe_message},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MetaAPIError as e:
            logger.warning(f"OAuth callback failed for {platform}: {e}")
            return APIResponse(
                success=False,
                message=e.safe_message,
                error={"code": e.error_code, "message": e.safe_message},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MarketingWorkspace.DoesNotExist:
            logger.error(f"OAuth callback — workspace not found")
            return APIResponse(
                success=False,
                message="Workspace not found.",
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            if str(e) == "NOT_CONFIGURED":
                return APIResponse(
                    success=False,
                    error={"code": "NOT_CONFIGURED", "message": f"{platform} integration is not configured yet."},
                )
            logger.exception(f"Unexpected error during OAuth callback for {platform}")
            return APIResponse(
                success=False,
                message="An unexpected error occurred during the connection process.",
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _handle_linkedin_callback(self, adapter, code, state, request):
        """Handle LinkedIn-specific OAuth callback with state-based workspace resolution."""
        # Validate state and get workspace_id
        workspace_id = adapter.validate_state(state)
        logger.info("LinkedIn OAuth callback — state validated")

        # Exchange code for token
        token_data = adapter.exchange_code_for_token(code)
        access_token = token_data.get('access_token')

        if not access_token:
            raise LinkedInOAuthError("No access token received from LinkedIn")

        # Fetch account info
        account_info = adapter.get_account_info(access_token)
        logger.info("LinkedIn account info retrieved")

        # Get publishable destinations
        member_sub = account_info.get('id')
        destinations = adapter.get_publishable_destinations(access_token, member_sub)

        if not member_sub:
            raise LinkedInOAuthError('No account identity received from LinkedIn')
        workspace = current_authority(request.oauth_authority, workspace_id)

        # Compute token expiration
        expires_in = token_data.get('expires_in')
        token_expires_at = None
        if expires_in:
            token_expires_at = timezone.now() + timezone.timedelta(seconds=int(expires_in))

        # Determine account type
        account_type = 'member'
        if destinations and len(destinations) > 1:
            # Has organization pages available
            account_type = 'member+organization'

        # Create or update connection
        connection, created = SocialConnection.objects.update_or_create(
            workspace=workspace,
            platform=SocialConnection.Platform.LINKEDIN,
            external_account_id=member_sub,
            defaults={
                'account_name': account_info.get('name', 'LinkedIn User'),
                'username': account_info.get('email', ''),
                'profile_url': f"https://www.linkedin.com/in/{member_sub}",
                'profile_image_url': account_info.get('profile_image_url'),
                'account_type': account_type,
                'oauth_provider': 'linkedin',
                'oauth_user_id': member_sub,
                'connected_user_name': account_info.get('name'),
                'connected_user_email': account_info.get('email'),
                'status': SocialConnection.Status.CONNECTED,
                'access_token_encrypted': encrypt_token(access_token),
                'refresh_token_encrypted': encrypt_token(token_data.get('refresh_token')),
                'token_created_at': timezone.now(),
                'token_expires_at': token_expires_at,
                'scopes': token_data.get('scopes', ''),
                'last_verified_at': timezone.now(),
                'publishing_enabled': True,
                'reauthorization_required': False,
                'last_error': None,
                'disconnected_at': None,
                'connected_by_id': request.oauth_authority.user_id,
            }
        )

        # Audit Log
        SocialAccountAuditLog.objects.create(
            workspace=workspace,
            social_connection=connection,
            user_id=request.oauth_authority.user_id,
            action=(
                SocialAccountAuditLog.Action.ACCOUNT_CONNECTION
                if created
                else SocialAccountAuditLog.Action.ACCOUNT_RECONNECTION
            ),
        )

        logger.info(
            f"LinkedIn connection {'created' if created else 'updated'} "
            f"for workspace — account_type={account_type}"
        )
        return APIResponse(success=True, data=SocialConnectionSerializer(connection).data)

    @action(detail=True, methods=['post'])
    def disconnect(self, request, pk=None):
        connection = self.get_object()

        # Attempt platform-side disconnect
        adapter = self.get_adapter(connection.platform)
        revoked = False
        if adapter and connection.access_token_encrypted:
            try:
                access_token = decrypt_token(connection.access_token_encrypted)
                revoked = adapter.disconnect(access_token) is True
            except Exception:
                logger.warning('Remote social revocation was not confirmed for %s', connection.pk)

        # Clear credentials and mark disconnected
        connection.status = SocialConnection.Status.DISCONNECTED
        connection.disconnected_at = timezone.now()
        connection.access_token_encrypted = None
        connection.refresh_token_encrypted = None
        connection.publishing_enabled = False
        connection.save()

        SocialAccountAuditLog.objects.create(
            workspace=connection.workspace,
            social_connection=connection,
            user=request.user if request.user.is_authenticated else None,
            action=SocialAccountAuditLog.Action.ACCOUNT_DISCONNECTION,
            new_value='remote_revocation_confirmed' if revoked else 'local_disconnect_only',
        )

        logger.info(f"Social connection disconnected: platform={connection.platform}")
        return APIResponse(success=True, message=(
            "Account disconnected and remote access revoked." if revoked else
            "Disconnected from Scaleezy. Remote revocation was not confirmed; remove access in the social platform's settings if needed."
        ), data={'remote_revocation_confirmed': revoked})

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        connection = self.get_object()
        if connection.status == SocialConnection.Status.DISCONNECTED or not connection.access_token_encrypted:
            return APIResponse(success=False, message="Reconnect this account before verifying it.", status=400)
        adapter = self.get_adapter(connection.platform)
        if not adapter:
            return APIResponse(success=False, message="Adapter missing", status=400)

        try:
            access_token = decrypt_token(connection.access_token_encrypted)
            account_info = adapter.get_account_info(access_token)
            if not account_info or (not account_info.get('id') and not account_info.get('accounts')):
                raise SocialPlatformError('Provider returned no verifiable account')
            connection.status = SocialConnection.Status.CONNECTED
            connection.last_verified_at = timezone.now()
            connection.last_error = None
            connection.reauthorization_required = False
            connection.save()
            SocialAccountAuditLog.objects.create(workspace=connection.workspace, social_connection=connection, user=request.user, action=SocialAccountAuditLog.Action.PERMISSION_UPDATE, new_value='VERIFIED')
            return APIResponse(success=True, message="Connection verified")
        except Exception as e:
            code = str(getattr(e, 'error_code', ''))
            expired = code.endswith('AUTH_FAILED') or getattr(e, 'status_code', None) == 401
            denied = code.endswith('PERMISSION_DENIED') or getattr(e, 'status_code', None) == 403
            if expired or denied:
                connection.status = SocialConnection.Status.TOKEN_EXPIRED if expired else SocialConnection.Status.PERMISSION_MISSING
                connection.reauthorization_required = True
            connection.last_error = ('Reconnect this account to restore access.' if expired or denied else 'Verification is temporarily unavailable. Retry without reconnecting.')
            connection.save(update_fields=['status', 'reauthorization_required', 'last_error', 'updated_at'])
            SocialAccountAuditLog.objects.create(workspace=connection.workspace, social_connection=connection, user=request.user, action=SocialAccountAuditLog.Action.PERMISSION_UPDATE, new_value='VERIFICATION_FAILED', error_message=connection.last_error)
            return APIResponse(success=False, message=connection.last_error, status=400 if expired or denied else 502)

    def perform_update(self, serializer):
        before = serializer.instance.publishing_enabled
        connection = serializer.save()
        if connection.publishing_enabled != before:
            SocialAccountAuditLog.objects.create(
                workspace=connection.workspace, social_connection=connection, user=self.request.user,
                action=SocialAccountAuditLog.Action.PUBLISHING_ENABLED if connection.publishing_enabled else SocialAccountAuditLog.Action.PUBLISHING_DISABLED,
                old_value=str(before), new_value=str(connection.publishing_enabled),
            )

    @action(detail=False, methods=['get'])
    def linkedin_status(self, request):
        """Check LinkedIn connection status for a workspace."""
        workspace_id = request.query_params.get('workspace_id')
        if not workspace_id:
            return APIResponse(success=False, message="workspace_id is required", status=400)

        # Authorise the workspace this action reads, not the one the permission
        # class resolved — otherwise the header could name the caller's own
        # workspace while this query targets somebody else's connection and
        # decrypts their OAuth token.
        _m, denied = authorize_workspace(request, workspace_id)
        if denied:
            return denied

        # Authorise the workspace this action reads, not the one the permission
        # class resolved — otherwise the header could name the caller's own
        # workspace while this query targets somebody else's connection and
        # decrypts their OAuth token.
        _m, denied = authorize_workspace(request, workspace_id)
        if denied:
            return denied

        try:
            connection = SocialConnection.objects.filter(
                workspace_id=workspace_id,
                platform=SocialConnection.Platform.LINKEDIN,
            ).exclude(status=SocialConnection.Status.DISCONNECTED).first()

            if not connection:
                return APIResponse(success=True, data={
                    "connected": False,
                    "status": "NOT_CONNECTED",
                })

            return APIResponse(success=True, data={
                "connected": connection.status == SocialConnection.Status.CONNECTED,
                "status": connection.status,
                "account_name": connection.account_name,
                "account_type": connection.account_type,
                "connected_at": connection.connected_at.isoformat() if connection.connected_at else None,
            })
        except Exception as e:
            logger.exception("Error checking LinkedIn status")
            return APIResponse(success=False, message="Could not check connection status.", status=500)

    @action(detail=False, methods=['get'])
    def linkedin_destinations(self, request):
        """Retrieve publishable destinations for a LinkedIn connection."""
        workspace_id = request.query_params.get('workspace_id')
        if not workspace_id:
            return APIResponse(success=False, message="workspace_id is required", status=400)

        _membership, denied = authorize_workspace(request, workspace_id)
        if denied:
            return denied

        try:
            connection = SocialConnection.objects.filter(
                workspace_id=workspace_id,
                platform=SocialConnection.Platform.LINKEDIN,
                status=SocialConnection.Status.CONNECTED,
            ).order_by('-connected_at').first()
            if connection is None:
                raise SocialConnection.DoesNotExist
        except SocialConnection.DoesNotExist:
            return APIResponse(
                success=False,
                message="No connected LinkedIn account found.",
                status=404,
            )

        try:
            adapter = LinkedInAdapter()
            access_token = decrypt_token(connection.access_token_encrypted)
            destinations = adapter.get_publishable_destinations(access_token, connection.external_account_id)
            return APIResponse(success=True, data={"destinations": destinations})
        except SocialPlatformError as e:
            return APIResponse(success=False, message=e.safe_message, status=400)
        except Exception:
            logger.exception("Error fetching LinkedIn destinations")
            return APIResponse(success=False, message="Could not fetch publishing destinations.", status=500)

    def _handle_meta_callback(self, adapter, code, state, request):
        """Handle Meta (Facebook & Instagram) unified OAuth callback."""
        # Validate state and get workspace_id
        workspace_id = adapter.validate_state(state)
        logger.info("Meta OAuth callback — state validated")

        # Exchange code for token
        token_data = adapter.exchange_code_for_token(code)
        access_token = token_data.get('access_token')

        if not access_token:
            raise MetaOAuthError("No access token received from Meta")

        # Fetch all FB pages and IG accounts
        account_info = adapter.get_account_info(access_token)
        accounts = account_info.get('accounts', [])
        if not accounts or any(not acc.get('id') or not acc.get('access_token') or acc.get('platform') not in ('FACEBOOK', 'INSTAGRAM') for acc in accounts):
            raise MetaOAuthError('No usable Facebook or Instagram accounts were authorized. Check page permissions and reconnect.')
        logger.info(f"Meta returned {len(accounts)} accounts.")

        workspace = current_authority(request.oauth_authority, workspace_id)

        # Compute token expiration
        expires_in = token_data.get('expires_in')
        token_expires_at = None
        if expires_in:
            token_expires_at = timezone.now() + timezone.timedelta(seconds=int(expires_in))

        created_connections = []

        for acc in accounts:
            acc_platform = acc.get('platform') # 'FACEBOOK' or 'INSTAGRAM'
            acc_id = acc.get('id')
            
            # Map platform to model enum
            platform_enum = SocialConnection.Platform.FACEBOOK if acc_platform == 'FACEBOOK' else SocialConnection.Platform.INSTAGRAM
            
            connection, created = SocialConnection.objects.update_or_create(
                workspace=workspace,
                platform=platform_enum,
                external_account_id=acc_id,
                defaults={
                    'account_name': acc.get('name', 'Unknown Meta Account'),
                    'username': acc.get('username', ''),
                    'profile_image_url': acc.get('picture'),
                    'account_type': acc.get('account_type', 'organization'),
                    'oauth_provider': 'facebook', # Both use FB OAuth
                    'oauth_user_id': acc_id,
                    'status': SocialConnection.Status.CONNECTED,
                    'access_token_encrypted': encrypt_token(acc.get('access_token')),
                    'refresh_token_encrypted': encrypt_token(token_data.get('refresh_token')),
                    'token_created_at': timezone.now(),
                    'token_expires_at': token_expires_at,
                    'scopes': token_data.get('scopes', ''),
                    'last_verified_at': timezone.now(),
                    'publishing_enabled': True,
                    'reauthorization_required': False,
                    'last_error': None,
                    'disconnected_at': None,
                    'connected_by_id': request.oauth_authority.user_id,
                }
            )

            # Audit Log
            SocialAccountAuditLog.objects.create(
                workspace=workspace,
                social_connection=connection,
                user_id=request.oauth_authority.user_id,
                action=SocialAccountAuditLog.Action.ACCOUNT_CONNECTION if created else SocialAccountAuditLog.Action.ACCOUNT_RECONNECTION
            )
            created_connections.append(SocialConnectionSerializer(connection).data)

        logger.info(f"Meta OAuth callback completed — synced {len(created_connections)} accounts.")
        
        # We return the list of all synced accounts for Meta
        return APIResponse(success=True, data={"synced_accounts": created_connections})

    def _handle_youtube_callback(self, adapter, code, state, request):
        """Handle YouTube OAuth callback."""
        workspace_id = adapter.validate_state(state)
        logger.info("YouTube OAuth callback — state validated")

        # Exchange code for token
        token_data = adapter.exchange_code_for_token(code)
        access_token = token_data.get('access_token')

        if not access_token:
            raise YouTubeOAuthError("No access token received from YouTube")

        # Fetch channel info
        account_info = adapter.get_account_info(access_token)
        logger.info("YouTube channel info retrieved")

        if not account_info.get('id'):
            raise YouTubeOAuthError('No YouTube channel identity was returned.')
        workspace = current_authority(request.oauth_authority, workspace_id)

        # Compute token expiration
        expires_in = token_data.get('expires_in')
        token_expires_at = None
        if expires_in:
            token_expires_at = timezone.now() + timezone.timedelta(seconds=int(expires_in))

        defaults = {
            'account_name': account_info.get('name', 'YouTube Channel'),
            'username': account_info.get('username', ''),
            'profile_image_url': account_info.get('profile_image_url'),
            'account_type': account_info.get('account_type', 'organization'),
            'oauth_provider': 'google',
            'oauth_user_id': account_info['id'],
            'status': SocialConnection.Status.CONNECTED,
            'access_token_encrypted': encrypt_token(access_token),
            'token_created_at': timezone.now(),
            'token_expires_at': token_expires_at,
            'scopes': token_data.get('scopes', ''),
            'last_verified_at': timezone.now(),
            'publishing_enabled': True,
            'reauthorization_required': False,
            'last_error': None,
            'disconnected_at': None,
            'connected_by_id': request.oauth_authority.user_id,
        }

        # Google returns a refresh token only on the first authorization. Only
        # overwrite the stored one when a new one actually came back, otherwise
        # reconnecting would wipe our ability to refresh offline.
        refresh_token = token_data.get('refresh_token')
        if refresh_token:
            defaults['refresh_token_encrypted'] = encrypt_token(refresh_token)

        # Create or update connection
        connection, created = SocialConnection.objects.update_or_create(
            workspace=workspace,
            platform=SocialConnection.Platform.YOUTUBE,
            external_account_id=account_info['id'],
            defaults=defaults,
        )

        # Audit Log
        SocialAccountAuditLog.objects.create(
            workspace=workspace,
            social_connection=connection,
            user_id=request.oauth_authority.user_id,
            action=SocialAccountAuditLog.Action.ACCOUNT_CONNECTION if created else SocialAccountAuditLog.Action.ACCOUNT_RECONNECTION
        )

        logger.info(f"YouTube OAuth callback completed — connection {'created' if created else 'updated'}")
        return APIResponse(success=True, data=SocialConnectionSerializer(connection).data)
