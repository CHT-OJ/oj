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
