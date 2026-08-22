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


def build(workspace_provider) -> AIProviderAdapter | None:
    """Instantiates the adapter for a WorkspaceAIProvider row."""
    from apps.social_accounts.utils.encryption import decrypt_token

    cls = get_adapter_class(workspace_provider.provider.key)
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

    return cls(
        credentials=credentials,
        model=workspace_provider.model_override or workspace_provider.provider.default_model,
        config=workspace_provider.config or {},
    )
