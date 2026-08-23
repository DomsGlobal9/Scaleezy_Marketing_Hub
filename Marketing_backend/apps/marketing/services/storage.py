import logging
import uuid

from django.conf import settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised when an upload genuinely failed and the caller must know."""


class SupabaseStorageService:
    BUCKET = 'Marketing_Poster_images'

    @classmethod
    def upload_file(cls, workspace_id: str, file_obj, filename: str, *,
                    strict: bool = True, prefix: str = 'workspace') -> str:
        """
        Uploads to Supabase Storage and returns the public URL.

        Storage failures are always honest. ``strict`` is retained only for
        call-site compatibility; false no longer permits placeholder assets.
        """
        if getattr(settings, 'STORAGE_TEST_MODE', False):
            # Deterministic, and above the `strict` check on purpose: a strict
            # caller under test wants the success path exercised, not a live
            # upload to whatever bucket the developer's .env points at.
            return f"https://storage.test/{prefix}/{workspace_id}/{filename}"

        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise StorageError(
                "File storage is not configured. Set SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY."
            )

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
            raise StorageError(f"Upload failed: {exc}") from exc

        if not res.ok:
            logger.error("Supabase upload rejected (%s): %s", res.status_code, res.text[:300])
            raise StorageError(f"Storage rejected the upload ({res.status_code}).")

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
