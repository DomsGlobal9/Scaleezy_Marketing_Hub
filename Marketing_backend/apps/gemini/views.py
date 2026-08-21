import logging

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from .models import GeminiGenerationRequest, GeminiGenerationResult
from .serializers import GeminiGenerationRequestSerializer, GeminiGenerationResultSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from apps.common.permissions import (
    IsWorkspaceMember,
    authorize_workspace,
    get_request_workspace,
)
from apps.common.mixins import WorkspaceScopedMixin
from apps.common.responses import APIResponse
from .services.generator import GeminiGeneratorService
from django.utils import timezone


logger = logging.getLogger(__name__)


class GeminiGenerationViewSet(WorkspaceScopedMixin, viewsets.ModelViewSet):
    queryset = GeminiGenerationRequest.objects.all()
    serializer_class = GeminiGenerationRequestSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember]
    requires_workspace = False


    def perform_create(self, serializer):
        # workspace is read-only on the serializer, so it is assigned here from
        # the caller's authorised workspace rather than the request payload.
        workspace, error = get_request_workspace(self.request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")
        serializer.save(workspace=workspace, user=self.request.user)

    def _quota_error(self, workspace):
        """
        Refuses the generation if the workspace is out of allowance.

        Returns an error response, or None to proceed. Checked here rather
        than in the AI router because this endpoint calls the Gemini service
        directly and would otherwise slip past the gate entirely.
        """
        from apps.billing.quota import QuotaExceeded, enforce

        try:
            enforce(workspace)
        except QuotaExceeded as exc:
            return APIResponse(
                success=False,
                message=exc.verdict.message,
                error={"code": exc.verdict.code, "message": exc.verdict.message},
                data=exc.verdict.as_dict(),
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        return None

    def _brand_context(self, request, task_type=None):
        """Brand intelligence for this generation, from the Context Gateway.

        This used to reach into the training engine for learned rules, which
        meant the generator held its own opinion about what brand knowledge
        is and saw none of the confirmed facts, stated preferences or hard
        rules the rest of the system had collected. It now asks the one
        service that owns that question, so precedence is resolved once and
        a second provider does not need a second copy of it.

        Best-effort: a brand with nothing compiled yet yields empty context
        and the prompt is simply unchanged.
        """
        from apps.brands.models import Brand
        from apps.context.services.context_gateway import (
            TaskType,
            build_generation_context,
            context_as_brief,
        )

        try:
            workspace, error = get_request_workspace(request)
            if error:
                return None
            brand = Brand.objects.filter(workspace=workspace).order_by('-is_default').first()
            if brand is None:
                return None
            context = build_generation_context(
                workspace, brand, task_type or TaskType.COPY,
                instruction=str(request.data.get('campaignName', ''))[:500],
            )
            return {'context': context, 'brief': context_as_brief(context)}
        except Exception:
            logger.exception("Could not build brand context")
            return None

    def _brand_rules(self, request):
        """The prompt-facing view of gateway context.

        Kept as a list of instruction lines because that is what the existing
        generator prompt consumes; the shape is the adapter boundary, not the
        intelligence.
        """
        gateway = self._brand_context(request)
        if not gateway:
            return []
        return gateway['brief']['brand_context']

    def _persist_content(self, request, brief, result, provider_key=''):
        """
        Saves a generation as a DRAFT ContentItem.

        Best-effort: a storage hiccup here must not lose the user the content
        they just waited for, so failures are logged and the payload is still
        returned.
        """
        from apps.brands.models import Brand
        from apps.content.models import ContentItem

        try:
            workspace, error = get_request_workspace(request)
            if error:
                return None

            content_format = {
                'video': ContentItem.Format.VIDEO,
                'carousel': ContentItem.Format.CAROUSEL,
            }.get(str(request.data.get('contentType', '')).lower(), ContentItem.Format.POSTER)

            slides = request.data.get('slides') or []

            return ContentItem.objects.create(
                workspace=workspace,
                brand=Brand.objects.filter(workspace=workspace).order_by('-is_default').first(),
                content_format=content_format,
                status=ContentItem.Status.DRAFT,
                headline=(result.get('postTitle') or '')[:500],
                caption=result.get('postDescription') or '',
                hashtags=result.get('postHashtags') or '',
                cta=(brief.get('offer') or '')[:255],
                preview_url=(result.get('posterImageUrl') or '')[:1000],
                slides=slides if isinstance(slides, list) else [],
                # Whichever provider the router actually selected. This
                # used to be hard-coded, so every generation claimed Gemini
                # produced it however it was routed.
                ai_provider=(provider_key or 'UNKNOWN')[:100],
                ai_prompt=str(brief)[:5000],
                created_by=request.user if request.user.is_authenticated else None,
            )
        except Exception:
            logger.exception("Could not persist generated content")
            return None

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
            # Closes the training loop: what reviewers have repeatedly
            # rejected becomes a constraint on the next generation.
            'brand_rules': self._brand_rules(request),
        }

        # Everything the Context Gateway resolved, carried alongside the
        # campaign fields so any adapter can use the structured form rather
        # than parsing the prose back out.
        gateway = self._brand_context(request)
        if gateway:
            request_data['brand_context'] = gateway['brief']['brand_context']
            request_data['structured'] = gateway['brief']['structured']
            request_data['brain_version'] = gateway['context']['brain_version']

        workspace, workspace_error = get_request_workspace(request)
        if workspace_error:
            return workspace_error
        quota_error = self._quota_error(workspace)
        if quota_error:
            return quota_error

        from apps.ai.router import AIRouter, NoProviderAvailable
        from apps.context.services.generation import NoProviderConfigured

        try:
            routed = self._route_generation(workspace, request_data)
        except (NoProviderAvailable, NoProviderConfigured) as exc:
            # Honest unavailability. A workspace with nothing routed has not
            # generated anything, and saying so beats an empty success.
            return APIResponse(
                success=False,
                message="No AI provider is configured for content generation.",
                error={'code': 'NO_PROVIDER', 'message': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            logger.exception("Generation failed")
            return APIResponse(
                success=False,
                message=str(e),
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        result_data = routed['payload']
        # Persist the generation. Previously this was returned to the browser
        # and never stored, so the copy existed only in React state and was
        # lost on refresh.
        content_item = self._persist_content(
            request, data, result_data, provider_key=routed['provider']
        )
        if content_item is not None:
            # Lightweight generation trace for future optimisation: which
            # brain, which providers, what failed. No prompt material.
            content_item.layout_config = {
                **(content_item.layout_config or {}),
                'generation_trace': {
                    'brain_version': routed.get('brain_version', ''),
                    **routed.get('trace', {}),
                },
            }
            content_item.save(update_fields=['layout_config'])

        response_payload = {
            'postTitle': result_data.get('postTitle', ''),
            'postDescription': result_data.get('postDescription', ''),
            'postHashtags': result_data.get('postHashtags', ''),
            'posterImageUrl': result_data.get('posterImageUrl', ''),
            'metadata': {
                **(result_data.get('metadata') or {}),
                'provider': routed['provider'],
                'provider_name': routed['provider_name'],
                'brain_version': routed['brain_version'],
            },
            'contentItemId': str(content_item.id) if content_item else None,
        }

        return APIResponse(
            success=True, data=response_payload, status=status.HTTP_201_CREATED
        )

    def _route_generation(self, workspace, request_data):
        """Run the generation through the accelerator, concurrently.

        Copy and imagery are dispatched together through
        `generate_copy_and_image` - the PR6 accelerator - instead of one
        after the other, so the user waits for the slower capability rather
        than the sum of both. Partial success is preserved: a failed poster
        costs a poster, never the copy that already succeeded, and a provider
        whose text result carries the poster is not asked twice.

        The provider-neutral result is mapped back to the response contract
        the frontend already speaks. Adapting at this boundary is deliberate -
        the alternative is rewriting the client every time a provider's
        result shape differs.
        """
        from apps.brands.models import Brand
        from apps.context.services.generation import generate_copy_and_image

        brand = Brand.objects.filter(workspace=workspace).order_by('-is_default').first()
        if brand is None:
            # No brand, no brand context - fall back to a plain routed TEXT
            # dispatch rather than failing a workspace that has not finished
            # setup.
            from apps.ai.models import Capability
            from apps.ai.router import AIRouter

            text = AIRouter(workspace).dispatch(Capability.TEXT, request_data)
            raw = text.get('raw') or {}
            return {
                'provider': text.get('provider', ''),
                'provider_name': text.get('provider_name', ''),
                'brain_version': '',
                'trace': {'capabilities': {'TEXT': {'status': 'OK'}}},
                'payload': {
                    'postTitle': text.get('headline') or raw.get('postTitle', ''),
                    'postDescription': text.get('caption') or raw.get('postDescription', ''),
                    'postHashtags': text.get('hashtags') or raw.get('postHashtags', ''),
                    'posterImageUrl': raw.get('posterImageUrl', ''),
                    'metadata': raw.get('metadata', {}),
                },
            }

        outcome = generate_copy_and_image(
            workspace, brand, request_data,
            instruction=str(request_data.get('campaign_name', ''))[:500],
        )
        text = outcome['text'] or {}
        image = outcome['image'] or {}
        raw = text.get('raw') or {}
        if not text:
            failure = outcome['trace']['capabilities'].get('TEXT', {})
            raise RuntimeError(failure.get('error', 'Generation produced no copy.'))

        return {
            'provider': text.get('provider', ''),
            'provider_name': text.get('provider_name', ''),
            'brain_version': outcome['trace'].get('brain_version', ''),
            'trace': outcome['trace'],
            'payload': {
                'postTitle': text.get('headline') or raw.get('postTitle', ''),
                'postDescription': text.get('caption') or raw.get('postDescription', ''),
                'postHashtags': text.get('hashtags') or raw.get('postHashtags', ''),
                'posterImageUrl': image.get('image_url', ''),
                'metadata': raw.get('metadata', {}),
            },
        }

    @action(detail=False, methods=['post'], url_path='generate-async')
    def generate_async(self, request):
        """
        Queues a generation and returns immediately with a request id to poll.

        Video and multi-slide carousels take long enough to hit a gateway
        timeout on the synchronous endpoint, and when they do the user loses
        work that the server may well have finished. Here the request row is
        the progress record: poll `GET /gemini/{id}/` for its status and
        `GET /gemini/{id}/results/` once it is COMPLETED.
        """
        import json

        workspace, error = get_request_workspace(request)
        if error:
            return error

        quota_error = self._quota_error(workspace)
        if quota_error:
            return quota_error

        data = request.data
        brief = {
            'campaign_name': data.get('campaignName', data.get('campaign_name', '')),
            'product': data.get('product', ''),
            'target_audience': data.get('audience', data.get('target_audience', '')),
            'location': data.get('location', ''),
            'occasion': data.get('occasion', ''),
            'offer': data.get('offer', ''),
            'brand_tone': data.get('brandTone', data.get('brand_tone', '')),
            'reference_image_base64': data.get('referenceImageBase64', ''),
            'contentType': data.get('contentType', ''),
            'slides': data.get('slides') or [],
            'brand_rules': self._brand_rules(request),
        }

        generation = GeminiGenerationRequest.objects.create(
            workspace=workspace,
            user=request.user if request.user.is_authenticated else None,
            prompt_data=json.dumps(brief),
            campaign_name=brief['campaign_name'][:255],
            product=brief['product'][:255],
            target_audience=brief['target_audience'][:255],
            location=brief['location'][:255],
            occasion=brief['occasion'][:255],
            offer=brief['offer'][:255],
            brand_tone=brief['brand_tone'][:255],
            content_format=str(data.get('contentType', ''))[:255],
            status=GeminiGenerationRequest.Status.PENDING,
        )

        from apps.gemini.tasks import generate_content

        task_result = generate_content.enqueue(str(generation.id))

        return APIResponse(
            success=True,
            data={
                'generationId': str(generation.id),
                'taskId': task_result.id,
                'status': generation.status,
                'pollUrl': f"/api/marketing/gemini/{generation.id}/",
            },
            status=status.HTTP_202_ACCEPTED,
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

            # The asset must belong to a workspace the caller is in. Without
            # this the service looked it up by bare id, so any authenticated
            # user could have another tenant's media fetched and analysed.
            from apps.marketing.models import MarketingAsset

            if not MarketingAsset.objects.filter(
                id=asset_id, workspace__in=self.accessible_workspace_ids()
            ).exists():
                return APIResponse(
                    success=False, message="Asset not found.", status=status.HTTP_404_NOT_FOUND
                )

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
