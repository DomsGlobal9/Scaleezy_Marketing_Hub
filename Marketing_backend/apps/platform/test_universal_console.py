"""
P6 — authoring standards and the inspiration library from the console.

The boundary first (a workspace OWNER, `is_staff`, and anonymous all get
nothing), then the lifecycle: a draft is created and edited, published (and
its predecessor retired), previewed honestly, retired with a reason; and a
published standard refuses in-place edits. The library side: curate, publish,
list with a live adoption count, retire.
"""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import PlatformAuditLog
from apps.audit.services import grant_platform_admin
from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.inspirations.models import BrandInspiration
from apps.marketing.services.storage import StorageError
from apps.universal.models import (
    EntryKind,
    LifecycleStatus,
    PlatformInspiration,
    UniversalScope,
    UniversalStandard,
)
from apps.universal.services import adopt_inspiration, publish_inspiration, publish_standard
from apps.workspaces.models import WorkspaceMember

User = get_user_model()

STANDARDS = '/api/platform/standards/'
INSPIRATIONS = '/api/platform/inspirations/'
UPLOAD = f'{INSPIRATIONS}upload/'
CLIENT_LIBRARY = '/api/marketing/universal/library/'

STANDARD_BODY = {
    'title': 'Short headlines',
    'rationale': 'Long headlines lose the scroll.',
    'category': 'COPY_STYLE',
    'attribute': 'length',
    'value': 'short',
    'guidance': 'Keep headlines under nine words.',
    'scope': 'GLOBAL',
}

INSPIRATION_BODY = {
    'title': 'Great minimal poster',
    'reference_url': 'https://example.test/poster',
    'annotation': 'Negative space doing the work.',
    'tags': ['minimal', 'poster'],
    'industry': 'Coffee',
    'channel': 'instagram',
}


class UniversalConsoleTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        self.owner, self.owner_api = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner@acme.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', industry='Coffee',
            website='https://acme.test', is_default=True, status=Brand.Status.ACTIVE,
        )
        self.staff = User.objects.create_user(username='staff@scaleezy.test', password='pw')
        grant_platform_admin(self.staff, note='test')
        self.staff_api = APIClient()
        self.staff_api.force_authenticate(user=self.staff)

    def actions(self):
        return set(PlatformAuditLog.objects.values_list('action', flat=True))

    # ───────────────────────────────────────────── the boundary

    def test_workspace_owner_staff_flag_and_anonymous_are_all_refused(self):
        for url in (STANDARDS, INSPIRATIONS):
            self.assertEqual(self.owner_api.get(url).status_code, status.HTTP_403_FORBIDDEN, url)
            self.assertEqual(
                self.owner_api.post(url, STANDARD_BODY, format='json').status_code,
                status.HTTP_403_FORBIDDEN, url,
            )
            self.assertEqual(APIClient().get(url).status_code, status.HTTP_401_UNAUTHORIZED, url)

        self.owner.is_staff = True
        self.owner.is_superuser = True
        self.owner.save(update_fields=['is_staff', 'is_superuser'])
        self.assertEqual(self.owner_api.get(STANDARDS).status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(UniversalStandard.objects.count(), 0)
        self.assertEqual(PlatformInspiration.objects.count(), 0)

    # ───────────────────────────────────────────── standards

    def test_create_draft_then_edit_it(self):
        response = self.staff_api.post(STANDARDS, STANDARD_BODY, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()['data']
        self.assertEqual(data['status'], LifecycleStatus.DRAFT)
        self.assertEqual(data['authored_by'], 'staff@scaleezy.test')
        self.assertIsNone(data['supersedes'])
        self.assertIn('UNIVERSAL_STANDARD_CREATED', self.actions())

        response = self.staff_api.patch(
            f"{STANDARDS}{data['id']}/", {'guidance': 'Under eight words.'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['guidance'], 'Under eight words.')
        edit = PlatformAuditLog.objects.get(action='UNIVERSAL_STANDARD_EDITED')
        self.assertEqual(edit.detail['changes']['guidance']['to'], 'Under eight words.')

        listing = self.staff_api.get(STANDARDS, {'status': 'DRAFT'})
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([s['id'] for s in listing.json()['data']['standards']], [data['id']])
        self.assertIn('UNIVERSAL_STANDARDS_VIEWED', self.actions())

    def test_create_refuses_missing_fields_and_bad_scope(self):
        missing = dict(STANDARD_BODY)
        missing.pop('guidance')
        response = self.staff_api.post(STANDARDS, missing, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('guidance', response.json()['message'])

        response = self.staff_api.post(
            STANDARDS, {**STANDARD_BODY, 'scope': 'GALAXY'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # A narrowed standard with no value applies to nobody: refused too.
        response = self.staff_api.post(
            STANDARDS, {**STANDARD_BODY, 'scope': 'INDUSTRY'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(UniversalStandard.objects.count(), 0)

    def test_publish_retires_the_superseded_standard_and_retire_takes_a_reason(self):
        old = publish_standard(UniversalStandard.objects.create(
            title='Old rule', category='COPY_STYLE', attribute='length',
            value='medium', guidance='Medium headlines.',
        ))
        response = self.staff_api.post(
            STANDARDS, {**STANDARD_BODY, 'supersedes': str(old.pk)}, format='json',
        )
        new_id = response.json()['data']['id']
        self.assertEqual(response.json()['data']['supersedes'], str(old.pk))

        response = self.staff_api.post(f'{STANDARDS}{new_id}/publish/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['status'], LifecycleStatus.PUBLISHED)
        old.refresh_from_db()
        self.assertEqual(old.status, LifecycleStatus.RETIRED)
        self.assertIn('UNIVERSAL_STANDARD_PUBLISHED', self.actions())

        response = self.staff_api.post(
            f'{STANDARDS}{new_id}/retire/', {'reason': 'too blunt'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['status'], LifecycleStatus.RETIRED)
        entry = PlatformAuditLog.objects.filter(
            action='UNIVERSAL_STANDARD_RETIRED', target=f'standard:{new_id}'
        ).get()
        self.assertEqual(entry.detail['reason'], 'too blunt')

    def test_a_published_standard_cannot_be_edited_in_place(self):
        live = publish_standard(UniversalStandard.objects.create(**{
            k: v for k, v in STANDARD_BODY.items()
        }))
        response = self.staff_api.patch(
            f'{STANDARDS}{live.pk}/', {'guidance': 'changed'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('supersede', response.json()['message'])
        live.refresh_from_db()
        self.assertEqual(live.guidance, STANDARD_BODY['guidance'])

    def test_preview_names_the_brands_a_standard_would_touch_and_audits(self):
        draft = UniversalStandard.objects.create(
            **{**STANDARD_BODY, 'scope': UniversalScope.INDUSTRY, 'scope_value': 'Coffee'}
        )
        response = self.staff_api.get(f'{STANDARDS}{draft.pk}/preview/')
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual(data['matched_brand_count'], 1)
        self.assertEqual(data['brands'][0]['id'], str(self.brand.pk))
        self.assertTrue(data['exact_match_only'])
        self.assertEqual(data['standard']['id'], str(draft.pk))
        self.assertIn('UNIVERSAL_STANDARD_PREVIEWED', self.actions())

    def test_unknown_standard_is_404(self):
        self.assertEqual(
            self.staff_api.get(f'{STANDARDS}{uuid.uuid4()}/preview/').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.staff_api.post(f'{STANDARDS}{uuid.uuid4()}/publish/', {}, format='json').status_code,
            status.HTTP_404_NOT_FOUND,
        )

    # ───────────────────────────────────────────── inspirations

    def test_create_publish_and_list_inspiration_with_live_adoption_count(self):
        response = self.staff_api.post(INSPIRATIONS, INSPIRATION_BODY, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()['data']
        self.assertEqual(data['status'], LifecycleStatus.DRAFT)
        self.assertEqual(data['curated_by'], 'staff@scaleezy.test')
        self.assertEqual(data['adoption_count'], 0)
        self.assertIn('PLATFORM_INSPIRATION_CREATED', self.actions())

        response = self.staff_api.post(f"{INSPIRATIONS}{data['id']}/publish/", {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['status'], LifecycleStatus.PUBLISHED)
        self.assertIn('PLATFORM_INSPIRATION_PUBLISHED', self.actions())

        # A client adopts it; the console count is the real row count.
        adopt_inspiration(PlatformInspiration.objects.get(pk=data['id']), self.brand, user=self.owner)
        self.assertEqual(BrandInspiration.objects.filter(brand=self.brand).count(), 1)

        listing = self.staff_api.get(INSPIRATIONS, {'status': 'PUBLISHED'})
        self.assertEqual(listing.status_code, 200)
        rows = listing.json()['data']['inspirations']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['adoption_count'], 1)
        self.assertEqual(rows[0]['tags'], ['minimal', 'poster'])
        self.assertIn('PLATFORM_INSPIRATIONS_VIEWED', self.actions())

    def test_inspiration_url_must_be_http_and_edit_and_retire_are_audited(self):
        response = self.staff_api.post(
            INSPIRATIONS, {**INSPIRATION_BODY, 'reference_url': 'ftp://x.test/a'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PlatformInspiration.objects.count(), 0)

        reference = publish_inspiration(PlatformInspiration.objects.create(**INSPIRATION_BODY))
        response = self.staff_api.patch(
            f'{INSPIRATIONS}{reference.pk}/', {'annotation': 'Updated note.'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['annotation'], 'Updated note.')
        self.assertIn('PLATFORM_INSPIRATION_EDITED', self.actions())

        response = self.staff_api.post(
            f'{INSPIRATIONS}{reference.pk}/retire/', {'reason': 'site gone'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        reference.refresh_from_db()
        self.assertEqual(reference.status, LifecycleStatus.RETIRED)
        entry = PlatformAuditLog.objects.get(action='PLATFORM_INSPIRATION_RETIRED')
        self.assertEqual(entry.detail['reason'], 'site gone')

        # Retired means out of the client gallery — and no further edits.
        from apps.universal.services import gallery_for

        self.assertEqual(gallery_for(self.workspace), [])
        response = self.staff_api.patch(
            f'{INSPIRATIONS}{reference.pk}/', {'annotation': 'x'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ───────────────────────────────────── entry kinds: link, text, uploads

    def test_links_and_text_are_authored_as_json_and_each_needs_its_content(self):
        # Text: the words are the content; the annotation is the note about them.
        response = self.staff_api.post(INSPIRATIONS, {
            'kind': 'text', 'title': 'Pattern-interrupt hook',
            'body': 'Stop scrolling if you hate Mondays.',
            'annotation': 'Names the feeling first.', 'tags': 'hook, short',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()['data']
        self.assertEqual(data['kind'], 'TEXT')
        self.assertEqual(data['body'], 'Stop scrolling if you hate Mondays.')
        self.assertEqual(data['reference_url'], '')
        self.assertEqual(data['file_url'], '')
        self.assertEqual(data['tags'], ['hook', 'short'])
        created = PlatformAuditLog.objects.get(action='PLATFORM_INSPIRATION_CREATED')
        self.assertEqual(created.detail['kind'], 'TEXT')

        for body, why in (
            ({'kind': 'TEXT', 'title': 'Empty'}, 'a text entry needs its words'),
            ({'title': 'No link'}, 'a link (the default kind) needs a URL'),
            ({'kind': 'IMAGE', 'title': 'x', 'reference_url': 'https://x.test/a.png'},
             'uploads are never authored as JSON'),
            ({'kind': 'BOGUS', 'title': 'x'}, 'unknown kinds are refused'),
            ({'kind': 'TEXT', 'title': 'Long', 'body': 'x' * 20001}, 'body has a ceiling'),
        ):
            response = self.staff_api.post(INSPIRATIONS, body, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, why)
        self.assertEqual(PlatformInspiration.objects.count(), 1)

        # Published, the client reads the words — and can narrow the gallery
        # to one kind. The curator stays platform-side.
        self.staff_api.post(f"{INSPIRATIONS}{data['id']}/publish/", {}, format='json')
        publish_inspiration(PlatformInspiration.objects.create(**INSPIRATION_BODY))
        gallery = self.owner_api.get(
            CLIENT_LIBRARY, {'kind': 'text'}, **workspace_header(self.workspace),
        )
        self.assertEqual(gallery.status_code, 200, gallery.content)
        rows = gallery.json()['data']['inspirations']
        self.assertEqual([r['kind'] for r in rows], ['TEXT'])
        self.assertEqual(rows[0]['body'], 'Stop scrolling if you hate Mondays.')
        self.assertNotIn('curated_by', rows[0])
        everything = self.owner_api.get(CLIENT_LIBRARY, **workspace_header(self.workspace))
        self.assertEqual(everything.json()['data']['count'], 2)

    def test_upload_makes_an_image_video_or_file_entry_and_refuses_the_rest(self):
        png = SimpleUploadedFile(
            'Hero shot (final).PNG', b'\x89PNG\r\n\x1a\n' + b'0' * 64, content_type='image/png',
        )
        response = self.staff_api.post(UPLOAD, {
            'file': png, 'title': 'Hero crop', 'annotation': 'One subject.',
            'tags': 'crop, hero', 'reference_url': 'https://example.test/source',
            'industry': 'Coffee',
        }, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()['data']
        self.assertEqual(data['kind'], 'IMAGE')
        self.assertEqual(data['status'], LifecycleStatus.DRAFT)
        self.assertEqual(data['mime_type'], 'image/png')
        self.assertEqual(data['file_name'], 'Hero-shot-final.png')
        self.assertTrue(
            data['file_url'].startswith('https://storage.test/library/platform/'), data['file_url'],
        )
        self.assertEqual(data['reference_url'], 'https://example.test/source')
        self.assertEqual(data['tags'], ['crop', 'hero'])
        self.assertEqual(data['industry'], 'Coffee')
        self.assertEqual(PlatformInspiration.objects.get(pk=data['id']).curated_by, self.staff)
        created = PlatformAuditLog.objects.get(action='PLATFORM_INSPIRATION_CREATED')
        self.assertEqual(created.detail['kind'], 'IMAGE')
        self.assertEqual(created.detail['file_name'], 'Hero-shot-final.png')

        # The kind follows the file, and a missing title falls back to its name.
        for name, kind in (('loop.mov', 'VIDEO'), ('deck.pdf', 'FILE'), ('notes.md', 'FILE')):
            response = self.staff_api.post(
                UPLOAD, {'file': SimpleUploadedFile(name, b'data')}, format='multipart',
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
            self.assertEqual(response.json()['data']['kind'], kind, name)
            self.assertEqual(response.json()['data']['title'], name)

        # Refused: no file, an empty file, a type off the allowlist, too large,
        # a bad source URL. Nothing is written for any of them.
        self.assertEqual(
            self.staff_api.post(UPLOAD, {'title': 'x'}, format='multipart').status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        for bad in (
            SimpleUploadedFile('empty.png', b''),
            SimpleUploadedFile('tool.exe', b'MZ'),
            SimpleUploadedFile('vector.svg', b'<svg/>'),
            SimpleUploadedFile('noext', b'data'),
            SimpleUploadedFile('page.html', b'<html/>'),
        ):
            response = self.staff_api.post(UPLOAD, {'file': bad}, format='multipart')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, bad.name)
            self.assertEqual(response.json()['error']['code'], 'INVALID_UPLOAD', bad.name)
        with patch('apps.platform.views_universal.MAX_UPLOAD_BYTES', 8):
            response = self.staff_api.post(
                UPLOAD, {'file': SimpleUploadedFile('big.png', b'0' * 9)}, format='multipart',
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('larger than', response.json()['error']['message'])
        # A body that declares itself oversized is refused before it is parsed.
        response = self.staff_api.post(
            UPLOAD, {'file': SimpleUploadedFile('big.png', b'1')}, format='multipart',
            CONTENT_LENGTH=str(30 * 1024 * 1024),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()['error']['code'], 'INVALID_UPLOAD')
        response = self.staff_api.post(
            UPLOAD, {'file': SimpleUploadedFile('a.png', b'1'),
                     'reference_url': 'https://x.test/a\nb'},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.staff_api.post(
            UPLOAD, {'file': SimpleUploadedFile('a.png', b'1'), 'reference_url': 'ftp://x.test/a'},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PlatformInspiration.objects.count(), 4)

        # Storage that fails writes no row: no dead cards in a client's gallery.
        with patch(
            'apps.platform.views_universal.SupabaseStorageService.upload_and_describe',
            side_effect=StorageError('bucket down'),
        ):
            response = self.staff_api.post(
                UPLOAD, {'file': SimpleUploadedFile('b.png', b'1')}, format='multipart',
            )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(PlatformInspiration.objects.count(), 4)

        # The boundary holds on this route too.
        self.assertEqual(
            self.owner_api.post(
                UPLOAD, {'file': SimpleUploadedFile('c.png', b'1')}, format='multipart',
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            APIClient().post(
                UPLOAD, {'file': SimpleUploadedFile('c.png', b'1')}, format='multipart',
            ).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertEqual(PlatformInspiration.objects.count(), 4)

    def test_kind_and_file_are_fixed_and_a_patch_keeps_the_content_rule(self):
        link = PlatformInspiration.objects.create(**INSPIRATION_BODY)
        text = PlatformInspiration.objects.create(
            title='Hook', kind=EntryKind.TEXT, body='Words.',
        )
        image = PlatformInspiration.objects.create(
            title='Pic', kind=EntryKind.IMAGE, file_url='https://storage.test/p.png',
            storage_path='library/platform/p.png', mime_type='image/png', file_name='p.png',
        )

        for pk, body, why in (
            (link.pk, {'kind': 'TEXT', 'body': 'x'}, 'a link cannot become text'),
            (link.pk, {'reference_url': ''}, 'a link cannot lose its URL'),
            (text.pk, {'body': '  '}, 'a text entry cannot lose its words'),
            (image.pk, {'kind': 'LINK', 'reference_url': 'https://x.test/'}, 'an upload stays an upload'),
        ):
            response = self.staff_api.patch(f'{INSPIRATIONS}{pk}/', body, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, why)

        # Restating the same kind is not a change.
        response = self.staff_api.patch(
            f'{INSPIRATIONS}{text.pk}/', {'kind': 'text', 'body': 'Better words.'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['body'], 'Better words.')

        # An upload's words and its credit can change; the file columns are
        # not authoring fields and are ignored however they are spelled.
        response = self.staff_api.patch(f'{INSPIRATIONS}{image.pk}/', {
            'title': 'Picture', 'reference_url': 'https://example.test/credit',
            'file_url': 'https://evil.test/x.png', 'storage_path': 'inspirations/other-tenant/x.png',
            'mime_type': 'text/html', 'file_name': 'x.html',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        image.refresh_from_db()
        self.assertEqual(image.title, 'Picture')
        self.assertEqual(image.reference_url, 'https://example.test/credit')
        self.assertEqual(image.file_url, 'https://storage.test/p.png')
        self.assertEqual(image.storage_path, 'library/platform/p.png')
        self.assertEqual(image.mime_type, 'image/png')
        self.assertEqual(image.file_name, 'p.png')
        edited = (
            PlatformAuditLog.objects.filter(action='PLATFORM_INSPIRATION_EDITED')
            .order_by('created_at').last()
        )
        self.assertEqual(set(edited.detail['changes']), {'title', 'reference_url'})

        # Published, an upload reaches the client with what it needs to render
        # and adopts as the matching brand inspiration type.
        publish_inspiration(image)
        gallery = self.owner_api.get(CLIENT_LIBRARY, **workspace_header(self.workspace))
        row = gallery.json()['data']['inspirations'][0]
        self.assertEqual((row['kind'], row['file_url'], row['mime_type']),
                         ('IMAGE', 'https://storage.test/p.png', 'image/png'))
        self.assertNotIn('storage_path', row)
        adopt = self.owner_api.post(
            f'{CLIENT_LIBRARY}{image.pk}/adopt/', {'brand_id': str(self.brand.pk)},
            format='json', **workspace_header(self.workspace),
        )
        self.assertEqual(adopt.status_code, status.HTTP_201_CREATED, adopt.content)
        adopted = BrandInspiration.objects.get(pk=adopt.json()['data']['inspiration_id'])
        self.assertEqual(adopted.inspiration_type, BrandInspiration.InspirationType.IMAGE)
        self.assertEqual(adopted.file_url, 'https://storage.test/p.png')
        self.assertIsNone(adopted.storage_path)

    def test_a_client_cannot_forge_adoption_provenance_on_its_own_rows(self):
        """The adoption count every tenant and the console see is computed from
        a metadata key; a tenant must not be able to mint it on its own rows."""
        reference = publish_inspiration(PlatformInspiration.objects.create(**INSPIRATION_BODY))
        headers = workspace_header(self.workspace)
        own = '/api/marketing/inspirations/'
        forged = {
            'brand': str(self.brand.pk), 'title': 'Mine', 'reference_url': 'https://mine.test/',
            'metadata': {'platform_inspiration_id': str(reference.pk), 'adopted_from_platform': True},
        }
        response = self.owner_api.post(own, forged, format='json', **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

        # Free-form metadata still works, and cannot be upgraded afterwards.
        response = self.owner_api.post(
            own, {**forged, 'metadata': {'duration_seconds': 15}}, format='json', **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        row_id = response.json()['id']
        response = self.owner_api.patch(
            f'{own}{row_id}/', {'metadata': {'platform_inspiration_id': str(reference.pk)}},
            format='json', **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        from apps.universal.services import adoption_count

        self.assertEqual(adoption_count(reference), 0)

        # A genuinely adopted row can round-trip its own provenance unchanged.
        adopted, _ = adopt_inspiration(reference, self.brand, user=self.owner)
        response = self.owner_api.patch(
            f'{own}{adopted.pk}/', {'metadata': adopted.metadata, 'annotation': 'Mine now.'},
            format='json', **headers,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(adoption_count(reference), 1)
