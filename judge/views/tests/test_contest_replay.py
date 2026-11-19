from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from judge.contest_replay import replay_data
from judge.models import Contest, ContestParticipation, ContestSubmission, Submission, SubmissionTestCase
from judge.models.tests.util import create_contest, create_contest_problem, create_problem, create_user


class ReplayTest(TestCase):
    fixtures = ['language_all.json', 'navbar.json']

    @classmethod
    def setUpTestData(cls):
        cls.user = create_user(username='official')
        cls.now = timezone.now().replace(microsecond=0)
        cls.contest = create_contest('history', is_visible=True, start_time=cls.now - timedelta(days=2),
                                     end_time=cls.now - timedelta(days=1))
        cls.part = ContestParticipation.objects.create(contest=cls.contest, user=cls.user.profile)
        cls.problems = [create_contest_problem(cls.contest, create_problem(code), order=i)
                        for i, code in enumerate(('taska', 'taskb'))]

    def attempt(self, problem_index, seconds, points, verdict, batches=(), part=None):
        part = part or self.part
        cp = self.problems[problem_index]
        sub = Submission.objects.create(problem=cp.problem, user=part.user, language=self.user.profile.language,
                                        result=verdict, status='D' if verdict != 'CE' else 'CE')
        Submission.objects.filter(pk=sub.pk).update(date=part.start + timedelta(seconds=seconds))
        ContestSubmission.objects.create(submission=sub, problem=cp, participation=part, points=points)
        for i, pts in enumerate(batches):
            SubmissionTestCase.objects.create(submission=sub, case=i + 1, batch=i + 1, status=verdict,
                                              points=pts, total=50)

    def test_every_checkpoint_matches_native_scorer(self):
        for seconds, pid, points, verdict, batches in [
            (3, 0, 0, 'CE', ()), (14, 0, 40, 'WA', (40, 0)), (65, 1, 100, 'AC', (50, 50)),
            (99, 0, 50, 'WA', (0, 50)), (130, 0, 40, 'WA', (40, 0)),
        ]:
            self.attempt(pid, seconds, points, verdict, batches)
            for fmt, config in [('default', {}), ('ioi', {}), ('ioi', {'last_score_altering': True}),
                                ('ioi', {'cumtime': True}), ('ioi16', {'cumtime': True}), ('ioi16', {}),
                                ('atcoder', {}), ('vnoj', {}), ('vnoj', {'LSO': True}), ('ecoo', {})]:
                with self.subTest(seconds=seconds, fmt=fmt, config=config):
                    Contest.objects.filter(pk=self.contest.pk).update(format_name=fmt, format_config=config)
                    contest = Contest.objects.get(pk=self.contest.pk)
                    part = contest.users.get(pk=self.part.pk)
                    part.recompute_results()
                    part.refresh_from_db()
                    history = replay_data(contest)['rows'][part.id]['events']
                    self.assertEqual(tuple(history[-1][3:]) if history else (0, 0, 0),
                                     (part.score, part.cumtime, part.tiebreaker))

    def test_virtual_is_only_compared_to_live_participants_of_this_contest(self):
        player = create_user('virtualplayer')
        rival = create_user('othervirtual')
        mine = ContestParticipation.objects.create(contest=self.contest, user=player.profile, virtual=1,
                                                   real_start=self.now - timedelta(seconds=15))
        ContestParticipation.objects.create(contest=self.contest, user=rival.profile, virtual=2)
        self.attempt(0, 10, 10, 'WA', part=mine)
        player.profile.current_contest = mine
        player.profile.save()
        self.client.force_login(player)
        url = reverse('contest_replay', args=[self.contest.key])
        self.assertContains(self.client.get(url), 'replay-data')
        data = self.client.get(url, {'own': 1}).json()
        self.assertEqual(set(data['rows']), {str(mine.pk)})
        self.assertEqual(data['rows'][str(mine.pk)]['events'][0][0], 10)
        self.assertEqual(set(replay_data(self.contest, mine)['rows']), {self.part.pk, mine.pk})

    def test_visibility_and_freeze_are_enforced_on_direct_requests(self):
        url = reverse('contest_replay', args=[self.contest.key])
        self.assertContains(self.client.get(url), 'replay-data')
        for changes in [{'scoreboard_visibility': Contest.SCOREBOARD_HIDDEN},
                        {'format_name': 'vnoj', 'frozen_last_minutes': 15},
                        {'format_name': 'icpc'}, {'end_time': self.now + timedelta(days=1)}]:
            with self.subTest(changes=changes):
                values = dict(scoreboard_visibility=Contest.SCOREBOARD_VISIBLE, format_name='default',
                              frozen_last_minutes=0, end_time=self.now - timedelta(days=1))
                values.update(changes)
                Contest.objects.filter(pk=self.contest.pk).update(**values)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.get(url, {'own': 1}).status_code, 403)
