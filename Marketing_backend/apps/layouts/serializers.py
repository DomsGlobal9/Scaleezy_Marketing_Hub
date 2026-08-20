from rest_framework import serializers

from . import export, registry


class PreviewSerializer(serializers.Serializer):
    """
    Compose without persisting anything — for the picker in the wizard.

    A photo may be uploaded inline, or named as an asset in the caller's own
    workspace. There is no field for an arbitrary image URL, deliberately.
    """

    layout = serializers.CharField(max_length=64, required=False, allow_blank=True)
    brand = serializers.UUIDField(required=False, allow_null=True)
    # Optional here, required on RenderSerializer: previewing an existing item
    # should show its real copy, but the wizard also previews before anything
    # has been saved.
    content_item = serializers.UUIDField(required=False, allow_null=True)

    headline = serializers.CharField(max_length=500, required=False, allow_blank=True)
    subheadline = serializers.CharField(max_length=500, required=False, allow_blank=True)
    offer = serializers.CharField(max_length=255, required=False, allow_blank=True)
    cta = serializers.CharField(max_length=255, required=False, allow_blank=True)

    photo_base64 = serializers.CharField(required=False, allow_blank=True)
    asset = serializers.UUIDField(required=False, allow_null=True)

    include_logo = serializers.BooleanField(required=False, allow_null=True, default=None)
    include_phone = serializers.BooleanField(required=False, allow_null=True, default=None)
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True)

    size = serializers.CharField(max_length=32, required=False, allow_blank=True)
    config = serializers.DictField(required=False)

    def validate_layout(self, value):
        if value and value not in registry.keys():
            raise serializers.ValidationError(f"Unknown layout '{value}'.")
        return value

    def validate_size(self, value):
        if value and value not in export.SIZES:
            raise serializers.ValidationError(f"Unknown export size '{value}'.")
        return value


class RenderSerializer(PreviewSerializer):
    """Compose for a stored ContentItem and keep the result."""

    content_item = serializers.UUIDField()


class ExportSerializer(serializers.Serializer):
    content_item = serializers.UUIDField()
    layout = serializers.CharField(max_length=64, required=False, allow_blank=True)
    sizes = serializers.ListField(
        child=serializers.CharField(max_length=32), required=False, allow_empty=False
    )
    asset = serializers.UUIDField(required=False, allow_null=True)
    include_logo = serializers.BooleanField(required=False, allow_null=True, default=None)
    include_phone = serializers.BooleanField(required=False, allow_null=True, default=None)
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True)

    def validate_layout(self, value):
        if value and value not in registry.keys():
            raise serializers.ValidationError(f"Unknown layout '{value}'.")
        return value

    def validate_sizes(self, value):
        unknown = [s for s in value if s not in export.SIZES]
        if unknown:
            raise serializers.ValidationError(
                f"Unknown export size(s): {', '.join(unknown)}"
            )
        return value
