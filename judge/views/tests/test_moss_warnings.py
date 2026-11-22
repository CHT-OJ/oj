from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import authenticate
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from requests import Timeout

from judge.models import ContestMoss, Profile, WarningLog
from judge.models.tests.util import create_contest, create_contest_participation, create_contest_problem, create_user


@override_settings(MOSS_API_KEY='fixture')
class MossWarningsTest(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user('moderator', is_superuser=True, is_staff=True)
        cls.alice = create_user('alice')
        cls.bob = create_user('bob')
        cls.outsider = create_user('outsider', is_staff=True, user_permissions=('moss_contest',))
        cls.contest = create_contest('spring', is_visible=True)
        create_contest_problem(cls.contest, 'task')
        for entrant in (cls.alice, cls.bob):
            create_contest_participation(cls.contest, entrant.profile)
        cls.report = ContestMoss.objects.create(contest=cls.contest, problem=cls.contest.problems.get(),
                                                language='C', submission_count=2, url='https://report.example/123/')
        cls.compute = reverse('compute_moss', args=[cls.contest.key])
        cls.clear = reverse('admin:judge_profile_clear_warnings', args=[cls.alice.profile.pk])

    def issue_warning(self, reason='Vi phạm'):
        return WarningLog.objects.create(offender=self.alice.profile, judge=self.admin.profile, reason=reason)

    def post_threshold(self, threshold=90):
        return self.client.post(self.compute, {'task': threshold}, content_type='application/json')

    def current_profile(self):
        return Profile.objects.select_related('user').get(pk=self.alice.profile.pk)

    @patch('judge.views.contests.get_requests')
    def test_moss_records_each_entrant_once_and_preserves_clear(self, fetch):
        fetch.return_value.content = (
            b'<TABLE><TR><TH>File 1<TH>File 2<TH>Lines Matched'
            b'<TR><TD><A>alice (90%)</A><TD><A>bob (95%)</A>'
            b'<TR><TD><A>alice (100%)</A><TD><A>outsider (97%)</A></TABLE>'
        )
        self.client.force_login(self.admin)
        page = self.client.get(reverse('contest_moss', args=[self.contest.key]))
        self.assertContains(page, self.compute)
        self.assertContains(page, 'data-problem="task"')
        self.assertCountEqual(self.post_threshold().json()['Result'], ['alice', 'bob'])
        fetch.assert_called_once_with(self.report.url, timeout=15)
        self.assertEqual(self.post_threshold().json()['Result'], [])
        self.assertEqual(self.current_profile().warn, 1)
        self.assertEqual(self.current_profile().warning_offender.get().judge, self.admin.profile)
        self.client.post(self.clear)
        self.assertEqual(self.post_threshold().json()['Result'], [])
        self.assertEqual(self.current_profile().warn, 0)
        self.assertTrue(self.current_profile().warning_offender.get().cleared)
        self.issue_warning()
        self.assertEqual(self.current_profile().warn, 1)

    @patch('judge.views.contests.get_requests')
    def test_historical_contest_warning_is_not_reissued(self, fetch):
        log = self.issue_warning('thí sinh moderator đã có hành vi chép bàitại contest #spring')
        fetch.return_value.content = b'<table><th>File 1</th><td><a>alice (100%)</a></td></table>'
        self.client.force_login(self.admin)
        self.assertEqual(self.post_threshold().json()['Result'], [])
        log.refresh_from_db()
        self.assertEqual(log.contest, self.contest)
        self.assertEqual(self.current_profile().warn, 1)

    @patch('judge.views.contests.get_requests')
    def test_threshold_permissions_and_failed_report(self, fetch):
        self.client.force_login(self.outsider)
        self.assertEqual(self.post_threshold().status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.post_threshold(101).status_code, 400)
        fetch.assert_not_called()
        fetch.return_value.content = b'<table><th>File 1</th><td><a>alice (89%)</a></td></table>'
        self.assertEqual(self.post_threshold().json()['Result'], [])
        ContestMoss.objects.create(contest=self.contest, problem=self.report.problem, language='Python',
                                   submission_count=2, url='https://report.example/124/')
        report = fetch.return_value
        report.content = b'<table><th>File 1</th><td><a>alice (95%)</a></td></table>'
        fetch.side_effect = [report, Timeout()]
        self.assertEqual(self.post_threshold().status_code, 502)
        self.assertFalse(WarningLog.objects.exists())

    def test_banner_deadlines_zero_and_anonymous(self):
        now = timezone.now()
        Profile.objects.filter(pk=self.alice.profile.pk).update(warn=1, last_warned=now)
        url = reverse('problem_list')
        banner = 'id="account-warning"'
        self.assertNotContains(self.client.get(url), banner)
        self.client.force_login(self.alice)
        with patch('judge.models.profile.timezone.now', return_value=now + timedelta(days=30) - timedelta(seconds=1)):
            self.assertContains(self.client.get(url), banner)
        with patch('judge.models.profile.timezone.now', return_value=now + timedelta(days=30)):
            self.assertNotContains(self.client.get(url), banner)
        profile = self.current_profile()
        self.assertEqual(profile.warn, 1)
        profile.warning_expires_at = now - timedelta(seconds=1)
        profile.save(update_fields=['warning_expires_at'])
        self.assertNotContains(self.client.get(url), banner)
        profile.warn, profile.warning_expires_at = 0, now + timedelta(days=90)
        profile.save(update_fields=['warn', 'warning_expires_at'])
        self.assertNotContains(self.client.get(url), banner)

    def test_fifth_warning_blocks_login_and_correction_lifts_only_warning_ban(self):
        self.alice.set_password('fixture-password')
        self.alice.save(update_fields=['password'])
        for i in range(4):
            self.issue_warning()
        self.assertIsNotNone(authenticate(username='alice', password='fixture-password'))
        fifth = self.issue_warning()
        profile = self.current_profile()
        self.assertEqual(profile.warn, 5)
        self.assertFalse(profile.user.is_active)
        self.assertEqual(profile.display_rank, 'banned')
        self.assertTrue(profile.is_unlisted)
        self.assertIsNone(authenticate(username='alice', password='fixture-password'))
        fifth.delete()
        self.assertEqual(self.current_profile().warn, 4)
        self.assertIsNotNone(authenticate(username='alice', password='fixture-password'))
        profile = self.current_profile()
        profile.ban_user('Quyết định riêng')
        self.issue_warning()
        self.client.force_login(self.admin)
        self.client.post(self.clear)
        profile = self.current_profile()
        self.assertFalse(profile.user.is_active)
        self.assertEqual(profile.ban_reason, 'Quyết định riêng')

    def test_admin_button_and_old_automatic_ban(self):
        profile = self.current_profile()
        profile.warn = 5
        profile.last_warned = timezone.now()
        profile.save()
        profile.ban_user(WarningLog.LEGACY_BAN_REASON)
        editor = create_user('profile_editor', is_staff=True, user_permissions=('change_profile',))
        for staff in (self.outsider, editor):
            self.client.force_login(staff)
            self.assertEqual(self.client.post(self.clear).status_code, 403)
        self.client.force_login(self.admin)
        page = self.client.get(reverse('admin:judge_profile_change', args=[profile.pk]))
        self.assertContains(page, 'formaction="%s"' % self.clear)
        self.assertEqual(self.client.get(self.clear).status_code, 405)
        self.assertEqual(self.client.post(self.clear).status_code, 302)
        profile = self.current_profile()
        self.assertTrue(profile.user.is_active)
        self.assertIsNone(profile.last_warned)
        self.assertEqual(profile.warn, 0)

    def test_deleting_log_preserves_unrelated_rank_and_hidden_status(self):
        Profile.objects.filter(pk=self.alice.profile.pk).update(display_rank='admin', is_unlisted=True)
        self.issue_warning().delete()
        profile = self.current_profile()
        self.assertEqual(profile.display_rank, 'admin')
        self.assertTrue(profile.is_unlisted)

    def test_deleting_a_cleared_record_cannot_decrement_a_later_warning(self):
        old = self.issue_warning()
        self.client.force_login(self.admin)
        self.client.post(self.clear)
        self.issue_warning()
        old.delete()
        self.assertEqual(self.current_profile().warn, 1)

    @override_settings(VNOJ_SHOULD_BAN_FOR_CHEATING_IN_CONTESTS=True, VNOJ_MAX_DISQUALIFICATIONS_BEFORE_BANNING=1)
    def test_overlapping_automatic_bans(self):
        participation = self.contest.users.get(user=self.alice.profile)
        for i in range(5):
            self.issue_warning()
        participation.is_disqualified = True
        participation.save(update_fields=['is_disqualified'])
        self.client.force_login(self.admin)
        self.client.post(self.clear)
        profile = self.current_profile()
        self.assertFalse(profile.user.is_active)
        self.assertNotEqual(profile.ban_reason, WarningLog.BAN_REASON)
        for i in range(5):
            self.issue_warning()
        participation.is_disqualified = False
        participation.save(update_fields=['is_disqualified'])
        participation.check_ban()
        self.assertEqual(self.current_profile().ban_reason, WarningLog.BAN_REASON)
        self.assertFalse(self.current_profile().user.is_active)
