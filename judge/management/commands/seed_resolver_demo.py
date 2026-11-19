import secrets

from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from judge.models import Contest, ContestParticipation, ContestProblem, ContestSubmission, Language, Problem, \
    ProblemGroup, ProblemType, Profile, Submission
from judge.resolver import build_resolver_payload


DEMO_MARKER = '[CHTOJ resolver demo v1]'
DIRECTOR_USERNAME = 'resolver_director'

DEMO_USERS = (
    ('resolver_ada', 'Ada Nguyen'),
    ('resolver_bruno', 'Bruno Tran'),
    ('resolver_chen', 'Chen Le'),
    ('resolver_daria', 'Daria Pham'),
    ('resolver_elena', 'Elena Vo'),
    ('resolver_farid', 'Farid Hoang'),
    ('resolver_gia', 'Gia Bui'),
    ('resolver_hugo', 'Hugo Do'),
)

PROBLEM_NAMES = (
    'Array Relay',
    'Bridge Signals',
    'Clockwork Graph',
    'Delta Delivery',
    'Echoes in the Grid',
)


def _reference_username(rank):
    return 'resolver_csv_%02d' % rank


# The source CSV contains 21 contestants plus a final "Total AC" summary row.
# Keep only the score columns here; real usernames and display names stay outside the repository.
VNOJ_REFERENCE_USERS = tuple(
    (_reference_username(rank), 'CSV Reference %02d' % rank)
    for rank in range(1, 22)
)

VNOJ_REFERENCE_SCORE_ROWS = (
    (6.475, 3.500, 6.000),
    (6.475, 1.400, 6.000),
    (6.475, 1.400, 6.000),
    (6.475, 1.400, 5.400),
    (7.000, None, 6.000),
    (6.475, 5.600, None),
    (6.475, 4.900, 0.600),
    (7.000, 3.500, 1.200),
    (6.475, 1.400, 3.600),
    (6.475, 4.200, 0.600),
    (None, 4.200, 6.000),
    (6.475, 1.400, 1.800),
    (6.475, 1.400, 1.800),
    (3.150, None, 6.000),
    (0.000, 1.400, 6.000),
    (6.475, 0.700, None),
    (6.475, None, None),
    (6.475, None, None),
    (6.475, None, None),
    (6.475, None, None),
    (None, None, None),
)

VNOJ_REFERENCE_PROBLEM_SPECS = (
    ('pe01_hwork', 'PE01 HWork', 7),
    ('pe02_bus', 'PE02 Bus', 7),
    ('pe03_leaves', 'PE03 Leaves', 7),
)

# Final component scores are transcribed from the CSV. The pre/post-freeze staging is
# intentionally synthetic because the CSV has no submission timestamps. It gives the
# Resolver a useful ceremony: several rows climb after the freeze, one exact tie appears,
# and zero-score/pending attempts remain visible without changing aggregate score.
VNOJ_REFERENCE_SUBMISSIONS = (
    (_reference_username(1), 0, 105, 6.475),
    (_reference_username(1), 1, 130, 1.400),
    (_reference_username(1), 1, 295, 3.500),
    (_reference_username(1), 2, 145, 6.000),
    (_reference_username(2), 0, 100, 6.475),
    (_reference_username(2), 1, 120, 1.400),
    (_reference_username(2), 2, 140, 6.000),
    (_reference_username(3), 0, 110, 6.475),
    (_reference_username(3), 1, 115, 0.700),
    (_reference_username(3), 1, 282, 1.400),
    (_reference_username(3), 2, 130, 6.000),
    (_reference_username(4), 0, 95, 6.475),
    (_reference_username(4), 1, 100, 1.400),
    (_reference_username(4), 2, 150, 5.400),
    (_reference_username(5), 0, 80, 7.000),
    (_reference_username(5), 2, 255, 6.000),
    (_reference_username(6), 0, 90, 6.475),
    (_reference_username(6), 1, 100, 1.400),
    (_reference_username(6), 1, 265, 5.600),
    (_reference_username(7), 0, 85, 6.475),
    (_reference_username(7), 1, 160, 4.900),
    (_reference_username(7), 2, 270, 0.600),
    (_reference_username(8), 0, 75, 7.000),
    (_reference_username(8), 1, 155, 3.500),
    (_reference_username(8), 2, 280, 1.200),
    (_reference_username(9), 0, 125, 6.475),
    (_reference_username(9), 1, 135, 1.400),
    (_reference_username(9), 2, 285, 3.600),
    (_reference_username(10), 0, 115, 6.475),
    (_reference_username(10), 1, 165, 4.200),
    (_reference_username(10), 2, 290, 0.600),
    (_reference_username(11), 1, 170, 4.200),
    (_reference_username(11), 2, 275, 6.000),
    (_reference_username(12), 0, 105, 6.475),
    (_reference_username(12), 1, 125, 1.400),
    (_reference_username(12), 2, 185, 1.800),
    (_reference_username(13), 0, 110, 6.475),
    (_reference_username(13), 1, 130, 1.400),
    (_reference_username(13), 2, 290, 1.800),
    (_reference_username(14), 0, 145, 3.150),
    (_reference_username(14), 2, 190, 6.000),
    (_reference_username(15), 0, 60, 0.000),
    (_reference_username(15), 1, 195, 1.400),
    (_reference_username(15), 2, 205, 6.000),
    (_reference_username(16), 0, 120, 6.475),
    (_reference_username(16), 1, 210, 0.700),
    (_reference_username(17), 0, 220, 6.475),
    (_reference_username(17), 1, 230, 0.000),
    (_reference_username(18), 0, 220, 6.475),
    (_reference_username(18), 1, 230, 0.000),
    (_reference_username(19), 0, 225, 6.475),
    (_reference_username(20), 0, 230, 6.475),
    (_reference_username(21), 1, 250, 0.000),
)


CONTEST_BLUEPRINTS = {
    'default': {
        'key': 'resolver_demo_default',
        'name': 'Resolver Demo — Default Sprint',
        'format_config': None,
        'frozen_last_minutes': 0,
        'problem_points': 100,
        'submissions': (
            ('resolver_ada', 0, 20, 40),
            ('resolver_ada', 0, 60, 100),
            # Default format deliberately uses the last submission time independently of maximum points.
            ('resolver_ada', 0, 200, 0),
            ('resolver_ada', 1, 120, 75),
            ('resolver_ada', 2, 260, 50),
            ('resolver_bruno', 0, 50, 100),
            ('resolver_bruno', 1, 100, 100),
            ('resolver_bruno', 2, 150, 50),
            ('resolver_bruno', 3, 200, 0),
            ('resolver_chen', 0, 30, 100),
            ('resolver_chen', 1, 90, 100),
            ('resolver_chen', 2, 180, 50),
            ('resolver_daria', 0, 30, 100),
            ('resolver_daria', 1, 90, 100),
            ('resolver_daria', 2, 180, 50),
            ('resolver_daria', 3, 250, 0),
            ('resolver_elena', 0, 70, 100),
            ('resolver_elena', 1, 140, 50),
            ('resolver_elena', 2, 210, 50),
            ('resolver_elena', 3, 270, 50),
            ('resolver_farid', 0, 120, 50),
            ('resolver_farid', 1, 240, 50),
            ('resolver_gia', 0, 80, 0),
            ('resolver_gia', 2, 220, 0),
            ('resolver_hugo', 0, 25, 100),
            ('resolver_hugo', 1, 80, 100),
            ('resolver_hugo', 2, 130, 100),
            ('resolver_hugo', 3, 190, 100),
        ),
        'disqualified': ('resolver_hugo',),
    },
    'icpc': {
        'key': 'resolver_demo_icpc',
        'name': 'Resolver Demo — ICPC Championship',
        'format_config': {'penalty': 20},
        'frozen_last_minutes': 60,
        'problem_points': 1,
        'submissions': (
            ('resolver_ada', 0, 12, 1),
            ('resolver_ada', 1, 35, 0),
            ('resolver_ada', 1, 50, 1),
            ('resolver_ada', 2, 100, 1),
            ('resolver_ada', 3, 245, 0),
            ('resolver_ada', 3, 270, 1),
            ('resolver_bruno', 0, 15, 0),
            ('resolver_bruno', 0, 30, 1),
            ('resolver_bruno', 1, 75, 1),
            ('resolver_bruno', 2, 200, 0),
            ('resolver_bruno', 2, 250, 1),
            ('resolver_bruno', 3, 260, 0),
            ('resolver_chen', 0, 25, 1),
            ('resolver_chen', 1, 70, 1),
            ('resolver_chen', 2, 110, 1),
            ('resolver_chen', 3, 150, 1),
            ('resolver_chen', 4, 235, 1),
            ('resolver_daria', 0, 10, 0),
            ('resolver_daria', 0, 40, 1),
            ('resolver_daria', 1, 20, 0),
            ('resolver_daria', 1, 60, 0),
            ('resolver_daria', 1, 90, 1),
            ('resolver_daria', 2, 130, 1),
            ('resolver_daria', 3, 180, 1),
            ('resolver_daria', 4, 250, 0),
            ('resolver_daria', 4, 290, 1),
            # Elena has the same official score keys as Chen but one extra, post-AC submission.
            ('resolver_elena', 0, 25, 1),
            ('resolver_elena', 1, 70, 1),
            ('resolver_elena', 2, 110, 1),
            ('resolver_elena', 3, 150, 1),
            ('resolver_elena', 4, 235, 1),
            ('resolver_elena', 4, 260, 0),
            ('resolver_farid', 0, 45, 1),
            ('resolver_farid', 1, 100, 0),
            ('resolver_farid', 2, 210, 1),
            ('resolver_farid', 4, 242, 0),
            ('resolver_gia', 0, 60, 0),
            ('resolver_gia', 1, 180, 0),
            ('resolver_gia', 2, 245, 0),
            ('resolver_gia', 3, 270, 0),
            ('resolver_hugo', 0, 20, 1),
            ('resolver_hugo', 1, 40, 1),
            ('resolver_hugo', 2, 70, 1),
            ('resolver_hugo', 3, 250, 1),
        ),
        'disqualified': ('resolver_hugo',),
    },
    'vnoj': {
        'key': 'resolver_demo_vnoj',
        'name': 'Resolver Demo — VNOJ Open',
        'format_config': {'penalty': 5, 'LSO': False},
        'frozen_last_minutes': 60,
        'problem_points': 100,
        'submissions': (
            ('resolver_ada', 0, 25, 100),
            ('resolver_ada', 1, 90, 40),
            ('resolver_ada', 1, 255, 100),
            ('resolver_ada', 2, 180, 60),
            ('resolver_ada', 3, 270, 0),
            ('resolver_bruno', 0, 20, 0),
            ('resolver_bruno', 0, 50, 100),
            ('resolver_bruno', 1, 130, 100),
            ('resolver_bruno', 2, 230, 100),
            # A full score before freeze suppresses this cell's pending presentation.
            ('resolver_bruno', 0, 260, 0),
            ('resolver_chen', 0, 80, 80),
            ('resolver_chen', 0, 250, 100),
            ('resolver_chen', 1, 120, 100),
            ('resolver_chen', 2, 200, 50),
            ('resolver_chen', 3, 238, 100),
            ('resolver_daria', 0, 30, 0),
            ('resolver_daria', 0, 60, 100),
            ('resolver_daria', 1, 100, 50),
            ('resolver_daria', 1, 200, 100),
            ('resolver_daria', 2, 220, 100),
            ('resolver_daria', 3, 250, 0),
            ('resolver_daria', 3, 280, 100),
            ('resolver_elena', 0, 40, 100),
            ('resolver_elena', 1, 140, 80),
            ('resolver_elena', 2, 190, 80),
            ('resolver_elena', 3, 230, 80),
            ('resolver_elena', 4, 239, 100),
            ('resolver_elena', 4, 270, 0),
            ('resolver_farid', 0, 100, 50),
            ('resolver_farid', 1, 150, 50),
            ('resolver_farid', 2, 200, 50),
            ('resolver_farid', 3, 250, 50),
            # Zero-point attempts remain visible but add no aggregate VNOJ penalty.
            ('resolver_gia', 0, 50, 0),
            ('resolver_gia', 1, 100, 0),
            ('resolver_gia', 2, 245, 0),
            ('resolver_gia', 3, 260, 0),
            ('resolver_hugo', 0, 20, 100),
            ('resolver_hugo', 1, 40, 100),
            ('resolver_hugo', 2, 60, 100),
        ),
        'disqualified': ('resolver_hugo',),
    },
    'vnoj_reference': {
        'key': 'resolver_demo_vnoj_reference',
        'name': 'Resolver Demo — VNOJ CSV Reference + Drama',
        'format_name': 'vnoj',
        'format_config': {'penalty': 5, 'LSO': False},
        'frozen_last_minutes': 60,
        'points_precision': 3,
        'problem_specs': VNOJ_REFERENCE_PROBLEM_SPECS,
        'problem_points': 7,
        'users': VNOJ_REFERENCE_USERS,
        'submissions': VNOJ_REFERENCE_SUBMISSIONS,
        'disqualified': (),
    },
}


class Command(BaseCommand):
    help = 'Seed local ended contests with realistic submissions for Resolver development.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--format',
            choices=('all', *CONTEST_BLUEPRINTS),
            default='all',
            help='Resolver format to seed (default: all).',
        )
        parser.add_argument(
            '--replace',
            action='store_true',
            help='Replace only contests previously created by this command.',
        )
        parser.add_argument(
            '--director-password',
            default=None,
            help='Password for the local resolver_director account (default: generate a random password).',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('seed_resolver_demo is local development data and requires DEBUG=True.')

        selected_formats = tuple(CONTEST_BLUEPRINTS) if options['format'] == 'all' else (options['format'],)
        language = self._get_language()
        director_password = options['director_password'] or secrets.token_urlsafe(24)
        user_specs = []
        seen_usernames = set()
        for format_name in selected_formats:
            for username, display_name in CONTEST_BLUEPRINTS[format_name].get('users', DEMO_USERS):
                if username not in seen_usernames:
                    user_specs.append((username, display_name))
                    seen_usernames.add(username)

        with transaction.atomic():
            director = self._ensure_director(language, director_password)
            profiles = self._ensure_contestants(language, user_specs)
            problem_group, problem_type = self._ensure_problem_metadata()
            contests = []

            for format_name in selected_formats:
                blueprint = CONTEST_BLUEPRINTS[format_name]
                contest = Contest.objects.filter(key=blueprint['key']).first()
                if contest is not None:
                    self._assert_owned_contest(contest)
                    if options['replace']:
                        self._delete_contest_data(contest)
                    else:
                        contests.append(contest)
                        self.stdout.write(
                            'Kept existing %s; pass --replace to rebuild it.' % contest.key,
                        )
                        continue

                contest = self._create_contest(
                    format_name,
                    blueprint,
                    director.profile,
                    profiles,
                    language,
                    problem_group,
                    problem_type,
                )
                contests.append(contest)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Resolver demo data is ready.'))
        self.stdout.write('Director login: %s / %s' % (DIRECTOR_USERNAME, director_password))
        self.stdout.write('Contestant accounts have unusable passwords and exist only as ranking data.')
        for contest in contests:
            self._write_contest_summary(contest)

    def _get_language(self):
        language = Language.objects.filter(key=settings.DEFAULT_USER_LANGUAGE).first()
        if language is None:
            language = Language.objects.order_by('id').first()
        if language is None:
            raise CommandError('No submission language exists. Load a language fixture before seeding demo data.')
        return language

    def _ensure_director(self, language, password):
        user = User.objects.filter(username=DIRECTOR_USERNAME).first()
        created = user is None
        if created:
            user = User(username=DIRECTOR_USERNAME, is_active=True, is_staff=True)
        else:
            self._assert_owned_user(user)

        user.first_name = 'Resolver'
        user.last_name = 'Director'
        user.is_active = True
        user.is_staff = True
        user.set_password(password)
        user.save()

        profile, _ = Profile.objects.get_or_create(user=user, defaults={'language': language})
        profile.about = '%s Local ceremony operator.' % DEMO_MARKER
        profile.username_display_override = 'Resolver Director'
        profile.save(update_fields=['about', 'username_display_override'])

        permission = Permission.objects.filter(
            content_type__app_label='judge',
            codename='edit_own_contest',
        ).first()
        if permission is None:
            raise CommandError('The judge.edit_own_contest permission is missing.')
        user.user_permissions.add(permission)
        return user

    def _ensure_contestants(self, language, user_specs):
        profiles = {}
        for username, display_name in user_specs:
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User(username=username, is_active=True)
                user.set_unusable_password()
                user.save()
            else:
                self._assert_owned_user(user)

            profile, _ = Profile.objects.get_or_create(user=user, defaults={'language': language})
            profile.about = '%s Generated contestant.' % DEMO_MARKER
            profile.username_display_override = display_name
            profile.save(update_fields=['about', 'username_display_override'])
            profiles[username] = profile
        return profiles

    def _assert_owned_user(self, user):
        try:
            about = user.profile.about or ''
        except Profile.DoesNotExist:
            about = ''
        if DEMO_MARKER not in about:
            raise CommandError(
                'Refusing to modify existing non-demo user %s.' % user.username,
            )

    def _ensure_problem_metadata(self):
        problem_group, _ = ProblemGroup.objects.get_or_create(
            name='resolver_demo',
            defaults={'full_name': 'Resolver demo problems'},
        )
        problem_type, _ = ProblemType.objects.get_or_create(
            name='resolver-demo',
            defaults={'full_name': 'Resolver demo'},
        )
        return problem_group, problem_type

    def _assert_owned_contest(self, contest):
        if DEMO_MARKER not in (contest.summary or ''):
            raise CommandError(
                'Refusing to replace existing non-demo contest %s.' % contest.key,
            )

    def _delete_contest_data(self, contest):
        submission_ids = list(
            ContestSubmission.objects.filter(participation__contest=contest)
            .values_list('submission_id', flat=True),
        )
        if submission_ids:
            Submission.objects.filter(id__in=submission_ids).delete()
        contest.delete()

    def _create_contest(self, format_name, blueprint, director, profiles, language, problem_group, problem_type):
        contest_format = blueprint.get('format_name', format_name)
        now = timezone.now().replace(second=0, microsecond=0)
        end_time = now - timezone.timedelta(days=1)
        start_time = end_time - timezone.timedelta(hours=5)
        contest = Contest.objects.create(
            key=blueprint['key'],
            name=blueprint['name'],
            description=(
                '%s\n\nGenerated ended contest for Resolver development. '
                'Its rows include partial scores, exact ties, failed attempts, freeze activity, and disqualification.'
            ) % DEMO_MARKER,
            summary='%s Safe local test data.' % DEMO_MARKER,
            start_time=start_time,
            end_time=end_time,
            is_visible=True,
            is_rated=False,
            scoreboard_visibility=Contest.SCOREBOARD_VISIBLE,
            show_submission_list=True,
            format_name=contest_format,
            format_config=blueprint['format_config'],
            frozen_last_minutes=blueprint['frozen_last_minutes'],
            points_precision=blueprint.get('points_precision', 0),
            locked_after=end_time,
        )
        contest.authors.add(director)

        problem_specs = blueprint.get('problem_specs')
        if problem_specs is None:
            problem_specs = tuple(
                (
                    'resdemo_%s_%s' % (format_name, chr(ord('a') + index)),
                    problem_name,
                    blueprint['problem_points'],
                )
                for index, problem_name in enumerate(PROBLEM_NAMES)
            )
        contest_problems = []
        for index, (code, problem_name, problem_points) in enumerate(problem_specs):
            problem = Problem.objects.filter(code=code).first()
            if problem is None:
                problem = Problem.objects.create(
                    code=code,
                    name='[Resolver Demo] %s' % problem_name,
                    description=(
                        '%s\n\nSynthetic problem used only to provide realistic local Resolver ranking data.'
                    ) % DEMO_MARKER,
                    source=DEMO_MARKER,
                    group=problem_group,
                    time_limit=2,
                    memory_limit=65536,
                    points=100,
                    partial=True,
                    is_public=True,
                    is_manually_managed=True,
                )
                problem.types.add(problem_type)
                problem.allowed_languages.add(language)
                problem.authors.add(director)
            elif DEMO_MARKER not in (problem.source or ''):
                raise CommandError('Refusing to reuse existing non-demo problem %s.' % code)

            contest_problems.append(ContestProblem.objects.create(
                problem=problem,
                contest=contest,
                points=problem_points,
                partial=contest_format != 'icpc',
                order=(index + 1) * 10,
            ))

        participations = {}
        user_specs = blueprint.get('users', DEMO_USERS)
        for username, _display_name in user_specs:
            participations[username] = ContestParticipation.objects.create(
                contest=contest,
                user=profiles[username],
                real_start=start_time,
                virtual=ContestParticipation.LIVE,
            )

        for sequence, (username, problem_index, minute, points) in enumerate(blueprint['submissions'], 1):
            self._create_submission(
                participation=participations[username],
                contest_problem=contest_problems[problem_index],
                language=language,
                submitted_at=start_time + timezone.timedelta(minutes=minute),
                points=points,
                sequence=sequence,
            )

        disqualified = set(blueprint['disqualified'])
        for username, participation in participations.items():
            participation.is_disqualified = username in disqualified
            participation.save(update_fields=['is_disqualified'])
            participation.recompute_results()

        contest.update_user_count()
        self._validate_contest(contest, blueprint)
        return contest

    def _create_submission(self, participation, contest_problem, language, submitted_at, points, sequence):
        max_points = contest_problem.points
        result = 'AC' if points == max_points else 'WA'
        submission = Submission.objects.create(
            user=participation.user,
            problem=contest_problem.problem,
            time=round(0.02 + (sequence % 9) * 0.013, 3),
            memory=1024 + sequence * 8,
            points=points,
            language=language,
            status='D',
            result=result,
            case_points=points,
            case_total=max_points,
            judged_date=submitted_at + timezone.timedelta(seconds=5),
            locked_after=participation.contest.end_time,
        )
        Submission.objects.filter(pk=submission.pk).update(date=submitted_at)
        ContestSubmission.objects.create(
            submission=submission,
            problem=contest_problem,
            participation=participation,
            points=points,
        )

    def _validate_contest(self, contest, blueprint):
        payload = build_resolver_payload(contest)
        expected_users = blueprint.get('users', DEMO_USERS)
        if not contest.ended:
            raise CommandError('Generated contest %s did not end in the past.' % contest.key)
        if len(payload['contestants']) != len(expected_users):
            raise CommandError('Generated contest %s has an incomplete field.' % contest.key)
        if ContestSubmission.objects.filter(participation__contest=contest).count() != len(blueprint['submissions']):
            raise CommandError('Generated contest %s has an incomplete submission history.' % contest.key)
        if any(participation.format_data is None for participation in contest.users.all()):
            raise CommandError('Generated contest %s was not recomputed.' % contest.key)

        if contest.frozen_last_minutes:
            pending = any(
                cell['frozen'] and cell['frozen'].get('pending')
                for contestant in payload['contestants']
                for cell in contestant['problems'].values()
            )
            if not pending:
                raise CommandError('Generated contest %s has no post-freeze cells.' % contest.key)

    def _write_contest_summary(self, contest):
        ranking_url = reverse('contest_ranking', args=(contest.key,))
        resolver_url = reverse('spotlight_ranking', args=(contest.key,))
        submission_count = ContestSubmission.objects.filter(participation__contest=contest).count()
        self.stdout.write('')
        self.stdout.write('%s (%s)' % (contest.name, contest.format_name))
        self.stdout.write('  %d contestants, %d submissions' % (contest.user_count, submission_count))
        self.stdout.write('  Ranking:  %s' % ranking_url)
        self.stdout.write('  Resolver: %s' % resolver_url)
