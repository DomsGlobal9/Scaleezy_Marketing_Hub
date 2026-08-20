"""
The provisional feedback vocabulary.

`CREATIVE_BRAIN.md` in the Content Engine package names nine groups and gives a
count for each — Typography 8, Copy & message 10, Line-by-line 10, Logo &
branding 6, Visual & background 6, Layout 5, Audio 3, Format & technical 4,
Strategy 4 — but never lists the elements themselves. (Those counts sum to 56,
not the 52 the spec claims elsewhere.)

The taxonomy is the input to the whole training engine, so it cannot be
invented and then quietly treated as authoritative. What follows is a
stand-in with the right shape and the documented per-group counts, seeded with
`is_provisional=True`. Every row is editable in Django admin, and the engine
reads keys from the database rather than from any constant here, so replacing
this with the real list is a data change — not a deploy, and not a migration
of anything already learned.

Group order matches the spec's ordering.
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


#: (group, key, label, description)
PROVISIONAL_ELEMENTS = [
    # Typography — 8
    (Group.TYPOGRAPHY, 'font_choice', 'Font choice', 'Typeface is wrong for the brand.'),
    (Group.TYPOGRAPHY, 'font_size', 'Font size', 'Type is too large or too small.'),
    (Group.TYPOGRAPHY, 'font_weight', 'Font weight', 'Too light, too heavy, wrong emphasis.'),
    (Group.TYPOGRAPHY, 'letter_spacing', 'Letter spacing', 'Tracking is cramped or loose.'),
    (Group.TYPOGRAPHY, 'line_height', 'Line height', 'Leading makes the block hard to read.'),
    (Group.TYPOGRAPHY, 'text_hierarchy', 'Text hierarchy', 'Eye lands on the wrong line first.'),
    (Group.TYPOGRAPHY, 'text_alignment', 'Text alignment', 'Ragged, centred or justified wrongly.'),
    (Group.TYPOGRAPHY, 'text_legibility', 'Legibility', 'Contrast or placement makes text hard to read.'),

    # Copy & message — 10
    (Group.COPY, 'headline', 'Headline', 'The main line does not land.'),
    (Group.COPY, 'subheadline', 'Subheadline', 'Supporting line is weak or redundant.'),
    (Group.COPY, 'body_copy', 'Body copy', 'The caption itself.'),
    (Group.COPY, 'call_to_action', 'Call to action', 'CTA missing, vague or off-brand.'),
    (Group.COPY, 'offer_clarity', 'Offer clarity', 'The deal is not obvious at a glance.'),
    (Group.COPY, 'tone_of_voice', 'Tone of voice', 'Does not sound like the brand.'),
    (Group.COPY, 'copy_length', 'Copy length', 'Too long or too short for the format.'),
    (Group.COPY, 'grammar_spelling', 'Grammar & spelling', 'Language errors.'),
    (Group.COPY, 'claim_accuracy', 'Claim accuracy', 'Says something untrue or unapprovable.'),
    (Group.COPY, 'hashtags', 'Hashtags', 'Wrong, spammy or missing tags.'),

    # Line-by-line — 10
    (Group.LINE_BY_LINE, 'line_1', 'Line 1', 'First line of the on-image copy.'),
    (Group.LINE_BY_LINE, 'line_2', 'Line 2', 'Second line of the on-image copy.'),
    (Group.LINE_BY_LINE, 'line_3', 'Line 3', 'Third line of the on-image copy.'),
    (Group.LINE_BY_LINE, 'line_4', 'Line 4', 'Fourth line of the on-image copy.'),
    (Group.LINE_BY_LINE, 'line_5', 'Line 5', 'Fifth line of the on-image copy.'),
    (Group.LINE_BY_LINE, 'line_6', 'Line 6', 'Sixth line of the on-image copy.'),
    (Group.LINE_BY_LINE, 'line_7', 'Line 7', 'Seventh line of the on-image copy.'),
    (Group.LINE_BY_LINE, 'line_8', 'Line 8', 'Eighth line of the on-image copy.'),
    (Group.LINE_BY_LINE, 'line_9', 'Line 9', 'Ninth line of the on-image copy.'),
    (Group.LINE_BY_LINE, 'line_10', 'Line 10', 'Tenth line of the on-image copy.'),

    # Logo & branding — 6
    (Group.LOGO, 'logo_presence', 'Logo presence', 'Logo missing, or present when it should not be.'),
    (Group.LOGO, 'logo_placement', 'Logo placement', 'Logo is in the wrong position.'),
    (Group.LOGO, 'logo_size', 'Logo size', 'Logo is too big or too small.'),
    (Group.LOGO, 'brand_colours', 'Brand colours', 'Off-palette colour use.'),
    (Group.LOGO, 'brand_fonts', 'Brand fonts', 'Not the brand typefaces.'),
    (Group.LOGO, 'tagline_usage', 'Tagline usage', 'Tagline wrong, missing or misplaced.'),

    # Visual & background — 6
    (Group.VISUAL, 'background_choice', 'Background', 'Backdrop is wrong for the message.'),
    (Group.VISUAL, 'imagery_subject', 'Imagery subject', 'Wrong subject, product or model.'),
    (Group.VISUAL, 'colour_palette', 'Colour palette', 'Overall colour direction is off.'),
    (Group.VISUAL, 'lighting', 'Lighting', 'Flat, blown out, or wrong mood.'),
    (Group.VISUAL, 'texture_detail', 'Texture & detail', 'Artefacts, noise, or plastic AI look.'),
    (Group.VISUAL, 'image_quality', 'Image quality', 'Soft, low-resolution or distorted.'),

    # Layout — 5
    (Group.LAYOUT, 'composition_balance', 'Composition balance', 'Weight sits wrongly on the canvas.'),
    (Group.LAYOUT, 'spacing_margins', 'Spacing & margins', 'Crowded edges or uneven gutters.'),
    (Group.LAYOUT, 'alignment_grid', 'Alignment & grid', 'Elements do not line up.'),
    (Group.LAYOUT, 'focal_point', 'Focal point', 'No clear place for the eye to start.'),
    (Group.LAYOUT, 'safe_area', 'Safe area', 'Content clipped by platform chrome.'),

    # Audio — 3
    (Group.AUDIO, 'music_choice', 'Music choice', 'Track does not fit the brand or edit.'),
    (Group.AUDIO, 'voiceover', 'Voiceover', 'Delivery, script or accent is wrong.'),
    (Group.AUDIO, 'sound_mix', 'Sound mix', 'Levels, ducking or silence problems.'),

    # Format & technical — 4
    (Group.FORMAT, 'aspect_ratio', 'Aspect ratio', 'Wrong shape for the destination.'),
    (Group.FORMAT, 'resolution', 'Resolution', 'Below the platform minimum.'),
    (Group.FORMAT, 'file_format', 'File format', 'Wrong container or codec.'),
    (Group.FORMAT, 'platform_specs', 'Platform specs', 'Breaks a channel requirement.'),

    # Strategy — 4
    (Group.STRATEGY, 'audience_fit', 'Audience fit', 'Not aimed at the intended audience.'),
    (Group.STRATEGY, 'timing_relevance', 'Timing & relevance', 'Wrong moment, season or occasion.'),
    (Group.STRATEGY, 'channel_fit', 'Channel fit', 'Wrong for the platform it is going to.'),
    (Group.STRATEGY, 'campaign_consistency', 'Campaign consistency', 'Out of step with the rest of the campaign.'),
]
