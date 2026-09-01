"""
Composing posters outside the request cycle.

Generation produced a photograph and copy as two separate things, so the
draft that reached Review was a bare image with no words on it — reviewers
kept asking where the poster went. `compose_generated_poster` closes that
gap: the same engine behind the studio's "Use this poster" runs automatically
after a generation persists, so the draft arrives with the brand's palette,
fonts, headline and offer already baked in.

Best-effort by design: a compose failure leaves the raw generated image in
place, because losing a paid generation to a font hiccup is worse than
showing the photo bare.
"""
import logging
import uuid

from django.core.exceptions import ValidationError

from apps.marketing.models import MarketingAsset
from apps.marketing.services.storage import SupabaseStorageService

from . import export as export_engine
from . import registry
from . import render as render_engine
from . import variants

logger = logging.getLogger(__name__)


def persist_composed(workspace, user, item, image, fmt, layout, suffix=''):
    """Uploads one composed image and records it as a MarketingAsset."""
    extension = 'pdf' if fmt == 'PDF' else 'jpg'
    stem = (item.headline or 'poster').lower()
    stem = ''.join(c if c.isalnum() else '-' for c in stem).strip('-')[:40] or 'poster'
    filename = f"{stem}-{layout}{('-' + suffix) if suffix else ''}.{extension}"

    described = SupabaseStorageService.upload_and_describe(
        str(workspace.id), export_engine.to_file(image, fmt), filename, prefix='composed'
    )

    return MarketingAsset.objects.create(
        workspace=workspace,
        asset_type=MarketingAsset.AssetType.POSTER,
        file_name=filename,
        file_url=described['url'],
        storage_path=described['path'],
        mime_type='application/pdf' if fmt == 'PDF' else 'image/jpeg',
        width=image.width,
        height=image.height,
        source=MarketingAsset.Source.COMPOSED,
        created_by=user if user and getattr(user, 'is_authenticated', False) else None,
    )


def saved_copy(item):
    """
    The copy dict a render persisted on this item, or {} — never a poisoned
    shape. `layout_config` is client-writable JSON, so the stored 'copy'
    cannot be trusted to be a dict of strings; anything malformed degrades to
    defaults rather than failing every later compose with a 500.
    """
    if item is None or not isinstance(item.layout_config, dict):
        return {}
    candidate = item.layout_config.get('copy')
    if not isinstance(candidate, dict):
        return {}
    cleaned = {}
    for key in ('subheadline', 'cta', 'phone'):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            cleaned[key] = value
    for key in ('include_logo', 'include_phone'):
        value = candidate.get(key)
        if isinstance(value, bool):
            cleaned[key] = value
    return cleaned


def source_photo_asset(item):
    """
    The photograph a composition should be built from.

    Once a poster has been composed, `item.asset` IS the composed poster —
    text already on it. Composing from that again would bake the words on
    twice, so the original photograph's id is recorded in `layout_config`
    the first time and preferred ever after.
    """
    if item is None:
        return None
    config = item.layout_config if isinstance(item.layout_config, dict) else {}
    source_id = config.get('source_asset')
    if not source_id:
        return item.asset
    try:
        return (
            MarketingAsset.objects.filter(
                pk=source_id, workspace_id=item.workspace_id
            ).first()
            or item.asset
        )
    except (ValueError, ValidationError):
        # A malformed id in stored config must not fail a render.
        return item.asset


def generated_layout(item):
    """
    The pattern an automatic compose uses when nobody named one.

    Falling through to the registry default meant every generated poster in a
    brand shared a single skeleton — reviewers saw "the same poster" over and
    over. The pick rotates across the photo-using patterns instead, keyed on
    the item's id: stable for the item (a recompose or revision never reshuffles
    a poster someone is already reviewing), different across items.

    Type-only patterns (`uses_photo=False`) are excluded — they would throw
    away the photograph the generation just paid for.
    """
    options = [
        key for key in registry.keys()
        if getattr(registry.get(key), 'uses_photo', True)
    ] or [registry.DEFAULT_KEY]
    try:
        seed = uuid.UUID(str(item.pk)).int
    except (ValueError, AttributeError, TypeError):
        seed = 0
    return options[seed % len(options)]


def compose_generated_poster(item, *, user=None):
    """
    Bake the generated copy onto the generated photo, automatically.

    Runs after a generation persists its DRAFT ContentItem. Returns the
    composed MarketingAsset, or None when there was nothing to compose or
    the composition failed — in which case the item is left exactly as the
    generation made it.
    """
    from apps.content.models import ContentItem

    if item is None or item.content_format != ContentItem.Format.POSTER:
        return None
    if item.brand is None or not (item.headline or item.cta):
        return None
    if item.asset is None or not getattr(item.asset, 'file_url', ''):
        return None

    try:
        # The recorded source photograph when there is one — composing from an
        # already composed poster would bake the words on twice.
        photo = render_engine.photo_for(asset=source_photo_asset(item))
        layout = (
            item.layout_plugin
            or (item.brand.layout_preference or '')
            or generated_layout(item)
        )
        _label, width, height, _platform = export_engine.SIZES['instagram_portrait']
        # The copy a studio render saved on this item travels into automatic
        # composes too, so a regenerated revision carries the same words the
        # studio showed — not a stripped-down subset of them.
        saved = saved_copy(item)
        spec = render_engine.spec_from(
            item.brand,
            headline=item.headline,
            subheadline=saved.get('subheadline', ''),
            offer=item.cta,
            cta=saved.get('cta', ''),
            width=width,
            height=height,
            photo=photo,
            include_logo=saved.get('include_logo'),
            include_phone=saved.get('include_phone'),
            phone=saved.get('phone', ''),
        )
        # The style variant this item wears — same skeleton, different dress.
        # A stored one is reused so a recompose never restyles a poster
        # someone is already reviewing; otherwise the item's id decides.
        stored = (item.layout_config or {}).get('style_variant')
        if isinstance(stored, dict):
            variant = variants.coerce(stored)
        else:
            variant = variants.variant_for(
                item, uses_photo=getattr(registry.get(layout), 'uses_photo', True)
            )
        spec = variants.apply(spec, variant)
        image = render_engine.compose(spec, layout)
        source = item.asset
        asset = persist_composed(item.workspace, user, item, image, 'JPEG', layout)
    except Exception:
        logger.exception("Auto-compose failed for content %s; raw image kept", item.pk)
        return None

    config = dict(item.layout_config or {})
    config.setdefault('source_asset', str(source.pk))
    config['style_variant'] = variant
    item.layout_plugin = layout
    item.layout_config = config
    item.asset = asset
    item.preview_url = asset.file_url or ''
    item.save(
        update_fields=['layout_plugin', 'layout_config', 'asset', 'preview_url', 'updated_at']
    )
    return asset
