from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.brands.models import Brand
from apps.workspaces.models import WorkspaceMember

User = get_user_model()


def normalised_host(url: str) -> str:
    """The comparable identity of a website: lowercase host, no leading www.

    "https://WWW.Acme.com/about" and "acme.com" are one company.
    """
    from urllib.parse import urlsplit

    raw = (url or '').strip()
    if not raw:
        return ''
    if '//' not in raw:
        raw = f'//{raw}'
    host = (urlsplit(raw).hostname or '').lower().strip('.')
    return host[4:] if host.startswith('www.') else host


class SignupSerializer(serializers.Serializer):
    """
    Public signup payload. Validation only — creation is orchestrated by
    SignupView inside one transaction, because the user, workspace, membership,
    brand and AI routing either all exist afterwards or none of them do.

    The email doubles as the username: login is by username, and a second
    identifier people have to remember is a support ticket waiting to happen.
    """

    # 150, not 254: the address becomes the username, whose column is 150.
    email = serializers.EmailField(max_length=150)
    password = serializers.CharField(
        write_only=True, min_length=8, max_length=128, trim_whitespace=False
    )
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)

    # What the client supplies about the brand. `website` is one of the two
    # fields a client will not be able to change after approval, so it is
    # collected here, at the one moment the client is expected to state it.
    brand_name = serializers.CharField(max_length=255)
    website = serializers.URLField(max_length=500, required=False, allow_blank=True)
    industry = serializers.CharField(max_length=100, required=False, allow_blank=True)
    workspace_name = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return email

    def validate_brand_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Brand name is required.")
        return name

    def validate_website(self, value):
        """One company, one enrolment.

        The email check catches the same *person* signing up twice; this
        catches the same *company* doing it from a second address, which is
        the case that actually produces duplicate clients in the approval
        queue. Compared on the registrable host, so www./trailing-slash/scheme
        variants of one site are recognised as the same site.
        """
        website = (value or '').strip()
        if not website:
            return website

        host = normalised_host(website)
        if not host:
            return website

        clash = next(
            (
                brand for brand in Brand.objects.exclude(status=Brand.Status.ARCHIVED)
                .exclude(website='').only('website')
                if normalised_host(brand.website) == host
            ),
            None,
        )
        if clash is not None:
            raise serializers.ValidationError(
                "A Scaleezy client is already registered for this website. "
                "Ask your colleague to add you to it, or contact support."
            )
        return website

    def validate(self, attrs):
        # Run Django's configured validators against an unsaved user so the
        # similarity check sees the email and names it would compare against.
        probe = User(
            username=attrs.get('email', ''),
            email=attrs.get('email', ''),
            first_name=attrs.get('first_name', ''),
            last_name=attrs.get('last_name', ''),
        )
        try:
            validate_password(attrs['password'], user=probe)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs


class WorkspaceMembershipSerializer(serializers.ModelSerializer):
    workspace_id = serializers.UUIDField(source='workspace.id', read_only=True)
    workspace_name = serializers.CharField(source='workspace.workspace_name', read_only=True)

    class Meta:
        model = WorkspaceMember
        fields = ['workspace_id', 'workspace_name', 'role', 'status']


class CurrentUserSerializer(serializers.ModelSerializer):
    """Shape returned by /auth/me/ — identity plus what it can reach."""

    memberships = serializers.SerializerMethodField()
    # A live read of the PlatformAdmin table on every /me/ call — never a
    # cached claim. The frontend uses it only to decide whether to SHOW the
    # console; every platform request is re-gated server-side by
    # IsPlatformAdmin, so a stale or forged value changes nothing.
    is_platform_admin = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'is_staff',
            'is_platform_admin', 'memberships',
        ]
        read_only_fields = fields

    def get_is_platform_admin(self, obj):
        from apps.audit.models import is_platform_admin

        return is_platform_admin(obj)

    def get_memberships(self, obj):
        qs = (
            WorkspaceMember.objects.select_related('workspace')
            .filter(user=obj, status=WorkspaceMember.Status.ACTIVE)
            .order_by('workspace__workspace_name')
        )
        return WorkspaceMembershipSerializer(qs, many=True).data


class ScaleezyTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Adds workspace context to the JWT payload so the frontend can route without
    a second round trip. Roles are still re-checked server-side on every
    request — the claim is a convenience, never the authority.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        memberships = list(
            WorkspaceMember.objects.filter(
                user=user, status=WorkspaceMember.Status.ACTIVE
            ).values('workspace_id', 'role')
        )
        token['memberships'] = [
            {'workspace_id': str(m['workspace_id']), 'role': m['role']} for m in memberships
        ]
        token['email'] = user.email
        return token
