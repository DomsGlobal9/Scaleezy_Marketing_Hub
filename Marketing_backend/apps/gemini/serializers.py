import json

from rest_framework import serializers
from .models import GeminiGenerationRequest, GeminiGenerationResult

class GeminiGenerationRequestSerializer(serializers.ModelSerializer):
    progress = serializers.SerializerMethodField()

    class Meta:
        model = GeminiGenerationRequest
        # `prompt_data` can contain a large reference image plus private brand
        # context. Polling used to return it every two seconds even though the
        # UI only needs status and compact progress, multiplying response size
        # and exposing provider-bound material unnecessarily.
        fields = [
            'id', 'workspace', 'user', 'campaign_name', 'product',
            'target_audience', 'location', 'occasion', 'offer', 'brand_tone',
            'content_format', 'visual_direction', 'status', 'provider', 'model',
            'error_message', 'created_at', 'completed_at', 'progress',
        ]
        read_only_fields = [
            'id', 'workspace', 'user', 'status', 'provider', 'model',
            'error_message', 'created_at', 'completed_at', 'progress',
        ]

    @staticmethod
    def get_progress(obj):
        try:
            brief = json.loads(obj.prompt_data or '{}')
        except (TypeError, ValueError):
            brief = {}
        if not isinstance(brief, dict):
            brief = {}
        state = brief.get('production_state') or {}
        if not isinstance(state, dict):
            state = {}
        slides = brief.get('slides') or []
        completed_slides = state.get('slides') or {}
        return {
            'content_type': str(brief.get('contentType') or 'poster').lower(),
            'completed_slides': len(completed_slides) if isinstance(completed_slides, dict) else 0,
            'total_slides': len(slides) if isinstance(slides, list) else 0,
            'copy_complete': isinstance(state.get('text'), dict),
            'video_complete': isinstance(state.get('video'), dict),
        }

class GeminiGenerationResultSerializer(serializers.ModelSerializer):
    generation_request = GeminiGenerationRequestSerializer(read_only=True)
    
    class Meta:
        model = GeminiGenerationResult
        fields = '__all__'
        read_only_fields = ['id', 'created_at']
