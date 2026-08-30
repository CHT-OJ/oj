import threading
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import connection, connections
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from judge.bridge.judge_handler import JudgeHandler
from judge.judgeapi import judge_submission
from judge.models import Contest, ContestSubmission, Language, Submission, SubmissionSource, SubmissionTestCase
from judge.models.tests.util import create_contest, create_contest_participation, create_contest_problem, \
    create_problem, create_user
from judge.submission_finalization import publish_aborted_result, publish_authoritative_result, \
    publish_infrastructure_failure
from judge.views.problem import get_contest_submission_count


class SubmissionFinalizationMixin:
    fixtures = ['language_all.json']

    def create_contest_state(self, suffix, *, format_name='default', format_config=None, frozen_minutes=0,
                             username=None, problem_points=100):
        now = timezone.now()
        user = create_user(username=username or 'finalize-user-%s' % suffix).profile
        problem = create_problem(
            code=('fp-%s' % suffix)[:20],
            points=problem_points,
            partial=True,
            is_public=True,
        )
        contest = create_contest(
            key=('fc-%s' % suffix)[:20],
            format_name=format_name,
            format_config=format_config,
            start_time=now - timezone.timedelta(hours=3),
            end_time=now - timezone.timedelta(hours=1),
            frozen_last_minutes=frozen_minutes,
        )
        participation = create_contest_participation(contest=contest, user=user)
        contest_problem = create_contest_problem(
            contest=contest,
            problem=problem,
            points=problem_points,
            partial=True,
        )
        return user, problem, contest, participation, contest_problem

    def create_submission(self, user, problem, participation, contest_problem, *, status='G', result=None,
                          points=None, case_points=0, case_total=0, minutes=10, rejudged=False,
                          is_pretested=False):
        submission = Submission.objects.create(
            user=user,
            problem=problem,
            language=Language.get_python3(),
            contest_object=participation.contest,
            status=status,
            result=result,
            points=points,
            case_points=case_points,
            case_total=case_total,
            rejudged_date=timezone.now() if rejudged else None,
            is_pretested=is_pretested,
        )
        Submission.objects.filter(id=submission.id).update(
            date=participation.start + timezone.timedelta(minutes=minutes),
        )
        submission.refresh_from_db()
        contest_submission = ContestSubmission.objects.create(
            submission=submission,
            problem=contest_problem,
            participation=participation,
            points=points or 0,
        )
        SubmissionSource.objects.create(submission=submission, source='print(1)')
        return submission, contest_submission

    def publish_completed(self, submission, points, total, result='AC', callback=None):
        return publish_authoritative_result(
            submission.id,
            {
                'status': 'D',
                'result': result,
                'points': points,
                'case_points': points,
                'case_total': total,
                'time': 0.1,
                'memory': 1024,
            },
            expected_statuses=Submission.IN_PROGRESS_GRADING_STATUS,
            callback=callback,
        )


class SubmissionFinalizationTestCase(SubmissionFinalizationMixin, TestCase):
    def create_handler(self, submission_id):
        handler = object.__new__(JudgeHandler)
        handler.name = 'test-judge'
        handler.judge_address = 'local-test'
        handler.judges = Mock()
        handler._working = submission_id
        handler.batch_id = None
        handler._submission_cache_id = None
        handler._submission_cache = {}
        return handler

    def test_authoritative_result_is_coherent_before_done_callback(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('atomic')
        submission, contest_submission = self.create_submission(
            user, problem, participation, contest_problem,
        )
        observed = []
        cache_keys = [
            'user_complete:%d' % user.id,
            'user_attempted:%s' % user.id,
            'contest_complete:%d' % participation.id,
            'contest_attempted:%d' % participation.id,
        ]
        for key in cache_keys:
            cache.set(key, 'stale')

        def observe(_publication):
            submission.refresh_from_db()
            contest_submission.refresh_from_db()
            participation.refresh_from_db()
            user.refresh_from_db()
            problem.refresh_from_db()
            observed.append({
                'submission': (submission.status, submission.result, submission.points),
                'contest_submission': contest_submission.points,
                'participation': participation.score,
                'profile': user.points,
                'problem_users': problem.user_count,
            })

        with CaptureQueriesContext(connection) as queries:
            with self.captureOnCommitCallbacks(execute=True):
                self.publish_completed(submission, 100, 100, callback=observe)
                self.assertEqual([cache.get(key) for key in cache_keys], ['stale'] * 4)
        self.assertLessEqual(len(queries), 35)

        self.assertEqual(observed, [{
            'submission': ('D', 'AC', 100),
            'contest_submission': 100,
            'participation': 100,
            'profile': 100,
            'problem_users': 1,
        }])
        self.assertEqual([cache.get(key) for key in cache_keys], [None] * 4)

    @patch('judge.bridge.judge_handler.event.post')
    def test_bridge_grading_end_publishes_done_event_after_coherent_commit(self, event_post):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('bridge-done')
        submission, contest_submission = self.create_submission(
            user, problem, participation, contest_problem,
        )
        SubmissionTestCase.objects.create(
            submission=submission,
            case=1,
            status='AC',
            time=0.2,
            memory=1024,
            points=100,
            total=100,
            batch=None,
        )
        handler = self.create_handler(submission.id)
        observed = []

        def observe(_channel, message):
            if message.get('type') != 'done-submission':
                return
            submission.refresh_from_db()
            contest_submission.refresh_from_db()
            participation.refresh_from_db()
            observed.append((submission.status, contest_submission.points, participation.score, message['status']))

        event_post.side_effect = observe
        with self.captureOnCommitCallbacks(execute=True):
            handler.on_grading_end({'submission-id': submission.id})
            self.assertEqual(observed, [])

        self.assertEqual(observed, [('D', 100, 100, 'D')])
        handler.judges.on_judge_free.assert_called_once_with(handler, submission.id)

        with self.captureOnCommitCallbacks(execute=True):
            handler.on_grading_end({'submission-id': submission.id})
        self.assertEqual(observed, [('D', 100, 100, 'D')])

    @patch('judge.bridge.judge_handler.event.post')
    def test_bridge_compile_error_replaces_score_before_events(self, event_post):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('bridge-ce')
        submission, contest_submission = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='P',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
            rejudged=True,
        )
        participation.recompute_results()
        handler = self.create_handler(submission.id)
        observed = []

        def observe(_channel, message):
            if message.get('type') != 'done-submission':
                return
            submission.refresh_from_db()
            contest_submission.refresh_from_db()
            participation.refresh_from_db()
            observed.append((submission.status, contest_submission.points, participation.score, message['status']))

        event_post.side_effect = observe
        with self.captureOnCommitCallbacks(execute=True):
            handler.on_compile_error({'submission-id': submission.id, 'log': 'bad source'})

        self.assertEqual(observed, [('CE', 0, 0, 'CE')])

    def test_wrong_acknowledgement_does_not_process_the_unexpected_submission(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('wrong-ack')
        expected, _contest_submission = self.create_submission(
            user, problem, participation, contest_problem, status='QU',
        )
        unexpected, _unexpected_contest = self.create_submission(
            user, problem, participation, contest_problem, status='QU', minutes=20,
        )
        handler = self.create_handler(expected.id)
        handler.close = Mock()
        handler.on_submission_processing = Mock()
        handler._no_response_job = None

        with self.captureOnCommitCallbacks(execute=True):
            handler.on_submission_acknowledged({'submission-id': unexpected.id})

        expected.refresh_from_db()
        unexpected.refresh_from_db()
        self.assertEqual(expected.status, 'IE')
        self.assertEqual(unexpected.status, 'QU')
        handler.close.assert_called_once_with()
        handler.on_submission_processing.assert_not_called()

    def test_wrong_terminal_packet_cannot_mutate_or_free_another_submission(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('wrong-terminal')
        expected, _expected_contest = self.create_submission(
            user, problem, participation, contest_problem, status='G', minutes=10,
        )
        unexpected, unexpected_contest = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='G',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
            minutes=20,
        )
        handler = self.create_handler(expected.id)
        handler.close = Mock()

        handler.on_compile_error({'submission-id': unexpected.id, 'log': 'forged'})

        unexpected.refresh_from_db()
        unexpected_contest.refresh_from_db()
        self.assertEqual((unexpected.status, unexpected.result, unexpected.points), ('G', 'AC', 100))
        self.assertEqual(unexpected_contest.points, 100)
        handler.close.assert_called_once_with()
        handler.judges.on_judge_free.assert_not_called()

    @patch('judge.bridge.judge_handler.event.post')
    def test_judge_disconnect_marks_infrastructure_failure_without_replacing_result(self, _event_post):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('disconnect')
        submission, contest_submission = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='G',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
            rejudged=True,
        )
        participation.recompute_results()
        handler = self.create_handler(submission.id)
        handler.name = None
        handler.client_address = ('127.0.0.1', 9999)
        handler._stop_ping = threading.Event()

        with self.captureOnCommitCallbacks(execute=True):
            handler.on_disconnect()

        submission.refresh_from_db()
        contest_submission.refresh_from_db()
        participation.refresh_from_db()
        self.assertEqual((submission.status, submission.result, submission.points), ('IE', 'AC', 100))
        self.assertEqual(contest_submission.points, 100)
        self.assertEqual(participation.score, 100)
        handler.judges.remove.assert_called_once_with(handler)

    def test_compile_error_replaces_old_rejudge_score_and_derived_state(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('ce')
        submission, contest_submission = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='P',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
            rejudged=True,
            is_pretested=True,
        )
        participation.recompute_results()
        user.calculate_points()
        problem.update_stats()
        SubmissionTestCase.objects.create(
            submission=submission,
            case=1,
            status='AC',
            time=0.1,
            memory=1024,
            points=100,
            total=100,
            batch=None,
        )

        with self.captureOnCommitCallbacks(execute=True):
            publish_authoritative_result(
                submission.id,
                {
                    'status': 'CE',
                    'result': 'CE',
                    'error': 'compiler error',
                    'time': None,
                    'memory': None,
                    'points': None,
                    'case_points': 0,
                    'case_total': 0,
                    'current_testcase': 0,
                    'batch': False,
                    'is_pretested': False,
                },
                expected_statuses=Submission.IN_PROGRESS_GRADING_STATUS,
                delete_testcases=True,
            )

        submission.refresh_from_db()
        contest_submission.refresh_from_db()
        participation.refresh_from_db()
        user.refresh_from_db()
        problem.refresh_from_db()
        self.assertEqual((submission.status, submission.result, submission.points), ('CE', 'CE', None))
        self.assertFalse(submission.is_pretested)
        self.assertFalse(submission.test_cases.exists())
        self.assertEqual(contest_submission.points, 0)
        self.assertEqual(participation.score, 0)
        self.assertEqual(user.points, 0)
        self.assertEqual(problem.user_count, 0)

    def test_infrastructure_error_preserves_previous_authoritative_result(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('ie')
        submission, contest_submission = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='G',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
            rejudged=True,
        )
        participation.recompute_results()
        user.calculate_points()
        problem.update_stats()

        with CaptureQueriesContext(connection) as queries:
            publish_infrastructure_failure(
                submission.id,
                'IE',
                'judge unavailable',
                expected_statuses=Submission.IN_PROGRESS_GRADING_STATUS,
            )
        self.assertLessEqual(len(queries), 5)

        submission.refresh_from_db()
        contest_submission.refresh_from_db()
        participation.refresh_from_db()
        user.refresh_from_db()
        problem.refresh_from_db()
        self.assertEqual(submission.status, 'IE')
        self.assertEqual(submission.short_status, 'IE')
        self.assertEqual((submission.result, submission.points, submission.case_points), ('AC', 100, 100))
        self.assertEqual(contest_submission.points, 100)
        self.assertEqual(participation.score, 100)
        self.assertEqual(user.points, 100)
        self.assertEqual(problem.user_count, 1)
        user.current_contest = participation
        self.assertEqual(get_contest_submission_count(problem, user, participation.virtual), 1)

        initial_failure, _initial_contest = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='IE',
            result=None,
            points=None,
            minutes=20,
        )
        self.assertIsNone(initial_failure.result)
        self.assertEqual(get_contest_submission_count(problem, user, participation.virtual), 1)

    def test_initial_abort_is_zero_but_rejudge_abort_preserves_old_score(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('abort')
        initial, initial_contest = self.create_submission(
            user, problem, participation, contest_problem, status='P', minutes=5,
        )
        prior, prior_contest = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='G',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
            rejudged=True,
            minutes=10,
        )
        participation.recompute_results()

        with self.captureOnCommitCallbacks(execute=True):
            publish_aborted_result(
                initial.id,
                expected_statuses=Submission.IN_PROGRESS_GRADING_STATUS,
            )
            publish_aborted_result(
                prior.id,
                expected_statuses=Submission.IN_PROGRESS_GRADING_STATUS,
            )

        initial.refresh_from_db()
        initial_contest.refresh_from_db()
        prior.refresh_from_db()
        prior_contest.refresh_from_db()
        participation.refresh_from_db()
        self.assertEqual((initial.status, initial.result, initial.points), ('AB', 'AB', 0))
        self.assertEqual(initial_contest.points, 0)
        self.assertEqual((prior.status, prior.result, prior.points), ('AB', 'AC', 100))
        self.assertEqual(prior_contest.points, 100)
        self.assertEqual(participation.score, 100)

    @patch('judge.judgeapi.judge_request', side_effect=OSError('bridge unavailable'))
    def test_rejudge_request_failure_retains_old_result_and_testcases(self, _judge_request):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('request-failure')
        submission, contest_submission = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='D',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
        )
        testcase = SubmissionTestCase.objects.create(
            submission=submission,
            case=1,
            status='AC',
            time=0.1,
            memory=1024,
            points=100,
            total=100,
            batch=None,
        )

        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(judge_submission(submission, rejudge=True))

        submission.refresh_from_db()
        contest_submission.refresh_from_db()
        self.assertEqual(submission.status, 'IE')
        self.assertEqual((submission.result, submission.points), ('AC', 100))
        self.assertTrue(SubmissionTestCase.objects.filter(id=testcase.id).exists())
        self.assertEqual(contest_submission.points, 100)

    def test_duplicate_queued_rejudge_is_idempotent_and_preserves_authoritative_data(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('duplicate-rejudge')
        submission, contest_submission = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='D',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
        )
        testcase = SubmissionTestCase.objects.create(
            submission=submission,
            case=1,
            status='AC',
            time=0.1,
            memory=1024,
            points=100,
            total=100,
            batch=None,
        )
        response = {'name': 'submission-received', 'submission-id': submission.id}

        with patch('judge.judgeapi.judge_request', return_value=response) as request:
            self.assertTrue(judge_submission(submission, rejudge=True))
            self.assertTrue(judge_submission(submission, rejudge=True))

        submission.refresh_from_db()
        contest_submission.refresh_from_db()
        self.assertEqual(request.call_count, 2)
        self.assertEqual((submission.status, submission.result, submission.points), ('QU', 'AC', 100))
        self.assertTrue(SubmissionTestCase.objects.filter(id=testcase.id).exists())
        self.assertEqual(contest_submission.points, 100)

    def test_multiple_default_submissions_recompute_the_best_score(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('best')
        first, first_contest = self.create_submission(
            user, problem, participation, contest_problem,
            status='G', result='AC', points=100, case_points=100, case_total=100, rejudged=True, minutes=5,
        )
        second, second_contest = self.create_submission(
            user, problem, participation, contest_problem,
            status='D', result='AC', points=80, case_points=80, case_total=100, minutes=10,
        )
        participation.recompute_results()

        self.publish_completed(first, 40, 100, result='WA')
        first_contest.refresh_from_db()
        second_contest.refresh_from_db()
        participation.refresh_from_db()
        self.assertEqual((first_contest.points, second_contest.points, participation.score), (40, 80, 80))

        first.status = 'G'
        first.save(update_fields=['status'])
        self.publish_completed(first, 100, 100)
        participation.refresh_from_db()
        self.assertEqual(participation.score, 100)

    def test_submission_finalization_does_not_implicitly_rerate_contest(self):
        user, problem, contest, participation, contest_problem = self.create_contest_state('rating')
        contest.is_rated = True
        contest.save(update_fields=['is_rated'])
        submission, _contest_submission = self.create_submission(
            user, problem, participation, contest_problem,
        )

        with patch.object(Contest, 'rate') as rate:
            self.publish_completed(submission, 100, 100)

        rate.assert_not_called()

    def test_icpc_rejudge_recomputes_attempts_solve_time_and_penalty(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state(
            'icpc',
            format_name='icpc',
            format_config={'penalty': 20},
        )
        wrong, _wrong_contest = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='D',
            result='WA',
            points=0,
            case_points=0,
            case_total=100,
            minutes=10,
        )
        accepted, _accepted_contest = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='G',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
            minutes=30,
            rejudged=True,
        )
        participation.recompute_results()
        participation.refresh_from_db()
        self.assertEqual((participation.score, participation.cumtime, participation.tiebreaker), (100, 50, 30))

        self.publish_completed(accepted, 0, 100, result='WA')
        participation.refresh_from_db()
        self.assertEqual((participation.score, participation.cumtime, participation.tiebreaker), (0, 0, 0))
        self.assertEqual(participation.format_data[str(contest_problem.id)]['tries'], 2)

        wrong.status = 'G'
        wrong.rejudged_date = timezone.now()
        wrong.save(update_fields=['status', 'rejudged_date'])
        self.publish_completed(wrong, 100, 100)
        participation.refresh_from_db()
        self.assertEqual((participation.score, participation.cumtime, participation.tiebreaker), (100, 10, 10))
        self.assertEqual(participation.format_data[str(contest_problem.id)]['tries'], 1)

    def test_icpc_post_freeze_rejudge_keeps_frozen_fields_consistent(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state(
            'icpc-freeze',
            format_name='icpc',
            format_config={'penalty': 20},
            frozen_minutes=60,
        )
        before_freeze, _before_contest = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='D',
            result='WA',
            points=0,
            case_points=0,
            case_total=100,
            minutes=30,
        )
        after_freeze, _after_contest = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='G',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
            minutes=90,
            rejudged=True,
        )
        participation.recompute_results()
        participation.refresh_from_db()
        self.assertEqual((participation.score, participation.frozen_score), (100, 0))
        self.assertTrue(participation.format_data[str(contest_problem.id)]['is_frozen'])

        self.publish_completed(after_freeze, 0, 100, result='WA')
        participation.refresh_from_db()
        self.assertEqual((participation.score, participation.frozen_score), (0, 0))
        self.assertEqual((participation.cumtime, participation.frozen_cumtime), (0, 0))

        before_freeze.status = 'G'
        before_freeze.rejudged_date = timezone.now()
        before_freeze.save(update_fields=['status', 'rejudged_date'])
        self.publish_completed(before_freeze, 100, 100)
        participation.refresh_from_db()
        self.assertEqual((participation.score, participation.frozen_score), (100, 100))
        self.assertEqual((participation.cumtime, participation.frozen_cumtime), (30, 30))

    def test_vnoj_rejudge_recomputes_best_score_penalty_and_freeze(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state(
            'vnoj',
            format_name='vnoj',
            format_config={'penalty': 5, 'LSO': False},
            frozen_minutes=60,
        )
        before_freeze, _before_contest = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='D',
            result='AC',
            points=50,
            case_points=50,
            case_total=100,
            minutes=30,
        )
        after_freeze, _after_contest = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='G',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
            minutes=90,
            rejudged=True,
        )
        participation.recompute_results()
        participation.refresh_from_db()
        self.assertEqual((participation.score, participation.cumtime), (100, 90 * 60 + 5 * 60))
        self.assertEqual((participation.frozen_score, participation.frozen_cumtime), (50, 30 * 60))

        self.publish_completed(after_freeze, 20, 100, result='WA')
        participation.refresh_from_db()
        self.assertEqual((participation.score, participation.cumtime), (50, 30 * 60))
        self.assertEqual((participation.frozen_score, participation.frozen_cumtime), (50, 30 * 60))

        before_freeze.status = 'G'
        before_freeze.rejudged_date = timezone.now()
        before_freeze.save(update_fields=['status', 'rejudged_date'])
        self.publish_completed(before_freeze, 100, 100)
        participation.refresh_from_db()
        self.assertEqual((participation.score, participation.cumtime), (100, 30 * 60))
        self.assertEqual((participation.frozen_score, participation.frozen_cumtime), (100, 30 * 60))

    def test_pretest_to_full_rejudge_uses_full_result_and_clears_pretest_flag(self):
        scenarios = (
            ('ac-to-wa', 100, 0, 'WA'),
            ('wa-to-ac', 0, 100, 'AC'),
            ('partial-change', 40, 80, 'AC'),
        )
        for suffix, pretest_points, full_points, full_result in scenarios:
            with self.subTest(suffix=suffix):
                user, problem, _contest, participation, contest_problem = self.create_contest_state(
                    'pretest-%s' % suffix,
                    username='pretest-user-%s' % suffix,
                )
                submission, contest_submission = self.create_submission(
                    user,
                    problem,
                    participation,
                    contest_problem,
                    status='G',
                    result='AC' if pretest_points else 'WA',
                    points=pretest_points,
                    case_points=pretest_points,
                    case_total=100,
                    rejudged=True,
                    is_pretested=False,
                )
                self.publish_completed(submission, full_points, 100, result=full_result)

                submission.refresh_from_db()
                contest_submission.refresh_from_db()
                participation.refresh_from_db()
                self.assertFalse(submission.is_pretested)
                self.assertFalse(contest_submission.is_pretest)
                self.assertEqual(contest_submission.points, full_points)
                self.assertEqual(participation.score, full_points)


class SubmissionFinalizationConcurrencyTestCase(SubmissionFinalizationMixin, TransactionTestCase):
    reset_sequences = True

    def test_unlocked_reference_interleaving_reproduces_stale_participation_write(self):
        user, first_problem, contest, participation, first_contest_problem = self.create_contest_state(
            'race-reference-a',
        )
        second_problem = create_problem(
            code='fp-race-ref-b',
            points=100,
            partial=True,
            is_public=True,
        )
        second_contest_problem = create_contest_problem(
            contest=contest,
            problem=second_problem,
            points=100,
            partial=True,
            order=2,
        )
        _first, first_contest = self.create_submission(
            user, first_problem, participation, first_contest_problem,
        )
        _second, second_contest = self.create_submission(
            user, second_problem, participation, second_contest_problem, minutes=20,
        )
        first_read = threading.Event()
        second_written = threading.Event()
        errors = []

        def first_unlocked_completion():
            try:
                ContestSubmission.objects.filter(id=first_contest.id).update(points=100)
                stale_score = ContestSubmission.objects.filter(participation=participation).aggregate(
                    score=Sum('points'),
                )['score']
                first_read.set()
                second_written.wait(timeout=5)
                type(participation).objects.filter(id=participation.id).update(score=stale_score)
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()

        def second_unlocked_completion():
            try:
                first_read.wait(timeout=5)
                ContestSubmission.objects.filter(id=second_contest.id).update(points=100)
                complete_score = ContestSubmission.objects.filter(participation=participation).aggregate(
                    score=Sum('points'),
                )['score']
                type(participation).objects.filter(id=participation.id).update(score=complete_score)
                second_written.set()
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=first_unlocked_completion),
            threading.Thread(target=second_unlocked_completion),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertTrue(first_read.is_set())
        self.assertTrue(second_written.is_set())
        self.assertEqual(errors, [])
        participation.refresh_from_db()
        authoritative_score = participation.submissions.aggregate(score=Sum('points'))['score']
        self.assertEqual(authoritative_score, 200)
        self.assertEqual(participation.score, 100)

    def test_attempt_number_counts_preserved_rejudge_result_but_not_initial_ie(self):
        user, problem, _contest, participation, contest_problem = self.create_contest_state('attempt-number')
        self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='IE',
            result='AC',
            points=100,
            case_points=100,
            case_total=100,
            rejudged=True,
            minutes=10,
        )
        self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='IE',
            result=None,
            points=None,
            minutes=20,
        )
        next_submission, _next_contest = self.create_submission(
            user,
            problem,
            participation,
            contest_problem,
            status='QU',
            minutes=30,
        )
        handler = object.__new__(JudgeHandler)

        self.assertEqual(handler.get_related_submission_data(next_submission.id).attempt_no, 2)

    def test_simultaneous_same_participation_completions_keep_both_results(self):
        user, first_problem, contest, participation, first_contest_problem = self.create_contest_state(
            'concurrent-a',
        )
        second_problem = create_problem(
            code='finalize-problem-concurrent-b',
            points=100,
            partial=True,
            is_public=True,
        )
        second_contest_problem = create_contest_problem(
            contest=contest,
            problem=second_problem,
            points=100,
            partial=True,
            order=2,
        )
        first, _first_contest = self.create_submission(
            user, first_problem, participation, first_contest_problem,
        )
        second, _second_contest = self.create_submission(
            user, second_problem, participation, second_contest_problem, minutes=20,
        )
        barrier = threading.Barrier(3)
        errors = []

        def finalize(submission):
            try:
                barrier.wait(timeout=5)
                self.publish_completed(submission, 100, 100)
            except Exception as error:
                errors.append(error)

        threads = [
            threading.Thread(target=finalize, args=(first,)),
            threading.Thread(target=finalize, args=(second,)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        participation.refresh_from_db()
        self.assertEqual(participation.score, 200)
        self.assertEqual(
            list(participation.submissions.order_by('id').values_list('points', flat=True)),
            [100, 100],
        )

    def test_simultaneous_different_participations_remain_independent(self):
        first_user, problem, contest, first_participation, contest_problem = self.create_contest_state(
            'concurrent-independent-a',
        )
        second_user = create_user(username='finalize-user-concurrent-independent-b').profile
        second_participation = create_contest_participation(contest=contest, user=second_user)
        first, _first_contest = self.create_submission(
            first_user, problem, first_participation, contest_problem,
        )
        second, _second_contest = self.create_submission(
            second_user, problem, second_participation, contest_problem, minutes=20,
        )
        barrier = threading.Barrier(3)
        errors = []

        def finalize(submission):
            try:
                barrier.wait(timeout=5)
                self.publish_completed(submission, 100, 100)
            except Exception as error:
                errors.append(error)

        threads = [
            threading.Thread(target=finalize, args=(first,)),
            threading.Thread(target=finalize, args=(second,)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        first_participation.refresh_from_db()
        second_participation.refresh_from_db()
        self.assertEqual(first_participation.score, 100)
        self.assertEqual(second_participation.score, 100)
