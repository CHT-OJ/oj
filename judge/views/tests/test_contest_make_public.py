from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from judge.models import Solution
from judge.models.tests.util import create_contest, create_contest_problem, create_problem, create_solution, create_user


class ContestProblemMakePublicTestCase(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls._now = timezone.now()

        cls.staff_editor = create_user(
            username='staff_editor',
            is_staff=True,
            is_superuser=True,
        )

        cls.normal_user = create_user(
            username='normal_user',
        )

        cls.contest = create_contest(
            key='test_publish',
            start_time=cls._now - timezone.timedelta(days=10),
            end_time=cls._now - timezone.timedelta(days=1),
            is_visible=True,
            authors=('staff_editor',),
        )

        # Private problem WITH editorial
        cls.problem_with_editorial = create_problem(
            code='prob_with_editorial',
            is_public=False,
            authors=('staff_editor',),
        )
        cls.solution = create_solution(
            problem=cls.problem_with_editorial,
            is_public=False,
            publish_on=cls._now + timezone.timedelta(days=100),
            content='Editorial content',
        )
        create_contest_problem(
            contest=cls.contest,
            problem=cls.problem_with_editorial,
            order=1,
        )

        # Private problem WITHOUT editorial
        cls.problem_without_editorial = create_problem(
            code='prob_no_editorial',
            is_public=False,
            authors=('staff_editor',),
        )
        create_contest_problem(
            contest=cls.contest,
            problem=cls.problem_without_editorial,
            order=2,
        )

        # Already-public problem with unpublished editorial
        cls.public_problem = create_problem(
            code='prob_already_public',
            is_public=True,
            authors=('staff_editor',),
        )
        cls.public_problem_solution = create_solution(
            problem=cls.public_problem,
            is_public=False,
            publish_on=cls._now + timezone.timedelta(days=100),
            content='Hidden editorial for public problem',
        )
        create_contest_problem(
            contest=cls.contest,
            problem=cls.public_problem,
            order=3,
        )

        # Already-public problem whose editorial is already published
        cls.settled_publish_on = cls._now - timezone.timedelta(days=30)
        cls.settled_problem = create_problem(
            code='prob_settled',
            is_public=True,
            authors=('staff_editor',),
        )
        cls.settled_solution = create_solution(
            problem=cls.settled_problem,
            is_public=True,
            publish_on=cls.settled_publish_on,
            content='Already published editorial',
        )
        create_contest_problem(
            contest=cls.contest,
            problem=cls.settled_problem,
            order=4,
        )

    def _get_url(self):
        return reverse('contest_problems_make_public', args=[self.contest.key])

    @patch('judge.views.contests.rescore_problem')
    def test_publishes_problems_and_editorials(self, mock_rescore):
        self.client.force_login(self.staff_editor)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._get_url())

        self.assertEqual(response.status_code, 302)

        self.problem_with_editorial.refresh_from_db()
        self.assertTrue(self.problem_with_editorial.is_public)

        self.solution.refresh_from_db()
        self.assertTrue(self.solution.is_public)
        self.assertLessEqual(self.solution.publish_on, timezone.now())

    @patch('judge.views.contests.rescore_problem')
    def test_problem_date_is_bumped_to_publish_time(self, mock_rescore):
        self.client.force_login(self.staff_editor)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._get_url())

        self.problem_with_editorial.refresh_from_db()
        self.solution.refresh_from_db()
        # Problem date and editorial publish_on share the single `now`.
        self.assertEqual(self.problem_with_editorial.date, self.solution.publish_on)

    @patch('judge.views.contests.rescore_problem')
    def test_no_editorial_does_not_break(self, mock_rescore):
        self.client.force_login(self.staff_editor)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._get_url())

        self.assertEqual(response.status_code, 302)

        self.problem_without_editorial.refresh_from_db()
        self.assertTrue(self.problem_without_editorial.is_public)
        self.assertFalse(Solution.objects.filter(problem=self.problem_without_editorial).exists())

    @patch('judge.views.contests.rescore_problem')
    def test_already_public_problem_editorial_is_published(self, mock_rescore):
        """Current VNOJ publishes editorials even when the problem is already public."""
        self.client.force_login(self.staff_editor)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._get_url())

        self.public_problem_solution.refresh_from_db()
        self.assertTrue(self.public_problem_solution.is_public)
        self.assertLessEqual(self.public_problem_solution.publish_on, timezone.now())

    @patch('judge.views.contests.rescore_problem')
    def test_already_public_problem_is_not_republished(self, mock_rescore):
        """Publishing the editorial must not re-date or rescore an already-public problem."""
        original_date = self.public_problem.date
        self.client.force_login(self.staff_editor)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._get_url())

        self.public_problem.refresh_from_db()
        self.assertEqual(self.public_problem.date, original_date)
        self.assertNotIn(
            self.public_problem.id,
            {call.args[0] for call in mock_rescore.delay.call_args_list},
        )

    @patch('judge.views.contests.rescore_problem')
    def test_published_editorial_keeps_its_publish_on(self, mock_rescore):
        """An editorial that is already public must not have its publish date moved."""
        self.client.force_login(self.staff_editor)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._get_url())

        self.settled_solution.refresh_from_db()
        self.assertTrue(self.settled_solution.is_public)
        self.assertEqual(self.settled_solution.publish_on, self.settled_publish_on)

    @patch('judge.views.contests.rescore_problem')
    def test_rescore_called_for_published_problems(self, mock_rescore):
        self.client.force_login(self.staff_editor)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._get_url())

        rescore_ids = {call.args[0] for call in mock_rescore.delay.call_args_list}
        self.assertIn(self.problem_with_editorial.id, rescore_ids)
        self.assertIn(self.problem_without_editorial.id, rescore_ids)
        self.assertNotIn(self.public_problem.id, rescore_ids)
        self.assertNotIn(self.settled_problem.id, rescore_ids)

    @patch('judge.views.contests.rescore_problem')
    def test_rescore_signals_publicity_change(self, mock_rescore):
        """CHT's rescore_problem takes a publicy_changed flag; keep passing it."""
        self.client.force_login(self.staff_editor)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._get_url())

        for call in mock_rescore.delay.call_args_list:
            self.assertEqual(call.args[1], True)

    def test_get_request_forbidden(self):
        self.client.force_login(self.staff_editor)
        response = self.client.get(self._get_url())
        self.assertEqual(response.status_code, 403)

    @patch('judge.views.contests.rescore_problem')
    def test_normal_user_permission_denied(self, mock_rescore):
        self.client.force_login(self.normal_user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._get_url())

        self.problem_with_editorial.refresh_from_db()
        self.assertFalse(self.problem_with_editorial.is_public)
        self.public_problem_solution.refresh_from_db()
        self.assertFalse(self.public_problem_solution.is_public)
        mock_rescore.delay.assert_not_called()

    @patch('judge.views.contests.rescore_problem')
    def test_anonymous_cannot_publish(self, mock_rescore):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._get_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login', response['Location'])

        self.problem_with_editorial.refresh_from_db()
        self.assertFalse(self.problem_with_editorial.is_public)
        mock_rescore.delay.assert_not_called()


@override_settings(MOSS_API_KEY=None)
class ContestProblemMakePublicNonStaffTestCase(TestCase):
    """A legitimate contest editor does not need `is_staff` to publish."""

    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls._now = timezone.now()

        cls.editor = create_user(
            username='nonstaff_editor',
            is_staff=False,
            user_permissions=('edit_own_contest', 'edit_own_problem'),
        )
        cls.stranger = create_user(username='problem_stranger')

        cls.contest = create_contest(
            key='nonstaff_publish',
            start_time=cls._now - timezone.timedelta(days=10),
            end_time=cls._now - timezone.timedelta(days=1),
            is_visible=True,
            authors=('nonstaff_editor',),
        )

        # The editor's own private problem, with an unpublished editorial.
        cls.own_problem = create_problem(
            code='nonstaff_own',
            is_public=False,
            authors=('nonstaff_editor',),
        )
        cls.own_solution = create_solution(
            problem=cls.own_problem,
            is_public=False,
            publish_on=cls._now + timezone.timedelta(days=100),
            content='Own editorial',
        )
        create_contest_problem(contest=cls.contest, problem=cls.own_problem, order=1)

        # Somebody else's already-public problem, with an unpublished editorial.
        cls.foreign_problem = create_problem(
            code='nonstaff_foreign',
            is_public=True,
            authors=('problem_stranger',),
        )
        cls.foreign_solution = create_solution(
            problem=cls.foreign_problem,
            is_public=False,
            publish_on=cls._now + timezone.timedelta(days=100),
            content='Foreign editorial',
        )
        create_contest_problem(contest=cls.contest, problem=cls.foreign_problem, order=2)

    def _get_url(self):
        return reverse('contest_problems_make_public', args=[self.contest.key])

    @patch('judge.views.contests.rescore_problem')
    def test_non_staff_editor_can_publish(self, mock_rescore):
        self.client.force_login(self.editor)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._get_url())

        self.assertEqual(response.status_code, 302)

        self.own_problem.refresh_from_db()
        self.own_solution.refresh_from_db()
        self.assertTrue(self.own_problem.is_public)
        self.assertTrue(self.own_solution.is_public)
        mock_rescore.delay.assert_any_call(self.own_problem.id, True)

    @patch('judge.views.contests.rescore_problem')
    def test_uneditable_public_problem_is_skipped_not_fatal(self, mock_rescore):
        """A public problem the editor cannot edit must not block the rest of the contest."""
        self.client.force_login(self.editor)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._get_url())

        self.assertEqual(response.status_code, 302)

        self.foreign_solution.refresh_from_db()
        self.assertFalse(self.foreign_solution.is_public)
        self.assertGreater(self.foreign_solution.publish_on, timezone.now())
        self.assertNotIn(
            self.foreign_problem.id,
            {call.args[0] for call in mock_rescore.delay.call_args_list},
        )

    @patch('judge.views.contests.rescore_problem')
    def test_permission_failure_rolls_back_the_whole_contest(self, mock_rescore):
        self.foreign_problem.is_public = False
        self.foreign_problem.save()
        self.client.force_login(self.editor)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self._get_url())
        self.own_problem.refresh_from_db()
        self.assertFalse(self.own_problem.is_public)
        mock_rescore.delay.assert_not_called()

    def test_non_staff_editor_sees_the_publish_button(self):
        """The UI gate must match the view gate: can_edit alone, no is_staff."""
        self.client.force_login(self.editor)
        response = self.client.get(reverse('contest_view', args=[self.contest.key]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self._get_url())

    def test_stranger_does_not_see_the_publish_button(self):
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('contest_view', args=[self.contest.key]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self._get_url())
