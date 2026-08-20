"""
Layout plugin registry.

Discovers every LayoutPattern under `patterns/`. Dropping a new file there is
the whole installation step — same contract as apps/ai/registry.py.
"""
import importlib
import logging
import pkgutil
from typing import Dict, Type

from .patterns.base import LayoutPattern

logger = logging.getLogger(__name__)

_registry: Dict[str, Type[LayoutPattern]] = {}
_loaded = False

#: Used when a brand names a layout that is not installed.
DEFAULT_KEY = 'agency_column'


def _discover():
    global _loaded
    if _loaded:
        return

    from . import patterns

    for module in pkgutil.iter_modules(patterns.__path__):
        if module.name == 'base':
            continue
        try:
            importlib.import_module(f'{patterns.__name__}.{module.name}')
        except Exception:
            logger.exception("Could not import layout pattern module %s", module.name)

    for cls in LayoutPattern.__subclasses__():
        if cls.key:
            _registry[cls.key] = cls
    _loaded = True
    logger.debug("Layout patterns registered: %s", sorted(_registry))


def get(key: str):
    """The pattern class for a key, or None."""
    _discover()
    return _registry.get(key)


def resolve(key: str):
    """
    The pattern for a key, falling back to the default.

    Never returns None: a brand whose layout was removed in a deploy should
    still get a poster, not a 500.
    """
    _discover()
    pattern = _registry.get(key) or _registry.get(DEFAULT_KEY)
    if pattern is None and _registry:
        pattern = sorted(_registry.items())[0][1]
    return pattern


def catalogue():
    _discover()
    return [cls.describe() for _, cls in sorted(_registry.items())]


def keys():
    _discover()
    return sorted(_registry)
