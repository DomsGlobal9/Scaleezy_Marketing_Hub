"""
Adapter registry.

Discovers every AIProviderAdapter subclass under apps/ai/adapters/. Dropping a
new file there is the whole installation step — no imports to update, no
router changes.
"""
import importlib
import logging
import pkgutil
from typing import Dict, Type

from .adapters.base import AIProviderAdapter

logger = logging.getLogger(__name__)

_registry: Dict[str, Type[AIProviderAdapter]] = {}
_loaded = False


def _adapter_subclasses(base=AIProviderAdapter):
    """Yield every adapter subclass, including shared-driver descendants.

    Provider integrations commonly share a protocol implementation (for
    example, several OpenAI-compatible services). ``__subclasses__()`` only
    returns the immediate children, which made those perfectly valid nested
    adapters invisible to discovery.
    """
    seen = set()

    def walk(parent):
        for child in parent.__subclasses__():
            if child in seen:
                continue
            seen.add(child)
            yield child
            yield from walk(child)

    yield from walk(base)


def _discover():
    global _loaded
    if _loaded:
        return

    from . import adapters

    for module in pkgutil.iter_modules(adapters.__path__):
        if module.name == 'base':
            continue
        try:
            importlib.import_module(f'{adapters.__name__}.{module.name}')
        except Exception:
            logger.exception("Could not import AI adapter module %s", module.name)

    for cls in _adapter_subclasses():
        if cls.key:
            _registry[cls.key] = cls
    _loaded = True
    logger.debug("AI adapters registered: %s", sorted(_registry))


def get_adapter_class(key: str):
    _discover()
    return _registry.get(key)


def all_adapters() -> Dict[str, Type[AIProviderAdapter]]:
    _discover()
    return dict(_registry)


def adapter_class_for_provider(provider):
    """Return the executable protocol class for a catalogue provider row."""
    from .models import ProviderIntegrationType

    if provider.integration_type == ProviderIntegrationType.OPENAI_COMPATIBLE:
        from .adapters.openai_compatible import CustomOpenAICompatibleAdapter

        return CustomOpenAICompatibleAdapter
    if provider.integration_type == ProviderIntegrationType.SCALEEZY_JSON:
        from .adapters.openai_compatible import ScaleezyJSONAdapter

        return ScaleezyJSONAdapter
    return get_adapter_class(provider.key)


def build(workspace_provider, *, model=None) -> AIProviderAdapter | None:
    """Instantiates the adapter for a WorkspaceAIProvider row, optionally overriding the model."""
    from apps.social_accounts.utils.encryption import decrypt_token

    cls = adapter_class_for_provider(workspace_provider.provider)
    if cls is None:
        logger.warning("No adapter installed for %s", workspace_provider.provider.key)
        return None

    credentials = ''
    if workspace_provider.credentials_encrypted:
        try:
            credentials = decrypt_token(workspace_provider.credentials_encrypted)
        except Exception:
            logger.exception(
                "Could not decrypt credentials for %s", workspace_provider.provider.key
            )

    chosen_model = model or workspace_provider.model_override or workspace_provider.provider.default_model
    adapter = cls(
        credentials=credentials,
        model=chosen_model,
        config=workspace_provider.config or {},
    )
    if workspace_provider.provider.is_custom:
        adapter.base_url = workspace_provider.provider.base_url
        adapter.display_name = workspace_provider.provider.display_name
        adapter.capabilities = tuple(workspace_provider.provider.capabilities or ())
        adapter.enforce_public_endpoint = True
        adapter.allow_anonymous = True
        adapter.unit_cost = float(workspace_provider.provider.unit_cost)
    return adapter
