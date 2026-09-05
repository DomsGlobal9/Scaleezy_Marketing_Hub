"""
The feedback vocabulary — the authoritative 56-element list.

This replaces the provisional stand-in seeded by migration 0002. The source of
truth is the production review console the creative team actually tags with
(the Content Engine review app), where these are the exact chip labels a
reviewer picks from, grouped exactly this way.

Two things the handover settles:

- The real count is **56, not 52**. The "52" in early spec documents was a
  stale figure; the nine documented per-group counts (8+10+10+6+6+5+3+4+4)
  always summed to 56, and production confirms 56.
- Group names in the console carry decoration ("LAYOUT & COMPOSITION" vs the
  spec's "Layout"). The group *codes* below are unchanged from the provisional
  seed, so no learned rule that keys on a group needs to move.

Migration 0003 promotes these rows to `is_provisional=False` and retires the
placeholders that have no production counterpart (deactivated, not deleted —
feedback already tagged with them keeps resolving). Rows remain editable in
Django admin and the engine reads keys from the database, so future curation
is still a data change, not a deploy.

Group order and per-group order match the console, so the dropdown a reviewer
sees and the seed a fresh database gets are the same list.
"""


class Group:
    """
    Group codes, repeated as plain strings rather than imported from the model.

    A data migration runs against historical models; importing the live enum
    would couple a frozen migration to a class that is free to change.
    """

    TYPOGRAPHY = 'TYPOGRAPHY'
    COPY = 'COPY'
    LINE_BY_LINE = 'LINE_BY_LINE'
    LOGO = 'LOGO'
    VISUAL = 'VISUAL'
    LAYOUT = 'LAYOUT'
    AUDIO = 'AUDIO'
    FORMAT = 'FORMAT'
    STRATEGY = 'STRATEGY'


#: (group, key, label, description) — labels are the console's chip text.
ELEMENTS = [
    # Typography — 8
    (Group.TYPOGRAPHY, 'headline_text', 'Headline text', 'The main on-image line itself is wrong — wording, not styling.'),
    (Group.TYPOGRAPHY, 'sub_line_text', 'Sub-line text', 'The supporting on-image line is wrong or redundant.'),
    (Group.TYPOGRAPHY, 'font_choice', 'Font choice', 'Typeface is wrong for the brand.'),
    (Group.TYPOGRAPHY, 'font_size', 'Font size', 'Type is too large or too small.'),
    (Group.TYPOGRAPHY, 'kerning_letter_spacing', 'Kerning / letter spacing', 'Tracking is cramped or loose.'),
    (Group.TYPOGRAPHY, 'line_breaks', 'Line breaks', 'Copy breaks in the wrong place.'),
    (Group.TYPOGRAPHY, 'text_alignment', 'Text alignment', 'Ragged, centred or justified wrongly.'),
    (Group.TYPOGRAPHY, 'readability_contrast', 'Readability / contrast', 'Contrast or placement makes text hard to read.'),

    # Copy & message — 10
    (Group.COPY, 'hook_strength', 'Hook strength', 'The opening does not stop the scroll.'),
    (Group.COPY, 'caption_quality', 'Caption quality', 'The caption under the post is weak.'),
    (Group.COPY, 'cta_strength', 'CTA strength', 'Call to action is missing, vague or off-brand.'),
    (Group.COPY, 'offer_clarity', 'Offer clarity', 'The deal is not obvious at a glance.'),
    (Group.COPY, 'message_accuracy', 'Message accuracy', 'Says something untrue or unapprovable.'),
    (Group.COPY, 'tone_of_voice', 'Tone of voice', 'Does not sound like the brand.'),
    (Group.COPY, 'grammar_spelling', 'Grammar / spelling', 'Language errors.'),
    (Group.COPY, 'word_choice', 'Word choice', 'Right meaning, wrong words.'),
    (Group.COPY, 'flow_readability', 'Flow / readability', 'The copy does not read smoothly end to end.'),
    (Group.COPY, 'length_too_long_short', 'Length — too long / short', 'Wrong length for the format.'),

    # Line-by-line — 10
    (Group.LINE_BY_LINE, 'opening_line_hook', 'Opening line (hook)', 'First line of the copy.'),
    (Group.LINE_BY_LINE, 'headline_line_1', 'Headline line 1', 'First headline line.'),
    (Group.LINE_BY_LINE, 'headline_line_2', 'Headline line 2', 'Second headline line.'),
    (Group.LINE_BY_LINE, 'sub_line', 'Sub-line', 'The sub-line as written.'),
    (Group.LINE_BY_LINE, 'body_caption_lines', 'Body / caption lines', 'The body or caption lines as written.'),
    (Group.LINE_BY_LINE, 'closing_line', 'Closing line', 'The final line before the CTA.'),
    (Group.LINE_BY_LINE, 'cta_line', 'CTA line', 'The call-to-action line as written.'),
    (Group.LINE_BY_LINE, 'hashtags', 'Hashtags', 'Wrong, spammy or missing tags.'),
    (Group.LINE_BY_LINE, 'punctuation', 'Punctuation', 'Punctuation errors or overuse.'),
    (Group.LINE_BY_LINE, 'emoji_use', 'Emoji use', 'Missing, excessive or off-brand emoji.'),

    # Logo & branding — 6
    (Group.LOGO, 'logo_missing', 'Logo missing', 'Logo absent where it should appear, or present where it should not.'),
    (Group.LOGO, 'logo_placement', 'Logo placement', 'Logo is in the wrong position.'),
    (Group.LOGO, 'logo_size', 'Logo size', 'Logo is too big or too small.'),
    (Group.LOGO, 'logo_contrast_halo', 'Logo contrast / halo', 'Logo disappears into the background or carries an artefact halo.'),
    (Group.LOGO, 'brand_colors', 'Brand colors', 'Off-palette colour use.'),
    (Group.LOGO, 'brand_consistency', 'Brand consistency', 'Does not look like the rest of the brand\u2019s output.'),

    # Visual & background — 6
    (Group.VISUAL, 'background_choice', 'Background choice', 'Backdrop is wrong for the message.'),
    (Group.VISUAL, 'image_quality', 'Image quality', 'Soft, low-resolution or distorted.'),
    (Group.VISUAL, 'looks_ai_fake', 'Looks AI / fake', 'Plastic skin, wrong hands, gibberish text — the AI tells.'),
    (Group.VISUAL, 'repetitive_scene', 'Repetitive scene', 'A scene or background already used in approved content.'),
    (Group.VISUAL, 'crop_focus', 'Crop & focus', 'Wrong crop, or focus on the wrong subject.'),
    (Group.VISUAL, 'lighting_color_grade', 'Lighting / color grade', 'Flat, blown out, or wrong mood.'),

    # Layout & composition — 5
    (Group.LAYOUT, 'spacing_padding', 'Spacing / padding', 'Crowded edges or uneven gutters.'),
    (Group.LAYOUT, 'element_alignment', 'Element alignment', 'Elements do not line up.'),
    (Group.LAYOUT, 'overflow_clipping', 'Overflow / clipping', 'Content runs off the canvas or is clipped.'),
    (Group.LAYOUT, 'balance_white_space', 'Balance / white space', 'Weight sits wrongly on the canvas.'),
    (Group.LAYOUT, 'visual_hierarchy', 'Visual hierarchy', 'No clear place for the eye to start.'),

    # Audio — 3
    (Group.AUDIO, 'music_choice', 'Music choice', 'Track does not fit the brand or edit.'),
    (Group.AUDIO, 'volume_mix', 'Volume / mix', 'Levels, ducking or silence problems.'),
    (Group.AUDIO, 'voiceover', 'Voiceover', 'Delivery, script or accent is wrong.'),

    # Format & technical — 4
    (Group.FORMAT, 'size_aspect_ratio', 'Size / aspect ratio', 'Wrong shape or dimensions for the destination.'),
    (Group.FORMAT, 'watermark_artifacts', 'Watermark / artifacts', 'Generator watermarks or compression artefacts.'),
    (Group.FORMAT, 'glyph_emoji_boxes', 'Glyph / emoji boxes', 'Tofu boxes where a glyph or emoji failed to render.'),
    (Group.FORMAT, 'file_quality_compression', 'File quality / compression', 'Below the platform\u2019s quality bar.'),

    # Strategy — 4
    (Group.STRATEGY, 'viral_potential', 'Viral potential', 'Nothing about it earns a share.'),
    (Group.STRATEGY, 'freshness_novelty', 'Freshness / novelty', 'Feels like something the brand already posted.'),
    (Group.STRATEGY, 'audience_fit', 'Audience fit', 'Not aimed at the intended audience.'),
    (Group.STRATEGY, 'posting_format_fit', 'Posting format fit', 'Wrong format for the channel it is going to.'),
]

#: Keys a reviewer can tag with after migration 0003 — the active vocabulary.
ELEMENT_KEYS = frozenset(key for _, key, _, _ in ELEMENTS)

# Backwards compatibility: migration 0002 imports this name. On a fresh
# database it now seeds the authoritative list (still flagged provisional),
# and 0003 immediately promotes it. On an existing database 0002 has already
# run, so this alias is only ever read by a rollback of 0003.
PROVISIONAL_ELEMENTS = ELEMENTS
