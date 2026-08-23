import uuid

from django.db import models
from django.utils import timezone

from apps.workspaces.models import MarketingWorkspace


class Plan(models.Model):
    """
    A global catalogue of what a workspace may consume in a billing period.

    A row, not a constant: changing a customer's allowance should never need a
    deploy — the same reasoning as the AI provider catalogue and the feedback
    vocabulary.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)

    #: Generations per period. 0 means unlimited, which is what the internal
    #: plan uses — not "none allowed".
    monthly_generations = models.PositiveIntegerField(
        default=100, help_text="Generations per period. 0 = unlimited."
    )
    #: Per-capability ceilings, keyed by apps.ai.models.Capability, e.g.
    #: {"IMAGE": 100, "VIDEO": 10, "TEXT": 500}. A capability that is absent,
    #: null or 0 is unlimited — so an existing plan with {} behaves exactly as
    #: it did before this column existed. Separate from monthly_generations,
    #: which stays as the overall ceiling; whichever binds first wins.
    #: A dict rather than columns because the capability list is a row in the
    #: AI catalogue, not a constant — adding VIDEO_ANALYSIS must not need a
    #: migration.
    capability_limits = models.JSONField(
        default=dict, blank=True,
        help_text='Per-capability ceilings, e.g. {"IMAGE": 100, "VIDEO": 10}. '
                  'Absent or 0 = unlimited.',
    )
    #: Spend ceiling across every AI provider, summed from AIUsageLog.
    monthly_spend_cap = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Spend ceiling per period. 0 = uncapped.",
    )
    max_scheduled_jobs = models.PositiveIntegerField(
        default=0, help_text="Concurrently scheduled publishing jobs. 0 = unlimited."
    )

    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_default = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'billing_plans'
        ordering = ['position', 'price']

    def __str__(self):
        return self.name


class Subscription(models.Model):
    """
    What a workspace is currently entitled to.

    Usage is deliberately *not* stored here. It is counted from the records
    that already exist — AIUsageLog for spend, ContentItem for generations —
    so a counter can never drift away from what actually happened.
    """

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        PAST_DUE = 'PAST_DUE', 'Past due'
        CANCELLED = 'CANCELLED', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        MarketingWorkspace, on_delete=models.CASCADE, related_name='subscription'
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    period_start = models.DateTimeField(default=timezone.now)
    period_end = models.DateTimeField(null=True, blank=True)

    #: Per-workspace overrides, for the customer who negotiated something.
    #: Null means "use the plan".
    generations_override = models.PositiveIntegerField(null=True, blank=True)
    spend_cap_override = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    #: Per-capability overrides for THIS client, same shape as
    #: Plan.capability_limits. This is the dial Super Admin turns to say
    #: "client A gets 100 posters, client B gets 50 videos" without inventing
    #: a plan per customer. A key present here wins over the plan; a key
    #: absent falls through to it.
    capability_limit_overrides = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_subscriptions'

    def __str__(self):
        return f"{self.workspace.workspace_name} on {self.plan.name}"

    # -- limits ----------------------------------------------------------
    @property
    def generation_limit(self) -> int:
        if self.generations_override is not None:
            return self.generations_override
        return self.plan.monthly_generations

    @property
    def spend_cap(self):
        if self.spend_cap_override is not None:
            return self.spend_cap_override
        return self.plan.monthly_spend_cap

    def limit_for(self, capability) -> int:
        """This client's ceiling for one capability. 0 = unlimited.

        Override first, then the plan. A malformed value counts as unlimited
        rather than as zero: a typo in a JSON field must not silently lock a
        paying customer out of the product.
        """
        for source in (self.capability_limit_overrides, self.plan.capability_limits):
            if not isinstance(source, dict):
                continue
            if capability in source:
                try:
                    return max(0, int(source[capability] or 0))
                except (TypeError, ValueError):
                    return 0
        return 0

    def all_capability_limits(self) -> dict:
        """Plan limits with this client's overrides applied, for display."""
        merged = {}
        for source in (self.plan.capability_limits, self.capability_limit_overrides):
            if isinstance(source, dict):
                for key, value in source.items():
                    try:
                        merged[str(key)] = max(0, int(value or 0))
                    except (TypeError, ValueError):
                        merged[str(key)] = 0
        return merged

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    def current_period(self):
        """
        (start, end) of the period usage is counted over.

        A subscription whose period has lapsed rolls forward rather than
        blocking the customer: billing is not this system's job, and a stale
        `period_end` must not silently become a hard stop.
        """
        start = self.period_start or self.created_at or timezone.now()
        end = self.period_end
        now = timezone.now()

        if end is None or end <= now:
            # Roll to a period containing now, keeping the original day.
            start = self._roll(start, now)
            end = self._add_month(start)
        return start, end

    @staticmethod
    def _add_month(moment):
        year = moment.year + (moment.month // 12)
        month = moment.month % 12 + 1
        day = min(moment.day, 28)  # never overflow a short month
        return moment.replace(year=year, month=month, day=day)

    @classmethod
    def _roll(cls, start, now):
        guard = 0
        while start <= now and guard < 600:
            nxt = cls._add_month(start)
            if nxt > now:
                return start
            start = nxt
            guard += 1
        return start
