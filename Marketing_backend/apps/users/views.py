import logging

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.ai.provisioning import AIProvisioningError, provision_default_ai
from apps.brands.models import Brand
from apps.common.responses import APIResponse
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

from .models import AuthAuditLog, SignupWebsiteClaim, record_auth_event
from .tasks import send_signup_alerts_task
from .serializers import (
    CurrentUserSerializer,
    ScaleezyTokenObtainPairSerializer,
    SignupSerializer,
    normalised_host,
)

logger = logging.getLogger(__name__)
User = get_user_model()


class SignupRateThrottle(AnonRateThrottle):
    """
    Public signup is an unauthenticated write target, so it is bounded per
    client IP. The rate is SIGNUP_THROTTLE_RATE (default 5/hour).

    Counted in Django's default cache. Without a CACHES setting that is
    per-process LocMem, so with N web workers the effective ceiling is up to
    N x the configured rate — adequate as abuse control, not a precise quota.
    REST_FRAMEWORK['NUM_PROXIES'] makes the IP the one the platform proxy
    appended, not the proxy itself; otherwise every signup shares one bucket.
    """

    scope = 'signup'


class SignupView(APIView):
    """
    POST /api/auth/signup/
        {email, password, brand_name, legal_name?, website?, industry?,
         location?, contact_person?, contact_phone?, first_name?, last_name?}
        -> {access, refresh, workspace_id, brand_id, brand_status}

    One transaction creates the user, their workspace, an OWNER membership, a
    PENDING brand and default AI routing — the same bootstrap the add-client
    path does, with the brand held at PENDING. Until a Scaleezy operator
    approves it, calibration is refused (apps.onboarding.services), which is
    the spend a pending client must not be able to incur. If platform AI
    cannot be provisioned the whole signup rolls back, so no half-built client
    is left behind to be repaired by hand.

    No email verification yet: this deployment has no mail backend, and a
    verification step that cannot send mail is a fake control. Rate limiting
    is the real abuse control here; verification is a follow-up once a mail
    provider is chosen.
    """

    permission_classes = [AllowAny]
    throttle_classes = [SignupRateThrottle]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        if not serializer.is_valid():
            first_error = next(iter(serializer.errors.values()), ['Invalid sign-up details.'])
            message = first_error[0] if isinstance(first_error, list) else str(first_error)
            return APIResponse(
                success=False,
                message=str(message),
                error={"code": "VALIDATION_ERROR", "fields": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        email = data['email']

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=data['password'],
                    first_name=data.get('first_name', ''),
                    last_name=data.get('last_name', ''),
                )
                workspace = MarketingWorkspace.objects.create(
                    customer_id='',
                    workspace_name=data.get('workspace_name') or data['brand_name'],
                    approval_status=MarketingWorkspace.Approval.PENDING,
                )
                WorkspaceMember.objects.create(
                    workspace=workspace, user=user, role=WorkspaceMember.Role.OWNER
                )
                brand = Brand.objects.create(
                    workspace=workspace,
                    name=data['brand_name'],
                    legal_name=data.get('legal_name', ''),
                    website=data.get('website', ''),
                    industry=data.get('industry', ''),
                    location=data.get('location', ''),
                    contact_person=data.get('contact_person', ''),
                    contact_phone=data.get('contact_phone', ''),
                    is_default=True,
                    status=Brand.Status.PENDING,
                    created_by=user,
                )
                # The concurrency-safe half of "one company, one enrolment":
                # the serializer's pre-check is friendly, this unique row is
                # what two simultaneous signups cannot both get past.
                host = normalised_host(data.get('website', ''))
                if host:
                    SignupWebsiteClaim.objects.create(website_host=host, workspace=workspace)
                provision_default_ai(workspace)
        except IntegrityError:
            # A simultaneous signup for the same email or the same website
            # got there first; the serializer check is advisory, this is real.
            record_auth_event(
                request, AuthAuditLog.Event.SIGNUP,
                username=email, succeeded=False, reason='duplicate account or website',
            )
            return APIResponse(
                success=False,
                message="An account already exists for this email or website.",
                error={"code": "VALIDATION_ERROR",
                       "fields": {"email": ["An account already exists for this email or website."]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except AIProvisioningError as exc:
            logger.error("Signup rejected, platform AI unavailable: %s", exc)
            record_auth_event(
                request, AuthAuditLog.Event.SIGNUP,
                username=email, succeeded=False, reason='platform AI unavailable',
            )
            return APIResponse(
                success=False,
                message="Sign-up is temporarily unavailable because platform AI is not ready.",
                error={"code": "AI_BOOTSTRAP_UNAVAILABLE", "message": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        record_auth_event(request, AuthAuditLog.Event.SIGNUP, user=user, username=email)
        logger.info(
            "Signup: user=%s workspace=%s brand=%s (pending approval)",
            user.pk, workspace.pk, brand.pk,
        )

        # Announce the signup to Scaleezy (email / WhatsApp, whichever is
        # configured) from the worker. Best effort: the client's signup must
        # not fail because an alert channel is down.
        try:
            send_signup_alerts_task.enqueue(str(brand.pk))
        except Exception as exc:
            logger.error("Signup alert could not be enqueued: %s", exc)

        # Sign the new user straight in: the same token shape as /login/, with
        # the membership claim populated by the same serializer.
        refresh = ScaleezyTokenObtainPairSerializer.get_token(user)
        return APIResponse(
            success=True,
            message="Account created. Your brand is awaiting Scaleezy approval.",
            data={
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'workspace_id': str(workspace.pk),
                'client_code': workspace.client_code,
                'brand_id': str(brand.pk),
                'brand_status': brand.status,
            },
            status=status.HTTP_201_CREATED,
        )


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
        revoked = False
        reason = ''

        if refresh:
            try:
                from rest_framework_simplejwt.tokens import RefreshToken

                RefreshToken(refresh).blacklist()
                revoked = True
            except TokenError as exc:
                # Already expired or already blacklisted — the desired end state.
                revoked = True
                reason = f"token already invalid: {exc}"
            except AttributeError:
                # token_blacklist is not installed. Report this loudly rather
                # than claiming a sign-out that did not happen: the refresh
                # token stays valid and self-renewing for its full lifetime.
                reason = 'token_blacklist app not installed — refresh token NOT revoked'
                logger.error("Logout could not revoke refresh token: %s", reason)
        else:
            reason = 'no refresh token supplied'

        record_auth_event(
            request,
            AuthAuditLog.Event.LOGOUT,
            user=request.user,
            succeeded=revoked,
            reason=reason,
        )

        return APIResponse(
            success=True,
            message="Signed out." if revoked else "Signed out on this device.",
            data={"refresh_token_revoked": revoked},
        )
