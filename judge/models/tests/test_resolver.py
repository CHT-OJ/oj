from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from judge.models import Contest, ContestParticipation
from judge.models.tests.util import create_contest_participation, create_contest_problem, create_problem, create_user
from judge.resolver import ResolverUnsupportedFormat, build_resolver_payload
from judge.views.contests import SpotlightContestRanking


@override_settings(MOSS_API_KEY=None)
class ResolverPayloadTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.editor = create_user(
            username='resolver-editor',
            is_staff=True,
            user_permissions=('edit_own_contest',),
        )
        cls.spotlight_user = create_user(
            username='resolver-spotlight',
            user_permissions=('can_view_spotlight',),
        )
        cls.normal_user = create_user(username='resolver-normal')
        cls.live_user = create_user(username='resolver-live')
        cls.live_user.profile.username_display_override = '</script><script>alert(1)</script>'
        cls.live_user.profile.save(update_fields=['username_display_override'])
        cls.virtual_user = create_user(username='resolver-virtual')
        cls.spectator = create_user(username='resolver-spectator')

        cls.contest = Contest.objects.create(
            key='resolver-payload',
            name='Resolver </script> Contest',
            description='',
            summary='Resolver payload test contest.',
            og_image='/resolver.png',
            start_time=now - timezone.timedelta(days=2),
            end_time=now - timezone.timedelta(days=1),
            format_name='icpc',
            format_config={'penalty': 17},
            frozen_last_minutes=60,
            is_visible=True,
            allow_spotlight=True,
        )
        cls.contest.authors.add(cls.editor.profile)
        first_problem = create_problem(code='resolver_first', name='Resolver First')
        second_problem = create_problem(code='resolver_second', name='Resolver Second')
        cls.later_problem = create_contest_problem(
            contest=cls.contest,
            problem=first_problem,
            points=1,
            order=20,
        )
        cls.earlier_problem = create_contest_problem(
            contest=cls.contest,
            problem=second_problem,
            points=1,
            order=7,
        )

        cls.live = create_contest_participation(
            contest=cls.contest,
            user=cls.live_user.profile,
            virtual=ContestParticipation.LIVE,
            score=1,
            cumtime=42,
            tiebreaker=30,
            frozen_score=0,
            frozen_cumtime=0,
            frozen_tiebreaker=0,
            format_data={
                str(cls.earlier_problem.id): {
                    'points': 1,
                    'time': 1800,
                    'tries': 2,
                    'frozen_points': 0,
                    'frozen_tries': 2,
                    'is_frozen': True,
                },
            },
        )
        create_contest_participation(
            contest=cls.contest,
            user=cls.virtual_user.profile,
            virtual=1,
            score=1,
        )
        create_contest_participation(
            contest=cls.contest,
            user=cls.spectator.profile,
            virtual=ContestParticipation.SPECTATE,
            score=1,
        )

    def fresh_contest(self, **updates):
        if updates:
            Contest.objects.filter(pk=self.contest.pk).update(**updates)
        return Contest.objects.get(pk=self.contest.pk)

    def resolver_view(self, user, contest=None):
        request = RequestFactory().get(reverse('spotlight_ranking', args=[self.contest.key]))
        request.user = user
        request.profile = user.profile
        request.LANGUAGE_CODE = 'vi'
        view = SpotlightContestRanking()
        view.setup(request, contest=self.contest.key)
        view.object = contest or self.fresh_contest()
        return view

    def test_payload_preserves_problem_order_labels_live_scope_and_icpc_fields(self):
        payload = build_resolver_payload(self.fresh_contest())

        self.assertEqual(payload['schema_version'], 1)
        self.assertEqual(payload['contest']['format'], 'icpc')
        self.assertEqual(payload['contest']['format_config'], {'penalty': 17})
        self.assertEqual(payload['contest']['rank_display_options'], self.contest.rank_display_options)
        self.assertTrue(payload['contest']['official_freeze_available'])
        self.assertEqual(
            [(problem['id'], problem['label'], problem['order']) for problem in payload['problems']],
            [
                (self.earlier_problem.id, 'A', 7),
                (self.later_problem.id, 'B', 20),
            ],
        )
        self.assertEqual([contestant['username'] for contestant in payload['contestants']], ['resolver-live'])

        contestant = payload['contestants'][0]
        self.assertTrue(contestant['profile_url'].endswith('/user/resolver-live'))
        self.assertEqual(contestant['user_css_class'], self.live_user.profile.css_class)
        self.assertIn('avatar_url', contestant)
        self.assertIn('rank_logo_url', contestant)
        cell = contestant['problems'][str(self.earlier_problem.id)]
        self.assertEqual(cell['final'], {'points': 1, 'time': 1800, 'tries': 2})
        self.assertEqual(cell['frozen'], {
            'points': 0,
            'time': 1800,
            'tries': 2,
            'pending': True,
        })
        self.assertEqual(contestant['final'], {'score': 1, 'cumtime': 42, 'tiebreaker': 30})
        self.assertEqual(contestant['frozen'], {'score': 0, 'cumtime': 0, 'tiebreaker': 0})

    def test_default_payload_has_no_official_freeze(self):
        self.live.score = 0.5
        self.live.cumtime = 125
        self.live.tiebreaker = 0
        self.live.format_data = {
            str(self.earlier_problem.id): {'points': 0.5, 'time': 125},
        }
        self.live.save(update_fields=['score', 'cumtime', 'tiebreaker', 'format_data'])

        payload = build_resolver_payload(self.fresh_contest(
            format_name='default',
            format_config=None,
            frozen_last_minutes=0,
        ))
        self.assertEqual(payload['contest']['format_config'], {})
        self.assertFalse(payload['contest']['official_freeze_available'])
        contestant = payload['contestants'][0]
        self.assertIsNone(contestant['frozen'])
        self.assertEqual(contestant['problems'][str(self.earlier_problem.id)], {
            'problem_id': self.earlier_problem.id,
            'attempted': True,
            'final': {'points': 0.5, 'time': 125},
            'frozen': None,
        })

    def test_vnoj_payload_normalizes_config_and_preserves_pending_frozen_fields(self):
        self.live.score = 75
        self.live.cumtime = 900
        self.live.tiebreaker = 600
        self.live.frozen_score = 50
        self.live.frozen_cumtime = 500
        self.live.frozen_tiebreaker = 300
        self.live.format_data = {
            str(self.earlier_problem.id): {
                'points': 75,
                'time': 600,
                'penalty': 1,
                'pending': 2,
                'frozen_points': 50,
                'frozen_time': 300,
                'frozen_penalty': 0,
            },
        }
        self.live.save()

        payload = build_resolver_payload(self.fresh_contest(
            format_name='vnoj',
            format_config={'LSO': True},
            frozen_last_minutes=45,
        ))
        self.assertEqual(payload['contest']['format_config'], {'penalty': 5, 'LSO': True})
        cell = payload['contestants'][0]['problems'][str(self.earlier_problem.id)]
        self.assertEqual(cell['final'], {'points': 75, 'time': 600, 'penalty': 1, 'pending': 2})
        self.assertEqual(cell['frozen'], {'points': 50, 'time': 300, 'penalty': 0, 'pending': 2})

    def test_unsupported_format_rejects_without_fallback(self):
        contest = self.fresh_contest(format_name='atcoder', format_config=None)
        with self.assertRaisesRegex(ResolverUnsupportedFormat, 'atcoder'):
            build_resolver_payload(contest)

    def test_spotlight_view_enforces_operator_authorization_and_escapes_payload(self):
        url = reverse('spotlight_ranking', args=[self.contest.key])
        self.assertIs(resolve(url).func.view_class, SpotlightContestRanking)

        with self.assertRaises(PermissionDenied):
            self.resolver_view(self.normal_user).get_context_data(object=self.contest)

        for user in (self.editor, self.spotlight_user):
            context = self.resolver_view(user).get_context_data(object=self.contest)
            script = str(context['resolver_data_script'])
            self.assertIn('id="resolver-data"', script)
            self.assertNotIn('</script><script>alert(1)</script>', script)
            self.assertIn(r'\u003C/script\u003E', script)

    def test_unsupported_view_renders_clear_error(self):
        contest = self.fresh_contest(format_name='atcoder', format_config=None)
        context = self.resolver_view(self.editor, contest).get_context_data(object=contest)
        self.assertIn('not supported by Resolver', context['resolver_error'])
        self.assertIsNone(context['resolver_data_script'])

    def test_spotlight_template_has_phase_three_ceremony_shell(self):
        source = (Path(settings.BASE_DIR) / 'templates/contest/spotlight-ranking.html').read_text(
            encoding='utf-8',
        )

        self.assertIn('id="resolver-setup"', source)
        self.assertIn('id="ranking-table"', source)
        self.assertIn('id="resolver-play"', source)
        self.assertIn('id="resolver-hud"', source)
        self.assertIn('id="resolver-shortcuts"', source)
        self.assertIn('id="resolver-fullscreen"', source)
        self.assertIn('data-resolver-preset="icpc"', source)
        self.assertIn('resolver/resolver.css', source)
        self.assertIn('resolver/bootstrap.js', source)
        self.assertNotIn('resolver-debug-output', source)
        self.assertNotIn('Resolver Phase 1 semantic core loaded.', source)
