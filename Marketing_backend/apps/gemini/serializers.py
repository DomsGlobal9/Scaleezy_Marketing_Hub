import json

from rest_framework import serializers
from .models import GeminiGenerationRequest, GeminiGenerationResult
from .execution import active_runs, execution_state


class GenerationListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        rows = list(data.all() if hasattr(data, 'all') else data)
        self.context['generation_active_runs'] = active_runs([row.pk for row in rows])
        return super().to_representation(rows)

class GeminiGenerationRequestSerializer(serializers.ModelSerializer):
    progress = serializers.SerializerMethodField()
    execution = serializers.SerializerMethodField()

    class Meta:
        model = GeminiGenerationRequest
        list_serializer_class = GenerationListSerializer
        # `prompt_data` can contain a large reference image plus private brand
        # context. Polling used to return it every two seconds even though the
        # UI only needs status and compact progress, multiplying response size
        # and exposing provider-bound material unnecessarily.
        fields = [
            'id', 'workspace', 'user', 'campaign_name', 'product',
            'target_audience', 'location', 'occasion', 'offer', 'brand_tone',
            'content_format', 'visual_direction', 'status', 'provider', 'model',
            'error_message', 'created_at', 'completed_at', 'progress', 'execution',
        ]

        read_only_fields = [
            'id', 'workspace', 'user', 'status', 'provider', 'model',
            'error_message', 'retry_count', 'created_at', 'updated_at',
            'completed_at', 'progress',
        ]

    def get_execution(self, obj):
        return execution_state(obj, self.context.get('generation_active_runs'))

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
