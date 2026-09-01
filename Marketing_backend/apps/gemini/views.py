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
from apps.brands.services.approval import approval_gate_response
from django.utils import timezone


logger = logging.getLogger(__name__)


# Moved to apps.context.services.generation so the background task records
# the same attribution the synchronous path does; kept under its old name
# because the call sites below read naturally with it.
from apps.context.services.generation import intelligence_in_force as _intelligence_in_force  # noqa: E402


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

        Persistence is part of completion. A response without a durable draft
        cannot enter review or publishing, so storage failure must be reported
        honestly rather than returning a success the user cannot recover.
        """
        from django.db import transaction

        from apps.brands.models import Brand
        from apps.content.models import ContentItem
        from apps.context.services.generation import create_generated_asset

        workspace, error = get_request_workspace(request)
        if error:
            raise PermissionDenied("No accessible workspace for this request.")

        content_format = {
            'video': ContentItem.Format.VIDEO,
            'carousel': ContentItem.Format.CAROUSEL,
        }.get(str(request.data.get('contentType', '')).lower(), ContentItem.Format.POSTER)

        slides = (
            result.get('slides')
            if content_format == ContentItem.Format.CAROUSEL
            else request.data.get('slides')
        ) or []

        creator = request.user if request.user.is_authenticated else None
        with transaction.atomic():
            asset = create_generated_asset(workspace, result, user=creator)
            return ContentItem.objects.create(
                workspace=workspace,
                brand=Brand.objects.filter(workspace=workspace).order_by('-is_default').first(),
                asset=asset,
                content_format=content_format,
                status=ContentItem.Status.DRAFT,
                headline=(result.get('postTitle') or '')[:500],
                caption=result.get('postDescription') or '',
                hashtags=result.get('postHashtags') or '',
                cta=(brief.get('offer') or '')[:255],
                preview_url=(
                    result.get('videoUrl')
                    or result.get('posterImageUrl')
                    or ''
                )[:1000],
                slides=slides if isinstance(slides, list) else [],
                # Whichever provider the router actually selected. This
                # used to be hard-coded, so every generation claimed Gemini
                # produced it however it was routed.
                ai_provider=(provider_key or 'UNKNOWN')[:100],
                ai_prompt=str(brief)[:5000],
                layout_plugin=str(brief.get('layout') or '')[:64],
                layout_config={
                    'creative_direction': brief.get('creative_direction') or {},
                },
                created_by=creator,
            )

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
            'contentType': data.get('contentType', ''),
            'slides': data.get('slides') or [],
            'video_duration': data.get('videoDuration', data.get('video_duration', '')),
            'video_aspect': data.get('videoAspect', data.get('video_aspect', '')),
            'video_style': data.get('videoStyle', data.get('video_style', '')),
            'video_script': data.get('videoScript', data.get('video_script', '')),
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

        from apps.brands.models import Brand
        from apps.context.services.creative_direction import (
            CreativeDirectionError,
            resolve_creative_direction,
        )

        brand = Brand.objects.filter(workspace=workspace).order_by('-is_default').first()
        try:
            creative_direction = resolve_creative_direction(
                workspace,
                brand,
                data.get('inspirationSelections', data.get('inspiration_selections', [])),
                layout=data.get('layout', ''),
            )
        except CreativeDirectionError as exc:
            return APIResponse(
                success=False,
                message=str(exc),
                error={'code': exc.code, 'message': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request_data['creative_direction'] = creative_direction
        request_data['layout'] = creative_direction['layout']

        quota_error = self._quota_error(workspace)
        if quota_error:
            return quota_error
        # No provider spend before Scaleezy approval. The router refuses too;
        # answering here keeps the 403 envelope instead of a generic failure.
        approval_error = approval_gate_response(workspace)
        if approval_error:
            return approval_error

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
        try:
            content_item = self._persist_content(
                request, request_data, result_data, provider_key=routed['provider']
            )
        except Exception:
            logger.exception("Generated content could not be persisted")
            return APIResponse(
                success=False,
                message="The content was generated but could not be saved. Please retry.",
                error={
                    'code': 'PERSISTENCE_FAILED',
                    'message': 'No draft or publishable asset was created.',
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if content_item is not None:
            # Lightweight generation trace for future optimisation: which
            # brain, which providers, what failed. No prompt material.
            content_item.layout_config = {
                **(content_item.layout_config or {}),
                'generation_trace': {
                    'brain_version': routed.get('brain_version', ''),
                    **routed.get('trace', {}),
                    **_intelligence_in_force(
                        content_item.brand, routed.get('brain_version', '')
                    ),
                },
                'creative_direction': creative_direction,
            }
            content_item.save(update_fields=['layout_config'])

            # Reviewers kept asking where the words on the poster went: the
            # generation produced a photo and copy as two separate things.
            # Bake the copy onto the photo with the same engine the studio's
            # "Use this poster" uses. Best-effort — a compose failure leaves
            # the raw generated image in place.
            from apps.layouts.services import compose_generated_poster

            compose_generated_poster(
                content_item,
                user=request.user if request.user.is_authenticated else None,
            )

        response_payload = {
            'postTitle': result_data.get('postTitle', ''),
            'postDescription': result_data.get('postDescription', ''),
            'postHashtags': result_data.get('postHashtags', ''),
            # The composed poster when there is one, the raw image otherwise -
            # the preview must show what will actually be reviewed.
            'posterImageUrl': (
                (content_item.preview_url if content_item else '')
                or result_data.get('posterImageUrl', '')
            ),
            'videoUrl': result_data.get('videoUrl', ''),
            'slideImageUrls': result_data.get('slideImageUrls') or [],
            'metadata': {
                **(result_data.get('metadata') or {}),
                'provider': routed['provider'],
                'provider_name': routed['provider_name'],
                'brain_version': routed['brain_version'],
                'creative_direction': {
                    'selection_count': creative_direction['selection_count'],
                    'layout': creative_direction['layout'],
                },
            },
            'contentItemId': str(content_item.id) if content_item else None,
            'assetId': str(content_item.asset_id) if content_item and content_item.asset_id else None,
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
        from apps.context.services.generation import generate_marketing_payload

        return generate_marketing_payload(
            workspace,
            request_data,
            instruction=str(request_data.get('campaign_name', ''))[:500],
        )

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
        # Refused before the request row exists: a pending client must not
        # leave a queued generation behind that runs the moment it is approved.
        approval_error = approval_gate_response(workspace)
        if approval_error:
            return approval_error

        data = request.data
        from apps.brands.models import Brand
        from apps.context.services.creative_direction import (
            CreativeDirectionError,
            resolve_creative_direction,
        )

        brand = Brand.objects.filter(workspace=workspace).order_by('-is_default').first()
        try:
            creative_direction = resolve_creative_direction(
                workspace,
                brand,
                data.get('inspirationSelections', data.get('inspiration_selections', [])),
                layout=data.get('layout', ''),
            )
        except CreativeDirectionError as exc:
            return APIResponse(
                success=False,
                message=str(exc),
                error={'code': exc.code, 'message': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
            'video_duration': data.get('videoDuration', data.get('video_duration', '')),
            'video_aspect': data.get('videoAspect', data.get('video_aspect', '')),
            'video_style': data.get('videoStyle', data.get('video_style', '')),
            'video_script': data.get('videoScript', data.get('video_script', '')),
            'brand_rules': self._brand_rules(request),
            'creative_direction': creative_direction,
            'layout': creative_direction['layout'],
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
                'pollUrl': f"/api/marketing/ai-generation/{generation.id}/",
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=['post'], url_path='analyze-image')
    def analyze_image(self, request):
        try:
            b64_image = request.data.get('referenceImageBase64', '')
            if not b64_image:
                return APIResponse(success=False, message="No image provided", status=400)

            from apps.ai.models import Capability
            from apps.ai.router import AIRouter

            workspace, error = get_request_workspace(request)
            if error:
                return error
            approval_error = approval_gate_response(workspace)
            if approval_error:
                return approval_error
            routed = AIRouter(workspace).dispatch(
                Capability.IMAGE_ANALYSIS,
                {'reference_image_base64': b64_image},
            )
            return APIResponse(success=True, data=routed.get('analysis', routed), status=200)
        except Exception as e:
            logger.exception("Image analysis failed")
            return APIResponse(success=False, message=str(e), status=500)

    @action(detail=False, methods=['post'], url_path='generate-captions')
    def generate_captions(self, request):
        try:
            b64_image = request.data.get('referenceImageBase64', '')
            if not b64_image:
                return APIResponse(success=False, message="No image provided", status=400)
                
            from apps.ai.models import Capability
            from apps.ai.router import AIRouter

            workspace, error = get_request_workspace(request)
            if error:
                return error
            approval_error = approval_gate_response(workspace)
            if approval_error:
                return approval_error
            routed = AIRouter(workspace).dispatch(
                Capability.IMAGE_CAPTION,
                {'reference_image_base64': b64_image},
            )
            return APIResponse(success=True, data=routed.get('captions', routed), status=200)
        except Exception as e:
            logger.exception("Image caption generation failed")
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

            from apps.ai.models import Capability
            from apps.ai.router import AIRouter

            workspace, error = get_request_workspace(request)
            if error:
                return error
            approval_error = approval_gate_response(workspace)
            if approval_error:
                return approval_error
            routed = AIRouter(workspace).dispatch(
                Capability.VIDEO_ANALYSIS,
                {'asset_id': str(asset_id)},
            )
            return APIResponse(success=True, data=routed.get('analysis', routed), status=200)
        except Exception as e:
            logger.exception("Video analysis failed")
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
