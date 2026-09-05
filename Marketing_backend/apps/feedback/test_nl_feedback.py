"""One box, your words: NL feedback replaces the 56-chip vocabulary.

The reviewer's sentence is now a full learning signal — element keys are
parsed from it in the worker and the training pass runs there, once. The
review itself never waits on (or fails with) the parse.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.content.serializers import ReviewActionSerializer
from apps.feedback.models import Feedback
from apps.feedback.nl import _coerce_keys
from apps.feedback.services import capture
from apps.jobs.models import TaskRun
from apps.workspaces.models import MarketingWorkspace


class CoerceKeysTests(TestCase):
    def test_provider_shapes_all_coerce_to_strings(self):
        self.assertEqual(_coerce_keys(['headline', 'resolution']), ['headline', 'resolution'])
        self.assertEqual(_coerce_keys('["headline", "tone_of_voice"]'), ['headline', 'tone_of_voice'])
        self.assertEqual(
            _coerce_keys('```json\n["headline"]\n```'), ['headline']
        )
        self.assertEqual(_coerce_keys({'elements': ['headline']}), ['headline'])
        self.assertEqual(_coerce_keys('not json at all'), [])
        self.assertEqual(_coerce_keys(None), [])
        self.assertEqual(_coerce_keys([{'not': 'a string'}, 'ok']), ['ok'])


class NoteOnlyIsALearningSignalTests(TestCase):
    def test_a_plain_sentence_satisfies_the_corrective_contract(self):
        serializer = ReviewActionSerializer(
            data={'note': 'The headline is too loud, make it title case.'},
            context={'requires_learning_signal': True},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_tapped_tags_alone_still_work_for_legacy_callers(self):
        serializer = ReviewActionSerializer(
            data={'elements': []},
            context={'requires_learning_signal': True},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('your own words', str(serializer.errors))


class CaptureDefersToParseTests(TestCase):
    def setUp(self):
        from apps.brands.models import Brand
        from apps.content.models import ContentItem

        self.workspace = MarketingWorkspace.objects.create(
            customer_id='fb1', workspace_name='Feedback'
        )
        self.brand = Brand.objects.create(
            workspace=self.workspace, name='Acme', status=Brand.Status.ACTIVE
        )
        self.item = ContentItem.objects.create(
            workspace=self.workspace, brand=self.brand, headline='Poster'
        )

    def test_wordy_correction_queues_the_parse_instead_of_learning_blind(self):
        feedback = capture(
            content_item=self.item,
            verdict=Feedback.Verdict.NEEDS_EDITS,
            feedback_text='Make the headline smaller and match the template case.',
        )
        self.assertIsNotNone(feedback)
        self.assertEqual(feedback.element_keys, [])
        run = TaskRun.objects.filter(
            task_path__endswith='parse_feedback_elements_task'
        ).first()
        self.assertIsNotNone(run)
        self.assertEqual(run.args, [str(feedback.pk)])

    def test_approvals_and_tagged_verdicts_do_not_queue_a_parse(self):
        capture(
            content_item=self.item,
            verdict=Feedback.Verdict.APPROVE,
            feedback_text='Lovely.',
        )
        capture(
            content_item=self.item,
            verdict=Feedback.Verdict.REJECT,
            element_keys=['headline'],
            feedback_text='Wrong headline.',
        )
        self.assertFalse(
            TaskRun.objects.filter(
                task_path__endswith='parse_feedback_elements_task'
            ).exists()
        )

    def test_the_parse_task_fills_keys_and_learns_once(self):
        from apps.feedback.tasks import parse_feedback_elements_task

        feedback = capture(
            content_item=self.item,
            verdict=Feedback.Verdict.NEEDS_EDITS,
            feedback_text='Headline too loud.',
            learn=False,
        )
        with patch(
            'apps.feedback.nl.parse_elements', return_value=['headline'],
        ) as parser, patch(
            'apps.feedback.training.TrainingEngine'
        ) as engine:
            result = parse_feedback_elements_task.func(str(feedback.pk))
        parser.assert_called_once()
        engine.assert_called_once()
        feedback.refresh_from_db()
        self.assertEqual(feedback.element_keys, ['headline'])
        self.assertEqual(result['parsed'], 1)

    def test_a_failed_parse_still_learns_from_the_words(self):
        from apps.feedback.tasks import parse_feedback_elements_task

        feedback = capture(
            content_item=self.item,
            verdict=Feedback.Verdict.NEEDS_EDITS,
            feedback_text='Something felt off.',
            learn=False,
        )
        with patch(
            'apps.feedback.nl.parse_elements', side_effect=RuntimeError('no provider'),
        ), patch('apps.feedback.training.TrainingEngine') as engine:
            result = parse_feedback_elements_task.func(str(feedback.pk))
        engine.assert_called_once()
        self.assertEqual(result['parsed'], 0)
