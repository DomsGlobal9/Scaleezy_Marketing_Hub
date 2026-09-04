"""Optional administrative contact fields must persist without becoming intelligence."""
import json

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.learning.models import LearningEvent
from apps.workspaces.models import WorkspaceMember

from .models import Brand
from .services.brand_brain import rebuild_brand_brain


BRANDS_URL = '/api/marketing/brands/'
CONTACTS = {'legal_name': 'Example Textiles Private Limited', 'contact_person': 'Mira Example'}
FORMATS = ('json', 'multipart')
METHODS = ('post', 'put', 'patch')


class BrandContactFieldTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Contact field tests', 'contacts')
        self.user, self.client = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.EDITOR, 'contact-editor'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Public trading brand', is_default=True
        )
        self.url = f'{BRANDS_URL}{self.brand.pk}/'
        self.headers = workspace_header(self.workspace)

    def send(self, method, data, *, format='json', client=None, headers=None):
        return getattr(client or self.client, method)(
            BRANDS_URL if method == 'post' else self.url,
            data, format=format, **(self.headers if headers is None else headers),
        )

    def assert_contacts(self, row, expected):
        for field, value in expected.items():
            self.assertEqual(row[field], value, field)

    def assert_persisted(self, brand_id, expected):
        brand = Brand.objects.get(pk=brand_id)
        self.assert_contacts({field: getattr(brand, field) for field in expected}, expected)
        for url in (f'{BRANDS_URL}{brand_id}/', f'{BRANDS_URL}current/'):
            response = self.client.get(url, **self.headers)
            self.assertEqual(response.status_code, 200, response.data)
            row = response.data['data'] if url.endswith('/current/') else response.data
            self.assertEqual(str(row['id']), str(brand_id))
            self.assert_contacts(row, expected)
        response = self.client.get(BRANDS_URL, **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        row = next(row for row in response.data if str(row['id']) == str(brand_id))
        self.assert_contacts(row, expected)

    def test_internal_create_and_legacy_api_create_default_to_empty_strings(self):
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.legal_name, '')
        self.assertEqual(self.brand.contact_person, '')
        for format in FORMATS:
            with self.subTest(format=format):
                response = self.send('post', {
                    'name': f'Legacy caller {format}', 'is_default': True,
                }, format=format)
                self.assertEqual(response.status_code, 201, response.data)
                self.assert_persisted(response.data['id'], {
                    'legal_name': '', 'contact_person': '',
                })

    def test_json_and_multipart_post_put_patch_round_trip_through_all_reads(self):
        contacts = {'legal_name': '示例织物有限公司', 'contact_person': 'மீரா 示例'}
        for format in FORMATS:
            for method in METHODS:
                with self.subTest(method=method, format=format):
                    response = self.send(method, {
                        'name': f'Public brand {method} {format}',
                        'is_default': True, **contacts,
                    }, format=format)
                    self.assertEqual(response.status_code, 201 if method == 'post' else 200,
                                     response.data)
                    self.assert_contacts(response.data, contacts)
                    self.assert_persisted(response.data['id'], contacts)

    def test_maximum_length_is_accepted_on_all_mutation_paths(self):
        contacts = {'legal_name': '名' * 255, 'contact_person': '人' * 150}
        for format in FORMATS:
            for method in METHODS:
                with self.subTest(method=method, format=format):
                    response = self.send(method, {
                        'name': f'Maximum {method} {format}', **contacts,
                    }, format=format)
                    self.assertEqual(response.status_code, 201 if method == 'post' else 200,
                                     response.data)
                    saved = Brand.objects.get(pk=response.data['id'])
                    self.assert_contacts({field: getattr(saved, field) for field in contacts},
                                         contacts)

    def test_over_limit_rejected_atomically_on_all_mutation_paths(self):
        Brand.objects.filter(pk=self.brand.pk).update(**CONTACTS)
        count_before = Brand.objects.count()
        for format in FORMATS:
            for method in METHODS:
                for field, limit in (('legal_name', 255), ('contact_person', 150)):
                    with self.subTest(method=method, format=format, field=field):
                        response = self.send(method, {
                            'name': f'Invalid {method} {format} {field}',
                            **CONTACTS, field: 'x' * (limit + 1),
                        }, format=format)
                        self.assertEqual(response.status_code, 400, response.data)
                        self.assertIn(field, response.data)
                        self.assertEqual(Brand.objects.count(), count_before)
                        self.brand.refresh_from_db()
                        self.assertEqual(self.brand.name, 'Public trading brand')
                        self.assert_contacts({key: getattr(self.brand, key) for key in CONTACTS},
                                             CONTACTS)

    def test_partial_edits_and_explicit_clears_preserve_the_other_values(self):
        Brand.objects.filter(pk=self.brand.pk).update(**CONTACTS)
        expected = dict(CONTACTS)
        for format in FORMATS:
            for field in CONTACTS:
                for value in (f'Updated {field} {format}', ''):
                    with self.subTest(format=format, field=field, value=value):
                        response = self.send('patch', {field: value}, format=format)
                        self.assertEqual(response.status_code, 200, response.data)
                        expected[field] = value
                        self.assert_persisted(self.brand.pk, expected)
                        self.brand.refresh_from_db()
                        self.assertEqual(self.brand.name, 'Public trading brand')

    def test_optional_fields_may_be_blank_on_every_mutation_path(self):
        for format in FORMATS:
            for method in METHODS:
                with self.subTest(method=method, format=format):
                    response = self.send(method, {
                        'name': f'Blank {method} {format}',
                        'legal_name': '', 'contact_person': '',
                    }, format=format)
                    self.assertEqual(response.status_code, 201 if method == 'post' else 200,
                                     response.data)
                    saved = Brand.objects.get(pk=response.data['id'])
                    self.assertEqual(saved.legal_name, '')
                    self.assertEqual(saved.contact_person, '')

    def test_null_and_structured_values_are_rejected_without_changing_contacts(self):
        Brand.objects.filter(pk=self.brand.pk).update(**CONTACTS)
        for field in CONTACTS:
            for value in (None, [], {'name': 'not a string'}):
                with self.subTest(field=field, value=value):
                    response = self.send('patch', {field: value})
                    self.assertEqual(response.status_code, 400, response.data)
                    self.assertIn(field, response.data)
        self.brand.refresh_from_db()
        self.assert_contacts({field: getattr(self.brand, field) for field in CONTACTS}, CONTACTS)

    def test_omitted_contact_fields_in_put_leave_existing_values_unchanged(self):
        Brand.objects.filter(pk=self.brand.pk).update(**CONTACTS)
        for format in FORMATS:
            with self.subTest(format=format):
                response = self.send('put', {'name': self.brand.name}, format=format)
                self.assertEqual(response.status_code, 200, response.data)
                self.assert_persisted(self.brand.pk, CONTACTS)

    def test_anonymous_requests_cannot_read_or_write_contact_fields(self):
        anonymous = APIClient()
        count_before = Brand.objects.count()
        for url in (BRANDS_URL, self.url, f'{BRANDS_URL}current/'):
            self.assertEqual(anonymous.get(url, **self.headers).status_code, 401)
        for format in FORMATS:
            for method in METHODS:
                with self.subTest(method=method, format=format):
                    response = self.send(method, {'name': 'Anonymous', **CONTACTS},
                                         client=anonymous, format=format)
                    self.assertEqual(response.status_code, 401, response.data)
        self.assertEqual(Brand.objects.count(), count_before)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.legal_name, '')
        self.assertEqual(self.brand.contact_person, '')

    def test_viewer_can_read_but_cannot_mutate_contact_fields_on_any_path(self):
        _, viewer = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.VIEWER, 'contact-viewer'
        )
        Brand.objects.filter(pk=self.brand.pk).update(**CONTACTS)
        count_before = Brand.objects.count()
        response = viewer.get(self.url, **self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_contacts(response.data, CONTACTS)
        for format in FORMATS:
            for method in METHODS:
                with self.subTest(method=method, format=format):
                    response = self.send(method, {'name': 'Forbidden',
                                                 'legal_name': 'Forbidden',
                                                 'contact_person': 'Forbidden'},
                                         client=viewer, format=format)
                    self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(Brand.objects.count(), count_before)
        self.assert_persisted(self.brand.pk, CONTACTS)

    def test_foreign_workspace_cannot_read_mutate_or_receive_contact_values(self):
        foreign = self.make_workspace('Other client', 'other-contact-client')
        _, outsider = self.authenticate_as(foreign, WorkspaceMember.Role.OWNER, 'outsider')
        other_brand = Brand.objects.create(workspace=foreign, name='Other brand', is_default=True)
        Brand.objects.filter(pk=self.brand.pk).update(**CONTACTS)
        other_headers = workspace_header(foreign)
        self.assertEqual(outsider.get(self.url, **other_headers).status_code, 404)
        for url in (BRANDS_URL, f'{BRANDS_URL}current/'):
            response = outsider.get(url, **other_headers)
            self.assertEqual(response.status_code, 200, response.data)
            for value in CONTACTS.values():
                self.assertNotIn(value, response.content.decode())
        for format in FORMATS:
            for method in ('put', 'patch'):
                with self.subTest(method=method, format=format):
                    response = self.send(method, {'name': 'Stolen',
                                                 'legal_name': 'Stolen',
                                                 'contact_person': 'Stolen'},
                                         client=outsider, headers=other_headers, format=format)
                    self.assertEqual(response.status_code, 404, response.data)
        self.assert_persisted(self.brand.pk, CONTACTS)
        other_brand.refresh_from_db()
        self.assertEqual(other_brand.legal_name, '')
        self.assertEqual(other_brand.contact_person, '')

    def test_workspace_injection_does_not_move_contact_values_between_tenants(self):
        foreign = self.make_workspace('Other workspace', 'contact-injection-target')
        for format in FORMATS:
            response = self.send('post', {'name': f'Own brand {format}',
                                         'workspace': str(foreign.pk), **CONTACTS}, format=format)
            self.assertEqual(response.status_code, 201, response.data)
            saved = Brand.objects.get(pk=response.data['id'])
            self.assertEqual(saved.workspace_id, self.workspace.pk)
            for method in ('put', 'patch'):
                with self.subTest(method=method, format=format):
                    response = self.send(method, {'name': self.brand.name,
                                                 'workspace': str(foreign.pk), **CONTACTS},
                                         format=format)
                    self.assertEqual(response.status_code, 200, response.data)
                    self.brand.refresh_from_db()
                    self.assertEqual(self.brand.workspace_id, self.workspace.pk)
        self.assertFalse(Brand.objects.filter(workspace=foreign).exists())

    def test_contact_only_changes_do_not_change_compiled_identity_or_learning(self):
        original = rebuild_brand_brain(self.brand)
        for format in FORMATS:
            with self.subTest(format=format):
                response = self.send('patch', CONTACTS, format=format)
                self.assertEqual(response.status_code, 200, response.data)
                self.brand.refresh_from_db()
                self.assertEqual(self.brand.creative_brain['identity'], original['identity'])
                self.assertEqual(self.brand.brain_version, original['brain_version'])
                compiled = json.dumps(self.brand.creative_brain)
                for field, value in CONTACTS.items():
                    self.assertNotIn(field, compiled)
                    self.assertNotIn(value, compiled)
                self.assertFalse(LearningEvent.objects.filter(brand=self.brand).exists())

    def test_mixed_identity_edit_records_only_identity_fields_not_contact_values(self):
        response = self.send('patch', {'name': 'New public brand', **CONTACTS})
        self.assertEqual(response.status_code, 200, response.data)
        event = LearningEvent.objects.get(brand=self.brand)
        self.assertEqual(event.context['fields'], ['name'])
        self.assertEqual(set(event.context['changes']), {'name'})
        self.brand.refresh_from_db()
        for field, value in CONTACTS.items():
            self.assertNotIn(field, json.dumps(event.context))
            self.assertNotIn(value, json.dumps(event.context))
            self.assertNotIn(field, json.dumps(self.brand.creative_brain))
            self.assertNotIn(value, json.dumps(self.brand.creative_brain))


class BrandContactMigrationTests(TestCase):
    merge = ('brands', '0007_merge_contact_guardrails')
    contact = ('brands', '0006_brand_intake_contact')
    guardrails = ('brands', '0006_brand_guardrails')

    def test_original_contact_migration_is_preserved_and_merge_has_one_leaf(self):
        loader = MigrationLoader(None)
        self.assertEqual(loader.graph.leaf_nodes('brands'), [self.merge])
        self.assertEqual(set(loader.get_migration(*self.merge).dependencies),
                         {self.contact, self.guardrails})
        self.assertEqual(loader.get_migration(*self.merge).operations, [])
        original = loader.get_migration(*self.contact)
        self.assertEqual(original.dependencies, [('brands', '0005_alter_brand_layout_preference')])
        self.assertEqual([operation.name for operation in original.operations],
                         ['legal_name', 'contact_person'])
        for operation, length in zip(original.operations, (255, 150)):
            self.assertEqual(operation.field.default, '')
            self.assertTrue(operation.field.blank)
            self.assertEqual(operation.field.max_length, length)
            self.assertFalse(operation.preserve_default)

    def test_merged_state_contains_contact_fields_and_guardrails(self):
        loader = MigrationLoader(None)
        model = loader.project_state([self.merge]).apps.get_model('brands', 'Brand')
        for name, limit in (('legal_name', 255), ('contact_person', 150)):
            field = model._meta.get_field(name)
            self.assertTrue(field.blank)
            self.assertFalse(field.null)
            self.assertEqual(field.max_length, limit)
            self.assertEqual(field.get_default(), '')
        self.assertEqual(model._meta.get_field('guardrails').get_default(), {})

    def test_either_already_applied_branch_only_plans_the_missing_migration(self):
        for applied, missing in ((self.contact, self.guardrails), (self.guardrails, self.contact)):
            with self.subTest(applied=applied):
                executor = MigrationExecutor(connection)
                executor.loader.applied_migrations = {
                    node: executor.loader.get_migration(*node)
                    for node in executor.loader.graph.forwards_plan(applied)
                }
                plan = executor.migration_plan([self.merge])
                self.assertEqual([(migration.app_label, migration.name) for migration, _ in plan],
                                 [missing, self.merge])
                self.assertFalse(any(backwards for _, backwards in plan))
