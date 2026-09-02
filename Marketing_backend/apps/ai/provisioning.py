"""
Default AI routing for a workspace.

A workspace with no route gets a 503 from every Create, because
`AIRouter._candidates()` has nothing to select. Until now the only cure was an
operator running `manage.py configure_ai_routing`, which means every new tenant
was born broken and stayed broken until a developer noticed. So the same
provisioning now runs on workspace creation — and lives here, once, with the
management command calling into it rather than keeping a second copy of the
rules. Two writers drift; the one that runs less often drifts further.

NO CREDENTIAL IS STORED BY DEFAULT.
`registry.build()` constructs an adapter whether or not a workspace credential
exists, and the adapter falls back to the server's own key. Leaving the column
empty is the safer configuration: the secret stays in the platform's secret
store instead of being copied into one database row per tenant, and rotating it
is one operation rather than N.

The provider is resolved from the registry and the catalogue together, not from
a hardcoded key. An adapter with no catalogue row cannot be routed, and a
catalogue row with no adapter produces a route that `build()` silently drops —
which looks configured and behaves like a 503.
"""
import logging

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from .models import AIProvider, Capability, Strategy, WorkspaceAIProvider, WorkspaceAIRoute
from .registry import all_adapters

logger = logging.getLogger(__name__)

#: The capabilities a workspace needs routed before Create works end to end.
#: TEXT alone produces copy with no poster; the generation accelerator asks for
#: both and keeps whichever succeeds.
REQUIRED_CAPABILITIES = (Capability.TEXT, Capability.IMAGE)

DEFAULT_PRIORITY = 100
DEFAULT_STRATEGY = Strategy.ROUND_ROBIN


class AIProvisioningError(ImproperlyConfigured):
    """The platform catalogue cannot satisfy the default tenant policy."""


def provider_serves(provider, adapter_class, capabilities) -> bool:
    """Both the catalogue and the code have to agree.

    Believing the catalogue alone is how a capability gets routed to an adapter
    that cannot serve it; believing the adapter alone ignores the operator's
    per-capability approval.
    """
    declared = {str(c) for c in (getattr(adapter_class, 'capabilities', ()) or ())}
    return all(
        provider.supports(capability) and capability in declared
        for capability in capabilities
    )


def eligible_providers(capabilities=REQUIRED_CAPABILITIES):
    """Catalogue rows that are switched on, installed, and genuinely capable.

    Ordered cheapest first with the key as a stable tie-break, so two identical
    databases resolve the same provider.
    """
    installed = all_adapters()
    return [
        provider
        for provider in AIProvider.objects.filter(is_available=True).order_by('unit_cost', 'key')
        if provider.key in installed
        and provider_serves(provider, installed[provider.key], capabilities)
    ]


def resolve_default_provider(capabilities=REQUIRED_CAPABILITIES):
    """The provider a workspace should be routed to, or None if none qualifies."""
    candidates = eligible_providers(capabilities)
    return candidates[0] if candidates else None


def resolve_default_providers(capabilities=REQUIRED_CAPABILITIES):
    """Resolve the cheapest eligible provider independently per capability.

    Requiring one vendor to implement the entire product capability set makes
    a deliberately composable router behave like a single-provider system.
    The returned mapping preserves the requested capability order.
    """
    resolved = {}
    for capability in capabilities:
        candidates = eligible_providers((capability,))
        resolved[capability] = candidates[0] if candidates else None
    return resolved


def provision_ai_routing(
    workspace,
    provider,
    *,
    capabilities=REQUIRED_CAPABILITIES,
    priority=DEFAULT_PRIORITY,
    credential=None,
    apply=True,
):
    """The single writer. Returns the list of changes, described in English.

    Idempotent by construction: every write is conditional on the row being
    absent or switched off, so a second run reports nothing and touches
    nothing. `apply=False` produces the same list without writing, which is
    what the management command's dry run reports.

    Scoped to one workspace on every query — provisioning that fanned out
    across tenants would be the worst possible place for a missing filter.
    """
    changes = []
    label = f'{workspace.workspace_name} ({workspace.pk})'

    with transaction.atomic():
        workspace_provider = WorkspaceAIProvider.objects.filter(
            workspace=workspace, provider=provider
        ).first()

        if workspace_provider is None:
            changes.append(f'{label}: create WorkspaceAIProvider (enabled)')
            if apply:
                workspace_provider = WorkspaceAIProvider.objects.create(
                    workspace=workspace, provider=provider, enabled=True,
                )
        elif not workspace_provider.enabled:
            changes.append(f'{label}: enable existing WorkspaceAIProvider')
            if apply:
                workspace_provider.enabled = True
                workspace_provider.save(update_fields=['enabled', 'updated_at'])

        if credential and workspace_provider is not None:
            # Encrypted with the same helper that protects the OAuth tokens.
            # Only the fact of a credential is ever reported, never its value.
            from apps.social_accounts.utils.encryption import encrypt_token

            changes.append(f'{label}: store workspace credential (encrypted)')
            if apply:
                workspace_provider.credentials_encrypted = encrypt_token(credential)
                workspace_provider.save(
                    update_fields=['credentials_encrypted', 'updated_at']
                )

        for capability in capabilities:
            route = WorkspaceAIRoute.objects.filter(
                workspace=workspace, capability=capability, provider=provider
            ).first()
            if route is None:
                changes.append(f'{label}: route {capability} -> {provider.key}')
                if apply:
                    WorkspaceAIRoute.objects.create(
                        workspace=workspace, capability=capability, provider=provider,
                        priority=priority, enabled=True, strategy=DEFAULT_STRATEGY,
                    )
            elif not route.enabled:
                changes.append(f'{label}: re-enable {capability} route')
                if apply:
                    route.enabled = True
                    route.save(update_fields=['enabled'])

    return changes


def provision_default_ai(workspace, *, capabilities=REQUIRED_CAPABILITIES):
    """Atomically make a new client ready for capability-based generation.

    Selection is based only on the enabled catalogue, installed adapter
    contract, supported capabilities and stable policy ordering. Product code
    never names a vendor. Unlike the repair helper below, this strict bootstrap
    raises when the platform cannot provide a usable route so the surrounding
    client-creation transaction can roll back instead of returning fake
    readiness.
    """
    resolved = resolve_default_providers(capabilities)
    missing = [capability for capability, provider in resolved.items() if provider is None]
    if missing:
        raise AIProvisioningError(
            "No installed, available platform AI provider serves the required "
            f"capabilities: {', '.join(str(capability) for capability in missing)}."
        )

    try:
        capabilities_by_provider = {}
        for capability, provider in resolved.items():
            capabilities_by_provider.setdefault(provider, []).append(capability)

        # One outer transaction keeps a split-provider bootstrap just as
        # atomic as the previous single-provider path.
        with transaction.atomic():
            for provider, provider_capabilities in capabilities_by_provider.items():
                provision_ai_routing(
                    workspace,
                    provider,
                    capabilities=provider_capabilities,
                )
    except Exception as exc:
        raise AIProvisioningError("Default AI routing could not be provisioned.") from exc

    workspace_providers = list(WorkspaceAIProvider.objects.filter(
        workspace=workspace,
        provider__in=capabilities_by_provider,
    ).select_related('provider').order_by('provider__key'))
    routes = list(
        WorkspaceAIRoute.objects.filter(
            workspace=workspace,
            capability__in=capabilities,
            enabled=True,
        ).order_by('priority', 'id')
    )
    return workspace_providers, routes


def ensure_default_ai_routing(workspace, *, capabilities=REQUIRED_CAPABILITIES):
    """Repair a workspace's missing default route. Never raises.

    This is the best-effort repair path used by operators and migrations. New
    client creation uses strict ``provision_default_ai`` instead, so it can
    roll the complete bootstrap back rather than claim that a client is ready
    without the routes Create requires. The atomic block inside
    ``provision_ai_routing`` keeps a repair failure scoped to its routing rows.

    Returns True when routing is in place afterwards.
    """
    try:
        resolved = resolve_default_providers(capabilities)
        missing = [capability for capability, provider in resolved.items() if provider is None]
        if missing:
            logger.warning(
                "No installed, available AI provider serves %s; workspace %s has no "
                "default routing and will 503 until one is configured.",
                ', '.join(str(c) for c in missing), workspace.pk,
            )
            return False

        capabilities_by_provider = {}
        for capability, provider in resolved.items():
            capabilities_by_provider.setdefault(provider, []).append(capability)

        changes = []
        with transaction.atomic():
            for provider, provider_capabilities in capabilities_by_provider.items():
                changes.extend(provision_ai_routing(
                    workspace,
                    provider,
                    capabilities=provider_capabilities,
                ))
        if changes:
            logger.info(
                "Default AI routing provisioned for workspace %s across %d provider(s) "
                "(%d change(s))",
                workspace.pk, len(capabilities_by_provider), len(changes),
            )
        return True
    except Exception:
        logger.exception(
            "Could not provision default AI routing for workspace %s",
            getattr(workspace, 'pk', None),
        )
        return False
