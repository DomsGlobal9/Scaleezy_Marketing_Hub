import uuid
from django.db import models
from apps.workspaces.models import MarketingWorkspace
from django.contrib.auth import get_user_model

User = get_user_model()

class SocialConnection(models.Model):
    class Platform(models.TextChoices):
        FACEBOOK = 'FACEBOOK', 'Facebook'
        INSTAGRAM = 'INSTAGRAM', 'Instagram'
        LINKEDIN = 'LINKEDIN', 'LinkedIn'
        X = 'X', 'X'
        TIKTOK = 'TIKTOK', 'TikTok'
        YOUTUBE = 'YOUTUBE', 'YouTube'
        GOOGLE_BUSINESS = 'GOOGLE_BUSINESS', 'Google Business Profile'

    class Status(models.TextChoices):
        NOT_CONNECTED = 'NOT_CONNECTED', 'Not Connected'
        CONNECTING = 'CONNECTING', 'Connecting'
        CONNECTED = 'CONNECTED', 'Connected'
        PERMISSION_MISSING = 'PERMISSION_MISSING', 'Permission Missing'
        TOKEN_EXPIRED = 'TOKEN_EXPIRED', 'Token Expired'
        REAUTHORIZATION_REQUIRED = 'REAUTHORIZATION_REQUIRED', 'Reauthorization Required'
        REVOKED = 'REVOKED', 'Revoked'
        CONNECTION_FAILED = 'CONNECTION_FAILED', 'Connection Failed'
        PUBLISHING_DISABLED = 'PUBLISHING_DISABLED', 'Publishing Disabled'
        DISCONNECTED = 'DISCONNECTED', 'Disconnected'
        PLATFORM_UNAVAILABLE = 'PLATFORM_UNAVAILABLE', 'Platform Unavailable'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(MarketingWorkspace, on_delete=models.CASCADE, related_name='social_connections')
    platform = models.CharField(max_length=50, choices=Platform.choices)
    account_type = models.CharField(max_length=50, blank=True, null=True)
    external_account_id = models.CharField(max_length=255)
    account_name = models.CharField(max_length=255)
    username = models.CharField(max_length=255, blank=True, null=True)
    profile_url = models.URLField(max_length=1000, blank=True, null=True)
    profile_image_url = models.URLField(max_length=1000, blank=True, null=True)

    connected_user_id = models.CharField(max_length=255, blank=True, null=True)
    connected_user_name = models.CharField(max_length=255, blank=True, null=True)
    connected_user_email = models.EmailField(blank=True, null=True)
    user_role = models.CharField(max_length=50, blank=True, null=True)

    oauth_provider = models.CharField(max_length=50, blank=True, null=True)
    oauth_user_id = models.CharField(max_length=255, blank=True, null=True)

    access_token_encrypted = models.TextField(blank=True, null=True)
    refresh_token_encrypted = models.TextField(blank=True, null=True)

    token_created_at = models.DateTimeField(blank=True, null=True)
    token_expires_at = models.DateTimeField(blank=True, null=True)
    last_token_refresh_at = models.DateTimeField(blank=True, null=True)

    scopes = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=50, choices=Status.choices, default=Status.NOT_CONNECTED)

    publishing_enabled = models.BooleanField(default=True)
    is_default_account = models.BooleanField(default=False)

    last_verified_at = models.DateTimeField(blank=True, null=True)
    last_published_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True, null=True)

    connected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='connected_social_accounts')
    connected_at = models.DateTimeField(auto_now_add=True)
    disconnected_at = models.DateTimeField(blank=True, null=True)

    reauthorization_required = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'social_connections'
        unique_together = ('workspace', 'platform', 'external_account_id')

    def __str__(self):
        return f"{self.platform} - {self.account_name}"


class SocialAccountSettings(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    social_connection = models.OneToOneField(SocialConnection, on_delete=models.CASCADE, related_name='settings')

    timezone = models.CharField(max_length=50, default='UTC')
    allowed_start_time = models.TimeField(blank=True, null=True)
    allowed_end_time = models.TimeField(blank=True, null=True)

    daily_post_limit = models.IntegerField(default=10)

    automatic_retry_enabled = models.BooleanField(default=True)
    comments_enabled = models.BooleanField(default=True)
    analytics_enabled = models.BooleanField(default=True)

    publishing_paused = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'social_account_settings'

    def __str__(self):
        return f"Settings for {self.social_connection}"


class SocialAccountAuditLog(models.Model):
    class Action(models.TextChoices):
        ACCOUNT_CONNECTION = 'ACCOUNT_CONNECTION', 'Account Connection'
        OAUTH_AUTHORIZATION = 'OAUTH_AUTHORIZATION', 'OAuth Authorization'
        PERMISSION_UPDATE = 'PERMISSION_UPDATE', 'Permission Update'
        TOKEN_REFRESH = 'TOKEN_REFRESH', 'Token Refresh'
        ACCOUNT_RECONNECTION = 'ACCOUNT_RECONNECTION', 'Account Reconnection'
        ACCOUNT_DISCONNECTION = 'ACCOUNT_DISCONNECTION', 'Account Disconnection'
        ACCESS_REVOCATION = 'ACCESS_REVOCATION', 'Access Revocation'
        PUBLISHING_ENABLED = 'PUBLISHING_ENABLED', 'Publishing Enabled'
        PUBLISHING_DISABLED = 'PUBLISHING_DISABLED', 'Publishing Disabled'
        PUBLISHING_PAUSED = 'PUBLISHING_PAUSED', 'Publishing Paused'
        PUBLISHING_RESUMED = 'PUBLISHING_RESUMED', 'Publishing Resumed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(MarketingWorkspace, on_delete=models.CASCADE, related_name='social_audit_logs')
    social_connection = models.ForeignKey(SocialConnection, on_delete=models.SET_NULL, null=True, related_name='audit_logs')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    action = models.CharField(max_length=50, choices=Action.choices)

    old_value = models.TextField(blank=True, null=True)
    new_value = models.TextField(blank=True, null=True)

    error_message = models.TextField(blank=True, null=True)

    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'social_account_audit_logs'

    def __str__(self):
        return f"{self.action} on {self.created_at}"
