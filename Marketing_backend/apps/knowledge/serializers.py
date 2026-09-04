from rest_framework import serializers
from apps.common.permissions import get_request_workspace
from apps.brands.models import Brand
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
        read_only_fields = [
            'id', 'workspace', 'created_by', 'status', 'created_at', 'updated_at',
            'storage_path', 'file_url', 'mime_type', 'file_name', 'content_hash', 'metadata',
        ]

    def validate(self, data):
        workspace, error = get_request_workspace(self.context['request'])
        if error or not workspace:
            raise serializers.ValidationError("Workspace is required and must be valid.")
        
        brand = data.get('brand') or getattr(self.instance, 'brand', None)
        if brand and brand.workspace_id != workspace.id:
            raise serializers.ValidationError({"brand": "Brand must belong to the authorized workspace."})

        if self.instance and 'brand' in data and data['brand'] != self.instance.brand:
            raise serializers.ValidationError({"brand": "Brand cannot be changed once set."})

        # Extracted facts cite this exact source. Replacing its contents would
        # make the old evidence appear to have come from a different document.
        if self.instance:
            for field in ('source_type', 'source_url', 'raw_text', 'language'):
                if field in data and data[field] != getattr(self.instance, field):
                    raise serializers.ValidationError({
                        field: "Source evidence is immutable. Add the corrected source and archive this one."
                    })
            
        return data

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
        # Make status and permanence read-only to force explicit actions
        read_only_fields = [
            'id', 'workspace', 'status', 'permanence', 'created_at', 'updated_at',
            'normalized_key', 'confidence', 'embedding_model', 'extracted_by_provider',
        ]

    def validate_supersedes(self, value):
        if value != getattr(self.instance, 'supersedes', None):
            raise serializers.ValidationError("Supersession is recorded by the source-processing service.")
        return value

    def validate(self, data):
        workspace, error = get_request_workspace(self.context['request'])
        if error or not workspace:
            raise serializers.ValidationError("Workspace is required and must be valid.")
            
        brand = data.get('brand') or getattr(self.instance, 'brand', None)
        if brand and brand.workspace_id != workspace.id:
            raise serializers.ValidationError({"brand": "Brand must belong to the authorized workspace."})

        if self.instance and 'brand' in data and data['brand'] != self.instance.brand:
            raise serializers.ValidationError({"brand": "Brand cannot be changed once set."})
            
        source = data.get('source', getattr(self.instance, 'source', None))
        if self.instance and source != self.instance.source:
            raise serializers.ValidationError({"source": "Source provenance cannot be changed or removed."})
        if source:
            if source.workspace_id != workspace.id:
                raise serializers.ValidationError({"source": "Source must belong to the authorized workspace."})
            if brand and source.brand_id != brand.id:
                raise serializers.ValidationError({"source": "Source must belong to the same brand."})
            if source.status == BrandSource.SourceStatus.ARCHIVED:
                raise serializers.ValidationError({"source": "Archived source evidence cannot be edited or reused."})

        if self.instance and self.instance.status in (
            BrandMemory.MemoryStatus.SUPERSEDED, BrandMemory.MemoryStatus.EXPIRED,
        ):
            raise serializers.ValidationError("Retired evidence cannot be edited. Add a new fact instead.")
        start = data.get('valid_from', getattr(self.instance, 'valid_from', None))
        end = data.get('valid_until', getattr(self.instance, 'valid_until', None))
        if start and end and end <= start:
            raise serializers.ValidationError({"valid_until": "Must be after valid_from."})
                
        supersedes = data.get('supersedes') or getattr(self.instance, 'supersedes', None)
        if supersedes:
            if supersedes.workspace_id != workspace.id:
                raise serializers.ValidationError({"supersedes": "Superseded memory must belong to the authorized workspace."})
            if brand and supersedes.brand_id != brand.id:
                raise serializers.ValidationError({"supersedes": "Superseded memory must belong to the same brand."})

        return data

class BrandSourceUploadSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)
    brand = serializers.PrimaryKeyRelatedField(
        queryset=Brand.objects.all(), # Overridden dynamically
        required=True
    )
    # A transcript uploaded as a PDF is still a transcript. The caller may say
    # what the file IS; the default keeps the pre-existing behaviour.
    source_type = serializers.ChoiceField(
        choices=BrandSource.SourceType.choices,
        required=False,
        default=BrandSource.SourceType.DOCUMENT,
    )
    title = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=''
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dynamically set the queryset for 'brand' to match the request's workspace
        request = self.context.get('request')
        if request:
            workspace, error = get_request_workspace(request)
            if not error and workspace:
                from apps.brands.models import Brand
                self.fields['brand'].queryset = Brand.objects.filter(workspace=workspace)
