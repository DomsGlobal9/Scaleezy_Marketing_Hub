from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from .models import GeminiGenerationRequest, GeminiGenerationResult
from .serializers import GeminiGenerationRequestSerializer, GeminiGenerationResultSerializer
from apps.common.responses import APIResponse
from .services.generator import GeminiGeneratorService
from django.utils import timezone


class GeminiGenerationViewSet(viewsets.ModelViewSet):
    queryset = GeminiGenerationRequest.objects.all()
    serializer_class = GeminiGenerationRequestSerializer
    permission_classes = [AllowAny]  # MVP: allow frontend access without auth

    @action(detail=False, methods=['post'])
    def generate(self, request):
        """
        Accepts campaign parameters, calls for text + poster,
        returns everything the frontend needs for the preview screen.
        """
        # Extract the frontend's payload directly (not via model serializer)

        
        data = request.data
        campaign_name = data.get('campaignName', data.get('campaign_name', ''))
        product = data.get('product', '')
        audience = data.get('audience', data.get('target_audience', ''))
        location = data.get('location', '')
        occasion = data.get('occasion', '')
        offer = data.get('offer', '')
        brand_tone = data.get('brandTone', data.get('brand_tone', ''))
        reference_image_base64 = data.get('referenceImageBase64', '')

        request_data = {
            'campaign_name': campaign_name,
            'product': product,
            'target_audience': audience,
            'location': location,
            'occasion': occasion,
            'offer': offer,
            'brand_tone': brand_tone,
            'reference_image_base64': reference_image_base64,
        }

        try:
            result_data = GeminiGeneratorService.generate_marketing_content(request_data)

            response_payload = {
                'postTitle': result_data.get('postTitle', ''),
                'postDescription': result_data.get('postDescription', ''),
                'postHashtags': result_data.get('postHashtags', ''),
                'posterImageUrl': result_data.get('posterImageUrl', ''),
                'metadata': result_data.get('metadata', {}),
            }

            return APIResponse(success=True, data=response_payload, status=status.HTTP_201_CREATED)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return APIResponse(
                success=False,
                message=str(e),
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'], url_path='analyze-image')
    def analyze_image(self, request):
        try:
            b64_image = request.data.get('referenceImageBase64', '')
            if not b64_image:
                return APIResponse(success=False, message="No image provided", status=400)
                
            analysis = GeminiGeneratorService.analyze_reference_image(b64_image)
            return APIResponse(success=True, data=analysis, status=200)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return APIResponse(success=False, message=str(e), status=500)

    @action(detail=False, methods=['post'], url_path='generate-captions')
    def generate_captions(self, request):
        try:
            b64_image = request.data.get('referenceImageBase64', '')
            if not b64_image:
                return APIResponse(success=False, message="No image provided", status=400)
                
            captions = GeminiGeneratorService.generate_captions_only(b64_image)
            return APIResponse(success=True, data=captions, status=200)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return APIResponse(success=False, message=str(e), status=500)

    @action(detail=False, methods=['post'], url_path='analyze-video')
    def analyze_video(self, request):
        try:
            asset_id = request.data.get('asset_id')
            if not asset_id:
                return APIResponse(success=False, message="No asset_id provided", status=400)
                
            analysis = GeminiGeneratorService.analyze_video(asset_id)
            return APIResponse(success=True, data=analysis, status=200)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return APIResponse(success=False, message=str(e), status=500)

    @action(detail=True, methods=['get'])
    def results(self, request, pk=None):
        try:
            req = self.get_object()
            if hasattr(req, 'result'):
                return APIResponse(success=True, data=GeminiGenerationResultSerializer(req.result).data)
            return APIResponse(success=False, message="Result not ready or failed.", status=404)
        except Exception as e:
            return APIResponse(success=False, message=str(e), status=400)
