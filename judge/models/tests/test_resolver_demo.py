from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Count
from django.test import TestCase, override_settings

from judge.management.commands.seed_resolver_demo import CONTEST_BLUEPRINTS, DEMO_MARKER, DEMO_USERS
from judge.models import Contest, ContestParticipation, ContestSubmission
from judge.resolver import build_resolver_payload


@override_settings(DEBUG=True, MOSS_API_KEY=None)
class ResolverDemoCommandTestCase(TestCase):
    fixtures = ['language_all.json']

    def test_seeds_real_submissions_freeze_cases_tie_and_disqualification(self):
        stdout = StringIO()
        call_command('seed_resolver_demo', stdout=stdout)

        self.assertIn('Resolver demo data is ready.', stdout.getvalue())
        self.assertEqual(
            set(Contest.objects.filter(summary__contains=DEMO_MARKER).values_list('key', flat=True)),
            {blueprint['key'] for blueprint in CONTEST_BLUEPRINTS.values()},
        )

        for format_name, blueprint in CONTEST_BLUEPRINTS.items():
            contest = Contest.objects.get(key=blueprint['key'])
            payload = build_resolver_payload(contest)

            self.assertTrue(contest.ended)
            self.assertEqual(contest.format_name, format_name)
            self.assertEqual(contest.user_count, len(DEMO_USERS))
            self.assertEqual(len(payload['contestants']), len(DEMO_USERS))
            expected_order = list(
                contest.users.filter(virtual=ContestParticipation.LIVE)
                .annotate(submission_count=Count('submission'))
                .order_by(
                    'is_disqualified',
                    '-score',
                    'cumtime',
                    'tiebreaker',
                    '-submission_count',
                )
                .values_list('id', flat=True)
            )
            self.assertEqual(
                [contestant['participation_id'] for contestant in payload['contestants']],
                expected_order,
            )
            self.assertEqual(
                [contestant['final_order'] for contestant in payload['contestants']],
                list(range(len(DEMO_USERS))),
            )
            self.assertEqual(
                ContestSubmission.objects.filter(participation__contest=contest).count(),
                len(blueprint['submissions']),
            )
            self.assertFalse(contest.users.filter(format_data__isnull=True).exists())

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

    @override_settings(DEBUG=False)
    def test_rejects_non_debug_database(self):
        with self.assertRaisesRegex(CommandError, 'requires DEBUG=True'):
            call_command('seed_resolver_demo', stdout=StringIO())
