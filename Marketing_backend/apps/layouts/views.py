import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.brands.models import Brand
from apps.common.mixins import WorkspaceScopedMixin
from apps.common.permissions import (
    HasWorkspaceRole,
    IsWorkspaceMember,
    get_request_workspace,
)
from apps.common.responses import APIResponse
from apps.content.models import ContentItem
from apps.marketing.models import MarketingAsset
from apps.marketing.services.storage import StorageError
from apps.workspaces.models import WorkspaceMember

# Aliased: two actions below are named `render` and `export`, and a bare
# module name would read as the method inside the class body.
from . import images, registry
from . import export as export_engine
from . import render as render_engine
from .serializers import ExportSerializer, PreviewSerializer, RenderSerializer
from .services import persist_composed, source_photo_asset

logger = logging.getLogger(__name__)


class LayoutViewSet(WorkspaceScopedMixin, viewsets.ViewSet):
    """
    Server-side poster composition.

    `preview` returns pixels and stores nothing. `render` and `export` persist
    MarketingAssets, so they need an editor.
    """

    permission_classes = [IsAuthenticated, IsWorkspaceMember, HasWorkspaceRole]
    requires_workspace = False
    required_role = WorkspaceMember.Role.EDITOR
    required_read_role = WorkspaceMember.Role.VIEWER

    # ViewSet has no queryset; scoping is done per action against the models
    # actually touched.
    queryset = ContentItem.objects.none()

    def list(self, request):
        """The installed layouts and the destinations they can be exported to."""
        return APIResponse(
            success=True,
            data={'layouts': registry.catalogue(), 'sizes': export_engine.catalogue()},
        )

    # -- helpers ---------------------------------------------------------
    def _brand(self, workspace, brand_id=None):
        qs = Brand.objects.filter(workspace=workspace)
        if brand_id:
            # Scoped to the workspace, so a brand id from another tenant is a
            # miss rather than a leak.
            return qs.filter(pk=brand_id).first()
        return qs.order_by('-is_default').first()

    def _asset(self, workspace, asset_id):
        if not asset_id:
            return None
        return MarketingAsset.objects.filter(pk=asset_id, workspace=workspace).first()

    def _content(self, workspace, content_id):
        return ContentItem.objects.filter(pk=content_id, workspace=workspace).first()

    def _spec_for(self, workspace, data, *, item=None, brand=None):
        brand = brand or self._brand(workspace, data.get('brand'))
        # `source_photo_asset` prefers the original photograph over a poster
        # this item already composed, so re-composing never bakes the words
        # onto an image that already carries them.
        photo = render_engine.photo_for(
            photo_base64=data.get('photo_base64', ''),
            asset=self._asset(workspace, data.get('asset')) or source_photo_asset(item),
        )

        size_key = data.get('size') or 'instagram_portrait'
        _label, width, height, _platform = export_engine.SIZES[size_key]

        return render_engine.spec_from(
            brand,
            headline=data.get('headline') or (item.headline if item else ''),
            subheadline=data.get('subheadline') or '',
            # ContentItem.cta is where the generator stores the offer line
            # (see apps/gemini/views.py), so it feeds the offer slot; the
            # call to action falls back to the brand's own keyword.
            offer=data.get('offer') or (item.cta if item else ''),
            cta=data.get('cta') or '',
            width=width,
            height=height,
            photo=photo,
            include_logo=data.get('include_logo'),
            include_phone=data.get('include_phone'),
            phone=data.get('phone', ''),
            config=data.get('config') or (item.layout_config if item else {}),
        ), brand

    def _layout_key(self, data, brand, item=None):
        return (
            data.get('layout')
            or (item.layout_plugin if item and item.layout_plugin else '')
            or (brand.layout_preference if brand else '')
            or registry.DEFAULT_KEY
        )

    # -- actions ---------------------------------------------------------
    @action(detail=False, methods=['post'])
    def preview(self, request):
        """Composes and returns a data URL. Nothing is stored."""
        workspace, error = get_request_workspace(request)
        if error:
            return error

        serializer = PreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        item = None
        if data.get('content_item'):
            item = self._content(workspace, data['content_item'])
            if item is None:
                return APIResponse(
                    success=False,
                    message="Content not found.",
                    error={"code": "NOT_FOUND", "message": "Content not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        spec, brand = self._spec_for(workspace, data, item=item)
        layout = self._layout_key(data, brand, item)

        try:
            image = render_engine.compose(spec, layout)
        except render_engine.RenderError as exc:
            return APIResponse(
                success=False, message=str(exc), status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        return APIResponse(
            success=True,
            data={
                'layout': layout,
                'width': image.width,
                'height': image.height,
                'preview': images.to_data_url(image),
            },
        )

    @action(detail=False, methods=['post'])
    def render(self, request):
        """
        Composes for a stored ContentItem, uploads it, and points the item at
        the result.

        The composed poster replaces the item's preview, and the layout used
        is recorded so the next render — and any export — is reproducible.
        """
        workspace, error = get_request_workspace(request)
        if error:
            return error

        serializer = RenderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        item = self._content(workspace, data['content_item'])
        if item is None:
            return APIResponse(
                success=False,
                message="Content not found.",
                error={"code": "NOT_FOUND", "message": "Content not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if item.status != ContentItem.Status.DRAFT:
            return APIResponse(
                success=False,
                message="Only a draft can be composed. Open a new revision first.",
                error={"code": "CONTENT_LOCKED", "message": item.get_status_display()},
                status=status.HTTP_409_CONFLICT,
            )

        spec, brand = self._spec_for(workspace, data, item=item)
        layout = self._layout_key(data, brand, item)

        try:
            image = render_engine.compose(spec, layout)
        except render_engine.RenderError as exc:
            return APIResponse(
                success=False, message=str(exc), status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        try:
            asset = self._persist(workspace, request.user, item, image, 'JPEG', layout)
        except StorageError as exc:
            return APIResponse(
                success=False,
                message=str(exc),
                error={"code": "STORAGE_FAILED", "message": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        config = dict(data['config']) if data.get('config') else dict(item.layout_config or {})
        # Remember which photograph this composition was built from — but only
        # the first time, and never a composed poster itself.
        if (
            item.asset_id
            and getattr(item.asset, 'source', '') != MarketingAsset.Source.COMPOSED
        ):
            config.setdefault('source_asset', str(item.asset_id))
        item.layout_plugin = layout
        item.layout_config = config
        item.asset = asset
        item.preview_url = asset.file_url or ''
        item.save(
            update_fields=['layout_plugin', 'layout_config', 'asset', 'preview_url', 'updated_at']
        )

        # Picking a layout is a taste decision, and it was going nowhere but
        # onto this one item. Two independent picks now establish a visual
        # preference through the ordinary threshold — no special case.
        self._record_layout_choice(item, layout, request.user)

        return APIResponse(
            success=True,
            data={
                'layout': layout,
                'asset': str(asset.id),
                'url': asset.file_url,
                'width': image.width,
                'height': image.height,
            },
            status=status.HTTP_201_CREATED,
        )

    def _record_layout_choice(self, item, layout, user):
        """One layout pick, recorded as ordinary evidence.

        Deliberately POSITIVE and deliberately not special-cased: it goes
        through the same threshold as everything else, so a single
        experimental pick proves nothing and two independent ones establish
        a leaning the Brand Brain can read.
        """
        from apps.learning.models import LearningEvent, LearningScope, SubjectType
        from apps.learning.services import (
            LearningError,
            record_event_safely,
            reinforce_preference,
        )

        if item.brand_id is None or not layout:
            return
        event = record_event_safely(
            workspace=item.workspace,
            brand=item.brand,
            event_type=LearningEvent.EventType.PREFERENCE_SIGNAL,
            outcome=LearningEvent.Outcome.POSITIVE,
            subject_type=SubjectType.CONTENT_ITEM,
            subject_id=item.pk,
            context={'action': 'LAYOUT_CHOSEN', 'layout': layout},
            dedupe_key=f'layout-chosen:{item.pk}:{layout}',
            created_by=user,
        )
        if event is None:
            return
        try:
            reinforce_preference(
                workspace=item.workspace,
                brand=item.brand,
                event=event,
                category='LAYOUT',
                attribute='poster_layout',
                value=layout,
                scope=LearningScope.BRAND,
            )
        except LearningError as exc:
            # A contradiction with the live preference, or a retired row.
            # Honest silence: the pick stands, the brand is not re-taught.
            logger.info("Layout preference not reinforced for %s: %s", item.pk, exc)

    @action(detail=False, methods=['post'])
    def export(self, request):
        """Composes the same poster once per destination size."""
        workspace, error = get_request_workspace(request)
        if error:
            return error

        serializer = ExportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        item = self._content(workspace, data['content_item'])
        if item is None:
            return APIResponse(
                success=False,
                message="Content not found.",
                error={"code": "NOT_FOUND", "message": "Content not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        spec, brand = self._spec_for(
            workspace,
            {
                'asset': data.get('asset'),
                'include_logo': data.get('include_logo'),
                'include_phone': data.get('include_phone'),
                'phone': data.get('phone', ''),
            },
            item=item,
        )
        layout = self._layout_key(data, brand, item)
        sizes = export_engine.valid(data.get('sizes') or export_engine.DEFAULT_SIZES)

        results, failures = [], []
        for size_key in sizes:
            try:
                image, fmt, _suffix = export_engine.render_size(spec, layout, size_key)
                asset = self._persist(
                    workspace, request.user, item, image, fmt, layout, suffix=size_key
                )
            except (render_engine.RenderError, StorageError) as exc:
                # One destination failing must not lose the caller the rest.
                logger.warning("Export %s failed for content %s: %s", size_key, item.pk, exc)
                failures.append({'size': size_key, 'error': str(exc)})
                continue

            label, width, height, platform = export_engine.SIZES[size_key]
            results.append({
                'size': size_key,
                'label': label,
                'platform': platform,
                'width': width,
                'height': height,
                'format': fmt,
                'asset': str(asset.id),
                'url': asset.file_url,
            })

        if not results:
            return APIResponse(
                success=False,
                message="Nothing could be exported.",
                error={"code": "EXPORT_FAILED", "message": "Nothing could be exported."},
                data={'failures': failures},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return APIResponse(
            success=True,
            data={'layout': layout, 'exports': results, 'failures': failures},
            status=status.HTTP_201_CREATED,
        )

    # -- persistence -----------------------------------------------------
    # Shared with the auto-compose path that runs after generation, so a
    # poster composed on the queue is stored exactly like one composed here.
    _persist = staticmethod(persist_composed)
