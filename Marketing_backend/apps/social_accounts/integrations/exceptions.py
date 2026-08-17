"""
Custom exceptions for social platform integrations.

These provide clean error handling that maps platform-specific API errors
to safe, user-friendly messages without exposing internal details.
"""


class SocialPlatformError(Exception):
    """Base exception for all social platform integration errors."""

    def __init__(self, message: str, safe_message: str = None, error_code: str = None):
        self.safe_message = safe_message or "An unexpected error occurred with the social platform."
        self.error_code = error_code or "PLATFORM_ERROR"
        super().__init__(message)


# ── LinkedIn Exceptions ──────────────────────────────────────────────────────


class LinkedInAPIError(SocialPlatformError):
    """Base exception for LinkedIn API errors."""

    def __init__(self, message: str, safe_message: str = None, error_code: str = None,
                 status_code: int = None):
        self.status_code = status_code
        super().__init__(
            message,
            safe_message=safe_message or "LinkedIn encountered an error. Please try again later.",
            error_code=error_code or "LINKEDIN_API_ERROR",
        )


class LinkedInConfigurationError(LinkedInAPIError):
    """LinkedIn integration is not configured."""

    def __init__(self, message: str = "LinkedIn integration is not configured."):
        super().__init__(
            message,
            safe_message="LinkedIn integration is not configured. Please contact your administrator.",
            error_code="LINKEDIN_NOT_CONFIGURED",
        )


class LinkedInAuthenticationError(LinkedInAPIError):
    """LinkedIn authentication failed (401)."""

    def __init__(self, message: str = "LinkedIn authentication failed."):
        super().__init__(
            message,
            safe_message="LinkedIn authentication failed. Please reconnect your LinkedIn account.",
            error_code="LINKEDIN_AUTH_FAILED",
            status_code=401,
        )


class LinkedInPermissionError(LinkedInAPIError):
    """Insufficient LinkedIn permissions (403)."""

    def __init__(self, message: str = "Insufficient LinkedIn permissions."):
        super().__init__(
            message,
            safe_message="Your LinkedIn account does not have the required permissions for this action.",
            error_code="LINKEDIN_PERMISSION_DENIED",
            status_code=403,
        )


class LinkedInPublishingError(LinkedInAPIError):
    """LinkedIn publishing failed."""

    def __init__(self, message: str = "LinkedIn publishing failed."):
        super().__init__(
            message,
            safe_message="Failed to publish to LinkedIn. Please check your content and try again.",
            error_code="LINKEDIN_PUBLISH_FAILED",
        )


class LinkedInMediaUploadError(LinkedInAPIError):
    """LinkedIn media upload failed."""

    def __init__(self, message: str = "LinkedIn media upload failed."):
        super().__init__(
            message,
            safe_message="Failed to upload media to LinkedIn. Please try again.",
            error_code="LINKEDIN_MEDIA_UPLOAD_FAILED",
        )


class LinkedInRateLimitError(LinkedInAPIError):
    """LinkedIn rate limit exceeded (429)."""

    def __init__(self, message: str = "LinkedIn rate limit exceeded."):
        super().__init__(
            message,
            safe_message="LinkedIn rate limit reached. Please wait a few minutes and try again.",
            error_code="LINKEDIN_RATE_LIMITED",
            status_code=429,
        )


class LinkedInOAuthError(LinkedInAPIError):
    """LinkedIn OAuth flow error."""

    def __init__(self, message: str = "LinkedIn OAuth error.", oauth_error: str = None):
        self.oauth_error = oauth_error
        safe_msg = "LinkedIn authorization failed."
        if oauth_error == "user_cancelled_authorize":
            safe_msg = "You cancelled the LinkedIn authorization. Please try again when ready."
        elif oauth_error == "user_cancelled_login":
            safe_msg = "You cancelled the LinkedIn login. Please try again when ready."
        super().__init__(
            message,
            safe_message=safe_msg,
            error_code="LINKEDIN_OAUTH_ERROR",
        )


class LinkedInStateValidationError(LinkedInAPIError):
    """OAuth state validation failed — possible CSRF."""

    def __init__(self, message: str = "Invalid or expired OAuth state."):
        super().__init__(
            message,
            safe_message="The authorization session has expired or is invalid. Please try connecting again.",
            error_code="LINKEDIN_INVALID_STATE",
        )
