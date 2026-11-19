from unittest.mock import Mock

from django.test import SimpleTestCase

from judge.bridge.judge_handler import SubmissionUnavailable
from judge.bridge.judge_list import JudgeList


class JudgeListFailureTestCase(SimpleTestCase):
    def make_judge(self):
        judge = Mock()
        judge.name = 'healthy-judge'
        judge.working = False
        judge.is_disabled = False
        judge.load = 0
        judge.can_judge.return_value = True
        judge.submit.side_effect = SubmissionUnavailable('submission vanished')
        return judge

    def test_missing_submission_does_not_remove_an_available_judge(self):
        judges = JudgeList()
        judge = self.make_judge()
        judges.judges.add(judge)

        judges.judge(7, 'problem', 'PY3', '', None, 0)

        self.assertIn(judge, judges.judges)
        self.assertNotIn(7, judges.submission_map)
        self.assertNotIn(7, judges.node_map)

    def test_missing_queued_submission_is_dropped_and_judge_stays_available(self):
        judges = JudgeList()
        judge = self.make_judge()
        judges.judge(8, 'problem', 'PY3', '', None, 0)
        self.assertIn(8, judges.node_map)

        judges.register(judge)

        self.assertIn(judge, judges.judges)
        self.assertNotIn(8, judges.submission_map)
        self.assertNotIn(8, judges.node_map)
