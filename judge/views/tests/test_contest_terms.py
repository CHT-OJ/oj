from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from judge.models import ContestParticipation
from judge.models.tests.util import create_contest, create_user

TERMS = 'You must not cheat.'
CODE = 's3cr3t'


class ContestEntryFormTestCaseMixin:
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()
        cls.user = create_user(username='entrant')
        # Terms/access-code bypass keys off can_edit, which needs the edit permission
        # in addition to authorship.
        cls.editor = create_user(username='entry_editor', user_permissions=('edit_own_contest',))

    def _join_url(self, contest):
        return reverse('contest_join', args=[contest.key])

    def _register_url(self, contest):
        return reverse('contest_register', args=[contest.key])

    def _make_contest(self, key, **kwargs):
        kwargs.setdefault('is_visible', True)
        kwargs.setdefault('authors', ('entry_editor',))
        return create_contest(key=key, **kwargs)

    def _participations(self, contest, user=None):
        return ContestParticipation.objects.filter(contest=contest, user=(user or self.user).profile)


class ContestJoinEntryTestCase(ContestEntryFormTestCaseMixin, TestCase):
    def test_no_terms_no_access_code_joins_directly(self):
        contest = self._make_contest('plain')
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self._participations(contest).exists())

    def test_terms_only_rejects_unchecked_agreement(self):
        contest = self._make_contest('terms_only', terms=TERMS)
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, _('You must agree to the terms to continue.'))
        self.assertFalse(self._participations(contest).exists())

    def test_terms_only_accepts_checked_agreement(self):
        contest = self._make_contest('terms_only_ok', terms=TERMS)
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest), {'terms_agreed': 'on'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self._participations(contest).exists())

    def test_access_code_only_rejects_wrong_code(self):
        contest = self._make_contest('code_only', access_code=CODE)
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest), {'access_code': 'nope'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, _('Wrong access code.'))
        self.assertFalse(self._participations(contest).exists())

    def test_access_code_only_accepts_right_code(self):
        contest = self._make_contest('code_only_ok', access_code=CODE)
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest), {'access_code': CODE})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self._participations(contest).exists())

    def test_terms_and_access_code_coexist_on_one_screen(self):
        contest = self._make_contest('both', terms=TERMS, access_code=CODE)
        self.client.force_login(self.user)
        response = self.client.get(self._join_url(contest))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, TERMS)
        self.assertContains(response, 'name="terms_agreed"')
        self.assertContains(response, 'name="access_code"')

    def test_both_requires_terms_even_with_right_code(self):
        contest = self._make_contest('both_code_ok', terms=TERMS, access_code=CODE)
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest), {'access_code': CODE})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, _('You must agree to the terms to continue.'))
        self.assertFalse(self._participations(contest).exists())

    def test_both_requires_code_even_with_terms_agreed(self):
        contest = self._make_contest('both_terms_ok', terms=TERMS, access_code=CODE)
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest), {'terms_agreed': 'on'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, _('Wrong access code.'))
        self.assertFalse(self._participations(contest).exists())

    def test_both_satisfied_joins(self):
        contest = self._make_contest('both_ok', terms=TERMS, access_code=CODE)
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest),
                                    {'terms_agreed': 'on', 'access_code': CODE})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self._participations(contest).exists())

    def test_terms_are_rendered_as_markdown_with_references(self):
        contest = self._make_contest('md_terms', terms='# Rule one')
        self.client.force_login(self.user)
        response = self.client.get(self._join_url(contest))
        self.assertContains(response, 'Rule one')
        # Markdown was actually rendered, not emitted verbatim.
        self.assertNotContains(response, '# Rule one')

    def test_editor_bypasses_terms_and_access_code(self):
        contest = self._make_contest('editor_bypass', terms=TERMS, access_code=CODE)
        self.client.force_login(self.editor)
        response = self.client.post(self._join_url(contest))
        self.assertEqual(response.status_code, 302)
        participation = self._participations(contest, self.editor).get()
        self.assertEqual(participation.virtual, ContestParticipation.SPECTATE)

    def test_editor_entry_form_hides_terms_and_access_code(self):
        contest = self._make_contest('editor_form', terms=TERMS, access_code=CODE)
        self.client.force_login(self.editor)
        response = self.client.get(self._join_url(contest))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, TERMS)
        self.assertNotContains(response, 'name="terms_agreed"')
        self.assertNotContains(response, 'name="access_code"')

    def test_virtual_join_after_end_still_enforces_terms(self):
        contest = self._make_contest(
            'ended_terms',
            terms=TERMS,
            start_time=self.now - timezone.timedelta(days=10),
            end_time=self.now - timezone.timedelta(days=1),
        )
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, _('You must agree to the terms to continue.'))
        self.assertFalse(self._participations(contest).exists())

    def test_virtual_join_after_end_succeeds_once_terms_agreed(self):
        contest = self._make_contest(
            'ended_terms_ok',
            terms=TERMS,
            start_time=self.now - timezone.timedelta(days=10),
            end_time=self.now - timezone.timedelta(days=1),
        )
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest), {'terms_agreed': 'on'})
        self.assertEqual(response.status_code, 302)
        participation = self._participations(contest).get()
        self.assertEqual(participation.virtual, 1)

    def test_disallow_virtual_still_blocks_after_terms(self):
        contest = self._make_contest(
            'no_virtual',
            terms=TERMS,
            disallow_virtual=True,
            start_time=self.now - timezone.timedelta(days=10),
            end_time=self.now - timezone.timedelta(days=1),
        )
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest), {'terms_agreed': 'on'})
        self.assertContains(response, _('Virtual joining is not allowed for this contest.'))
        self.assertFalse(self._participations(contest).exists())

    def test_banned_user_still_blocked_after_terms(self):
        banned = create_user(username='banned_entrant')
        contest = self._make_contest('banned', terms=TERMS, banned_users=('banned_entrant',))
        self.client.force_login(banned)
        response = self.client.post(self._join_url(contest), {'terms_agreed': 'on'})
        self.assertContains(response, _('Banned from joining'))
        self.assertFalse(self._participations(contest, banned).exists())


class ContestRegisterEntryTestCase(ContestEntryFormTestCaseMixin, TestCase):
    def _registerable(self, key, **kwargs):
        kwargs.setdefault('start_time', self.now + timezone.timedelta(days=5))
        kwargs.setdefault('end_time', self.now + timezone.timedelta(days=10))
        kwargs.setdefault('registration_start', self.now - timezone.timedelta(days=1))
        kwargs.setdefault('registration_end', self.now + timezone.timedelta(days=1))
        return self._make_contest(key, **kwargs)

    def test_register_without_terms_or_code(self):
        contest = self._registerable('reg_plain')
        self.client.force_login(self.user)
        response = self.client.post(self._register_url(contest))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self._participations(contest).exists())

    def test_register_rejects_unchecked_terms(self):
        contest = self._registerable('reg_terms', terms=TERMS)
        self.client.force_login(self.user)
        response = self.client.post(self._register_url(contest))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, _('You must agree to the terms to continue.'))
        self.assertFalse(self._participations(contest).exists())

    def test_register_rejects_wrong_access_code(self):
        contest = self._registerable('reg_code', access_code=CODE)
        self.client.force_login(self.user)
        response = self.client.post(self._register_url(contest), {'access_code': 'bad'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, _('Wrong access code.'))
        self.assertFalse(self._participations(contest).exists())

    def test_register_with_terms_and_code(self):
        contest = self._registerable('reg_both', terms=TERMS, access_code=CODE)
        self.client.force_login(self.user)
        response = self.client.post(self._register_url(contest),
                                    {'terms_agreed': 'on', 'access_code': CODE})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self._participations(contest).exists())

    def test_editor_cannot_register_even_with_terms(self):
        contest = self._registerable('reg_editor', terms=TERMS)
        self.client.force_login(self.editor)
        response = self.client.post(self._register_url(contest))
        self.assertContains(response, _('You cannot register for this contest.'))
        self.assertFalse(self._participations(contest, self.editor).exists())

    def test_registration_window_still_enforced_after_terms(self):
        contest = self._registerable(
            'reg_closed',
            terms=TERMS,
            registration_start=self.now - timezone.timedelta(days=5),
            registration_end=self.now - timezone.timedelta(days=2),
        )
        self.client.force_login(self.user)
        response = self.client.post(self._register_url(contest), {'terms_agreed': 'on'})
        self.assertContains(response, _('You cannot register for this contest now.'))
        self.assertFalse(self._participations(contest).exists())

    def test_registration_not_required_still_reported_after_terms(self):
        contest = self._make_contest(
            'reg_not_required',
            terms=TERMS,
            start_time=self.now + timezone.timedelta(days=5),
            end_time=self.now + timezone.timedelta(days=10),
        )
        self.client.force_login(self.user)
        response = self.client.post(self._register_url(contest), {'terms_agreed': 'on'})
        self.assertContains(response, _('Registration is not required for this contest.'))
        self.assertFalse(self._participations(contest).exists())


class ContestTermsServerSideTestCase(ContestEntryFormTestCaseMixin, TestCase):
    def test_terms_validation_is_server_side(self):
        """A client that never renders the form still cannot bypass the terms."""
        contest = self._make_contest('server_side', terms=TERMS)
        self.client.force_login(self.user)
        # Post a bogus payload straight at the endpoint, skipping the form entirely.
        response = self.client.post(self._join_url(contest), {'terms_agreed': ''})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self._participations(contest).exists())

    def test_access_code_validation_is_server_side(self):
        contest = self._make_contest('server_side_code', access_code=CODE)
        self.client.force_login(self.user)
        response = self.client.post(self._join_url(contest), {'access_code': ''})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self._participations(contest).exists())

    def test_terms_field_defaults_to_blank(self):
        contest = self._make_contest('blank_terms')
        self.assertEqual(contest.terms, '')
