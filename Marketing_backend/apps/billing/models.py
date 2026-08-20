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
