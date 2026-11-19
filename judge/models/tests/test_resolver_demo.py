from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Count
from django.test import TestCase, override_settings

from judge.management.commands.seed_resolver_demo import (
    CONTEST_BLUEPRINTS,
    DEMO_MARKER,
    DEMO_USERS,
    VNOJ_REFERENCE_SCORE_ROWS,
    VNOJ_REFERENCE_USERS,
)
from judge.models import Contest, ContestParticipation, ContestSubmission
from judge.resolver import build_resolver_payload


@override_settings(DEBUG=True, MOSS_API_KEY=None)
class ResolverDemoCommandTestCase(TestCase):
    fixtures = ['language_all.json']

    def test_seeds_real_submissions_freeze_cases_tie_and_disqualification(self):
        stdout = StringIO()
        call_command('seed_resolver_demo', stdout=stdout)

        self.assertIn('Resolver demo data is ready.', stdout.getvalue())
        password = next(
            line.rsplit(' / ', 1)[1]
            for line in stdout.getvalue().splitlines()
            if line.startswith('Director login: ')
        )
        self.assertNotEqual(password, 'resolver-demo')
        self.assertTrue(User.objects.get(username='resolver_director').check_password(password))
        self.assertTrue(all(
            not User.objects.get(username=username).has_usable_password()
            for username, _display_name in DEMO_USERS
        ))
        self.assertEqual(
            set(Contest.objects.filter(summary__contains=DEMO_MARKER).values_list('key', flat=True)),
            {blueprint['key'] for blueprint in CONTEST_BLUEPRINTS.values()},
        )

        for format_name, blueprint in CONTEST_BLUEPRINTS.items():
            expected_users = blueprint.get('users', DEMO_USERS)
            contest = Contest.objects.get(key=blueprint['key'])
            payload = build_resolver_payload(contest)

            self.assertTrue(contest.ended)
            self.assertEqual(contest.format_name, blueprint.get('format_name', format_name))
            self.assertEqual(contest.user_count, len(expected_users))
            self.assertEqual(len(payload['contestants']), len(expected_users))
            ranking = {
                participation.id: (
                    participation.is_disqualified,
                    -participation.score,
                    participation.cumtime,
                    participation.tiebreaker,
                    -participation.submission_count,
                )
                for participation in (
                    contest.users.filter(virtual=ContestParticipation.LIVE)
                    .annotate(submission_count=Count('submission'))
                )
            }
            actual_order = [contestant['participation_id'] for contestant in payload['contestants']]
            self.assertCountEqual(actual_order, ranking)
            self.assertEqual(
                [ranking[participation_id] for participation_id in actual_order],
                sorted(ranking.values()),
            )
            self.assertEqual(
                [contestant['final_order'] for contestant in payload['contestants']],
                list(range(len(expected_users))),
            )
            self.assertEqual(
                ContestSubmission.objects.filter(participation__contest=contest).count(),
                len(blueprint['submissions']),
            )
            self.assertFalse(contest.users.filter(format_data__isnull=True).exists())

            if 'resolver_hugo' in {username for username, _display_name in expected_users}:
                hugo = contest.users.get(user__user__username='resolver_hugo')
                self.assertTrue(hugo.is_disqualified)
                self.assertEqual((hugo.score, hugo.cumtime, hugo.tiebreaker), (-9999, 0, 0))

            if blueprint['frozen_last_minutes']:
                self.assertTrue(payload['contest']['official_freeze_available'])
                self.assertTrue(any(
                    cell['frozen'] and cell['frozen'].get('pending')
                    for contestant in payload['contestants']
                    for cell in contestant['problems'].values()
                ))
            else:
                self.assertFalse(payload['contest']['official_freeze_available'])

        icpc = Contest.objects.get(key=CONTEST_BLUEPRINTS['icpc']['key'])
        chen = icpc.users.get(user__user__username='resolver_chen')
        elena = icpc.users.get(user__user__username='resolver_elena')
        self.assertEqual(
            (chen.score, chen.cumtime, chen.tiebreaker),
            (elena.score, elena.cumtime, elena.tiebreaker),
        )
        self.assertNotEqual(chen.submissions.count(), elena.submissions.count())

        vnoj = Contest.objects.get(key=CONTEST_BLUEPRINTS['vnoj']['key'])
        gia = vnoj.users.get(user__user__username='resolver_gia')
        self.assertEqual((gia.score, gia.cumtime, gia.tiebreaker), (0, 0, 0))
        self.assertGreater(gia.submissions.count(), 0)

    def test_vnoj_reference_fixture_matches_csv_scores_and_has_drama(self):
        blueprint = CONTEST_BLUEPRINTS['vnoj_reference']
        call_command('seed_resolver_demo', format='vnoj_reference', stdout=StringIO())

        contest = Contest.objects.get(key=blueprint['key'])
        payload = build_resolver_payload(contest)
        contestants = {contestant['username']: contestant for contestant in payload['contestants']}

        self.assertEqual(contest.format_name, 'vnoj')
        self.assertEqual(contest.points_precision, 3)
        self.assertEqual(len(contestants), len(VNOJ_REFERENCE_USERS))
        self.assertEqual(set(contestants), {username for username, _display_name in VNOJ_REFERENCE_USERS})

        for rank, (username, _display_name) in enumerate(VNOJ_REFERENCE_USERS):
            contestant = contestants[username]
            expected_score = sum(score or 0 for score in VNOJ_REFERENCE_SCORE_ROWS[rank])
            self.assertAlmostEqual(contestant['final']['score'], expected_score, places=3)

        problem_ids = {problem['code']: str(problem['id']) for problem in payload['problems']}
        leader = contestants[VNOJ_REFERENCE_USERS[0][0]]
        self.assertEqual(leader['frozen']['score'], 13.875)
        self.assertEqual(leader['final']['score'], 15.975)
        self.assertEqual(leader['problems'][problem_ids['pe02_bus']]['frozen']['points'], 1.4)
        self.assertTrue(leader['problems'][problem_ids['pe02_bus']]['final']['pending'])

        zero_score = contestants[VNOJ_REFERENCE_USERS[20][0]]
        self.assertTrue(zero_score['problems'][problem_ids['pe02_bus']]['final']['pending'])
        self.assertEqual(zero_score['final']['score'], 0)

        tied = [contestants[VNOJ_REFERENCE_USERS[rank - 1][0]] for rank in (17, 18)]
        self.assertEqual(
            [
                (contestant['final']['score'], contestant['final']['cumtime'], contestant['final']['tiebreaker'])
                for contestant in tied
            ],
            [(6.475, 220 * 60, 220 * 60), (6.475, 220 * 60, 220 * 60)],
        )
        self.assertEqual(
            ContestSubmission.objects.filter(participation__contest=contest).count(),
            len(blueprint['submissions']),
        )

    def test_existing_data_is_kept_and_owned_contest_can_be_replaced(self):
        call_command('seed_resolver_demo', format='default', stdout=StringIO())
        contest = Contest.objects.get(key=CONTEST_BLUEPRINTS['default']['key'])
        original_id = contest.id
        original_counts = (
            Contest.objects.count(),
            ContestParticipation.objects.count(),
            ContestSubmission.objects.count(),
            User.objects.count(),
        )

        stdout = StringIO()
        call_command('seed_resolver_demo', format='default', stdout=stdout)
        self.assertIn('Kept existing resolver_demo_default', stdout.getvalue())
        self.assertEqual(original_counts, (
            Contest.objects.count(),
            ContestParticipation.objects.count(),
            ContestSubmission.objects.count(),
            User.objects.count(),
        ))

        call_command('seed_resolver_demo', format='default', replace=True, stdout=StringIO())
        replacement = Contest.objects.get(key=CONTEST_BLUEPRINTS['default']['key'])
        self.assertNotEqual(replacement.id, original_id)
        self.assertEqual(original_counts, (
            Contest.objects.count(),
            ContestParticipation.objects.count(),
            ContestSubmission.objects.count(),
            User.objects.count(),
        ))

    @patch('judge.management.commands.seed_resolver_demo.secrets.token_urlsafe')
    def test_generates_director_password_unless_explicitly_supplied(self, token_urlsafe):
        token_urlsafe.return_value = 'generated-local-password'
        stdout = StringIO()
        call_command('seed_resolver_demo', format='default', stdout=stdout)
        token_urlsafe.assert_called_once_with(24)
        self.assertEqual(stdout.getvalue().count('generated-local-password'), 1)
        self.assertTrue(
            User.objects.get(username='resolver_director').check_password('generated-local-password'),
        )

        explicit_stdout = StringIO()
        call_command(
            'seed_resolver_demo',
            format='default',
            director_password='explicit-local-password',
            stdout=explicit_stdout,
        )
        token_urlsafe.assert_called_once_with(24)
        self.assertEqual(explicit_stdout.getvalue().count('explicit-local-password'), 1)
        self.assertTrue(
            User.objects.get(username='resolver_director').check_password('explicit-local-password'),
        )

    @override_settings(DEBUG=False)
    def test_rejects_non_debug_database(self):
        with self.assertRaisesRegex(CommandError, 'requires DEBUG=True'):
            call_command('seed_resolver_demo', stdout=StringIO())
