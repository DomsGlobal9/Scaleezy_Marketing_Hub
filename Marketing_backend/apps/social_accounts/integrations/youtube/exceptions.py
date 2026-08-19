"""
Custom exceptions for YouTube API interactions.
"""

class YouTubeAPIError(Exception):
    """Base exception for all YouTube API errors."""
    def __init__(self, message: str, error_code: str = "YOUTUBE_API_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)

    @property
    def safe_message(self) -> str:
        return self.message


class YouTubeAuthenticationError(YouTubeAPIError):
    """Raised when the access token is invalid, expired, or missing."""
    def __init__(self, message: str = "Authentication failed. Please reconnect your YouTube account."):
        super().__init__(message, "YOUTUBE_AUTH_FAILED")


class YouTubePermissionError(YouTubeAPIError):
    """Raised when the token lacks necessary permissions (scopes)."""
    def __init__(self, message: str = "Permission denied. Please ensure all requested permissions were granted during connection."):
        super().__init__(message, "YOUTUBE_PERMISSION_DENIED")


class YouTubeRateLimitError(YouTubeAPIError):
    """Raised when the YouTube API quota is exceeded."""
    def __init__(self, message: str = "YouTube API quota exceeded. Please try again later."):
        super().__init__(message, "YOUTUBE_QUOTA_EXCEEDED")


class YouTubeOAuthError(YouTubeAPIError):
    """Raised when OAuth flow fails (e.g., user denied access)."""
    def __init__(self, message: str = "YouTube authorization failed or was cancelled."):
        super().__init__(message, "YOUTUBE_OAUTH_ERROR")


class YouTubeStateValidationError(YouTubeAPIError):
    """Raised when the OAuth state parameter is invalid or expired."""
    def __init__(self, message: str = "Authorization session expired or invalid. Please try connecting again."):
        super().__init__(message, "YOUTUBE_STATE_INVALID")


class YouTubeConfigurationError(YouTubeAPIError):
    """Raised when the backend is missing YouTube App configuration."""
    def __init__(self, message: str = "YouTube integration is not fully configured."):
        super().__init__(message, "YOUTUBE_NOT_CONFIGURED")


class YouTubePublishingError(YouTubeAPIError):
    """Raised when publishing a video fails."""
    def __init__(self, message: str = "Failed to upload video to YouTube."):
        super().__init__(message, "YOUTUBE_PUBLISHING_ERROR")


class YouTubeMediaUploadError(YouTubeAPIError):
    """Raised when media upload fails."""
    def __init__(self, message: str = "Failed to process video for YouTube."):
        super().__init__(message, "YOUTUBE_MEDIA_UPLOAD_ERROR")
