from rest_framework import serializers
from .models import BrandSource, BrandMemory

class BrandSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrandSource
        fields = [
            'id', 'workspace', 'brand', 'source_type', 'title',
            'source_url', 'storage_path', 'file_url', 'mime_type',
            'file_name', 'language', 'status', 'raw_text', 'metadata',
            'content_hash', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'workspace', 'created_by', 'status', 'created_at', 'updated_at']

class BrandMemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BrandMemory
        fields = [
            'id', 'workspace', 'brand', 'source', 'memory_type',
            'content', 'normalized_key', 'confidence', 'scope',
            'permanence', 'status', 'valid_from', 'valid_until',
            'supersedes', 'embedding_model', 'extracted_by_provider',
            'created_at', 'updated_at'
        ]
        # Exclude embedding as it can be large and not usually needed in list/detail APIs
        read_only_fields = ['id', 'workspace', 'created_at', 'updated_at']
