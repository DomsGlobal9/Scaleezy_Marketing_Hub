"""
The Context Gateway.

One place answers "what does Scaleezy know about this brand, for this job?".
Before this, anything that wanted brand intelligence went and got it itself —
the generator read learned rules straight out of the training engine, and
anything else would have grown its own copy of that logic. Every such reader is
a place the precedence rules can be got wrong, and a place a new AI provider
would have to reimplement.

So the gateway consumes the COMPILED brain from PR4, never the raw records
behind it. The precedence contest has already happened; re-reading the sources
here would let a raw inference sit beside the resolved answer and quietly win.
Callers get one provider-neutral object and no way to reach past it.

Task-aware on purpose. Copy generation does not need the layout grid and image
generation does not need the objection list, and sending everything on every
call is how a context window fills with things the model then has to ignore.
Hard rules are the exception: they travel with every task, because a
constraint that only applies to some jobs is not a constraint.
"""
import hashlib

from django.core.cache import cache

from apps.brands.services.brand_brain import (
    SCHEMA_VERSION,
    brain_snapshot_needs_refresh,
    compile_brand_brain,
)

#: Context payload shape. Bump when a consumer must notice a change.
#: 2 adds the brand's own description and stated audience. The bump is also the
#: invalidation: it is part of the cache key, so cuts made before the fields
#: existed stop being addressed instead of serving a context missing them.
CONTEXT_SCHEMA_VERSION = 2


class TaskType:
    COPY = 'COPY'
    IMAGE = 'IMAGE'
    VIDEO = 'VIDEO'
    IMAGE_ANALYSIS = 'IMAGE_ANALYSIS'

    ALL = (COPY, IMAGE, VIDEO, IMAGE_ANALYSIS)


class ContextError(Exception):
    """The requested context cannot be built."""


#: Claim categories each task actually acts on. A claim outside its task's set
#: is dropped from `preferences` — it is real, it is just not this job.
COPY_CATEGORIES = {'TONE', 'COPY_STYLE', 'HOOK', 'CTA', 'STRUCTURE', 'MOOD', 'FACT'}
VISUAL_CATEGORIES = {
    'TYPOGRAPHY', 'COLOR', 'LAYOUT', 'COMPOSITION', 'IMAGERY',
    'PHOTOGRAPHY', 'ILLUSTRATION', 'BRANDING',
}
MOTION_CATEGORIES = {'MOTION', 'PACING'}

#: Per task: which narrative sections carry weight, which claim categories are
#: relevant, and whether raw inspiration signals are worth the tokens.
TASK_PROFILES = {
    TaskType.COPY: {
        'sections': {'positioning', 'audience', 'voice', 'verified_truth'},
        'categories': COPY_CATEGORIES,
        'inspirations': False,
    },
    TaskType.IMAGE: {
        'sections': {'visual_language', 'verified_truth'},
        'categories': VISUAL_CATEGORIES,
        'inspirations': True,
    },
    TaskType.VIDEO: {
        'sections': {'visual_language', 'voice', 'verified_truth'},
        'categories': VISUAL_CATEGORIES | MOTION_CATEGORIES | {'TONE', 'HOOK'},
        'inspirations': True,
    },
    TaskType.IMAGE_ANALYSIS: {
        'sections': {'visual_language'},
        'categories': VISUAL_CATEGORIES,
        'inspirations': True,
    },
}

#: How long a cut context may be reused. Short on purpose: the brain_version
#: in the key does the real invalidation; the TTL only bounds memory.
CONTEXT_CACHE_SECONDS = 600

#: Budget. Enough to steer a generation, not enough to bury it.
MAX_ITEMS = 12
MAX_SOFT_RULES = 10
MAX_INSPIRATION_SIGNALS = 8


def resolved_brain(brand, *, recompile_if_missing=True):
    """Resolve a currently eligible compiled brain without database writes.

    Normal generation reuses the snapshot. Only a missing/unsafe snapshot is
    recompiled by its existing owner; raw records never bypass precedence.
    """
    brain = brand.creative_brain or {}
    try:
        if brain.get('schema_version') == SCHEMA_VERSION and brain.get('brain_version'):
            if not brain_snapshot_needs_refresh(brand, brain):
                return brain
        if not recompile_if_missing:
            return {}
        return compile_brand_brain(brand)
    except Exception as exc:
        # A warm cache is not permission to use withdrawn or expired evidence.
        raise ContextError('Current brand context is unavailable. Refresh the brand context and retry.') from exc


def _section(brain, profile, name, value, empty):
    """Sections outside the task's profile collapse to empty rather than
    vanish, so the payload shape is the same whatever the task."""
    return value if name in profile['sections'] else empty


def build_generation_context(
    workspace,
    brand,
    task_type=TaskType.COPY,
    *,
    instruction='',
    channel='',
    content_format='',
    objective='',
):
    """The one call an AI capability makes to learn about a brand.

    Raises rather than guessing if the brand is not the caller's: a gateway
    that silently returned the wrong tenant's intelligence would be the worst
    possible place for that bug to live.
    """
    if brand is None:
        raise ContextError("A brand is required to build generation context.")
    if brand.workspace_id != workspace.id:
        raise ContextError("Brand does not belong to this workspace.")
    if task_type not in TASK_PROFILES:
        raise ContextError(f"Unknown task type: {task_type}")

    profile = TASK_PROFILES[task_type]
    brain = resolved_brain(brand)
    if not brain:
        raise ContextError("This brand has no compiled Brand Brain.")
    # Existing universal precedence and generation attribution read this same
    # instance. Keep them aligned with the resolved snapshot, without saving a
    # derived cache from a read endpoint or changing the persisted Brain shape.
    brand.creative_brain = brain

    # The universal layer: Scaleezy's own craft standards, at rank 80+ and
    # already filtered so none of them touches an attribute this brand has a
    # position on. Resolved BEFORE the cache key is built, because retiring a
    # standard or a client switching the layer off has to invalidate the cut
    # immediately — otherwise a retired standard keeps reaching generations
    # for the life of the cache entry.
    from apps.universal.services import (
        patterns_as_context,
        patterns_for,
        standards_as_context,
        standards_for,
    )

    universal_standards, universal_ver = standards_for(
        workspace, brand, channel=channel, content_format_or_type=content_format,
    )
    learned_patterns, learned_pattern_ver = patterns_for(
        workspace, brand, channel=channel,
    )

    # ---- context cache -------------------------------------------------
    # Selection over an unchanged brain is deterministic, so the cut is
    # reusable until the brain moves. The brain_version in the key is the
    # invalidation: new learning compiles a new version and stale entries
    # simply stop being addressed. Workspace and brand ids are in the key,
    # so one tenant's context is unreachable from another's request by
    # construction.
    cache_key = 'genctx:' + hashlib.sha256('|'.join([
        str(workspace.id), str(brand.pk), brain.get('brain_version', ''),
        str(CONTEXT_SCHEMA_VERSION), task_type, universal_ver, learned_pattern_ver,
        instruction or '', channel or '', content_format or '', objective or '',
    ]).encode('utf-8')).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    identity = brain.get('identity', {})
    positioning = brain.get('positioning', {})
    audiences = brain.get('audiences', {})
    voice = brain.get('voice', {})
    visual = brain.get('visual_language', {})

    relevant = [
        claim for claim in brain.get('preferences', [])
        if claim.get('category') in profile['categories']
    ][:MAX_ITEMS]

    context = {
        'context_schema_version': CONTEXT_SCHEMA_VERSION,
        'workspace_id': str(workspace.id),
        'brand_id': str(brand.pk),
        # Which brain this was cut from. Two contexts with the same
        # brain_version and the same task inputs are the same context.
        'brain_version': brain.get('brain_version', ''),
        # Which universal standards this cut carried. In the trace as well as
        # the key, so "did standard X reach client Y" is answerable later.
        'universal_version': universal_ver,
        'universal_standards': standards_as_context(universal_standards),
        'learned_pattern_version': learned_pattern_ver,
        'learned_patterns': patterns_as_context(learned_patterns),
        'task_type': task_type,

        'brand_identity': {
            'name': identity.get('name', ''),
            'industry': identity.get('industry', ''),
            # Not task-gated: what the brand actually is bears on copy, imagery
            # and video alike, and a model that does not know it invents one.
            'description': identity.get('description', ''),
            'tagline': identity.get('tagline', ''),
            'cta_keyword': identity.get('cta_keyword', ''),
            'canon': identity.get('canon', [])[:MAX_ITEMS],
        },
        'verified_truth': _section(
            brain, profile, 'verified_truth',
            brain.get('verified_product_truth', [])[:MAX_ITEMS], [],
        ),
        'positioning': _section(
            brain, profile, 'positioning',
            {
                'statements': positioning.get('statements', [])[:MAX_ITEMS],
                'competitors': positioning.get('competitors', [])[:MAX_ITEMS],
            },
            {'statements': [], 'competitors': []},
        ),
        'audience': _section(
            brain, profile, 'audience',
            {
                'stated': audiences.get('stated', ''),
                'pains': audiences.get('pains', [])[:MAX_ITEMS],
                'objections': audiences.get('objections', [])[:MAX_ITEMS],
            },
            {'stated': '', 'pains': [], 'objections': []},
        ),
        'voice': _section(
            brain, profile, 'voice',
            {'tone': voice.get('tone', ''), 'claims': voice.get('claims', [])[:MAX_ITEMS]},
            {'tone': '', 'claims': []},
        ),
        'visual_language': _section(
            brain, profile, 'visual_language',
            {
                'palette': visual.get('palette', {}),
                'fonts': visual.get('fonts', {}),
                'claims': visual.get('claims', [])[:MAX_ITEMS],
            },
            {'palette': {}, 'fonts': {}, 'claims': []},
        ),

        # Never trimmed and never task-filtered. A hard rule the model was not
        # told about is not a rule.
        'hard_rules': brain.get('hard_rules', []),
        'soft_rules': brain.get('soft_rules', [])[:MAX_SOFT_RULES],
        'preferences': relevant,
        'win_patterns': brain.get('win_patterns', [])[:MAX_ITEMS],
        'avoid_patterns': brain.get('avoid_patterns', [])[:MAX_ITEMS],
        'inspiration_signals': (
            brain.get('inspiration_signals', [])[:MAX_INSPIRATION_SIGNALS]
            if profile['inspirations'] else []
        ),

        'task_context': {
            'instruction': instruction or '',
            'channel': channel or '',
            'format': content_format or '',
            'objective': objective or '',
        },

        # Surfaced, never resolved here. The gateway does not get to pick a
        # winner the compiler deliberately refused to pick.
        'unresolved_conflicts': brain.get('conflicts', []),
        'unresolved_conflict_count': brain.get('unresolved_conflict_count', 0),

        'source_summary': {
            'memories': len(brain.get('sources', {}).get('memory_ids', [])),
            'rules': len(brain.get('sources', {}).get('rule_ids', [])),
            'preferences': len(brain.get('sources', {}).get('preference_ids', [])),
            'inspiration_signals': len(
                brain.get('sources', {}).get('inspiration_signal_ids', [])
            ),
        },
    }

    cache.set(cache_key, context, timeout=CONTEXT_CACHE_SECONDS)
    return context


def context_as_brief(context):
    """Flatten context into the provider-neutral brief the AI router carries.

    Still no provider in sight: an adapter turns this into whatever shape its
    API wants, which is the whole reason a second provider does not mean a
    second copy of the brand-learning logic.
    """
    identity = context['brand_identity']
    lines = []
    if identity['name']:
        lines.append(f"Brand: {identity['name']}")
    if identity['industry']:
        lines.append(f"Industry: {identity['industry']}")
    # In the prose, not only in `structured`: an adapter that reads the brief as
    # a paragraph would otherwise never see what the brand is or who it is for,
    # which is the whole reason those fields are collected.
    if identity.get('description'):
        lines.append(f"About: {identity['description']}")
    if identity['tagline']:
        lines.append(f"Tagline: {identity['tagline']}")
    if context['audience'].get('stated'):
        lines.append(f"Audience: {context['audience']['stated']}")
    if context['voice']['tone']:
        lines.append(f"Voice: {context['voice']['tone']}")
    for truth in context['verified_truth']:
        lines.append(f"Verified: {truth}")
    # Whether the words go INTO the image is not the gateway's call: it
    # depends on the content type and creative mode the brief carries, which
    # the context never sees. `on_image_text_lines` decides per dispatch.
    for rule in context['hard_rules']:
        lines.append(f"MUST: {rule.get('text', '')}")
    for rule in context['soft_rules']:
        lines.append(f"Prefer: {rule.get('text', '')}")
    for pattern in context['avoid_patterns']:
        lines.append(f"Avoid: {pattern}")
    # Resolved preference claims, so what the brand has taught Scaleezy - a
    # calibration verdict, an adjustment note - reaches the provider in the
    # prose brief and not only in the structured block.
    for claim in context['preferences']:
        label = claim.get('attribute') or claim.get('category', '')
        value = claim.get('value', '')
        if value:
            lines.append(f"Prefer ({label}): {value}")
    # Last, and labelled as ours rather than as the brand's. Position in the
    # prose mirrors authority: everything above outranks these, and the label
    # is what makes the suggestion attributable when a client asks where it
    # came from.
    for standard in context.get('universal_standards', []):
        lines.append(f"Scaleezy craft standard: {standard['guidance']}")
    for pattern in context.get('learned_patterns', []):
        lines.append(
            'Scaleezy learned pattern: '
            f"{pattern['category']} / {pattern['attribute']} = {pattern['value']} "
            f"({pattern['contributor_count']} contributing client(s))"
        )

    return {
        'task': context['task_type'],
        'instruction': context['task_context']['instruction'],
        'brand_context': lines,
        'brand_id': context['brand_id'],
        'brain_version': context['brain_version'],
        # Kept structured alongside the prose so an adapter that prefers
        # fields over a paragraph does not have to parse it back out.
        'structured': {
            'identity': identity,
            'voice': context['voice'],
            'visual_language': context['visual_language'],
            'hard_rules': context['hard_rules'],
            'preferences': context['preferences'],
            'avoid_patterns': context['avoid_patterns'],
            'win_patterns': context['win_patterns'],
            'learned_patterns': context.get('learned_patterns', []),
        },
    }


# --------------------------------------------------------------------------
# Words in the picture. One decision, shared by every image dispatch — the
# provider-neutral IMAGE brief and the Gemini two-step pipeline alike — so no
# adapter can drift back to its own idea of what text a poster carries.
# --------------------------------------------------------------------------

#: What the image model is told wherever the compose engine still owns the
#: words — catalogue-template posters and carousel slides. An image model that
#: renders its own headline there produces the half-cropped double text
#: reviewers called "unfinished": its lettering fights the composed typography
#: and gets clipped by the layout.
NO_TEXT_LINE = (
    "MUST: The image is a photograph/visual only - absolutely no text, "
    "lettering, numbers, captions, watermarks or logos rendered in the "
    "image. All typography is composed onto it later."
)


#: The poster compositions a delegated design rotates through. Every AI-original
#: poster used to be told ONE recipe (the framed social-sale panel), so a
#: brand's drafts came back as the same template in different colours - the
#: founder's "more or less the same template design". Each archetype places
#: the headline, the CTA and the optional vertical offer line coherently; the
#: on-image text rules around it are unchanged. `composition` is the image
#: call's MUST line, with `{cta}` / `{offer}` filled from the archetype's own
#: phrases only when the brief carries a CTA / offer, so nothing is invented.
#: `step1` is how the copy model is told to describe the composition in its
#: imagePrompt, with `{cta}` / `{offer}` filled from `step1_cta` /
#: `step1_offer` the same conditional way (see `step1_line`): a copy model
#: told to keep an edge clear for an offer that does not exist describes
#: one, and the image model then invents its wording. The first entry is
#: the legacy recipe, verbatim, and the fallback wherever no archetype was
#: picked.
COMPOSITION_ARCHETYPES = (
    {
        'key': 'framed_panel',
        'label': 'Framed panel',
        'composition': (
            'Compose a clean social-sale poster: a framed border, a centred photo '
            'panel, the headline overlaid on the photo{cta}{offer}, small social '
            'icons, dotted accents.'
        ),
        'cta': ', a CTA pill',
        'offer': ', the offer line set vertically along one edge',
        'step1': (
            'a framed border, a centred photo panel, and a big, bold, uppercase '
            'headline overlaid on the photo with high contrast and generous '
            'margins{cta}{offer}'
        ),
        'step1_cta': ', plus room for a small call-to-action pill',
        'step1_offer': ' and an offer line set vertically along one edge',
    },
    {
        'key': 'full_bleed_band',
        'label': 'Full-bleed photo with bottom band',
        'composition': (
            'Compose a full-bleed poster: the photograph fills the entire frame '
            'edge to edge, and a solid brand-colour band across the bottom third '
            'carries the headline{cta}{offer}.'
        ),
        'cta': ' and a CTA pill',
        'offer': ', with the offer line set vertically along one side edge of the photo',
        'step1': (
            'a full-bleed photograph filling the whole frame, with a solid '
            'brand-colour band across the bottom third reserved for the '
            'headline{cta}{offer}'
        ),
        'step1_cta': ' and a small call-to-action pill',
        'step1_offer': ', and one side edge kept clear for an offer line set vertically',
    },
    {
        'key': 'split_vertical',
        'label': 'Vertical split',
        'composition': (
            'Compose a split poster: the photograph occupies one half of the frame '
            'and the other half is a flat brand-colour field carrying the headline '
            'stacked in large type{cta}{offer}.'
        ),
        'cta': ' above a CTA pill',
        'offer': ', the offer line set vertically along the outer edge of the colour half',
        'step1': (
            'a vertical split - the photograph on one half, a flat brand-colour '
            'half on the other with the headline stacked in large '
            'type{cta}{offer}'
        ),
        'step1_cta': ' above a small call-to-action pill',
        'step1_offer': ', and the outer edge kept clear for a vertical offer line',
    },
    {
        'key': 'magazine_cover',
        'label': 'Magazine cover',
        'composition': (
            'Compose a magazine-cover poster: a full-bleed portrait photograph with '
            'the headline set as ONE bold title across the top of the frame - the '
            'only title on the poster, no cover lines or secondary headlines'
            '{cta}{offer}.'
        ),
        'cta': ', a small CTA pill in a bottom corner',
        'offer': ', the offer line set vertically along one edge',
        'step1': (
            'a full-bleed portrait photograph with the headline as one bold '
            'title across the top - the only title on the poster, no cover '
            'lines or secondary headlines{cta}{offer}'
        ),
        'step1_cta': ', a small call-to-action pill in a bottom corner',
        'step1_offer': ', and one edge kept clear for a vertical offer line',
    },
    {
        'key': 'minimal_centred',
        'label': 'Minimal centred',
        'composition': (
            'Compose a minimal poster: generous negative space on a calm '
            'brand-colour or off-white ground, a smaller centred photograph, the '
            'headline set beneath it{cta}{offer}.'
        ),
        'cta': ' and a CTA pill under the headline',
        'offer': ', the offer line set vertically along one edge in small type',
        'step1': (
            'generous negative space on a calm ground, a smaller centred '
            'photograph with the headline beneath it{cta}{offer}'
        ),
        'step1_cta': ' and a small call-to-action pill under that',
        'step1_offer': ', and one edge kept clear for a small vertical offer line',
    },
    {
        'key': 'diagonal_cut',
        'label': 'Diagonal cut',
        'composition': (
            'Compose a diagonal-cut poster: the photograph is clipped along a bold '
            'diagonal, and the remaining flat brand-colour wedge carries the '
            'headline{cta}{offer}.'
        ),
        'cta': ' with a CTA pill beneath it',
        'offer': ', the offer line set vertically along the edge of the wedge',
        'step1': (
            'a photograph clipped on a bold diagonal, with the flat '
            'brand-colour wedge left for the headline{cta}{offer}'
        ),
        'step1_cta': ', a small call-to-action pill beneath it',
        'step1_offer': ", and a vertical offer line along the wedge's edge",
    },
    {
        'key': 'type_first',
        'label': 'Type first',
        'composition': (
            'Compose a type-first poster: the giant headline is the background '
            'element filling the frame, and the photographed subject sits BESIDE '
            'or BENEATH it, overlapping at most the descender space and never '
            'covering a letter, so every word stays fully legible{cta}{offer}.'
        ),
        'cta': ', a CTA pill in a lower corner',
        'offer': ', the offer line set vertically along one edge',
        'step1': (
            'a giant headline as the background element with the photographed '
            'subject placed beside or beneath it - overlapping at most the '
            'descender space, never covering the letters{cta}{offer}'
        ),
        'step1_cta': ' - a small call-to-action pill in a lower corner',
        'step1_offer': ', and one edge kept clear for a vertical offer line',
    },
    {
        'key': 'polaroid_card',
        'label': 'Polaroid card',
        'composition': (
            'Compose a polaroid-card poster: ONE photograph sits as a slightly '
            'tilted white-bordered card on a textured brand-colour ground (no '
            'second card or inset), and the headline is set beside it{cta}{offer}.'
        ),
        'cta': ' with a CTA pill below',
        'offer': ', the offer line set vertically along the far edge',
        'step1': (
            'a slightly tilted polaroid-style photo card on a textured '
            'brand-colour ground with the headline set beside it{cta}{offer}'
        ),
        'step1_cta': ', a small call-to-action pill below the headline',
        'step1_offer': ', and the far edge kept clear for a vertical offer line',
    },
)

DEFAULT_COMPOSITION_ARCHETYPE = COMPOSITION_ARCHETYPES[0]['key']

#: Scene seeds. Within one brand template - or one archetype - every run used
#: to bring back the same pose in the same setting, because nothing varied the
#: photograph itself. One of these rides in each poster brief (least recently
#: used per brand) and is applied in template mode and archetype mode alike.
#: Product-neutral on purpose: "the hero subject/product" is a saree, a
#: coffee bag or a sofa alike. A seed marked `crops_face` frames tighter than
#: a face - it is never drawn, and never rendered, for a poster that carries
#: the brand ambassador's photo (see `scene_directive`).
SCENE_VARIANTS = (
    {
        'key': 'studio_three_quarter',
        'directive': (
            'the hero subject/product in a studio seamless backdrop in a '
            'brand-palette tone, shown three-quarter view under soft '
            'directional light'
        ),
    },
    {
        'key': 'heritage_courtyard_walk',
        'directive': (
            'the hero subject/product in a heritage courtyard or arched veranda, '
            'a walking shot caught mid-stride under warm natural light'
        ),
    },
    {
        'key': 'detail_close_up',
        'crops_face': True,
        'directive': (
            'a close-up detail of the hero product - its texture, finish and '
            'craft - with the subject only partly in frame and shallow depth of '
            'field'
        ),
    },
    {
        'key': 'street_golden_hour',
        'directive': (
            'the hero subject/product on a city street at golden hour, standing '
            'or leaning candidly with long soft shadows and glowing backlight'
        ),
    },
    {
        'key': 'interior_lounge_seated',
        'directive': (
            'the hero subject/product in an elegant interior lounge, seated on a '
            'sofa or bench, side-lit through a window'
        ),
    },
    {
        'key': 'motion_mid_frame',
        'directive': (
            'the hero subject/product in motion mid-frame - a turn, a step, a '
            'pour, a reveal - against a clean gradient ground'
        ),
    },
)

#: Appended to every scene seed when the brand ambassador's photo rides in
#: the brief: a seed may vary the setting and the pose, never the face.
#: Live, 2026-09-05: a polaroid composition put the model's face in a small
#: second card and a headless torso in the main one - "visible" was met,
#: the founder's "face is cut" was not. The face belongs in the main
#: photograph, not only in an inset.
FACE_VISIBLE_LINE = (
    "the brand ambassador's face stays fully visible inside the main "
    "photograph, never only in a smaller inset, card or second frame"
)


def composition_archetype(key):
    """The archetype row for `key`, or the legacy framed panel when the key
    is absent or unknown - so a brief that never picked one still works."""
    wanted = str(key or '').strip()
    for row in COMPOSITION_ARCHETYPES:
        if row['key'] == wanted:
            return row
    return COMPOSITION_ARCHETYPES[0]


def scene_variant(key):
    """The scene row for `key`, or None: with no seed picked, no scene line
    is emitted and the brief reads exactly as it did before."""
    wanted = str(key or '').strip()
    for row in SCENE_VARIANTS:
        if row['key'] == wanted:
            return row
    return None


def brief_cta_and_offer(brief):
    """The CTA wording and offer wording a brief carries, each '' when absent.

    The CTA is the brief's own (`brief['cta']`, typed into the studio's
    brief as "CTA: Shop the collection" - see `brief_fields`) when it has
    one, else the brand identity's `cta_keyword`. One reading for the image
    call's text lines, the finished picture's text check and Step 1's
    composition sentence, so none describes a pill or an offer line the
    others do not know about.
    """
    identity = (brief.get('structured') or {}).get('identity') or {}
    cta = (
        ' '.join(str(brief.get('cta') or '').split())
        or ' '.join(str(identity.get('cta_keyword') or '').split())
    )
    offer = ' '.join(str(brief.get('offer') or '').split())
    return cta, offer


def step1_line(archetype, cta, offer):
    """How Step 1 describes the composition: the archetype's own words, with
    the CTA pill and the vertical offer line mentioned ONLY when the brief
    carries them. Live, a poster whose brief had no offer came back with an
    invented strapline in the edge Step 1 had told the model to keep clear
    for one."""
    return archetype['step1'].format(
        cta=archetype['step1_cta'] if cta else '',
        offer=archetype['step1_offer'] if offer else '',
    )


def _composition_line(archetype, cta, offer):
    return 'MUST: ' + archetype['composition'].format(
        cta=archetype['cta'] if cta else '',
        offer=archetype['offer'] if offer else '',
    )


def scene_directive(brief):
    """How this brief's photograph is shot, or '' with no seed picked.

    One reading for both callers - the image call's MUST line and Step 1's
    scene sentence - so the copy model and the image model never describe
    two different scenes. Where the brief carries the brand ambassador's
    photo (`ambassador_image_base64`), a seed that would crop the face is
    swapped for the first face-safe one and every seed says the face stays
    visible: the ambassador exists to be recognised.
    """
    scene = scene_variant(brief.get('scene_variant'))
    if scene is None:
        return ''
    ambassador = bool(brief.get('ambassador_image_base64'))
    if ambassador and scene.get('crops_face'):
        scene = next(row for row in SCENE_VARIANTS if not row.get('crops_face'))
    directive = scene['directive']
    if ambassador:
        directive += ', and ' + FACE_VISIBLE_LINE
    return directive


def _scene_line(brief):
    directive = scene_directive(brief)
    if not directive:
        return []
    return [
        'MUST: Shoot the photograph as ' + directive + ' - a photograph '
        'made fresh for this poster, never a repeat of an earlier one.'
    ]


def _direction(brief):
    direction = brief.get('creative_direction')
    return direction if isinstance(direction, dict) else {}


def poster_renders_its_own_text(brief):
    """Whether this generation's words are typography the image model paints.

    True for a delegated poster design (AI_ORIGINAL, REFERENCE, or no stated
    mode): since the no-default-dress decision those ship the provider's
    poster untouched, so a headline the image does not carry is a headline
    nobody sees. False wherever the compose engine still owns the words - a
    CATALOG_TEMPLATE poster - and for carousel slides, whose behaviour is
    deliberately unchanged.
    """
    content_type = str(brief.get('contentType') or '').strip().lower()
    if content_type not in ('', 'poster'):
        return False
    mode = str(_direction(brief).get('mode') or '').strip().upper()
    return mode != 'CATALOG_TEMPLATE'


def _has_brand_template(direction):
    """A BRAND_TEMPLATE selection: the brand's own poster design is the spec."""
    return any(
        isinstance(row, dict) and row.get('kind') == 'BRAND_TEMPLATE'
        for row in (direction.get('selections') or [])
    )


def _mirrors_reference(direction):
    return str(direction.get('mode') or '').strip().upper() == 'REFERENCE'


def on_image_text_lines(brief, headline):
    """The brief lines that put a poster's words INTO the image.

    The founder's directive - "add the headline text on the image too" - in
    the style of the classic social-sale template: big bold uppercase
    headline over the photo, a CTA pill, the offer set vertically along an
    edge, framed border, small social icons, dotted accents. The headline is
    quoted verbatim so the model has an exact string to spell, never a
    paraphrase; the CTA is the brief's own when typed, else the brand's
    keyword, and the offer the campaign's (typed or chip alike, see
    `brief_cta_and_offer`), each only when present. Text stops there: no
    paragraphs on the image.

    With no headline there is nothing to render and inventing words is worse
    than none, so the no-text line applies - as it does wherever the compose
    engine still owns the words (see `poster_renders_its_own_text`).

    The composition comes from `brief['composition_archetype']` (see
    `COMPOSITION_ARCHETYPES`; the framed social-sale panel when absent) and
    the photograph's scene from `brief['scene_variant']` (nothing when
    absent) - both picked least-recently-used per brand by the generation
    layer, so one brand's drafts stop sharing a single layout and pose.
    """
    headline = ' '.join(str(headline or '').split())
    if not headline or not poster_renders_its_own_text(brief):
        return [NO_TEXT_LINE]

    # Format adaptation: the attached image is the brand's own APPROVED
    # creative, and the job is the same poster on a new canvas — not a new
    # photograph, not new words, not a new design. Every other branch below
    # exists to make something new; this one exists to change nothing but
    # the frame.
    if brief.get('format_adaptation'):
        return [
            'MUST: Render this exact headline ON the image, word for word and '
            f'correctly spelled: "{headline}", with the same typographic '
            'treatment the attached approved creative gives it.',
            'MUST: Reproduce every text element of the attached creative '
            'verbatim - same wording, casing, hierarchy and relative '
            'placement, recomposed gracefully for the new canvas. Add no '
            'text element and drop none.',
        ]

    cta, offer = brief_cta_and_offer(brief)
    direction = _direction(brief)

    # Template mode: the template's own typography IS the spec. The founder's
    # uppercase-headline/CTA-pill style below belongs to the classic
    # social-sale poster; imposing it here uppercased a title-case template's
    # headline and painted a second CTA button under the template's own one.
    # INSPIRED fidelity deliberately skips this: no pixels are attached, so
    # "the template's own slots" would reference a design the model cannot
    # see — those generations take the REFERENCE mirror branch below.
    template_exact = (
        str(brief.get('template_fidelity') or 'EXACT').upper() != 'INSPIRED'
    )
    if _has_brand_template(direction) and template_exact:
        available = []
        if cta:
            available.append(f'call-to-action wording: "{cta}"')
        if offer:
            available.append(f'offer wording: "{offer}"')
        return [
            'MUST: Render this exact headline ON the image, word for word and '
            f'correctly spelled: "{headline}". Set it exactly where and how the '
            "template sets its own headline - same position, size relationship, "
            'typeface feel and CAPITALISATION STYLE as the template (do not '
            'force uppercase unless the template itself uses it).',
            "MUST: The template's design already contains all of its text "
            'elements. Fill THOSE slots with this campaign\'s wording'
            + (', using ' + ' and '.join(available) + ' where the template has '
               'a matching slot' if available else '')
            + '. Do NOT add any button, pill, banner or text element the '
            'template does not already have. The finished poster carries '
            'EXACTLY ONE call-to-action element in total: when the '
            "template's design shows more than one (a button plus a text "
            'link, say), keep only the most prominent slot and leave the '
            'others out entirely.',
            'MUST: No words beyond the template\'s own text slots - no '
            'paragraphs, captions, hashtags, watermarks or third-party logos.',
            # Structure fidelity, not scene fidelity: every run of one
            # template used to reproduce its photo - same model, same pose,
            # same props - so two drafts were near-identical posters.
            "MUST: Keep the template's structure; the photograph and scene "
            'must be entirely new - vary pose, setting and hero colour '
            'treatment within the brand palette.',
            *_scene_line(brief),
        ]

    lines = [
        'MUST: Render this exact headline ON the image, word for word and '
        f'correctly spelled: "{headline}". Set it as the dominant element in big, '
        'bold, uppercase display typography with high contrast against the photo '
        'and generous margins, fully inside the frame - never cropped or clipped.'
    ]
    extras = []
    if cta:
        extras.append(f'a call-to-action pill/button reading "{cta}"')
    if offer:
        extras.append(
            f'the offer line "{offer}" set vertically along one edge of the frame'
        )
    if extras:
        lines.append(
            'MUST: Also render ' + ' and '.join(extras) + ', smaller than the '
            'headline and clearly legible.'
        )
    lines.append(
        'MUST: No other words on the image - no paragraphs, captions, hashtags, '
        'watermarks or third-party logos; only the headline'
        + (' and the CTA/offer line' if extras else '') + ' above.'
    )
    if _mirrors_reference(direction):
        # The reference lends its typographic feel; the layout itself comes
        # from the rotating archetype below, so mirroring a reference no
        # longer hard-wires every poster into the framed panel.
        lines.append(
            "MUST: Mirror the reference's typographic hierarchy and text "
            'treatment - headline weight'
            + (', CTA styling' if cta else '')
            + (', vertical offer text' if offer else '')
            + " - while using this brand's own colour palette and the "
            'composition below.'
        )
    lines.append(
        _composition_line(
            composition_archetype(brief.get('composition_archetype')), cta, offer,
        )
    )
    lines.extend(_scene_line(brief))
    return lines
