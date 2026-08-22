"""Idempotent platform-managed AI setup for newly created workspaces.

This is the application service counterpart of ``configure_ai_routing``. The
management command remains useful for existing tenants and operator repair;
new clients must not need that operator step before their first generation.
"""

from django.core.exceptions import ImproperlyConfigured

from .models import AIProvider, Capability, Strategy, WorkspaceAIProvider, WorkspaceAIRoute
from .registry import all_adapters


REQUIRED_CAPABILITIES = (Capability.TEXT, Capability.IMAGE)


class AIProvisioningError(ImproperlyConfigured):
    """The platform catalogue cannot satisfy the default tenant policy."""


def _provider_supports(provider, adapter_class, capabilities):
    declared = {str(capability) for capability in (adapter_class.capabilities or ())}
    return all(
        provider.supports(capability) and capability in declared
        for capability in capabilities
    )


def resolve_default_provider(*, capabilities=REQUIRED_CAPABILITIES):
    """Select a provider whose catalogue row and installed adapter agree."""
    installed = all_adapters()
    candidates = [
        provider
        for provider in AIProvider.objects.filter(is_available=True).order_by('unit_cost', 'key')
        if provider.key in installed
        and _provider_supports(provider, installed[provider.key], capabilities)
    ]
    return candidates[0] if candidates else None


def provision_default_ai(workspace, *, capabilities=REQUIRED_CAPABILITIES):
    """Ensure the minimum provider and routes needed by Create.

    The provider is selected only by availability, installed adapter contract,
    declared capability and policy ordering. No caller or product workflow
    names a vendor. Platform-managed credentials remain outside tenant-visible
    records; a workspace credential can override them through the adapter.
    """
    provider = resolve_default_provider(capabilities=capabilities)
    if provider is None:
        raise AIProvisioningError(
            "No installed, available platform AI provider serves the required "
            f"capabilities: {', '.join(capabilities)}."
        )

    workspace_provider, _ = WorkspaceAIProvider.objects.get_or_create(
        workspace=workspace,
        provider=provider,
        defaults={'enabled': True},
    )
    if not workspace_provider.enabled:
        workspace_provider.enabled = True
        workspace_provider.save(update_fields=['enabled', 'updated_at'])

    routes = []
    for capability in capabilities:
        route, _ = WorkspaceAIRoute.objects.get_or_create(
            workspace=workspace,
            capability=capability,
            provider=provider,
            defaults={
                'priority': 100,
                'enabled': True,
                'strategy': Strategy.FAILOVER,
            },
        )
        if not route.enabled:
            route.enabled = True
            route.save(update_fields=['enabled'])
        routes.append(route)

    return workspace_provider, routes
