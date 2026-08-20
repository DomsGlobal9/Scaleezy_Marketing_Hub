"""
Capability router.

Callers ask for a capability — never a provider. The router resolves which
providers the workspace has routed to that capability, applies the configured
strategy, and records every call.
"""
import logging
import time
from typing import Any, Dict, List

from django.utils import timezone

from .adapters.base import AIProviderError
from .models import AIUsageLog, Strategy, WorkspaceAIProvider, WorkspaceAIRoute
from .registry import build

logger = logging.getLogger(__name__)


class NoProviderAvailable(Exception):
    """No enabled, credentialed provider is routed to this capability."""


class AIRouter:
    def __init__(self, workspace):
        self.workspace = workspace

    # ── resolution ───────────────────────────────────────────────────────
    def _candidates(self, capability: str) -> List[Dict[str, Any]]:
        routes = (
            WorkspaceAIRoute.objects.select_related('provider')
            .filter(workspace=self.workspace, capability=capability, enabled=True)
            .order_by('priority')
        )
        enabled = {
            wp.provider_id: wp
            for wp in WorkspaceAIProvider.objects.select_related('provider').filter(
                workspace=self.workspace, enabled=True
            )
        }

        out = []
        for route in routes:
            wp = enabled.get(route.provider_id)
            if wp is None:
                continue  # routed but the provider is switched off
            if not route.provider.is_available:
                continue  # operator kill switch
            if not route.provider.supports(capability):
                continue
            adapter = build(wp)
            if adapter is None:
                continue
            out.append({'route': route, 'workspace_provider': wp, 'adapter': adapter})
        return out

    def strategy_for(self, capability: str) -> str:
        route = (
            WorkspaceAIRoute.objects.filter(
                workspace=self.workspace, capability=capability, enabled=True
            )
            .order_by('priority')
            .first()
        )
        return route.strategy if route else Strategy.FAILOVER

    # ── execution ────────────────────────────────────────────────────────
    def _run_one(self, candidate, capability, brief, strategy, content_item_id, selected=True):
        adapter = candidate['adapter']
        started = time.monotonic()
        try:
            result = adapter.run(capability, brief)
            duration = time.monotonic() - started
            log = self._log(candidate, capability, strategy, duration, True, '',
                            content_item_id, selected)
            return {'result': result, 'duration': duration, 'candidate': candidate, 'log': log}
        except Exception as exc:
            duration = time.monotonic() - started
            self._log(candidate, capability, strategy, duration, False, str(exc)[:500],
                      content_item_id, False)
            raise

    def _log(self, candidate, capability, strategy, duration, ok, error,
             content_item_id, selected):
        try:
            return AIUsageLog.objects.create(
                workspace=self.workspace,
                provider=candidate['route'].provider,
                capability=capability,
                content_item_id=content_item_id,
                cost=candidate['adapter'].estimate_cost(capability),
                latency_ms=int(duration * 1000),
                success=ok,
                error=error,
                strategy=strategy,
                selected=selected,
            )
        except Exception:
            logger.exception("Could not write AI usage log")
            return None

    def dispatch(self, capability: str, brief: Dict[str, Any],
                 content_item_id=None) -> Dict[str, Any]:
        # Spend is checked before the call, not after: an over-cap workspace
        # that only finds out from AIUsageLog has already been billed for the
        # generation that took it over.
        from apps.billing.quota import enforce

        enforce(self.workspace)

        candidates = self._candidates(capability)
        if not candidates:
            raise NoProviderAvailable(
                f"No AI provider is enabled for {capability} in this workspace."
            )

        strategy = self.strategy_for(capability)

        if strategy == Strategy.BEST_OF and len(candidates) > 1:
            return self._best_of(candidates, capability, brief, content_item_id)
        if strategy == Strategy.ROUND_ROBIN and len(candidates) > 1:
            candidates = self._rotate(candidates, capability)

        # FAILOVER: first one that works wins.
        errors = []
        for candidate in candidates:
            try:
                outcome = self._run_one(
                    candidate, capability, brief, strategy, content_item_id
                )
                return self._shape(outcome, strategy)
            except Exception as exc:
                errors.append(f"{candidate['route'].provider.key}: {exc}")
                continue

        raise NoProviderAvailable(
            f"Every provider for {capability} failed. " + " | ".join(errors[:3])
        )

    def _best_of(self, candidates, capability, brief, content_item_id):
        """
        Run every routed provider and keep the best result.

        Costs N times a normal generation, which is why it is opt-in per
        capability rather than a default.
        """
        outcomes = []
        for candidate in candidates:
            try:
                outcomes.append(
                    self._run_one(
                        candidate, capability, brief, Strategy.BEST_OF,
                        content_item_id, selected=False,
                    )
                )
            except Exception:
                continue

        if not outcomes:
            raise NoProviderAvailable(f"Every provider for {capability} failed.")

        best = max(
            outcomes,
            key=lambda o: o['candidate']['adapter'].score(o['result'], o['duration']),
        )
        # Mark the winner, so cost reporting can tell the kept result from the
        # ones that were paid for and discarded.
        if best.get('log'):
            AIUsageLog.objects.filter(id=best['log'].id).update(selected=True)

        return self._shape(best, Strategy.BEST_OF, considered=len(outcomes))

    def _rotate(self, candidates, capability):
        """Start from the provider used least recently for this capability."""
        last = (
            AIUsageLog.objects.filter(workspace=self.workspace, capability=capability)
            .order_by('-created_at')
            .values_list('provider_id', flat=True)
            .first()
        )
        if last is None:
            return candidates
        for i, c in enumerate(candidates):
            if c['route'].provider_id == last:
                return candidates[i + 1:] + candidates[: i + 1]
        return candidates

    @staticmethod
    def _shape(outcome, strategy, considered=1):
        provider = outcome['candidate']['route'].provider
        return {
            **outcome['result'],
            'provider': provider.key,
            'provider_name': provider.display_name,
            'strategy': strategy,
            'considered': considered,
            'latency_ms': int(outcome['duration'] * 1000),
        }

    # ── diagnostics ──────────────────────────────────────────────────────
    def health(self, workspace_provider) -> Dict[str, Any]:
        adapter = build(workspace_provider)
        if adapter is None:
            result = {'ok': False, 'detail': 'No adapter installed for this provider.'}
        else:
            try:
                result = adapter.health_check()
            except Exception as exc:
                result = {'ok': False, 'detail': str(exc)[:300]}

        workspace_provider.last_health_check_at = timezone.now()
        workspace_provider.last_health_ok = bool(result.get('ok'))
        workspace_provider.last_error = '' if result.get('ok') else str(result.get('detail', ''))
        workspace_provider.save(
            update_fields=['last_health_check_at', 'last_health_ok', 'last_error', 'updated_at']
        )
        return result
