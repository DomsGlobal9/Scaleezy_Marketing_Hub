import logging

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.common.responses import APIResponse

from .models import AuthAuditLog, record_auth_event
from .serializers import CurrentUserSerializer, ScaleezyTokenObtainPairSerializer

logger = logging.getLogger(__name__)


class LoginView(TokenObtainPairView):
    """
    POST /api/auth/login/  {username, password} -> {access, refresh}

    Every attempt, successful or not, is written to AuthAuditLog.
    """

    serializer_class = ScaleezyTokenObtainPairSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        username = str(request.data.get('username', ''))[:255]
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except (TokenError, InvalidToken) as exc:
            record_auth_event(
                request, AuthAuditLog.Event.LOGIN_FAILED,
                username=username, succeeded=False, reason=str(exc)[:255],
            )
            raise InvalidToken(exc.args[0])
        except Exception as exc:
            record_auth_event(
                request, AuthAuditLog.Event.LOGIN_FAILED,
                username=username, succeeded=False, reason='Invalid credentials',
            )
            logger.info("Login failed for %r", username)
            # Deliberately generic: never reveal whether the account exists.
            return APIResponse(
                success=False,
                message="Invalid username or password.",
                error={"code": "INVALID_CREDENTIALS", "message": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = serializer.user
        record_auth_event(
            request, AuthAuditLog.Event.LOGIN_SUCCESS, user=user, username=username
        )
        logger.info("Login succeeded for user=%s", user.pk)
        return APIResponse(success=True, data=serializer.validated_data)


class RefreshView(TokenRefreshView):
    """POST /api/auth/refresh/  {refresh} -> {access}"""

    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            record_auth_event(
                request, AuthAuditLog.Event.TOKEN_REFRESH_FAILED,
                succeeded=False, reason='Invalid or expired refresh token',
            )
            return APIResponse(
                success=False,
                message="Session expired. Please sign in again.",
                error={"code": "TOKEN_INVALID", "message": "Session expired."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        record_auth_event(request, AuthAuditLog.Event.TOKEN_REFRESH)
        return APIResponse(success=True, data=serializer.validated_data)


class MeView(APIView):
    """GET /api/auth/me/ -> the caller plus their workspace memberships."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return APIResponse(success=True, data=CurrentUserSerializer(request.user).data)


class LogoutView(APIView):
    """
    POST /api/auth/logout/  {refresh}

    Blacklists the refresh token when the blacklist app is installed; the access
    token remains valid until it expires, which is inherent to stateless JWT.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get('refresh')
        if refresh:
            try:
                from rest_framework_simplejwt.tokens import RefreshToken

                RefreshToken(refresh).blacklist()
            except Exception:
                # Blacklist app not installed, or token already unusable.
                # Logging out must not fail because of this.
                logger.debug("Refresh token could not be blacklisted", exc_info=True)

        record_auth_event(request, AuthAuditLog.Event.LOGOUT, user=request.user)
        return APIResponse(success=True, message="Signed out.")
