"""
Only human judgment weighs into universal learning.

PR7's aggregation multiplies a brand's contribution to cross-client patterns
by how many learning events it holds. That was safe while the only writers
were review feedback and calibration — every event WAS a judgment. The ledger
now also records bookkeeping (a PUBLISHED marker when content ships), and
this proves the boundary: judgment events move the weight, bookkeeping does
not, so a brand cannot buy influence over every other client's patterns by
publishing a lot.
"""
from django.test import TestCase

from apps.brands.models import Brand
from apps.common.testing import TenantFixtureMixin
from apps.learning.models import LearningEvent, SubjectType
from apps.learning.services import record_event
from apps.universal.aggregation import JUDGMENT_EVENT_TYPES, _event_counts
from apps.workspaces.models import MarketingWorkspace, WorkspaceMember


class AggregationWeightTests(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace = self.make_workspace('Acme', 'c1')
        # PR7 counts CLIENT workspaces only; the fixture default may differ.
        if self.workspace.kind != MarketingWorkspace.Kind.CLIENT:
            self.workspace.kind = MarketingWorkspace.Kind.CLIENT
            self.workspace.save(update_fields=['kind'])
        self.user, _ = self.authenticate_as(
            self.workspace, WorkspaceMember.Role.OWNER, 'owner@acme.test'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme Coffee', is_default=True,
            status=Brand.Status.ACTIVE,
        )

    def record(self, event_type, *, outcome=LearningEvent.Outcome.NEUTRAL, key=''):
        return record_event(
            workspace=self.workspace,
            brand=self.brand,
            event_type=event_type,
            outcome=outcome,
            subject_type=SubjectType.OTHER,
            dedupe_key=key,
        )

    def weight_key(self):
        return (self.workspace.pk, self.brand.pk)

    def test_judgment_counts_and_bookkeeping_does_not(self):
        # Two human judgments: they weigh.
        self.record(LearningEvent.EventType.APPROVED,
                    outcome=LearningEvent.Outcome.POSITIVE, key='j1')
        self.record(LearningEvent.EventType.REJECTED,
                    outcome=LearningEvent.Outcome.NEGATIVE, key='j2')
        totals, _ = _event_counts()
        self.assertEqual(totals.get(self.weight_key(), 0), 2)

        # Fifty shipped posts: the ledger grows, the weight does not move.
        for i in range(50):
            self.record(LearningEvent.EventType.PUBLISHED, key=f'p{i}')
        self.record(LearningEvent.EventType.PERFORMANCE_OBSERVED, key='perf1')

        totals, breakdown = _event_counts()
        self.assertEqual(
            totals.get(self.weight_key(), 0), 2,
            'bookkeeping events must not buy influence over universal patterns',
        )
        self.assertNotIn(
            'PUBLISHED:NEUTRAL', breakdown.get(self.weight_key(), {}),
        )
        # The rows themselves are still in the ledger — excluded from the
        # weight, not erased from history.
        self.assertEqual(
            LearningEvent.objects.filter(
                workspace=self.workspace,
                event_type=LearningEvent.EventType.PUBLISHED,
            ).count(),
            50,
        )

    def test_the_boundary_is_exactly_the_declared_judgment_set(self):
        """Every event type is deliberately on one side of the line.

        If someone adds a new EventType, this fails until they decide —
        here, on purpose — whether it is a judgment or bookkeeping.
        """
        bookkeeping = {
            LearningEvent.EventType.PUBLISHED,
            LearningEvent.EventType.PERFORMANCE_OBSERVED,
        }
        declared = set(JUDGMENT_EVENT_TYPES) | bookkeeping
        self.assertEqual(
            declared, set(LearningEvent.EventType),
            'a new LearningEvent.EventType must be explicitly classified as '
            'judgment (JUDGMENT_EVENT_TYPES) or bookkeeping (this test)',
        )
        self.assertFalse(set(JUDGMENT_EVENT_TYPES) & bookkeeping)
