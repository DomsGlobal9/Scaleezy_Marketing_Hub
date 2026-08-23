"""
The universal layer, natural-language input, and own-site enrichment.

The invariants worth defending, in order of how expensive they are to get
wrong: universal intelligence never outranks a client's own; no client content
ever crosses into another client's context; a natural-language parse never
writes anything a person did not confirm, and can never mint a hard rule; and
enrichment can never be pointed at a host that is not the brand's own.
"""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from apps.ai.models import Capability
from apps.brands.models import Brand
from apps.brands.services.brand_brain import rebuild_brand_brain
from apps.common.testing import TenantFixtureMixin
from apps.context.services.context_gateway import (
    TaskType,
    build_generation_context,
    context_as_brief,
)
from apps.inspirations.models import BrandInspiration
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import BrandRule
from apps.universal import enrichment, nl
from apps.universal.models import (
    RANK_UNIVERSAL_STANDARD,
    EntryKind,
    LifecycleStatus,
    PlatformInspiration,
    UniversalScope,
    UniversalStandard,
)
from apps.universal.services import (
    UniversalError,
    adopt_inspiration,
    adoption_count,
    gallery_for,
    preview_affected,
    publish_inspiration,
    publish_standard,
    retire_standard,
    set_client_universal,
    standards_for,
)
from apps.workspaces.models import WorkspaceMember


def make_standard(**kwargs):
    defaults = dict(
        title='Short headlines', category='COPY_STYLE', attribute='length',
        value='short', guidance='Keep headlines under nine words.',
        scope=UniversalScope.GLOBAL,
    )
    defaults.update(kwargs)
    return UniversalStandard.objects.create(**defaults)


class UniversalBase(TenantFixtureMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.workspace = self.make_workspace('Acme', 'c1')
        self.user, self.api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', industry='Coffee',
            website='https://acme.test', is_default=True, status=Brand.Status.ACTIVE,
        )
        rebuild_brand_brain(self.brand)


class AuthorityTests(UniversalBase):
    """The rule the whole layer exists to respect."""

    def test_the_universal_rank_is_weaker_than_every_brand_rank(self):
        from apps.brands.services import brand_brain

        self.assertGreater(RANK_UNIVERSAL_STANDARD, brand_brain.RANK_INSPIRATION_SIGNAL)
        self.assertGreater(RANK_UNIVERSAL_STANDARD, brand_brain.RANK_HARD_EXPLICIT_RULE)

    def test_a_standard_is_dropped_when_the_brand_already_has_a_position(self):
        published = publish_standard(make_standard())
        kept, _ = standards_for(self.workspace, self.brand)
        self.assertEqual([s.pk for s in kept], [published.pk])

        # Now the brand states its own position on the same attribute.
        self.brand.creative_brain = {
            'preferences': [
                {'category': 'COPY_STYLE', 'attribute': 'length', 'value': 'long'}
            ]
        }
        self.brand.save(update_fields=['creative_brain'])

        kept, _ = standards_for(self.workspace, self.brand)
        self.assertEqual(kept, [])

    def test_only_published_standards_reach_a_generation(self):
        draft = make_standard(title='Draft rule')
        kept, _ = standards_for(self.workspace, self.brand)
        self.assertEqual(kept, [])

        publish_standard(draft)
        kept, _ = standards_for(self.workspace, self.brand)
        self.assertEqual(len(kept), 1)

        retire_standard(draft)
        kept, _ = standards_for(self.workspace, self.brand)
        self.assertEqual(kept, [])

    def test_scope_matches_exactly_and_never_leaks_to_a_neighbour(self):
        publish_standard(make_standard(
            title='Coffee only', scope=UniversalScope.INDUSTRY, scope_value='Coffee',
        ))
        publish_standard(make_standard(
            title='Fashion only', category='TONE', attribute='register',
            value='bold', scope=UniversalScope.INDUSTRY, scope_value='Fashion',
        ))
        kept, _ = standards_for(self.workspace, self.brand)
        self.assertEqual([s.title for s in kept], ['Coffee only'])

    def test_a_client_can_switch_the_layer_off(self):
        publish_standard(make_standard())
        self.assertEqual(len(standards_for(self.workspace, self.brand)[0]), 1)

        set_client_universal(self.workspace, standards=False, by=self.user)
        kept, version = standards_for(self.workspace, self.brand)
        self.assertEqual(kept, [])
        # The version changes too, so their cached context is invalidated.
        self.assertEqual(version, 'off')


class GatewayIntegrationTests(UniversalBase):
    def test_a_standard_reaches_the_brief_labelled_as_scaleezy(self):
        publish_standard(make_standard())
        context = build_generation_context(self.workspace, self.brand, TaskType.COPY)
        self.assertEqual(len(context['universal_standards']), 1)
        entry = context['universal_standards'][0]
        self.assertEqual(entry['rank'], RANK_UNIVERSAL_STANDARD)
        self.assertEqual(entry['authority'], 'universal_standard')

        brief = context_as_brief(context)
        line = next(
            l for l in brief['brand_context'] if l.startswith('Scaleezy craft standard:')
        )
        self.assertIn('under nine words', line)

    def test_retiring_a_standard_invalidates_cached_context(self):
        standard = publish_standard(make_standard())
        first = build_generation_context(self.workspace, self.brand, TaskType.COPY)
        self.assertEqual(len(first['universal_standards']), 1)

        retire_standard(standard)
        # Same brain version, so only the universal_version in the cache key
        # can save this from serving a retired standard.
        second = build_generation_context(self.workspace, self.brand, TaskType.COPY)
        self.assertEqual(second['universal_standards'], [])
        self.assertNotEqual(first['universal_version'], second['universal_version'])

    def test_the_brand_line_ordering_puts_ours_last(self):
        publish_standard(make_standard())
        brief = context_as_brief(
            build_generation_context(self.workspace, self.brand, TaskType.COPY)
        )
        lines = brief['brand_context']
        standard_index = next(
            i for i, l in enumerate(lines) if l.startswith('Scaleezy craft standard:')
        )
        self.assertEqual(standard_index, len(lines) - 1)

    def test_preview_is_honest_about_free_text_industries(self):
        preview = preview_affected(
            make_standard(scope=UniversalScope.INDUSTRY, scope_value='Coffee')
        )
        self.assertEqual(preview['matched_brand_count'], 1)
        self.assertTrue(preview['exact_match_only'])
        self.assertIn('free text', preview['note'])


class PlatformInspirationTests(UniversalBase):
    def setUp(self):
        super().setUp()
        self.reference = PlatformInspiration.objects.create(
            title='Great minimal poster',
            reference_url='https://example.test/poster',
            annotation='Negative space doing the work.',
            tags=['minimal'],
        )

    def test_an_unpublished_reference_is_neither_visible_nor_adoptable(self):
        self.assertEqual(gallery_for(self.workspace), [])
        with self.assertRaises(UniversalError):
            adopt_inspiration(self.reference, self.brand, user=self.user)

    def test_adoption_copies_into_the_brands_own_inspirations(self):
        publish_inspiration(self.reference, by=self.user)
        self.assertEqual(len(gallery_for(self.workspace)), 1)

        adopted, created = adopt_inspiration(self.reference, self.brand, user=self.user)
        self.assertTrue(created)
        self.assertEqual(adopted.brand, self.brand)
        self.assertEqual(adopted.workspace, self.workspace)
        self.assertEqual(adopted.reference_url, self.reference.reference_url)
        self.assertTrue(adopted.metadata['adopted_from_platform'])
        self.assertEqual(adoption_count(self.reference), 1)

    def test_adoption_is_idempotent(self):
        publish_inspiration(self.reference)
        adopt_inspiration(self.reference, self.brand, user=self.user)
        _, created = adopt_inspiration(self.reference, self.brand, user=self.user)
        self.assertFalse(created)
        self.assertEqual(
            BrandInspiration.objects.filter(brand=self.brand).count(), 1
        )

    def test_the_library_holds_no_tenant_reference_at_all(self):
        # Structural: there is no path from a client's rows into the library.
        field_names = {f.name for f in PlatformInspiration._meta.get_fields()}
        self.assertNotIn('workspace', field_names)
        self.assertNotIn('brand', field_names)

    def test_a_client_who_opted_out_sees_an_empty_gallery(self):
        publish_inspiration(self.reference)
        set_client_universal(self.workspace, inspirations=False, by=self.user)
        self.assertEqual(gallery_for(self.workspace), [])

    def test_an_adopted_upload_points_at_the_platform_file_but_never_owns_it(self):
        image = publish_inspiration(PlatformInspiration.objects.create(
            title='Hero crop', kind=EntryKind.IMAGE,
            file_url='https://storage.test/library/platform/hero.png',
            storage_path='library/platform/hero.png',
            mime_type='image/png', file_name='hero.png',
            reference_url='https://example.test/source',  # a credit, not the content
            annotation='Tight crop, one subject.',
        ))
        adopted, created = adopt_inspiration(image, self.brand, user=self.user)
        self.assertTrue(created)
        self.assertEqual(adopted.inspiration_type, BrandInspiration.InspirationType.IMAGE)
        self.assertEqual(adopted.file_url, image.file_url)
        self.assertEqual(adopted.mime_type, 'image/png')
        self.assertEqual(adopted.file_name, 'hero.png')
        self.assertEqual(adopted.reference_url, 'https://example.test/source')
        # The object is the platform's: the brand row must not look like it
        # owns a storage path it could later be asked to clean up.
        self.assertIsNone(adopted.storage_path)
        self.assertEqual(adopted.metadata['platform_kind'], 'IMAGE')

        # The credit URL is not what makes it a duplicate — the platform id is.
        _, again = adopt_inspiration(image, self.brand, user=self.user)
        self.assertFalse(again)
        self.assertEqual(BrandInspiration.objects.filter(brand=self.brand).count(), 1)

        video = publish_inspiration(PlatformInspiration.objects.create(
            title='Loop', kind=EntryKind.VIDEO, file_url='https://storage.test/l.mp4',
            mime_type='video/mp4', file_name='l.mp4',
        ))
        deck = publish_inspiration(PlatformInspiration.objects.create(
            title='Deck', kind=EntryKind.FILE, file_url='https://storage.test/d.pdf',
            mime_type='application/pdf', file_name='d.pdf',
        ))
        self.assertEqual(
            adopt_inspiration(video, self.brand, user=self.user)[0].inspiration_type,
            BrandInspiration.InspirationType.VIDEO,
        )
        self.assertEqual(
            adopt_inspiration(deck, self.brand, user=self.user)[0].inspiration_type,
            BrandInspiration.InspirationType.REFERENCE,
        )

    def test_an_adopted_text_entry_carries_its_words_and_the_note(self):
        text = publish_inspiration(PlatformInspiration.objects.create(
            title='Pattern-interrupt hook', kind=EntryKind.TEXT,
            body='Stop scrolling if you hate Mondays.',
            annotation='Names the feeling before the product.',
        ))
        adopted, created = adopt_inspiration(text, self.brand, user=self.user)
        self.assertTrue(created)
        self.assertEqual(adopted.inspiration_type, BrandInspiration.InspirationType.TEXT)
        self.assertIsNone(adopted.reference_url)
        self.assertIsNone(adopted.file_url)
        self.assertEqual(
            adopted.annotation,
            'Stop scrolling if you hate Mondays.\n\nNames the feeling before the product.',
        )
        self.assertFalse(adopt_inspiration(text, self.brand, user=self.user)[1])

    def test_the_gallery_can_be_narrowed_to_one_kind(self):
        publish_inspiration(self.reference)
        publish_inspiration(PlatformInspiration.objects.create(
            title='Hook', kind=EntryKind.TEXT, body='Words.',
        ))
        self.assertEqual(len(gallery_for(self.workspace)), 2)
        self.assertEqual(
            [row.kind for row in gallery_for(self.workspace, kind='text')], ['TEXT']
        )
        self.assertEqual(
            [row.kind for row in gallery_for(self.workspace, kind='LINK')], ['LINK']
        )


class NaturalLanguageTests(UniversalBase):
    NOTE = "We never discount, and our tone is warm but not cutesy."

    def parse_returning(self, proposals):
        return patch(
            'apps.ai.router.AIRouter.dispatch',
            return_value={'raw': {'proposals': proposals}, 'provider': 'TEST'},
        )

    def test_the_note_is_stored_verbatim_before_anything_parses_it(self):
        note = nl.capture_note(self.brand, self.NOTE, user=self.user)
        self.assertEqual(note.raw_text, self.NOTE)
        self.assertEqual(note.brand, self.brand)
        self.assertEqual(note.metadata['origin'], 'NATURAL_LANGUAGE_NOTE')

    def test_a_parse_writes_nothing_to_the_brand(self):
        note = nl.capture_note(self.brand, self.NOTE, user=self.user)
        memories_before = BrandMemory.objects.count()
        rules_before = BrandRule.objects.count()

        with self.parse_returning([
            {'kind': 'TONE', 'category': 'TONE', 'attribute': 'register',
             'value': 'warm', 'text': 'Tone is warm but not cutesy',
             'quote': 'our tone is warm but not cutesy'},
        ]):
            result = nl.propose_from_note(self.workspace, self.brand, note, user=self.user)

        self.assertEqual(len(result['proposals']), 1)
        self.assertFalse(result['proposals'][0]['accepted'])
        self.assertEqual(BrandMemory.objects.count(), memories_before)
        self.assertEqual(BrandRule.objects.count(), rules_before)

    def test_a_proposal_the_note_does_not_contain_is_dropped(self):
        note = nl.capture_note(self.brand, self.NOTE, user=self.user)
        with self.parse_returning([
            {'kind': 'FACT', 'text': 'We are the market leader',
             'quote': 'we are the market leader'},  # never said
            {'kind': 'PREFERENCE', 'text': 'No discounting',
             'quote': 'We never discount'},
        ]):
            result = nl.propose_from_note(self.workspace, self.brand, note)
        self.assertEqual([p['text'] for p in result['proposals']], ['No discounting'])

    def test_an_accepted_preference_becomes_a_soft_rule_never_a_hard_one(self):
        note = nl.capture_note(self.brand, self.NOTE, user=self.user)
        rule = nl.accept_proposal(
            self.workspace, self.brand,
            {'kind': 'PREFERENCE', 'text': 'Never discount'},
            note=note, user=self.user,
        )
        self.assertEqual(rule.hardness, BrandRule.Hardness.SOFT)

    def test_a_hard_rule_cannot_be_proposed_at_all(self):
        self.assertNotIn('HARD_RULE', nl.PROPOSAL_KINDS)
        with self.assertRaises(nl.NLError):
            nl.accept_proposal(
                self.workspace, self.brand, {'kind': 'HARD_RULE', 'text': 'x'}
            )

    def test_an_accepted_fact_is_confirmed_and_traceable_to_the_note(self):
        note = nl.capture_note(self.brand, self.NOTE, user=self.user)
        memory = nl.accept_proposal(
            self.workspace, self.brand,
            {'kind': 'FACT', 'text': 'We never discount'},
            note=note, user=self.user,
        )
        self.assertEqual(memory.status, BrandMemory.MemoryStatus.CONFIRMED)
        self.assertEqual(memory.source, note)

    def test_an_empty_note_is_refused(self):
        with self.assertRaises(nl.NLError):
            nl.capture_note(self.brand, '   ')


class EnrichmentSafetyTests(UniversalBase):
    """Enrichment is an outbound fetcher, so its guards are the feature."""

    def test_only_the_brands_own_host_is_allowed(self):
        with self.assertRaises(enrichment.UnsafeURL):
            enrichment.assert_safe(
                'https://competitor.test/pricing', allowed_host='acme.test'
            )

    def test_plain_http_is_refused(self):
        with self.assertRaises(enrichment.UnsafeURL):
            enrichment.assert_safe('http://acme.test/', allowed_host='acme.test')

    def test_private_and_metadata_addresses_are_refused(self):
        # The SSRF case: a host that resolves inside the network.
        with patch('apps.universal.enrichment.socket.getaddrinfo',
                   return_value=[(2, 1, 6, '', ('169.254.169.254', 0))]):
            with self.assertRaises(enrichment.UnsafeURL):
                enrichment.assert_safe('https://acme.test/', allowed_host='acme.test')

        with patch('apps.universal.enrichment.socket.getaddrinfo',
                   return_value=[(2, 1, 6, '', ('127.0.0.1', 0))]):
            with self.assertRaises(enrichment.UnsafeURL):
                enrichment.assert_safe('https://acme.test/', allowed_host='acme.test')

    def test_a_host_resolving_to_a_mix_is_refused(self):
        with patch('apps.universal.enrichment.socket.getaddrinfo', return_value=[
            (2, 1, 6, '', ('93.184.216.34', 0)),
            (2, 1, 6, '', ('10.0.0.5', 0)),
        ]):
            with self.assertRaises(enrichment.UnsafeURL):
                enrichment.assert_safe('https://acme.test/', allowed_host='acme.test')

    def test_www_and_bare_host_are_the_same_site(self):
        with patch('apps.universal.enrichment.socket.getaddrinfo',
                   return_value=[(2, 1, 6, '', ('93.184.216.34', 0))]):
            self.assertTrue(
                enrichment.assert_safe(
                    'https://www.acme.test/about', allowed_host='acme.test'
                )
            )

    def test_links_off_the_brands_host_are_never_followed(self):
        html = (
            '<a href="/about">About</a>'
            '<a href="https://acme.test/products">Products</a>'
            '<a href="https://evil.test/x">Evil</a>'
        )
        links = enrichment.own_links(html, 'https://acme.test/', allowed_host='acme.test')
        self.assertEqual(
            links, ['https://acme.test/about', 'https://acme.test/products']
        )

    def test_a_pending_client_cannot_run_enrichment(self):
        from apps.brands.services.approval import SpendNotApproved

        self.brand.status = Brand.Status.PENDING
        self.brand.save(update_fields=['status'])
        with self.assertRaises(SpendNotApproved):
            enrichment.enrich_brand_from_own_site(self.workspace, self.brand)

    def test_a_brand_with_no_website_is_refused(self):
        self.brand.website = ''
        self.brand.save(update_fields=['website'])
        with self.assertRaises(enrichment.EnrichmentError):
            enrichment.enrich_brand_from_own_site(self.workspace, self.brand)

    def test_a_full_review_queue_stops_enrichment_proposing_more(self):
        for i in range(enrichment.MAX_OPEN_CANDIDATES):
            BrandMemory.objects.create(
                workspace=self.workspace, brand=self.brand,
                memory_type=BrandMemory.MemoryType.FACT,
                content=f'candidate {i}',
                status=BrandMemory.MemoryStatus.CANDIDATE,
            )
        report = enrichment.enrich_brand_from_own_site(self.workspace, self.brand)
        self.assertTrue(report['skipped'])
        self.assertEqual(report['pages_fetched'], 0)

    def test_captured_pages_are_marked_discovered_and_never_confirmed(self):
        with patch(
            'apps.universal.enrichment.safe_fetch',
            return_value=('Acme roasts coffee in small batches.', 'hash-1'),
        ):
            report = enrichment.enrich_brand_from_own_site(
                self.workspace, self.brand, user=self.user
            )
        self.assertFalse(report['skipped'])
        source = BrandSource.objects.get(pk=report['sources_created'][0])
        self.assertEqual(source.metadata['origin'], 'DISCOVERED')
        self.assertTrue(source.metadata['own_site'])
        # Raw material only: nothing was promoted onto the brand or confirmed.
        self.assertFalse(
            BrandMemory.objects.filter(
                brand=self.brand, status=BrandMemory.MemoryStatus.CONFIRMED
            ).exists()
        )
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.name, 'Acme Coffee')

    def test_an_unchanged_page_produces_no_second_source(self):
        with patch('apps.universal.enrichment.safe_fetch',
                   return_value=('Same text', 'hash-same')):
            first = enrichment.enrich_brand_from_own_site(self.workspace, self.brand)
            second = enrichment.enrich_brand_from_own_site(self.workspace, self.brand)
        self.assertEqual(len(first['sources_created']), 1)
        self.assertEqual(second['sources_created'], [])
        self.assertEqual(second['pages_unchanged'], 1)
