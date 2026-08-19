"""
Custom exceptions for Meta (Facebook & Instagram) API interactions.
"""

class MetaAPIError(Exception):
    """Base exception for all Meta API errors."""
    def __init__(self, message: str, error_code: str = "META_API_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)

    @property
    def safe_message(self) -> str:
        return self.message


class MetaAuthenticationError(MetaAPIError):
    """Raised when the access token is invalid, expired, or missing."""
    def __init__(self, message: str = "Authentication failed. Please reconnect your Meta account."):
        super().__init__(message, "META_AUTH_FAILED")


class MetaPermissionError(MetaAPIError):
    """Raised when the token lacks necessary permissions (scopes)."""
    def __init__(self, message: str = "Permission denied. Please ensure all requested permissions were granted during connection."):
        super().__init__(message, "META_PERMISSION_DENIED")


class MetaRateLimitError(MetaAPIError):
    """Raised when the Meta Graph API rate limit is exceeded."""
    def __init__(self, message: str = "Rate limit exceeded. Please try again later."):
        super().__init__(message, "META_RATE_LIMITED")


class MetaOAuthError(MetaAPIError):
    """Raised when OAuth flow fails (e.g., user denied access)."""
    def __init__(self, message: str = "Meta authorization failed or was cancelled.", oauth_error: str = None):
        if oauth_error == "access_denied":
            message = "You cancelled the Meta connection process."
        super().__init__(message, "META_OAUTH_ERROR")


class MetaStateValidationError(MetaAPIError):
    """Raised when the OAuth state parameter is invalid or expired."""
    def __init__(self, message: str = "Authorization session expired or invalid. Please try connecting again."):
        super().__init__(message, "META_STATE_INVALID")


class MetaConfigurationError(MetaAPIError):
    """Raised when the backend is missing Meta App configuration."""
    def __init__(self, message: str = "Meta integration is not fully configured."):
        super().__init__(message, "META_NOT_CONFIGURED")


class MetaPublishingError(MetaAPIError):
    """Raised when publishing a post fails."""
    def __init__(self, message: str = "Failed to publish post to Meta."):
        super().__init__(message, "META_PUBLISHING_ERROR")


class MetaMediaUploadError(MetaAPIError):
    """Raised when uploading media for a post fails (especially for Instagram)."""
    def __init__(self, message: str = "Failed to upload or process media for Meta."):
        super().__init__(message, "META_MEDIA_UPLOAD_ERROR")
