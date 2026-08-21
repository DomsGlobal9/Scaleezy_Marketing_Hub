"""
Provider adapter contract.

Mirrors SocialPlatformAdapter, which is the pattern already proven in this
codebase for pluggable third parties. Adding a provider means writing one
subclass and registering it — the router never changes.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable


class AIProviderError(Exception):
    """Provider failed in a way the router should treat as unavailable."""


class AIProviderAdapter(ABC):
    #: Must match AIProvider.key in the catalogue.
    key: str = ''
    display_name: str = ''
    #: Capability values this adapter implements.
    capabilities: Iterable[str] = ()
    default_model: str = ''
    #: Indicative cost per generation, used for BEST_OF scoring.
    unit_cost: float = 0.0
    #: True for adapters whose TEXT result already carries the poster URL in
    #: its raw payload (one upstream call answers both). A capability trait,
    #: not a provider name: callers may use it to skip a redundant IMAGE
    #: dispatch when the same provider serves both capabilities.
    yields_poster_with_text: bool = False

    def __init__(self, *, credentials: str = '', model: str = '', config: Dict[str, Any] = None):
        self.credentials = credentials
        self.model = model or self.default_model
        self.config = config or {}

    # Each adapter implements only the capabilities it declares. The default
    # raises so a misconfigured route fails loudly rather than silently
    # returning nothing.
    def generate_text(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        raise AIProviderError(f"{self.key} does not support text generation.")

    def generate_image(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        raise AIProviderError(f"{self.key} does not support image generation.")

    def analyze_image(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        raise AIProviderError(f"{self.key} does not support image analysis.")

    def generate_video(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        raise AIProviderError(f"{self.key} does not support video generation.")

    def generate_embedding(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        raise AIProviderError(f"{self.key} does not support embeddings.")

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """{'ok': bool, 'detail': str}. Must never raise."""

    def estimate_cost(self, capability: str) -> float:
        return float(self.unit_cost)

    def score(self, result: Dict[str, Any], duration_s: float) -> float:
        """
        Quality x cost x speed, for BEST_OF. Adapters that can judge their own
        output should override and set result['quality_score'].
        """
        quality = float(result.get('quality_score', 0.8))
        cost = max(0.0, 1.0 - (float(self.unit_cost) / 0.10))
        speed = max(0.0, 1.0 - (duration_s / 30.0))
        return quality * 0.5 + cost * 0.3 + speed * 0.2

    def run(self, capability: str, brief: Dict[str, Any]) -> Dict[str, Any]:
        from apps.ai.models import Capability

        return {
            Capability.TEXT: self.generate_text,
            Capability.IMAGE: self.generate_image,
            Capability.IMAGE_ANALYSIS: self.analyze_image,
            Capability.VIDEO: self.generate_video,
            Capability.EMBEDDING: self.generate_embedding,
        }[capability](brief)
