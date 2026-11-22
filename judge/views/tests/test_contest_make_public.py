from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from judge.models import Solution
from judge.models.tests.util import create_contest, create_contest_problem, create_organization, create_problem, \
    create_solution, create_user


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
    """Publishing global private problems requires judge.change_public_visibility;
    non-staff editors with that permission (or org-scoped editors for single-org
    private problems) do not need is_staff."""

    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls._now = timezone.now()

        cls.editor = create_user(
            username='nonstaff_editor',
            is_staff=False,
            user_permissions=('edit_own_contest', 'edit_own_problem', 'change_public_visibility'),
        )
        cls.limited_editor = create_user(
            username='limited_editor',
            is_staff=False,
            user_permissions=('edit_own_contest', 'edit_own_problem'),
        )
        cls.staff_no_perm = create_user(
            username='staff_no_perm',
            is_staff=True,
            user_permissions=('edit_own_contest', 'edit_own_problem'),
        )
        cls.stranger = create_user(username='problem_stranger')

        cls.contest = create_contest(
            key='nonstaff_publish',
            start_time=cls._now - timezone.timedelta(days=10),
            end_time=cls._now - timezone.timedelta(days=1),
            is_visible=True,
            authors=('nonstaff_editor', 'limited_editor', 'staff_no_perm'),
        )

        # The editor's own private problem, with an unpublished editorial.
        cls.own_problem = create_problem(
            code='nonstaff_own',
            is_public=False,
            authors=('nonstaff_editor', 'limited_editor', 'staff_no_perm'),
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

    def _get_url(self, contest=None):
        return reverse('contest_problems_make_public', args=[(contest or self.contest).key])

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
    def test_editor_without_global_perm_cannot_publish_global_private_problem(self, mock_rescore):
        self.client.force_login(self.limited_editor)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._get_url())

        self.assertNotEqual(response.status_code, 302)
        self.assertContains(response, 'You do not have permission to publish this problem.')
        self.own_problem.refresh_from_db()
        self.own_solution.refresh_from_db()
        self.assertFalse(self.own_problem.is_public)
        self.assertFalse(self.own_solution.is_public)
        mock_rescore.delay.assert_not_called()

    @patch('judge.views.contests.rescore_problem')
    def test_is_staff_alone_does_not_grant_global_publish(self, mock_rescore):
        self.client.force_login(self.staff_no_perm)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._get_url())

        self.assertNotEqual(response.status_code, 302)
        self.assertContains(response, 'You do not have permission to publish this problem.')
        self.own_problem.refresh_from_db()
        self.assertFalse(self.own_problem.is_public)
        mock_rescore.delay.assert_not_called()

    @patch('judge.views.contests.rescore_problem')
    def test_scheduled_future_editorial_keeps_scheduled_date(self, mock_rescore):
        future_date = self._now + timezone.timedelta(days=14)
        scheduled_problem = create_problem(
            code='prob_scheduled_ed',
            is_public=True,
            authors=('nonstaff_editor',),
        )
        scheduled_solution = create_solution(
            problem=scheduled_problem,
            is_public=True,
            publish_on=future_date,
            content='Scheduled editorial',
        )
        create_contest_problem(contest=self.contest, problem=scheduled_problem, order=3)

        self.client.force_login(self.editor)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._get_url())

        self.assertEqual(response.status_code, 302)
        scheduled_solution.refresh_from_db()
        self.assertTrue(scheduled_solution.is_public)
        self.assertEqual(scheduled_solution.publish_on, future_date)

    @patch('judge.views.contests.rescore_problem')
    def test_org_editor_can_publish_single_org_private_problem_only(self, mock_rescore):
        org_a = create_organization(name='PubOrgA', admins=('limited_editor',))
        org_b = create_organization(name='PubOrgB', admins=('limited_editor',))
        org_contest = create_contest(
            key='org_a_publish',
            start_time=self._now - timezone.timedelta(days=10),
            end_time=self._now - timezone.timedelta(days=1),
            is_visible=True,
            is_organization_private=True,
            organizations=('PubOrgA',),
            authors=('limited_editor',),
        )
        org_only_prob = create_problem(
            code='org_a_only_prob',
            is_public=False,
            is_organization_private=True,
            organizations=('PubOrgA',),
            authors=('limited_editor',),
        )
        create_contest_problem(contest=org_contest, problem=org_only_prob, order=1)

        # Single-org private problem in single-org private contest -> allowed
        self.client.force_login(self.limited_editor)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._get_url(org_contest))
        self.assertEqual(response.status_code, 302)
        org_only_prob.refresh_from_db()
        self.assertTrue(org_only_prob.is_public)
        mock_rescore.delay.assert_called_once_with(org_only_prob.id, True)

        # Multi-org private problem (Org A + Org B) -> denied & rolls back whole batch
        mock_rescore.reset_mock()
        org_only_prob_2 = create_problem(
            code='org_a_only_prob2',
            is_public=False,
            is_organization_private=True,
            organizations=('PubOrgA',),
            authors=('limited_editor',),
        )
        shared_prob = create_problem(
            code='org_ab_shared_prob',
            is_public=False,
            is_organization_private=True,
            organizations=(org_a.name, org_b.name),
            authors=('limited_editor',),
        )
        create_contest_problem(contest=org_contest, problem=org_only_prob_2, order=2)
        create_contest_problem(contest=org_contest, problem=shared_prob, order=3)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._get_url(org_contest))
        self.assertNotEqual(response.status_code, 302)
        self.assertContains(response, 'You do not have permission to publish this problem.')
        org_only_prob_2.refresh_from_db()
        shared_prob.refresh_from_db()
        self.assertFalse(org_only_prob_2.is_public)
        self.assertFalse(shared_prob.is_public)
        mock_rescore.delay.assert_not_called()

    @patch('judge.views.contests.rescore_problem')
    def test_org_editor_cannot_publish_suggested_problem_without_global_perm(self, mock_rescore):
        create_organization(name='PubOrgSug', admins=('limited_editor',))
        org_contest = create_contest(
            key='org_sug_publish',
            start_time=self._now - timezone.timedelta(days=10),
            end_time=self._now - timezone.timedelta(days=1),
            is_visible=True,
            is_organization_private=True,
            organizations=('PubOrgSug',),
            authors=('limited_editor',),
        )
        suggested_prob = create_problem(
            code='org_sug_prob',
            is_public=False,
            is_organization_private=True,
            organizations=('PubOrgSug',),
            authors=('limited_editor',),
        )
        suggested_prob.suggester = self.limited_editor.profile
        suggested_prob.save(update_fields=['suggester'])
        create_contest_problem(contest=org_contest, problem=suggested_prob, order=1)

        self.client.force_login(self.limited_editor)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._get_url(org_contest))
        self.assertNotEqual(response.status_code, 302)
        self.assertContains(response, 'You do not have permission to publish this problem.')
        suggested_prob.refresh_from_db()
        self.assertFalse(suggested_prob.is_public)
        mock_rescore.delay.assert_not_called()

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
