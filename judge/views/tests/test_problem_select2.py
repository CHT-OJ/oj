from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from judge.models import Contest
from judge.models.tests.util import create_contest, create_organization, create_problem, create_user


class ProblemSelect2ViewTestCase(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.viewer = create_user(username='select2_viewer')
        cls.org_admin = create_user(username='select2_org_admin')
        cls.org = create_organization(name='Alpha', admins=('select2_org_admin',))
        cls.other_org = create_organization(name='Beta', admins=('select2_org_admin',))

        cls.public_problem = create_problem(code='pubprob', name='Public Problem', is_public=True)
        cls.org_problem = create_problem(
            code='orgprob',
            name='Org Problem',
            is_public=True,
            is_organization_private=True,
            organizations=('Alpha',),
        )
        cls.other_org_problem = create_problem(
            code='betaprob',
            name='Beta Problem',
            is_public=True,
            is_organization_private=True,
            organizations=('Beta',),
        )

    def _results(self, url, term=''):
        response = self.client.get(url, {'term': term})
        self.assertEqual(response.status_code, 200)
        return response.json()['results']

    def _texts(self, url, term=''):
        return [r['text'] for r in self._results(url, term)]

    # --- [CODE] Name rendering ------------------------------------------

    def test_general_picker_shows_code_and_name(self):
        self.client.force_login(self.viewer)
        texts = self._texts(reverse('problem_select2'), 'pubprob')
        self.assertIn('[pubprob] Public Problem', texts)

    def test_public_picker_shows_code_and_name(self):
        self.client.force_login(self.viewer)
        texts = self._texts(reverse('public_problem_select2'), 'pubprob')
        self.assertIn('[pubprob] Public Problem', texts)

    def test_org_picker_shows_code_and_name(self):
        self.client.force_login(self.org_admin)
        texts = self._texts(reverse('org_problem_select2', args=[self.org.id]), 'orgprob')
        self.assertIn('[orgprob] Org Problem', texts)

    # --- search by code or name -----------------------------------------

    def test_search_matches_code(self):
        self.client.force_login(self.viewer)
        self.assertIn('[pubprob] Public Problem', self._texts(reverse('problem_select2'), 'pubpro'))

    def test_search_matches_name(self):
        self.client.force_login(self.viewer)
        self.assertIn('[pubprob] Public Problem', self._texts(reverse('problem_select2'), 'Public Prob'))

    # --- the public endpoint must not leak organization-private problems --

    def test_public_endpoint_excludes_organization_private_problems(self):
        self.client.force_login(self.org_admin)
        texts = self._texts(reverse('public_problem_select2'))
        self.assertIn('[pubprob] Public Problem', texts)
        self.assertNotIn('[orgprob] Org Problem', texts)
        self.assertNotIn('[betaprob] Beta Problem', texts)

    def test_public_endpoint_excludes_org_private_problems_for_anonymous(self):
        texts = self._texts(reverse('public_problem_select2'))
        self.assertNotIn('[orgprob] Org Problem', texts)

    # --- the organization endpoint is scoped and permission-checked -------

    def test_org_endpoint_returns_only_that_organizations_private_problems(self):
        self.client.force_login(self.org_admin)
        texts = self._texts(reverse('org_problem_select2', args=[self.org.id]))
        self.assertIn('[orgprob] Org Problem', texts)
        self.assertNotIn('[betaprob] Beta Problem', texts)
        self.assertNotIn('[pubprob] Public Problem', texts)

    def test_org_endpoint_respects_user_visibility(self):
        """A user outside the organization cannot enumerate its private problems."""
        hidden = create_problem(
            code='hiddenprob',
            name='Hidden Problem',
            is_public=False,
            is_organization_private=True,
            organizations=('Alpha',),
        )
        self.client.force_login(self.viewer)
        texts = self._texts(reverse('org_problem_select2', args=[self.org.id]))
        self.assertNotIn('[%s] %s' % (hidden.code, hidden.name), texts)

    def test_org_endpoint_does_not_duplicate_multi_org_problems(self):
        """The m2m join must not emit a problem once per matching organization."""
        create_problem(
            code='sharedprob',
            name='Shared Problem',
            is_public=True,
            is_organization_private=True,
            organizations=('Alpha', 'Beta'),
        )
        self.client.force_login(self.org_admin)
        texts = self._texts(reverse('org_problem_select2', args=[self.org.id]), 'sharedprob')
        self.assertEqual(texts.count('[sharedprob] Shared Problem'), 1)


@override_settings(MOSS_API_KEY=None)
class ContestEditProblemPickerTestCase(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.editor = create_user(
            username='picker_editor',
            user_permissions=('edit_own_contest',),
        )
        cls.org = create_organization(name='Gamma', admins=('picker_editor',))
        cls.other_org = create_organization(name='Delta', admins=('picker_editor',))

    def _edit_page(self, contest):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('contest_edit', args=[contest.key]))
        self.assertEqual(response.status_code, 200)
        return response

    def test_single_organization_contest_gets_split_picker(self):
        contest = create_contest(
            key='org_contest',
            authors=('picker_editor',),
            is_organization_private=True,
            organizations=('Gamma',),
        )
        response = self._edit_page(contest)
        self.assertContains(response, 'data-problem-src')
        self.assertContains(response, _('Organization problems'))
        self.assertContains(response, _('Public problems'))
        self.assertContains(response, reverse('org_problem_select2', args=[self.org.id]))
        self.assertContains(response, reverse('public_problem_select2'))

    def test_global_contest_keeps_the_normal_picker(self):
        contest = create_contest(key='global_contest', authors=('picker_editor',))
        response = self._edit_page(contest)
        self.assertNotContains(response, 'data-problem-src')
        self.assertNotContains(response, _('Organization problems'))

    def test_public_contest_with_one_org_keeps_general_picker(self):
        contest = create_contest(key='public_org', authors=('picker_editor',), is_organization_private=False,
                                 organizations=('Gamma',))
        response = self._edit_page(contest)
        self.assertNotContains(response, 'data-problem-src')
        self.assertNotContains(response, reverse('org_problem_select2', args=[self.org.pk]))

    def test_multi_organization_contest_falls_back_to_normal_picker(self):
        """Never silently pick organizations.first() when the context is ambiguous."""
        contest = create_contest(
            key='multi_org_contest',
            authors=('picker_editor',),
            is_organization_private=True,
            organizations=('Gamma', 'Delta'),
        )
        response = self._edit_page(contest)
        self.assertEqual(contest.organizations.count(), 2)
        self.assertNotContains(response, 'data-problem-src')
        self.assertNotContains(response, _('Organization problems'))


@override_settings(MOSS_API_KEY=None)
class ContestEditPickerInitialTabTestCase(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.editor = create_user(
            username='tab_editor',
            user_permissions=('edit_own_contest',),
        )
        cls.org = create_organization(name='Epsilon', admins=('tab_editor',))
        cls.contest = create_contest(
            key='tab_contest',
            authors=('tab_editor',),
            is_organization_private=True,
            organizations=('Epsilon',),
        )

    def _edit_html(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse('contest_edit', args=[self.contest.key]))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_selected_organization_problem_initializes_on_org_tab(self):
        from judge.models.tests.util import create_contest_problem
        problem = create_problem(
            code='epsprob',
            name='Epsilon Problem',
            is_public=True,
            is_organization_private=True,
            organizations=('Epsilon',),
        )
        create_contest_problem(contest=self.contest, problem=problem, order=1)

        html = self._edit_html()
        self.assertIn('data-problem-src="org"', html)
        self.assertIn('[epsprob] Epsilon Problem', html)

    def test_selected_public_problem_initializes_on_public_tab(self):
        from judge.models.tests.util import create_contest_problem
        problem = create_problem(code='plainprob', name='Plain Problem', is_public=True)
        create_contest_problem(contest=self.contest, problem=problem, order=1)

        html = self._edit_html()
        self.assertIn('data-problem-src="public"', html)
        self.assertIn('[plainprob] Plain Problem', html)


@override_settings(MOSS_API_KEY=None)
class ContestCreateOrganizationPickerTestCase(TestCase):
    """The split picker must also be available while *creating* an organization contest."""

    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.org_admin = create_user(
            username='create_org_admin',
            user_permissions=('create_private_contest', 'add_contest'),
        )
        cls.outsider = create_user(username='create_outsider')
        cls.org = create_organization(name='Zeta', admins=('create_org_admin',))
        cls.org_problem = create_problem(
            code='zetaprob',
            name='Zeta Problem',
            is_public=True,
            is_organization_private=True,
            organizations=('Zeta',),
        )

    def _url(self):
        return reverse('contest_create_organization', args=[self.org.slug])

    def _create_page(self):
        self.client.force_login(self.org_admin)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        return response

    def test_create_page_enables_the_split_picker(self):
        self.assertContains(self._create_page(), 'data-problem-src')

    def test_create_page_offers_both_problem_sources(self):
        response = self._create_page()
        self.assertContains(response, _('Organization problems'))
        self.assertContains(response, _('Public problems'))

    def test_org_endpoint_points_at_this_organization(self):
        response = self._create_page()
        self.assertContains(response, reverse('org_problem_select2', args=[self.org.id]))

    def test_public_endpoint_is_present(self):
        self.assertContains(self._create_page(), reverse('public_problem_select2'))

    def test_org_endpoint_is_not_another_organization(self):
        other = create_organization(name='Eta', admins=('create_org_admin',))
        response = self._create_page()
        self.assertNotContains(response, reverse('org_problem_select2', args=[other.id]))

    def test_non_admin_cannot_open_the_create_page(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 403)

    @patch('judge.views.contests.on_new_contest')
    def test_creating_a_contest_still_works(self, mock_on_new_contest):
        self.client.force_login(self.org_admin)
        now = timezone.now()
        response = self.client.post(self._url(), {
            'key': 'zeta_picker',
            'name': 'Zeta Picker Contest',
            'start_time': (now + timezone.timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': (now + timezone.timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S'),
            'scoreboard_visibility': Contest.SCOREBOARD_VISIBLE,
            'format_name': 'default',
            'description': '',
            'contest_problems-TOTAL_FORMS': '1',
            'contest_problems-INITIAL_FORMS': '0',
            'contest_problems-MIN_NUM_FORMS': '0',
            'contest_problems-MAX_NUM_FORMS': '1000',
            'contest_problems-0-problem': str(self.org_problem.id),
            'contest_problems-0-points': '100',
            'contest_problems-0-order': '1',
            'contest_problems-0-max_submissions': '',
        })

        self.assertEqual(response.status_code, 302, getattr(response, 'context', None))
        contest = Contest.objects.get(key='zeta_picker')
        self.assertTrue(contest.is_organization_private)
        self.assertEqual(list(contest.organizations.all()), [self.org])
        self.assertEqual(
            list(contest.contest_problems.values_list('problem_id', flat=True)),
            [self.org_problem.id],
        )


@override_settings(MOSS_API_KEY=None)
class ContestProblemPolicyAndBoundStateTestCase(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.student_a = create_user(
            username='member_a',
            user_permissions=('add_contest', 'edit_own_contest'),
        )
        cls.tester_user = create_user(
            username='only_tester',
            user_permissions=('add_contest', 'edit_own_contest'),
        )
        cls.dual_admin = create_user(
            username='dual_org_admin',
            user_permissions=('create_private_contest', 'add_contest', 'edit_own_contest'),
        )
        cls.org_a = create_organization(name='PolicyOrgA', admins=('dual_org_admin',))
        cls.org_b = create_organization(name='PolicyOrgB', admins=('dual_org_admin',))
        cls.org_a.members.add(cls.student_a.profile)

        cls.public_prob = create_problem(code='pol_pub', name='Policy Public', is_public=True)
        cls.org_a_prob = create_problem(
            code='pol_orga',
            name='Policy Org A',
            is_public=True,
            is_organization_private=True,
            organizations=('PolicyOrgA',),
        )
        cls.org_b_prob = create_problem(
            code='pol_orgb',
            name='Policy Org B',
            is_public=True,
            is_organization_private=True,
            organizations=('PolicyOrgB',),
        )
        cls.tester_only_prob = create_problem(
            code='pol_secret',
            name='Policy Secret',
            is_public=False,
            testers=('only_tester',),
        )

    def _base_post(self, key, name, problem_id, order='1', points='100', max_submissions=''):
        now = timezone.now()
        return {
            'key': key,
            'name': name,
            'start_time': (now + timezone.timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': (now + timezone.timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S'),
            'scoreboard_visibility': Contest.SCOREBOARD_VISIBLE,
            'format_name': 'default',
            'description': '',
            'contest_problems-TOTAL_FORMS': '1',
            'contest_problems-INITIAL_FORMS': '0',
            'contest_problems-MIN_NUM_FORMS': '0',
            'contest_problems-MAX_NUM_FORMS': '1000',
            'contest_problems-0-problem': str(problem_id),
            'contest_problems-0-points': points,
            'contest_problems-0-order': order,
            'contest_problems-0-max_submissions': max_submissions,
        }

    def test_org_member_cannot_inject_org_private_problem_into_global_contest(self):
        self.client.force_login(self.student_a)
        response = self.client.post(
            reverse('contest_new'),
            self._base_post('student_global', 'Student Global', self.org_a_prob.id),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Contest.objects.filter(key='student_global').exists())

    def test_tester_cannot_inject_unpublished_problem_into_own_contest(self):
        self.client.force_login(self.tester_user)
        response = self.client.post(
            reverse('contest_new'),
            self._base_post('tester_global', 'Tester Global', self.tester_only_prob.id),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Contest.objects.filter(key='tester_global').exists())

    def test_dual_admin_cannot_inject_org_b_problem_into_org_a_contest(self):
        self.client.force_login(self.dual_admin)
        response = self.client.post(
            reverse('contest_create_organization', args=[self.org_a.slug]),
            self._base_post('policyorga_leak', 'Org A Contest', self.org_b_prob.id),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Contest.objects.filter(key='policyorga_leak').exists())
        # Must not leak the unauthorized problem's title back into the rendered option.
        self.assertNotContains(response, '[pol_orgb] Policy Org B')

    def test_org_create_validation_error_preserves_valid_bound_problem_selection(self):
        self.client.force_login(self.dual_admin)
        # Missing required org key prefix triggers ContestForm validation error
        # while the chosen public problem on row 0 is valid and must be preserved.
        data = self._base_post('bad_prefix', 'Org A Contest', self.public_prob.id, points='75', max_submissions='5')
        response = self.client.post(reverse('contest_create_organization', args=[self.org_a.slug]), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '[pol_pub] Policy Public')
        self.assertContains(response, 'data-problem-src="public"')
        self.assertContains(response, 'value="75"')
        self.assertContains(response, 'value="5"')

    def test_edit_contest_preserves_new_selection_on_error_and_allows_deleting_legacy_row(self):
        from judge.models.tests.util import create_contest_problem
        contest = create_contest(
            key='policyorga_edit',
            authors=('dual_org_admin',),
            is_organization_private=True,
            organizations=('PolicyOrgA',),
        )
        legacy_cp = create_contest_problem(contest=contest, problem=self.org_b_prob, order=1)

        self.client.force_login(self.dual_admin)
        url = reverse('contest_edit', args=[contest.key])
        now = timezone.now()

        # 1. Duplicate order error while adding a valid org A problem on row 1 -> preserves row 1 selection!
        dup_data = {
            'key': contest.key,
            'name': contest.name,
            'start_time': (now + timezone.timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': (now + timezone.timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S'),
            'scoreboard_visibility': Contest.SCOREBOARD_VISIBLE,
            'format_name': 'default',
            'description': '',
            'contest_problems-TOTAL_FORMS': '2',
            'contest_problems-INITIAL_FORMS': '1',
            'contest_problems-MIN_NUM_FORMS': '0',
            'contest_problems-MAX_NUM_FORMS': '1000',
            'contest_problems-0-id': str(legacy_cp.id),
            'contest_problems-0-problem': str(self.org_b_prob.id),
            'contest_problems-0-points': '100',
            'contest_problems-0-order': '1',
            'contest_problems-0-max_submissions': '',
            'contest_problems-1-id': '',
            'contest_problems-1-problem': str(self.org_a_prob.id),
            'contest_problems-1-points': '200',
            'contest_problems-1-order': '1',
            'contest_problems-1-max_submissions': '3',
        }
        response = self.client.post(url, dup_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '[pol_orga] Policy Org A')
        self.assertContains(response, 'value="200"')
        self.assertContains(response, 'value="3"')

        # 2. Deleting legacy out-of-policy row 0 while keeping valid row 1 succeeds!
        fix_data = dict(dup_data)
        fix_data['contest_problems-0-DELETE'] = 'on'
        fix_data['contest_problems-1-order'] = '2'
        response = self.client.post(url, fix_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(contest.contest_problems.values_list('problem_id', flat=True)),
            [self.org_a_prob.id],
        )
