from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from judge.forms import ProblemSubmitForm
from judge.models import ContestParticipation, Judge, Language, Submission, SubmissionSource
from judge.models.tests.util import create_contest, create_contest_problem, create_problem, create_user


@override_settings(MOSS_API_KEY=None)
class ProblemTwoTabAndSubmitTestCase(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls._now = timezone.now()
        cls.user = create_user(username='tab_solver')
        cls.muted_user = create_user(username='tab_muted')
        cls.muted_user.profile.mute = True
        cls.muted_user.profile.save(update_fields=['mute'])
        cls.author = create_user(username='tab_author')
        cls.contest_author = create_user(username='tab_contest_author')

        cls.cpp = Language.objects.filter(file_only=False).order_by('id').first()
        cls.py = Language.objects.filter(file_only=False).exclude(id=cls.cpp.id).order_by('id').first()
        cls.file_lang, _ = Language.objects.get_or_create(
            key='SCRATCH',
            defaults={
                'name': 'Scratch',
                'short_name': 'SB3',
                'common_name': 'Scratch',
                'ace': 'text',
                'pygments': 'text',
                'extension': 'sb3',
                'file_only': True,
                'file_size_limit': 5,
            },
        )
        if not cls.file_lang.file_only:
            cls.file_lang.file_only = True
            cls.file_lang.extension = 'sb3'
            cls.file_lang.file_size_limit = 5
            cls.file_lang.save()

        cls.user.profile.language = cls.cpp
        cls.user.profile.save(update_fields=['language'])

        cls.problem = create_problem(
            code='tab_prob_1',
            name='Tab Problem 1',
            is_public=True,
            authors=('tab_author',),
        )
        cls.problem.allowed_languages.set([cls.cpp, cls.py, cls.file_lang])

        cls.problem_2 = create_problem(
            code='tab_prob_2',
            name='Tab Problem 2',
            is_public=True,
            authors=('tab_author',),
        )
        cls.problem_2.allowed_languages.set([cls.cpp, cls.py])

        cls.judge = Judge.objects.create(name='tab_test_judge', online=True, auth_key='secret')
        cls.judge.runtimes.set([cls.cpp, cls.py, cls.file_lang])
        cls.judge.problems.set([cls.problem, cls.problem_2])

    def _detail_url(self, problem=None):
        return reverse('problem_detail', args=[(problem or self.problem).code])

    def test_guest_sees_comments_tab_only_with_unique_comments_id(self):
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('class="problem-tabs"', html)
        self.assertNotIn('id="inline-submit"', html)
        self.assertNotIn('id="submit-panel"', html)
        self.assertIn('id="comments-panel"', html)
        self.assertEqual(html.count('id="comments"'), 1)

    def test_authenticated_user_defaults_to_submit_tab_and_loads_ace_once(self):
        self.client.force_login(self.user)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="problem-tab-submit"', html)
        self.assertIn('id="submit-panel"', html)
        self.assertIn('id="comments-panel"', html)
        self.assertEqual(html.count('id="comments"'), 1)
        # Martor already loads plugins/js/ace.js when comments are unlocked, so CDN ace.js must not be loaded again.
        self.assertNotIn('/ace.js"></script>', html.replace('plugins/js/ace.js', ''))
        # Right-aligned report issue button inside .problem-tabs-actions, not colliding in title_row.
        self.assertIn('class="problem-tabs-actions"', html)
        self.assertIn(reverse('new_problem_ticket', args=[self.problem.code]), html)

    def test_muted_user_does_not_see_clarify_or_issue_button(self):
        self.client.force_login(self.muted_user)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'class="problem-tabs-actions"')

    @patch.object(Submission, 'judge')
    def test_inline_submit_valid_creates_single_submission_and_redirects(self, mock_judge):
        self.client.force_login(self.user)
        before = Submission.objects.count()
        response = self.client.post(self._detail_url(), {
            'submit_solution': '1',
            'source': 'print(1)',
            'language': str(self.py.id),
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Submission.objects.count(), before + 1)
        sub = Submission.objects.latest('id')
        self.assertEqual(sub.language_id, self.py.id)
        self.assertEqual(sub.source.source, 'print(1)')
        self.assertEqual(response['Location'], reverse('submission_status', args=[sub.id]))
        mock_judge.assert_called_once()

    def test_inline_submit_invalid_keeps_submit_tab_active_and_preserves_language(self):
        self.client.force_login(self.user)
        response = self.client.post(self._detail_url(), {
            'submit_solution': '1',
            'source': '',
            'language': str(self.py.id),
        })
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('data-has-errors="true"', html)
        self.assertIn('id="problem-tab-submit" role="tab" href="#submit" data-tab="submit"', html)
        # Selected non-default language (py) must remain selected on the re-rendered form.
        self.assertIn(f'value="{self.py.id}"', html)
        self.assertRegex(html, rf'<option value="{self.py.id}"[^>]*selected>')

    def test_invalid_comment_post_keeps_comments_tab_active(self):
        self.client.force_login(self.user)
        response = self.client.post(self._detail_url(), {
            'body': '',
            'parent': '',
        })
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('data-has-errors="true"', html)
        self.assertIn(
            'id="comments-panel" role="tabpanel" aria-labelledby="problem-tab-comments"\n'
            '         class="problem-tab-panel active"',
            html,
        )

    def test_standalone_submit_and_resubmit_prefill_source(self):
        self.client.force_login(self.user)
        sub = Submission.objects.create(user=self.user.profile, problem=self.problem, language=self.py)
        SubmissionSource.objects.create(submission=sub, source='print(42)')

        standalone = self.client.get(reverse('problem_submit', args=[self.problem.code]))
        self.assertEqual(standalone.status_code, 200)
        self.assertContains(standalone, '/ace.js"></script>')

        resubmit = self.client.get(reverse('problem_submit', args=[self.problem.code, sub.id]))
        self.assertEqual(resubmit.status_code, 200)
        self.assertContains(resubmit, 'print(42)')
        self.assertRegex(resubmit.content.decode(), rf'<option value="{self.py.id}"[^>]*selected>')

    def test_live_vs_virtual_contest_sidebar_clarification_and_assignees(self):
        contest = create_contest(
            key='tab_live_contest',
            start_time=self._now - timezone.timedelta(hours=1),
            end_time=self._now + timezone.timedelta(hours=2),
            is_visible=True,
            use_clarifications=True,
            authors=('tab_contest_author',),
        )
        # Deliberately give both problems the same order to verify deterministic (order, pk) sorting.
        cp1 = create_contest_problem(contest=contest, problem=self.problem, order=1, max_submissions=10)
        cp2 = create_contest_problem(contest=contest, problem=self.problem_2, order=1, max_submissions=10)
        self.assertLess(cp1.pk, cp2.pk)

        part = ContestParticipation.objects.create(
            contest=contest,
            user=self.user.profile,
            virtual=ContestParticipation.LIVE,
            real_start=self._now - timezone.timedelta(minutes=10),
        )
        self.user.profile.current_contest = part
        self.user.profile.save(update_fields=['current_contest'])

        self.client.force_login(self.user)
        response = self.client.get(self._detail_url(self.problem))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="contest-problems-list"', html)
        self.assertIn('class="contest-problem-nav"', html)
        self.assertIn('aria-current="page"', html)
        self.assertEqual(response.context_data['contest_codes'], [self.problem.code, self.problem_2.code])
        self.assertTrue(response.context_data['can_request_clarification'])
        self.assertFalse(response.context_data['can_report_issue'])
        # Comment lock disables Martor, so submit-js must load ACE_URL/ace.js once.
        self.assertContains(response, '/ace.js"></script>')

        # Virtual participation must NOT get contest clarification mode or assign tickets to contest authors.
        vpart = ContestParticipation.objects.create(
            contest=contest,
            user=self.user.profile,
            virtual=1,
            real_start=self._now - timezone.timedelta(minutes=5),
        )
        self.user.profile.current_contest = vpart
        self.user.profile.save(update_fields=['current_contest'])
        vresp = self.client.get(self._detail_url(self.problem))
        self.assertEqual(vresp.status_code, 200)
        self.assertFalse(vresp.context_data['can_request_clarification'])
        self.assertTrue(vresp.context_data['can_report_issue'])

    def test_code_and_file_only_form_validation_matrix(self):
        # 1. Code language with source, no file -> valid
        f1 = ProblemSubmitForm(data={'language': self.cpp.id, 'source': 'int main(){}'})
        self.assertTrue(f1.is_valid(), f1.errors)

        # 2. Code language with empty source -> invalid
        f2 = ProblemSubmitForm(data={'language': self.cpp.id, 'source': ''})
        self.assertFalse(f2.is_valid())

        # 3. Code language with unexpected file -> invalid
        sb3 = SimpleUploadedFile('proj.sb3', b'dummy', content_type='application/octet-stream')
        f3 = ProblemSubmitForm(data={'language': self.cpp.id, 'source': ''}, files={'submission_file': sb3})
        self.assertFalse(f3.is_valid())

        # 4. File-only language with valid extension file, empty source -> valid
        sb3_ok = SimpleUploadedFile('solution.sb3', b'not-a-zip-or-raw', content_type='application/octet-stream')
        f4 = ProblemSubmitForm(data={'language': self.file_lang.id, 'source': ''}, files={'submission_file': sb3_ok})
        self.assertTrue(f4.is_valid(), f4.errors)

        # 5. File-only language with no file -> invalid
        f5 = ProblemSubmitForm(data={'language': self.file_lang.id, 'source': ''})
        self.assertFalse(f5.is_valid())

        # 6. File-only language with both source and file -> invalid
        sb3_both = SimpleUploadedFile('solution.sb3', b'data', content_type='application/octet-stream')
        f6 = ProblemSubmitForm(
            data={'language': self.file_lang.id, 'source': 'code'},
            files={'submission_file': sb3_both},
        )
        self.assertFalse(f6.is_valid())
