from rest_framework import serializers

from .models import Brand


class BrandSerializer(serializers.ModelSerializer):
    has_logo = serializers.BooleanField(read_only=True)

    class Meta:
        model = Brand
        fields = '__all__'
        # `workspace` is assigned server-side from the authorised request. A
        # client-writable workspace is exactly how the Phase 1c audit found
        # cross-tenant writes on the other viewsets.
        read_only_fields = [
            'id',
            'workspace',
            'logo_url',
            'logo_storage_path',
            'logo_file_name',
            'created_by',
            'created_at',
            'updated_at',
        ]

    def validate_palette(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Palette must be an object of colour roles.")
        return value

    def validate_fonts(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Fonts must be an object.")
        return value

    def validate_competitors(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Competitors must be a list.")
        return value

    def validate_creative_brain(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("creative_brain must be an object.")
        return value


class BrandLogoUploadSerializer(serializers.Serializer):
    file = serializers.ImageField()
