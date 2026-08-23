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
    """The compiled brain, compiled now only if there is not one yet.

    Normal generation reads the snapshot. Recompiling per request would re-run
    the whole learning read path on the hot path for a result that only
    changes when someone teaches the brand something.
    """
    brain = brand.creative_brain or {}
    if brain.get('schema_version') == SCHEMA_VERSION and brain.get('brain_version'):
        return brain
    if not recompile_if_missing:
        return {}
    return compile_brand_brain(brand)


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
                'layout_preference': visual.get('layout_preference', ''),
                'claims': visual.get('claims', [])[:MAX_ITEMS],
            },
            {'palette': {}, 'fonts': {}, 'layout_preference': '', 'claims': []},
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
