"""Phase 5 — capability routing, per-customer switches, strategies."""
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.ai.adapters.base import AIProviderAdapter
from apps.ai.models import (
    AIProvider,
    AIUsageLog,
    Capability,
    ProviderIntegrationType,
    Strategy,
    WorkspaceAIProvider,
    WorkspaceAIRoute,
)
from apps.ai.router import AIRouter, NoProviderAvailable
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()


class FakeAdapter(AIProviderAdapter):
    key = 'fake'
    display_name = 'Fake'
    capabilities = (Capability.TEXT, Capability.IMAGE)
    unit_cost = 0.01

    def generate_text(self, brief):
        return {'headline': 'from-fake', 'quality_score': 0.5}

    def generate_image(self, brief):
        return {'image_url': 'https://fake/img.png'}

    def health_check(self):
        return {'ok': True, 'detail': 'fake ready'}


class BetterAdapter(FakeAdapter):
    key = 'better'
    display_name = 'Better'
    unit_cost = 0.01

    def generate_text(self, brief):
        return {'headline': 'from-better', 'quality_score': 0.99}


class BrokenAdapter(FakeAdapter):
    key = 'broken'
    display_name = 'Broken'

    def generate_text(self, brief):
        raise RuntimeError("provider exploded")


def _install(monkey_registry):
    """Point the registry at the test adapters."""
    return patch('apps.ai.registry.get_adapter_class', side_effect=monkey_registry.get)


class RouterTests(APITestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.adapters = {'fake': FakeAdapter, 'better': BetterAdapter, 'broken': BrokenAdapter}

        # update_or_create, not create: the seed migration discovers every
        # AIProviderAdapter subclass, and these test adapters are subclasses
        # too, so the catalogue rows may already exist.
        self.providers = {}
        for key, cls in self.adapters.items():
            self.providers[key], _ = AIProvider.objects.update_or_create(
                key=key,
                defaults={
                    'display_name': cls.display_name,
                    'capabilities': [Capability.TEXT, Capability.IMAGE],
                    'unit_cost': cls.unit_cost,
                    'is_available': True,
                },
            )

    def enable(self, key, capability=Capability.TEXT, priority=10,
               strategy=Strategy.ROUND_ROBIN, enabled=True):
        WorkspaceAIProvider.objects.get_or_create(
            workspace=self.ws, provider=self.providers[key], defaults={'enabled': enabled}
        )
        WorkspaceAIRoute.objects.create(
            workspace=self.ws, capability=capability, provider=self.providers[key],
            priority=priority, strategy=strategy,
        )

    def route(self, capability=Capability.TEXT, brief=None):
        with _install(self.adapters):
            return AIRouter(self.ws).dispatch(capability, brief or {})

    # ── resolution ───────────────────────────────────────────────────────
    def test_no_route_configured_raises(self):
        with self.assertRaises(NoProviderAvailable):
            self.route()

    def test_routes_to_the_configured_provider(self):
        self.enable('fake')
        result = self.route()
        self.assertEqual(result['headline'], 'from-fake')
        self.assertEqual(result['provider'], 'fake')

    def test_a_disabled_provider_is_not_used_even_when_routed(self):
        """The on/off switch overrides routing."""
        self.enable('fake')
        WorkspaceAIProvider.objects.filter(workspace=self.ws).update(enabled=False)
        with self.assertRaises(NoProviderAvailable):
            self.route()

    def test_operator_kill_switch_disables_it_for_everyone(self):
        self.enable('fake')
        AIProvider.objects.filter(key='fake').update(is_available=False)
        with self.assertRaises(NoProviderAvailable):
            self.route()

    def test_capabilities_route_independently(self):
        """The headline requirement: one AI for copy, another for images."""
        self.enable('fake', capability=Capability.TEXT)
        self.enable('better', capability=Capability.IMAGE)

        self.assertEqual(self.route(Capability.TEXT)['provider'], 'fake')
        self.assertEqual(self.route(Capability.IMAGE)['provider'], 'better')

    def test_provider_that_cannot_serve_a_capability_is_skipped(self):
        AIProvider.objects.filter(key='fake').update(capabilities=[Capability.IMAGE])
        self.enable('fake', capability=Capability.TEXT)
        with self.assertRaises(NoProviderAvailable):
            self.route(Capability.TEXT)

    # ── strategies ───────────────────────────────────────────────────────
    def test_failover_skips_a_broken_provider(self):
        self.enable('broken', priority=1, strategy=Strategy.FAILOVER)
        self.enable('fake', priority=2, strategy=Strategy.FAILOVER)
        self.assertEqual(self.route()['provider'], 'fake')

    def test_failover_raises_when_every_provider_fails(self):
        self.enable('broken', priority=1, strategy=Strategy.FAILOVER)
        with self.assertRaises(NoProviderAvailable):
            self.route()

    def test_round_robin_rotates_the_first_provider_between_calls(self):
        self.enable('fake', priority=1)
        self.enable('better', priority=2)

        self.assertEqual(self.route()['provider'], 'fake')
        self.assertEqual(self.route()['provider'], 'better')
        self.assertEqual(self.route()['provider'], 'fake')

    def test_round_robin_falls_through_when_the_selected_provider_fails(self):
        self.enable('broken', priority=1)
        self.enable('fake', priority=2)

        result = self.route()

        self.assertEqual(result['provider'], 'fake')
        self.assertEqual(result['strategy'], Strategy.ROUND_ROBIN)
        self.assertTrue(
            AIUsageLog.objects.filter(
                workspace=self.ws,
                provider=self.providers['broken'],
                success=False,
            ).exists()
        )

    def test_best_of_keeps_the_highest_scoring_result(self):
        self.enable('fake', priority=1, strategy=Strategy.BEST_OF)
        self.enable('better', priority=2, strategy=Strategy.BEST_OF)
        result = self.route()
        self.assertEqual(result['headline'], 'from-better')
        self.assertEqual(result['considered'], 2)

    def test_best_of_marks_only_the_winner_as_selected(self):
        """Cost reporting must distinguish the kept result from the discarded."""
        self.enable('fake', priority=1, strategy=Strategy.BEST_OF)
        self.enable('better', priority=2, strategy=Strategy.BEST_OF)
        self.route()
        logs = AIUsageLog.objects.filter(workspace=self.ws, success=True)
        self.assertEqual(logs.count(), 2)
        self.assertEqual(logs.filter(selected=True).count(), 1)
        self.assertEqual(logs.get(selected=True).provider.key, 'better')

    def test_internal_dispatch_under_best_of_calls_exactly_one_provider(self):
        """QA overhead never multiplies: BEST_OF is for buying the customer a
        better asset, so an internal (judge/focus) dispatch takes the single
        first candidate and its log row is marked is_internal."""
        self.enable('fake', priority=1, strategy=Strategy.BEST_OF)
        self.enable('better', priority=2, strategy=Strategy.BEST_OF)

        with _install(self.adapters):
            result = AIRouter(self.ws).dispatch(Capability.TEXT, {}, internal=True)

        self.assertEqual(result['provider'], 'fake')
        logs = AIUsageLog.objects.filter(workspace=self.ws)
        self.assertEqual(logs.count(), 1)
        self.assertTrue(logs.get().is_internal)

        # A normal dispatch on the same routes still races both providers,
        # and its rows stay customer-billable.
        self.assertEqual(self.route()['provider'], 'better')
        self.assertEqual(
            AIUsageLog.objects.filter(workspace=self.ws, is_internal=False).count(), 2
        )

    def test_one_router_reads_the_route_policy_once_for_many_capabilities(self):
        self.enable('fake', capability=Capability.TEXT)
        self.enable('better', capability=Capability.IMAGE)
        router = AIRouter(self.ws)

        with _install(self.adapters), self.assertNumQueries(2):
            text = router._candidates(Capability.TEXT)
            image = router._candidates(Capability.IMAGE)
            text_strategy = router.strategy_for(Capability.TEXT)
            missing_strategy = router.strategy_for(Capability.VIDEO)

        self.assertEqual([row['route'].provider.key for row in text], ['fake'])
        self.assertEqual([row['route'].provider.key for row in image], ['better'])
        self.assertEqual(text_strategy, Strategy.ROUND_ROBIN)
        self.assertEqual(missing_strategy, Strategy.ROUND_ROBIN)

    # ── usage logging ────────────────────────────────────────────────────
    def test_a_successful_call_is_logged(self):
        self.enable('fake')
        self.route()
        log = AIUsageLog.objects.get(workspace=self.ws)
        self.assertTrue(log.success)
        self.assertEqual(log.capability, Capability.TEXT)

    def test_a_failure_is_logged_too(self):
        self.enable('broken', priority=1)
        self.enable('fake', priority=2)
        self.route()
        self.assertTrue(
            AIUsageLog.objects.filter(workspace=self.ws, success=False).exists()
        )


class AIConsoleAPITests(APITestCase):
    def setUp(self):
        self.ws = MarketingWorkspace.objects.create(customer_id='a', workspace_name='Alpha')
        self.other = MarketingWorkspace.objects.create(customer_id='b', workspace_name='Beta')
        self.provider, _ = AIProvider.objects.update_or_create(
            key='fake',
            defaults={'display_name': 'Fake', 'capabilities': [Capability.TEXT],
                      'is_available': True},
        )
        self.better_provider, _ = AIProvider.objects.update_or_create(
            key='better',
            defaults={
                'display_name': 'Better',
                'capabilities': [Capability.TEXT, Capability.IMAGE],
                'is_available': True,
            },
        )

        self.admin = User.objects.create_user(username='admin2', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.admin, role=WorkspaceMember.Role.ADMIN
        )
        self.editor = User.objects.create_user(username='ed', password='pw')
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.editor, role=WorkspaceMember.Role.EDITOR
        )

    def as_(self, user, ws=None):
        self.client.force_authenticate(user=user)
        self.client.credentials(HTTP_X_WORKSPACE_ID=str((ws or self.ws).id))

    def test_catalogue_requires_auth(self):
        self.assertEqual(
            self.client.get('/api/marketing/ai/catalogue/').status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_catalogue_lists_providers_and_vocabularies(self):
        self.as_(self.admin)
        res = self.client.get('/api/marketing/ai/catalogue/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.data['data']
        self.assertTrue(any(p['key'] == 'fake' for p in data['providers']))
        self.assertTrue(data['capabilities'])
        self.assertTrue(data['strategies'])

    def test_admin_can_enable_a_provider(self):
        self.as_(self.admin)
        res = self.client.post(
            '/api/marketing/ai/providers/',
            {'provider': str(self.provider.id), 'enabled': True, 'credentials': 'sk-secret'},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        wp = WorkspaceAIProvider.objects.get(workspace=self.ws)
        self.assertTrue(wp.enabled)
        self.assertTrue(wp.has_credentials)

    @patch('apps.ai.endpoint_security.socket.getaddrinfo')
    def test_admin_can_onboard_a_custom_ai_without_provider_or_model_defaults(self, resolve):
        resolve.return_value = [
            (2, 1, 6, '', ('93.184.216.34', 443)),
        ]
        self.as_(self.admin)

        res = self.client.post(
            '/api/marketing/ai/providers/custom/',
            {
                'display_name': 'My chosen AI',
                'base_url': 'https://ai.example.com/v1/',
                'credentials': 'customer-owned-secret',
                'model': 'chosen-model-2026',
                'integration_type': ProviderIntegrationType.OPENAI_COMPATIBLE,
                'capabilities': [Capability.TEXT, Capability.IMAGE, Capability.EMBEDDING],
                'enabled': True,
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        configured = WorkspaceAIProvider.objects.get(
            workspace=self.ws, provider__display_name='My chosen AI'
        )
        self.assertEqual(configured.model_override, 'chosen-model-2026')
        self.assertNotIn('customer-owned-secret', configured.credentials_encrypted)
        self.assertEqual(configured.provider.default_model, '')
        self.assertEqual(configured.provider.base_url, 'https://ai.example.com/v1')
        self.assertEqual(
            configured.provider.integration_type,
            ProviderIntegrationType.OPENAI_COMPATIBLE,
        )
        self.assertEqual(
            configured.provider.capabilities,
            [Capability.TEXT, Capability.IMAGE, Capability.EMBEDDING],
        )
        self.assertNotIn('credentials', res.data['data'])

    @patch('apps.ai.adapters.openai_compatible.validate_public_https_endpoint')
    @patch('apps.ai.adapters.openai_compatible.httpx.post')
    @patch('apps.ai.endpoint_security.socket.getaddrinfo')
    def test_custom_ai_executes_through_airouter_without_a_vendor_branch(
        self, resolve, post, validate_endpoint
    ):
        resolve.return_value = [(2, 1, 6, '', ('93.184.216.34', 443))]
        validate_endpoint.return_value = 'https://chosen.example.com/v1'
        upstream = Mock(status_code=200)
        upstream.json.return_value = {
            'id': 'custom-response',
            'model': 'manual-model',
            'choices': [{
                'message': {
                    'content': (
                        '{"headline":"Chosen AI","caption":"Manual route",'
                        '"hashtags":"#chosen"}'
                    ),
                },
            }],
        }
        post.return_value = upstream
        self.as_(self.admin)
        created = self.client.post(
            '/api/marketing/ai/providers/custom/',
            {
                'display_name': 'Chosen endpoint',
                'base_url': 'https://chosen.example.com/v1',
                'credentials': 'chosen-key',
                'model': 'manual-model',
                'integration_type': ProviderIntegrationType.OPENAI_COMPATIBLE,
                'capabilities': [Capability.TEXT],
            },
            format='json',
        )
        configured = WorkspaceAIProvider.objects.get(id=created.data['data']['id'])
        WorkspaceAIRoute.objects.create(
            workspace=self.ws,
            provider=configured.provider,
            capability=Capability.TEXT,
            priority=10,
        )

        result = AIRouter(self.ws).dispatch(Capability.TEXT, {'topic': 'launch'})

        self.assertEqual(result['headline'], 'Chosen AI')
        self.assertEqual(
            post.call_args.args[0],
            'https://chosen.example.com/v1/chat/completions',
        )
        self.assertEqual(post.call_args.kwargs['json']['model'], 'manual-model')
        self.assertEqual(
            post.call_args.kwargs['headers']['Authorization'],
            'Bearer chosen-key',
        )

    @patch('apps.ai.adapters.openai_compatible.validate_public_https_endpoint')
    @patch('apps.ai.adapters.openai_compatible.httpx.post')
    @patch('apps.ai.endpoint_security.socket.getaddrinfo')
    def test_universal_custom_ai_can_route_every_capability(
        self, resolve, post, validate_endpoint
    ):
        resolve.return_value = [(2, 1, 6, '', ('93.184.216.34', 443))]
        validate_endpoint.return_value = 'https://gateway.example.com/scaleezy'
        upstream = Mock(status_code=200)
        upstream.json.return_value = {'result': {'video_url': 'https://cdn.example.com/video.mp4'}}
        post.return_value = upstream
        self.as_(self.admin)
        created = self.client.post(
            '/api/marketing/ai/providers/custom/',
            {
                'display_name': 'Universal gateway',
                'base_url': 'https://gateway.example.com/scaleezy',
                'credentials': 'gateway-key',
                'model': 'manual-video-model',
                'integration_type': ProviderIntegrationType.SCALEEZY_JSON,
                'capabilities': list(Capability.values),
            },
            format='json',
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        configured = WorkspaceAIProvider.objects.get(id=created.data['data']['id'])
        self.assertEqual(configured.provider.capabilities, list(Capability.values))

        for capability in Capability.values:
            with self.subTest(capability=capability):
                routed = self.client.post(
                    '/api/marketing/ai/routes/replace-set/',
                    {
                        'capability': capability,
                        'strategy': Strategy.FAILOVER,
                        'routes': [{'provider': str(configured.provider_id), 'priority': 10}],
                    },
                    format='json',
                )
                self.assertEqual(routed.status_code, status.HTTP_200_OK, routed.data)

        result = AIRouter(self.ws).dispatch(Capability.VIDEO, {'topic': 'launch'})
        self.assertEqual(result['video_url'], 'https://cdn.example.com/video.mp4')
        self.assertEqual(post.call_args.args[0], 'https://gateway.example.com/scaleezy')
        self.assertEqual(post.call_args.kwargs['json'], {
            'capability': Capability.VIDEO,
            'model': 'manual-video-model',
            'brief': {'topic': 'launch'},
        })

    @patch('apps.ai.endpoint_security.socket.getaddrinfo')
    def test_openai_compatible_custom_ai_rejects_video_capabilities(self, resolve):
        resolve.return_value = [(2, 1, 6, '', ('93.184.216.34', 443))]
        self.as_(self.admin)
        res = self.client.post(
            '/api/marketing/ai/providers/custom/',
            {
                'display_name': 'No standard video API',
                'base_url': 'https://video.example.com/v1',
                'model': 'video-model',
                'integration_type': ProviderIntegrationType.OPENAI_COMPATIBLE,
                'capabilities': [Capability.VIDEO],
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('capabilities', res.data)

    @patch('apps.ai.endpoint_security.socket.getaddrinfo')
    def test_custom_ai_is_visible_and_configurable_only_in_its_owner_workspace(self, resolve):
        resolve.return_value = [(2, 1, 6, '', ('93.184.216.34', 443))]
        WorkspaceMember.objects.create(
            workspace=self.other, user=self.admin, role=WorkspaceMember.Role.ADMIN
        )
        self.as_(self.admin)
        created = self.client.post(
            '/api/marketing/ai/providers/custom/',
            {
                'display_name': 'Alpha private AI',
                'base_url': 'https://alpha-ai.example.com/v1',
                'credentials': 'alpha-secret',
                'model': 'alpha-model',
                'integration_type': ProviderIntegrationType.OPENAI_COMPATIBLE,
                'capabilities': [Capability.TEXT],
            },
            format='json',
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        custom = AIProvider.objects.get(display_name='Alpha private AI')

        self.as_(self.admin, self.other)
        catalogue = self.client.get('/api/marketing/ai/catalogue/')
        self.assertFalse(any(
            row['id'] == str(custom.id)
            for row in catalogue.data['data']['providers']
        ))
        injected = self.client.post(
            '/api/marketing/ai/providers/',
            {
                'provider': str(custom.id),
                'credentials': 'stolen-target',
                'model_override': 'stolen-model',
                'enabled': True,
            },
            format='json',
        )
        self.assertEqual(injected.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(WorkspaceAIProvider.objects.filter(
            workspace=self.other, provider=custom
        ).exists())

    def test_custom_ai_rejects_missing_fields_and_non_public_endpoints(self):
        self.as_(self.admin)
        cases = (
            ({}, ('display_name', 'base_url', 'model', 'integration_type', 'capabilities')),
            ({
                'display_name': 'Local AI',
                'base_url': 'http://localhost:8000/v1',
                'credentials': 'secret',
                'model': 'local',
                'integration_type': ProviderIntegrationType.OPENAI_COMPATIBLE,
                'capabilities': [Capability.TEXT],
            }, ('base_url',)),
            ({
                'display_name': 'Private AI',
                'base_url': 'https://127.0.0.1/v1',
                'credentials': 'secret',
                'model': 'private',
                'integration_type': ProviderIntegrationType.OPENAI_COMPATIBLE,
                'capabilities': [Capability.TEXT],
            }, ('base_url',)),
        )

        for payload, fields in cases:
            with self.subTest(payload=payload):
                res = self.client.post(
                    '/api/marketing/ai/providers/custom/', payload, format='json'
                )
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
                for field in fields:
                    self.assertIn(field, res.data)

    @patch('apps.ai.endpoint_security.socket.getaddrinfo')
    def test_custom_ai_rejects_a_hostname_that_resolves_to_a_private_address(self, resolve):
        resolve.return_value = [(2, 1, 6, '', ('10.0.0.12', 443))]
        self.as_(self.admin)

        res = self.client.post(
            '/api/marketing/ai/providers/custom/',
            {
                'display_name': 'Rebound AI',
                'base_url': 'https://looks-public.example.com/v1',
                'model': 'private-target',
                'integration_type': ProviderIntegrationType.OPENAI_COMPATIBLE,
                'capabilities': [Capability.TEXT],
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('base_url', res.data)
        self.assertFalse(AIProvider.objects.filter(display_name='Rebound AI').exists())

    @patch('apps.ai.endpoint_security.socket.getaddrinfo')
    def test_custom_ai_can_be_saved_without_a_key_when_endpoint_needs_none(self, resolve):
        resolve.return_value = [(2, 1, 6, '', ('93.184.216.34', 443))]
        self.as_(self.admin)

        res = self.client.post(
            '/api/marketing/ai/providers/custom/',
            {
                'display_name': 'Public endpoint AI',
                'base_url': 'https://public-ai.example.com/v1',
                'model': 'public-model',
                'integration_type': ProviderIntegrationType.OPENAI_COMPATIBLE,
                'capabilities': [Capability.TEXT],
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertFalse(res.data['data']['has_credentials'])

    @patch('apps.ai.endpoint_security.socket.getaddrinfo')
    def test_editor_cannot_onboard_a_custom_ai(self, resolve):
        resolve.return_value = [(2, 1, 6, '', ('93.184.216.34', 443))]
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/ai/providers/custom/',
            {
                'display_name': 'Forbidden AI',
                'base_url': 'https://forbidden.example.com/v1',
                'credentials': 'secret',
                'model': 'model',
                'integration_type': ProviderIntegrationType.SCALEEZY_JSON,
                'capabilities': list(Capability.values),
            },
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_duplicate_provider_configuration_returns_friendly_validation(self):
        WorkspaceAIProvider.objects.create(
            workspace=self.ws, provider=self.provider, enabled=True
        )
        self.as_(self.admin)

        res = self.client.post(
            '/api/marketing/ai/providers/',
            {'provider': str(self.provider.id), 'enabled': True},
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already configured', str(res.data['provider']))

    def test_configured_provider_identity_is_immutable(self):
        configured = WorkspaceAIProvider.objects.create(
            workspace=self.ws, provider=self.provider, enabled=True
        )
        self.as_(self.admin)

        res = self.client.patch(
            f'/api/marketing/ai/providers/{configured.id}/',
            {'provider': str(self.better_provider.id)},
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        configured.refresh_from_db()
        self.assertEqual(configured.provider, self.provider)

    def test_disabling_provider_disables_its_active_routes(self):
        configured = WorkspaceAIProvider.objects.create(
            workspace=self.ws, provider=self.provider, enabled=True
        )
        route = WorkspaceAIRoute.objects.create(
            workspace=self.ws,
            capability=Capability.TEXT,
            provider=self.provider,
            enabled=True,
        )
        self.as_(self.admin)

        res = self.client.patch(
            f'/api/marketing/ai/providers/{configured.id}/',
            {'enabled': False},
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        route.refresh_from_db()
        self.assertFalse(route.enabled)

    def test_admin_assigns_tasks_per_model_and_removed_task_clears_route(self):
        configured = WorkspaceAIProvider.objects.create(
            workspace=self.ws,
            provider=self.better_provider,
            enabled=True,
            capabilities=[Capability.TEXT, Capability.IMAGE],
        )
        route = WorkspaceAIRoute.objects.create(
            workspace=self.ws,
            capability=Capability.IMAGE,
            provider=self.better_provider,
            enabled=True,
        )
        self.as_(self.admin)

        res = self.client.patch(
            f'/api/marketing/ai/providers/{configured.id}/',
            {
                'model_override': 'chosen-text-model',
                'capabilities': [Capability.TEXT],
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        configured.refresh_from_db()
        self.assertEqual(configured.model_override, 'chosen-text-model')
        self.assertEqual(configured.capabilities, [Capability.TEXT])
        self.assertFalse(WorkspaceAIRoute.objects.filter(pk=route.pk).exists())

    def test_route_rejects_task_not_assigned_to_workspace_model(self):
        WorkspaceAIProvider.objects.create(
            workspace=self.ws,
            provider=self.better_provider,
            enabled=True,
            capabilities=[Capability.IMAGE],
        )
        self.as_(self.admin)

        res = self.client.post(
            '/api/marketing/ai/routes/replace-set/',
            {
                'capability': Capability.TEXT,
                'routes': [{'provider': str(self.better_provider.id), 'priority': 10}],
                'strategy': Strategy.FAILOVER,
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Assign this capability', str(res.data))
        self.assertFalse(WorkspaceAIRoute.objects.filter(workspace=self.ws).exists())

    def test_deleting_provider_configuration_removes_its_routes_only(self):
        configured = WorkspaceAIProvider.objects.create(
            workspace=self.ws, provider=self.provider, enabled=True
        )
        own_route = WorkspaceAIRoute.objects.create(
            workspace=self.ws,
            capability=Capability.TEXT,
            provider=self.provider,
        )
        other_route = WorkspaceAIRoute.objects.create(
            workspace=self.other,
            capability=Capability.TEXT,
            provider=self.provider,
        )
        self.as_(self.admin)

        res = self.client.delete(f'/api/marketing/ai/providers/{configured.id}/')

        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(WorkspaceAIRoute.objects.filter(pk=own_route.pk).exists())
        self.assertTrue(WorkspaceAIRoute.objects.filter(pk=other_route.pk).exists())

    def test_credentials_are_encrypted_and_never_returned(self):
        self.as_(self.admin)
        res = self.client.post(
            '/api/marketing/ai/providers/',
            {'provider': str(self.provider.id), 'enabled': True, 'credentials': 'sk-secret'},
            format='json',
        )
        self.assertNotIn('credentials', res.data)
        wp = WorkspaceAIProvider.objects.get(workspace=self.ws)
        self.assertNotIn('sk-secret', wp.credentials_encrypted)
        self.assertTrue(res.data['has_credentials'])

    def test_editor_cannot_change_providers(self):
        self.as_(self.editor)
        res = self.client.post(
            '/api/marketing/ai/providers/',
            {'provider': str(self.provider.id), 'enabled': True},
            format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_editor_cannot_read_provider_or_routing_administration(self):
        self.as_(self.editor)

        for url in (
            '/api/marketing/ai/catalogue/',
            '/api/marketing/ai/providers/',
            '/api/marketing/ai/routes/',
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_provider_config_is_workspace_scoped(self):
        WorkspaceAIProvider.objects.create(workspace=self.other, provider=self.provider)
        self.as_(self.admin)
        res = self.client.get('/api/marketing/ai/providers/')
        self.assertEqual(len(res.data), 0)

    def test_route_set_rejects_a_provider_that_cannot_serve_the_capability(self):
        WorkspaceAIProvider.objects.create(
            workspace=self.ws, provider=self.provider, enabled=True
        )
        self.as_(self.admin)

        with patch('apps.ai.views.all_adapters', return_value={'fake': FakeAdapter}):
            res = self.client.post(
                '/api/marketing/ai/routes/replace-set/',
                {
                    'capability': Capability.VIDEO,
                    'routes': [{'provider': str(self.provider.id), 'priority': 10}],
                    'strategy': Strategy.FAILOVER,
                },
                format='json',
            )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(WorkspaceAIRoute.objects.filter(workspace=self.ws).exists())

    def test_individual_route_rows_are_read_only(self):
        """Every mutation must use the validated, atomic replace-set action."""
        route = WorkspaceAIRoute.objects.create(
            workspace=self.ws,
            capability=Capability.TEXT,
            provider=self.provider,
            priority=10,
            strategy=Strategy.FAILOVER,
        )
        self.as_(self.admin)

        attempts = (
            (
                'post',
                '/api/marketing/ai/routes/',
                {
                    'capability': Capability.TEXT,
                    'provider': str(self.better_provider.id),
                    'priority': 20,
                },
            ),
            (
                'put',
                f'/api/marketing/ai/routes/{route.id}/',
                {
                    'capability': Capability.IMAGE,
                    'provider': str(self.better_provider.id),
                    'priority': 20,
                },
            ),
            (
                'patch',
                f'/api/marketing/ai/routes/{route.id}/',
                {'provider': str(self.better_provider.id)},
            ),
            ('delete', f'/api/marketing/ai/routes/{route.id}/', None),
        )

        for method, url, payload in attempts:
            with self.subTest(method=method):
                response = getattr(self.client, method)(url, payload, format='json')
                self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        route.refresh_from_db()
        self.assertEqual(
            (route.capability, route.provider, route.priority, route.strategy),
            (Capability.TEXT, self.provider, 10, Strategy.FAILOVER),
        )
        self.assertEqual(WorkspaceAIRoute.objects.filter(workspace=self.ws).count(), 1)

    def test_route_set_replace_is_atomic_when_a_provider_is_not_enabled(self):
        WorkspaceAIProvider.objects.create(
            workspace=self.ws, provider=self.provider, enabled=True
        )
        original = WorkspaceAIRoute.objects.create(
            workspace=self.ws,
            capability=Capability.TEXT,
            provider=self.provider,
            priority=10,
        )
        self.as_(self.admin)

        with patch(
            'apps.ai.views.all_adapters',
            return_value={'fake': FakeAdapter, 'better': BetterAdapter},
        ):
            res = self.client.post(
                '/api/marketing/ai/routes/replace-set/',
                {
                    'capability': Capability.TEXT,
                    'routes': [
                        {'provider': str(self.better_provider.id), 'priority': 10},
                    ],
                    'strategy': Strategy.FAILOVER,
                },
                format='json',
            )

        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(WorkspaceAIRoute.objects.filter(pk=original.pk).exists())

    def test_route_set_preserves_multiple_providers_and_their_priority(self):
        WorkspaceAIProvider.objects.create(
            workspace=self.ws, provider=self.provider, enabled=True
        )
        WorkspaceAIProvider.objects.create(
            workspace=self.ws, provider=self.better_provider, enabled=True
        )
        WorkspaceAIRoute.objects.create(
            workspace=self.ws,
            capability=Capability.TEXT,
            provider=self.provider,
            priority=10,
        )
        self.as_(self.admin)

        with patch(
            'apps.ai.views.all_adapters',
            return_value={'fake': FakeAdapter, 'better': BetterAdapter},
        ):
            res = self.client.post(
                '/api/marketing/ai/routes/replace-set/',
                {
                    'capability': Capability.TEXT,
                    'routes': [
                        {'provider': str(self.better_provider.id), 'priority': 10},
                        {'provider': str(self.provider.id), 'priority': 20},
                    ],
                    'strategy': Strategy.FAILOVER,
                },
                format='json',
            )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        routes = list(WorkspaceAIRoute.objects.filter(
            workspace=self.ws, capability=Capability.TEXT
        ).order_by('priority'))
        self.assertEqual(len(routes), 2)
        self.assertEqual(
            [(route.provider, route.priority, route.strategy) for route in routes],
            [
                (self.better_provider, 10, Strategy.FAILOVER),
                (self.provider, 20, Strategy.FAILOVER),
            ],
        )

    def test_route_set_defaults_to_round_robin_when_strategy_is_omitted(self):
        WorkspaceAIProvider.objects.create(
            workspace=self.ws, provider=self.provider, enabled=True
        )
        self.as_(self.admin)

        with patch('apps.ai.views.all_adapters', return_value={'fake': FakeAdapter}):
            response = self.client.post(
                '/api/marketing/ai/routes/replace-set/',
                {
                    'capability': Capability.TEXT,
                    'routes': [
                        {'provider': str(self.provider.id), 'priority': 10},
                    ],
                },
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            WorkspaceAIRoute.objects.get(
                workspace=self.ws,
                capability=Capability.TEXT,
            ).strategy,
            Strategy.ROUND_ROBIN,
        )

    def test_route_set_rejects_duplicates_without_changing_existing_routes(self):
        WorkspaceAIProvider.objects.create(
            workspace=self.ws, provider=self.provider, enabled=True
        )
        original = WorkspaceAIRoute.objects.create(
            workspace=self.ws,
            capability=Capability.TEXT,
            provider=self.provider,
            priority=10,
        )
        self.as_(self.admin)

        res = self.client.post(
            '/api/marketing/ai/routes/replace-set/',
            {
                'capability': Capability.TEXT,
                'routes': [
                    {'provider': str(self.provider.id), 'priority': 10},
                    {'provider': str(self.provider.id), 'priority': 20},
                ],
                'strategy': Strategy.FAILOVER,
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            list(WorkspaceAIRoute.objects.filter(workspace=self.ws)),
            [original],
        )

    def test_resolved_shows_what_the_router_would_do(self):
        self.as_(self.admin)
        res = self.client.get('/api/marketing/ai/routes/resolved/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn(Capability.TEXT, res.data['data'])

    def test_usage_summary_includes_reliability_and_latency(self):
        for success, latency in ((True, 100), (True, 200), (False, 300)):
            AIUsageLog.objects.create(
                workspace=self.ws,
                provider=self.provider,
                capability=Capability.TEXT,
                success=success,
                latency_ms=latency,
                cost='0.0100',
            )
        self.as_(self.admin)

        res = self.client.get('/api/marketing/ai/usage/summary/')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        row = res.data['data'][0]
        self.assertEqual(row['calls'], 3)
        self.assertEqual(row['successful_calls'], 2)
        self.assertEqual(row['failed_calls'], 1)
        self.assertEqual(row['average_latency_ms'], 200.0)
        self.assertEqual(row['success_rate_percent'], 66.67)
