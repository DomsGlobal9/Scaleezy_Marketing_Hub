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
from .services import persist_composed, saved_copy, source_photo_asset

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
        from . import variants

        return APIResponse(
            success=True,
            data={
                'layouts': registry.catalogue(),
                'sizes': export_engine.catalogue(),
                # A template is a (pattern, style variant) pair; the axes are
                # what the Templates gallery explains and the total is the
                # number the founder asked for out loud.
                'templates': {
                    'total': variants.catalogue_size(),
                    'axes': {
                        'palette': list(variants.PALETTES),
                        'photo': list(variants.PHOTOS),
                        'paper': list(variants.PAPERS),
                        'casing': list(variants.CASINGS),
                        'pairing': list(variants.PAIRINGS),
                    },
                },
            },
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

        # Copy the studio saved with its last render, so an export or later
        # compose reproduces the poster that was actually on screen. Guarded
        # to a dict of strings: layout_config is client-writable JSON, and a
        # poisoned 'copy' must degrade to defaults, never 500 every preview.
        saved = saved_copy(item)

        # Key-presence semantics for the optional lines: an explicitly blank
        # subheadline/cta/phone means "remove that line", while an absent key
        # falls back to what was saved. Headline and offer keep their `or`
        # fallback — a poster with no headline is never what blank meant.
        def line(key):
            return str(data[key]) if key in data else saved.get(key, '')

        config = data.get('config') or (item.layout_config if item else {})
        spec = render_engine.spec_from(
            brand,
            headline=data.get('headline') or (item.headline if item else ''),
            subheadline=line('subheadline'),
            # ContentItem.cta is where the generator stores the offer line
            # (see apps/gemini/views.py), so it feeds the offer slot; the
            # call to action falls back to the brand's own keyword.
            offer=data.get('offer') or (item.cta if item else ''),
            cta=line('cta'),
            width=width,
            height=height,
            photo=photo,
            include_logo=(
                data.get('include_logo')
                if data.get('include_logo') is not None
                else saved.get('include_logo')
            ),
            include_phone=(
                data.get('include_phone')
                if data.get('include_phone') is not None
                else saved.get('include_phone')
            ),
            phone=line('phone'),
            config=config,
        )
        # The paid focal point steers studio renders and exports too, not
        # just the automatic compose — otherwise every manual re-render and
        # multi-size export silently reverts to the centred crop. Same
        # dict-with-'x' gate the compose path uses; cover() re-clamps every
        # value, so client-writable JSON degrades to centred, never fails.
        for source in (config, item.layout_config if item else None):
            if isinstance(source, dict):
                focus_info = source.get('photo_focus')
                if isinstance(focus_info, dict) and 'x' in focus_info:
                    spec.photo_focus = focus_info
                    break
        return spec, brand

    def _layout_key(self, data, brand, item=None):
        return (
            data.get('layout')
            or (item.layout_plugin if item and item.layout_plugin else '')
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
        if not layout:
            return APIResponse(
                success=False,
                message='Choose a template before previewing it.',
                error={'code': 'TEMPLATE_REQUIRED', 'message': 'Choose a template first.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

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
        if not layout:
            return APIResponse(
                success=False,
                message='Choose a template before composing this poster.',
                error={'code': 'TEMPLATE_REQUIRED', 'message': 'Choose a template first.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        try:
            image = render_engine.compose(spec, layout)
        except render_engine.RenderError as exc:
            return APIResponse(
                success=False, message=str(exc), status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        # Before anything persists: the rewrite record needs the before-values,
        # and the uploaded filename should carry the edited headline. Nothing
        # is saved yet, so a storage failure below still leaves the item alone.
        self._record_studio_rewrite(item, data, request.user)
        if data.get('headline'):
            item.headline = data['headline']
        if data.get('offer'):
            item.cta = data['offer']

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
        # The paid focal point (or its cached skip marker) survives a client
        # config replacing the rest of layout_config, exactly the way the
        # saved 'copy' does below — losing it would re-buy the vision call
        # on the next compose, or permanently recentre the crop.
        stored_config = item.layout_config if isinstance(item.layout_config, dict) else {}
        if 'photo_focus' not in config and isinstance(
            stored_config.get('photo_focus'), dict
        ):
            config['photo_focus'] = stored_config['photo_focus']
        # Remember which photograph this composition was built from — but only
        # the first time, and never a composed poster itself.
        if (
            item.asset_id
            and getattr(item.asset, 'source', '') != MarketingAsset.Source.COMPOSED
        ):
            config.setdefault('source_asset', str(item.asset_id))

        # The copy this poster was composed with. Edited headline/offer land on
        # the item itself (they are its own columns); the slots without columns
        # are kept in config so exports and future composes reproduce what was
        # on screen. Explicit blanks CLEAR their line — deleting a subheadline
        # in the studio must actually remove it, not resurrect the saved one.
        # Starts from the stored copy even when a client config replaces the
        # rest of layout_config, so the saved words survive that replacement.
        supplied = config.get('copy')
        copy_state = dict(supplied) if isinstance(supplied, dict) else dict(saved_copy(item))
        for key in ('subheadline', 'cta', 'phone'):
            if key in data:
                if data[key]:
                    copy_state[key] = data[key]
                else:
                    copy_state.pop(key, None)
        for key in ('include_logo', 'include_phone'):
            if data.get(key) is not None:
                copy_state[key] = data[key]
        if copy_state:
            config['copy'] = copy_state
        else:
            config.pop('copy', None)

        # A manual Poster Studio render is an explicit per-content template
        # choice. Record that truth so a later request-edits pass preserves
        # this layout instead of treating the older AI/reference source mode
        # as permission to silently choose a different one. Original source
        # provenance remains available separately for audit/lineage.
        previous_direction = config.get('creative_direction')
        if isinstance(previous_direction, dict) and previous_direction.get('mode') not in (
            None,
            '',
            'CATALOG_TEMPLATE',
        ):
            config.setdefault('source_creative_direction', dict(previous_direction))
        config['creative_direction'] = {
            'mode': 'CATALOG_TEMPLATE',
            'layout': layout,
            'selection_count': 0,
            'selections': [],
            'instructions': [f'Use the selected Scaleezy composition layout: {layout}.'],
        }

        item.layout_plugin = layout
        item.layout_config = config
        item.asset = asset
        item.preview_url = asset.file_url or ''
        item.save(
            update_fields=[
                'headline', 'cta', 'layout_plugin', 'layout_config',
                'asset', 'preview_url', 'updated_at',
            ]
        )

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

    @staticmethod
    def _record_studio_rewrite(item, data, user):
        """
        A studio rewrite is the same statement of intent as a draft PATCH:
        (what the machine wrote, what the human wanted). Recorded the same way
        the content endpoint's `_record_rewrite` does, so corrections made
        here reach the training loop instead of silently overwriting.
        """
        changed = {}
        if data.get('headline') and data['headline'] != item.headline:
            changed['headline'] = {'from': item.headline, 'to': data['headline']}
        if data.get('offer') and data['offer'] != item.cta:
            changed['cta'] = {'from': item.cta, 'to': data['offer']}
        if not changed or item.brand_id is None:
            return

        from apps.learning.models import LearningEvent, SubjectType
        from apps.learning.services import record_event_safely

        # Keep the first generated wording, so the pair survives the edit.
        config = dict(item.layout_config or {})
        if config.get('original_generated') is None:
            config['original_generated'] = {
                field: change['from'] for field, change in changed.items()
            }
            item.layout_config = config

        record_event_safely(
            workspace=item.workspace,
            brand=item.brand,
            event_type=LearningEvent.EventType.EDITED,
            outcome=LearningEvent.Outcome.NEGATIVE,
            subject_type=SubjectType.CONTENT_ITEM,
            subject_id=item.pk,
            context={
                'action': 'DRAFT_REWRITTEN',
                'fields': sorted(changed),
                'changes': {
                    field: {
                        'from': str(change['from'])[:300],
                        'to': str(change['to'])[:300],
                    }
                    for field, change in changed.items()
                },
            },
            created_by=user,
        )

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

        # The full payload, exactly like preview and render: the serializer
        # accepts the same copy overrides, so an export composes the words on
        # screen rather than silently reverting to older ones.
        spec, brand = self._spec_for(workspace, data, item=item)
        layout = self._layout_key(data, brand, item)
        if not layout:
            return APIResponse(
                success=False,
                message='Choose a template before exporting this poster.',
                error={'code': 'TEMPLATE_REQUIRED', 'message': 'Choose a template first.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
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
