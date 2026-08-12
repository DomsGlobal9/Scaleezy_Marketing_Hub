from django.conf import settings
import uuid
import os

class SupabaseStorageService:
    @staticmethod
    def upload_file(workspace_id: str, file_obj, filename: str) -> str:
        """
        Uploads a file to Supabase storage and returns the public URL.
        """
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            # Fallback for local dev when Supabase isn't configured
            print(f"[Storage Mock] Uploaded {filename} for workspace {workspace_id}")
            return f"https://mock-storage.url/workspace_{workspace_id}/{uuid.uuid4()}_{filename}"
            
        import requests
        
        bucket_name = 'Marketing_Poster_images'
        path_on_supastorage = f"workspace/{workspace_id}/{uuid.uuid4()}_{filename}"
        
        upload_url = f"{settings.SUPABASE_URL}/storage/v1/object/{bucket_name}/{path_on_supastorage}"
        headers = {
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": file_obj.content_type if hasattr(file_obj, 'content_type') else "application/octet-stream"
        }
        
        try:
            res = requests.post(upload_url, headers=headers, data=file_obj.read())
            if not res.ok:
                print(f"Supabase upload failed: {res.text}")
                return f"https://mock-storage.url/workspace_{workspace_id}/{uuid.uuid4()}_{filename}"
                
            public_url = f"{settings.SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{path_on_supastorage}"
            return public_url
        except Exception as e:
            print(f"Supabase upload exception: {e}")
            return f"https://mock-storage.url/workspace_{workspace_id}/{uuid.uuid4()}_{filename}"
