import logging
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised when an upload genuinely failed and the caller must know."""


class SupabaseStorageService:
    BUCKET = 'Marketing_Poster_images'

    @staticmethod
    def _mock_url(workspace_id: str, filename: str) -> str:
        return f"https://mock-storage.url/workspace_{workspace_id}/{uuid.uuid4()}_{filename}"

    @classmethod
    def upload_file(cls, workspace_id: str, file_obj, filename: str, *,
                    strict: bool = False, prefix: str = 'workspace') -> str:
        """
        Uploads to Supabase Storage and returns the public URL.

        `strict=True` raises StorageError instead of returning a placeholder.
        Non-strict is the historical behaviour and is kept for the asset
        library, but it is genuinely dangerous: the row is created pointing at
        a URL that serves nothing, and the failure only surfaces later when
        publishing tries to fetch the media.
        """
        if getattr(settings, 'STORAGE_TEST_MODE', False):
            # Deterministic, and above the `strict` check on purpose: a strict
            # caller under test wants the success path exercised, not a live
            # upload to whatever bucket the developer's .env points at.
            return f"https://storage.test/{prefix}/{workspace_id}/{filename}"

        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            if strict:
                raise StorageError(
                    "File storage is not configured. Set SUPABASE_URL and "
                    "SUPABASE_SERVICE_ROLE_KEY."
                )
            logger.warning("[Storage Mock] %s for workspace %s", filename, workspace_id)
            return cls._mock_url(workspace_id, filename)

        import requests

        # SUPABASE_URL is stored with /rest/v1/ appended for the data API.
        base_url = (
            settings.SUPABASE_URL.replace("/rest/v1/", "").replace("/rest/v1", "").rstrip("/")
        )
        path = f"{prefix}/{workspace_id}/{uuid.uuid4()}_{filename}"
        upload_url = f"{base_url}/storage/v1/object/{cls.BUCKET}/{path}"
        headers = {
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": getattr(file_obj, 'content_type', None) or "application/octet-stream",
        }

        try:
            res = requests.post(upload_url, headers=headers, data=file_obj.read(), timeout=60)
        except Exception as exc:
            logger.exception("Supabase upload failed for %s", filename)
            if strict:
                raise StorageError(f"Upload failed: {exc}") from exc
            return cls._mock_url(workspace_id, filename)

        if not res.ok:
            logger.error("Supabase upload rejected (%s): %s", res.status_code, res.text[:300])
            if strict:
                raise StorageError(f"Storage rejected the upload ({res.status_code}).")
            return cls._mock_url(workspace_id, filename)

        return f"{base_url}/storage/v1/object/public/{cls.BUCKET}/{path}"

    @classmethod
    def upload_and_describe(cls, workspace_id: str, file_obj, filename: str, *,
                            prefix: str = 'workspace') -> dict:
        """Strict upload returning both the public URL and the storage path."""
        url = cls.upload_file(
            workspace_id, file_obj, filename, strict=True, prefix=prefix
        )
        # Path is the tail of the public URL after the bucket segment.
        marker = f"/public/{cls.BUCKET}/"
        path = url.split(marker, 1)[1] if marker in url else ''
        return {"url": url, "path": path}
