from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from judge.contest_replay import replay_data
from judge.models import Contest, ContestParticipation, ContestSubmission, Submission, SubmissionTestCase
from judge.models.tests.util import create_contest, create_contest_problem, create_organization, create_problem, \
    create_user


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
                    self.assertEqual(tuple(history[-1][3:6]) if history else (0, 0, 0),
                                     (part.score, part.cumtime, part.tiebreaker))
                    cells = {str(event[1]): event[2] for event in history if event[2] is not None}
                    self.assertEqual(cells, part.format_data or {})

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
        ranking = reverse('contest_ranking', args=[self.contest.key])
        self.assertRedirects(self.client.get(url), ranking)
        self.assertContains(self.client.get(ranking), 'id="replay-options"')
        data = self.client.get(url, {'own': 1}).json()
        self.assertEqual(set(data['rows']), {str(mine.pk)})
        self.assertEqual(data['rows'][str(mine.pk)]['events'][0][0], 10)
        self.assertEqual(set(self.client.get(url, {'data': 1}).json()['rows']), {str(self.part.pk), str(mine.pk)})
        self.assertNotIn('contest', data)

    def test_visibility_and_freeze_are_enforced_on_direct_requests(self):
        url = reverse('contest_replay', args=[self.contest.key])
        ranking = reverse('contest_ranking', args=[self.contest.key])
        self.assertRedirects(self.client.get(url), ranking)
        self.assertContains(self.client.get(ranking), 'id="replay-options"')
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
                self.assertEqual(self.client.get(url, {'data': 1}).status_code, 403)

    def test_show_virtual_uses_the_selected_cache_and_raw_table(self):
        virtual = create_user('cachevirtual')
        ContestParticipation.objects.create(contest=self.contest, user=virtual.profile, virtual=1)
        self.contest.scoreboard_cache_timeout = 60
        self.contest.save()
        url = reverse('contest_ranking', args=[self.contest.key])
        for enabled in ('false', 'true', 'false'):
            response = self.client.get(url, {'show_virtual': enabled, 'raw': 1})
            self.assertContains(response, 'class="fav-button')
            self.assertEqual(b'data-username="cachevirtual"' in response.content, enabled == 'true')

    def test_roster_queries_and_organization_visibility(self):
        listed = create_organization('School', is_unlisted=False)
        hidden = create_organization('Unlisted', is_unlisted=True)
        self.user.profile.organizations.add(hidden)
        for i in range(3):
            profile = create_user('team%d' % i).profile
            profile.organizations.add(listed)
            ContestParticipation.objects.create(contest=self.contest, user=profile)
        with self.assertNumQueries(5):
            rows = replay_data(self.contest)['rows']
        self.assertEqual(len(rows), 4)
        self.assertIsNone(rows[self.part.pk]['org'])
        self.assertEqual({r['org']['name'] for r in rows.values() if r['org']}, {'School'})

    def test_simultaneous_submissions_keep_the_native_order_tiebreak(self):
        self.attempt(0, 16, 20, 'WA')
        self.attempt(0, 16, 40, 'WA')
        events = replay_data(self.contest)['rows'][self.part.pk]['events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][2], {'points': 40, 'time': 16})
        self.assertEqual(events[0][7], 2)
