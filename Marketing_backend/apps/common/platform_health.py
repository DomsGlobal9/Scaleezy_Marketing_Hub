"""
Platform health signals, each of which knows whether it is real.

The trap this module exists to avoid: a console tile that reads "0 knowledge
failures" when nothing in the codebase has ever processed a knowledge source.
That is not a healthy platform, it is a disconnected sensor rendered as good
news — the most dangerous number an operations console can show, because it
is indistinguishable from the number you want to see.

So every signal carries `live`. A signal is live when some code path can
actually produce the state it counts. When it cannot, the value is None and
`reason` says what is missing, and the console must render "not monitored"
rather than a zero.

`live` is a fact about the codebase, not a runtime probe, so it is stated
here next to each signal. When a writer lands, its health signal must start
counting the durable state in the same delivery.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.db.models import F
from django.utils import timezone

#: A worker that has not claimed anything for this long is presumed dead.
#: Long enough not to trip on an idle queue with `run_tasks --interval 5`,
#: short enough that a scheduled post is not hours late before anyone notices.
WORKER_SILENCE_ALERT = timedelta(minutes=30)

#: How long a client may do nothing before the portfolio calls it inactive.
DEFAULT_INACTIVE_DAYS = 14


@dataclass(frozen=True)
class Signal:
    """One number on the operations console, and whether it means anything."""

    key: str
    label: str
    value: Optional[int]
    live: bool
    #: Why this signal is not live. Empty when it is.
    reason: str = ''
    #: True when a non-zero value needs somebody to do something.
    actionable: bool = True

    def as_dict(self):
        return {
            'key': self.key,
            'label': self.label,
            'value': self.value,
            'live': self.live,
            'reason': self.reason,
            'actionable': self.actionable,
            # What the UI should print. Never "0" for a dead sensor.
            'display': (str(self.value) if self.live else 'Not monitored'),
        }


def platform_signals(*, inactive_days=DEFAULT_INACTIVE_DAYS):
    """Every operations signal, live ones counted, dead ones declared.

    One function so the console, the API and any future alerting agree on
    both the numbers and on which numbers exist.
    """
    from apps.ai.models import WorkspaceAIRoute
    from apps.brands.models import Brand
    from apps.inspirations.models import BrandInspiration
    from apps.jobs.models import TaskRun
    from apps.knowledge.models import BrandSource
    from apps.publishing.models import PublishingJob
    from apps.social_accounts.models import SocialConnection
    from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

    now = timezone.now()
    active_workspaces = MarketingWorkspace.objects.filter(
        status=MarketingWorkspace.Status.ACTIVE
    )

    signals = [
        Signal(
            key='pending_approvals',
            label='Clients awaiting approval',
            value=Brand.objects.filter(status=Brand.Status.PENDING).count(),
            live=True,
        ),
        Signal(
            key='failed_publishing_jobs',
            label='Failed publishing jobs',
            value=PublishingJob.objects.filter(
                status=PublishingJob.Status.FAILED,
                workspace__in=active_workspaces,
            ).count(),
            live=True,
        ),
        Signal(
            key='brain_compile_failures',
            label='Brand Brains failing to compile',
            # Real from the moment `rebuild_brand_brain_safely` records a
            # failure; before that column existed this could not be asked.
            value=Brand.objects.filter(
                status=Brand.Status.ACTIVE,
                brain_failed_at__isnull=False,
            ).exclude(brain_compiled_at__gt=F('brain_failed_at')).count(),
            live=True,
        ),
        Signal(
            key='knowledge_failed',
            label='Knowledge sources failed',
            value=BrandSource.objects.filter(
                workspace__in=active_workspaces,
                status=BrandSource.SourceStatus.FAILED,
            ).count(),
            live=True,
        ),
        Signal(
            key='knowledge_needs_review',
            label='Knowledge needs review',
            value=BrandSource.objects.filter(
                workspace__in=active_workspaces,
                status=BrandSource.SourceStatus.NEEDS_REVIEW,
            ).count(),
            live=True,
        ),
        Signal(
            key='inspiration_analysis_failed',
            label='Inspiration analysis failed',
            value=BrandInspiration.objects.eligible_for_retrieval().filter(
                workspace__in=active_workspaces,
                analysis_status=BrandInspiration.AnalysisStatus.FAILED,
            ).count(),
            live=True,
        ),
        Signal(
            key='workspaces_without_ai_routing',
            label='Clients with no AI routing',
            value=active_workspaces.exclude(
                id__in=WorkspaceAIRoute.objects.filter(enabled=True)
                .values('workspace_id')
            ).count(),
            live=True,
        ),
        Signal(
            key='social_connections_needing_attention',
            label='Social connections needing attention',
            value=SocialConnection.objects.filter(
                workspace__in=active_workspaces,
                status__in=[
                    SocialConnection.Status.TOKEN_EXPIRED,
                    SocialConnection.Status.REAUTHORIZATION_REQUIRED,
                    SocialConnection.Status.PERMISSION_MISSING,
                    SocialConnection.Status.REVOKED,
                ],
            ).count(),
            live=True,
        ),
        Signal(
            key='inactive_clients',
            label=f'Clients inactive {inactive_days}+ days',
            # Real now that `last_active_at` has a writer
            # (apps/common/permissions.py::touch_last_active). Before that it
            # was null for every member and this counted the whole platform.
            value=active_workspaces.exclude(
                id__in=WorkspaceMember.objects.filter(
                    status=WorkspaceMember.Status.ACTIVE,
                    last_active_at__gte=now - timedelta(days=inactive_days),
                ).values('workspace_id')
            ).count(),
            live=True,
        ),
        Signal(
            key='stale_worker',
            label='Background worker silent',
            # 1 or 0, not a count: either the queue is moving or it is not.
            value=int(
                TaskRun.objects.filter(
                    status='READY', enqueued_at__lt=now - WORKER_SILENCE_ALERT
                ).exists()
            ),
            live=True,
        ),
    ]

    return signals



def platform_health(*, inactive_days=DEFAULT_INACTIVE_DAYS):
    """The console payload: every signal, plus what genuinely needs attention.

    `needs_attention` counts only LIVE signals with a non-zero value — a dead
    sensor is never evidence that anything is fine, and never evidence that
    anything is wrong either.
    """
    signals = platform_signals(inactive_days=inactive_days)
    return {
        'signals': [signal.as_dict() for signal in signals],
        'needs_attention': sum(
            1 for s in signals if s.live and s.actionable and (s.value or 0) > 0
        ),
        'unmonitored': [s.key for s in signals if not s.live],
        'generated_at': timezone.now().isoformat(),
    }
