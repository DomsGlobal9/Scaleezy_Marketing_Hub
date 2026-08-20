from rest_framework import serializers
from .models import GeminiGenerationRequest, GeminiGenerationResult

class GeminiGenerationRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeminiGenerationRequest
        fields = '__all__'
        read_only_fields = [
            'id', 'workspace', 'user', 'status', 'provider', 'model',
            'error_message', 'created_at', 'completed_at',
        ]

class GeminiGenerationResultSerializer(serializers.ModelSerializer):
    generation_request = GeminiGenerationRequestSerializer(read_only=True)
    
    class Meta:
        model = GeminiGenerationResult
        fields = '__all__'
        read_only_fields = ['id', 'created_at']
