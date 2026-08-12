from rest_framework import serializers
from .models import MarketingAsset

class MarketingAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketingAsset
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']

class UploadAssetSerializer(serializers.Serializer):
    workspace_id = serializers.UUIDField()
    file = serializers.FileField()
    source = serializers.ChoiceField(choices=MarketingAsset.Source.choices, default=MarketingAsset.Source.MANUAL_UPLOAD)
