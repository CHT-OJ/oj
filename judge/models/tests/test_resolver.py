from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth.context_processors import PermWrapper
from django.core.exceptions import PermissionDenied
from django.template.loader import get_template
from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from judge.admin.contest import ContestAdmin
from judge.models import Contest, ContestParticipation
from judge.models.contest import RankDisplayOptions
from judge.models.tests.util import create_contest_participation, create_contest_problem, create_organization, \
    create_problem, create_user
from judge.resolver import ResolverUnsupportedFormat, _serialize_avatar, build_resolver_payload
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
        cls.live_user.first_name = 'Resolver Live Name'
        cls.live_user.save(update_fields=['first_name'])
        cls.live_user.profile.username_display_override = '</script><script>alert(1)</script>'
        cls.live_user.profile.save(update_fields=['username_display_override'])
        cls.visible_organizations = [
            create_organization(name='Resolver Alpha Org', slug='resolver-alpha', short_name='RA', is_unlisted=False),
            create_organization(name='Resolver Beta Org', slug='resolver-beta', short_name='RB', is_unlisted=False),
        ]
        cls.unlisted_organization = create_organization(
            name='Resolver Hidden Org',
            slug='resolver-hidden',
            short_name='RH',
            is_unlisted=True,
        )
        cls.live_user.profile.organizations.add(
            *cls.visible_organizations,
            cls.unlisted_organization,
        )
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
        self.assertEqual(contestant['full_name'], 'Resolver Live Name')
        self.assertIn('avatar_url', contestant)
        self.assertIn('rank_logo_url', contestant)
        self.assertEqual(contestant['final_order'], 0)
        self.assertEqual(contestant['frozen_order'], 0)
        self.assertEqual(
            [(organization['short_name'], organization['url']) for organization in contestant['organizations']],
            [('RA', '/organization/resolver-alpha'), ('RB', '/organization/resolver-beta')],
        )
        self.assertNotIn('RH', [organization['short_name'] for organization in contestant['organizations']])
        problem = payload['problems'][0]
        self.assertEqual(problem['first_solve_participation_id'], self.live.id)
        self.assertEqual(problem['final_total_ac'], 1)
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

    def test_rank_display_options_are_serialized_without_an_independent_resolver_default(self):
        for option in (
                RankDisplayOptions.AVATAR,
                RankDisplayOptions.LOGO,
                RankDisplayOptions.HIDDEN,
        ):
            with self.subTest(option=option):
                payload = build_resolver_payload(self.fresh_contest(rank_display_options=option))
                self.assertEqual(payload['contest']['rank_display_options'], option)
                self.assertIn('avatar_url', payload['contestants'][0])
                self.assertIn('rank_logo_url', payload['contestants'][0])

    def test_uploaded_resolver_avatar_uses_a_64_pixel_thumbnail(self):
        avatar = SimpleNamespace(thumbnail={'64x64': '/cache/resolver-avatar.jpg'})
        profile = SimpleNamespace(avt_url=avatar)
        self.assertEqual(_serialize_avatar(profile), '/avatar/cache/resolver-avatar.jpg')

    def test_identity_payload_prefetches_multiple_organizations_without_n_plus_one_queries(self):
        second_user = create_user(username='resolver-second-live')
        second_user.profile.organizations.add(*self.visible_organizations)
        create_contest_participation(
            contest=self.contest,
            user=second_user.profile,
            virtual=ContestParticipation.LIVE,
            format_data={},
        )

        contest = self.fresh_contest()
        # Problems, final order, frozen order, rich participations, and one
        # organization prefetch: this count must stay constant as users grow.
        with self.assertNumQueries(5):
            payload = build_resolver_payload(contest)
        self.assertEqual(len(payload['contestants']), 2)
        self.assertTrue(all(len(contestant['organizations']) == 2 for contestant in payload['contestants']))

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

    def test_resolver_response_permission_matrix_and_sensitive_cache_headers(self):
        url = reverse('spotlight_ranking', args=[self.contest.key])

        self.client.force_login(self.normal_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'id="resolver-data"', status_code=403)

        self.client.force_login(self.editor)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="resolver-data"')
        cache_control = response['Cache-Control']
        self.assertIn('no-store', cache_control)
        self.assertIn('no-cache', cache_control)
        self.assertIn('private', cache_control)
        self.assertIn('max-age=0', cache_control)

        self.client.force_login(self.spotlight_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        Contest.objects.filter(pk=self.contest.pk).update(
            start_time=timezone.now() - timezone.timedelta(hours=1),
            end_time=timezone.now() + timezone.timedelta(hours=1),
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'id="resolver-data"', status_code=403)

        self.client.force_login(self.editor)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        Contest.objects.filter(pk=self.contest.pk).update(
            start_time=timezone.now() - timezone.timedelta(days=2),
            end_time=timezone.now() - timezone.timedelta(days=1),
            is_private=True,
        )
        self.client.force_login(self.spotlight_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'id="resolver-data"', status_code=403)

    def test_spotlight_tab_visibility_matches_resolver_authorization(self):
        resolver_url = reverse('spotlight_ranking', args=[self.contest.key])
        template = get_template('contest/contest-tabs.html')

        def render_tabs(user, can_edit):
            request = RequestFactory().get(reverse('contest_view', args=[self.contest.key]))
            request.user = user
            request.profile = user.profile
            return template.template.render({
                'contest': self.fresh_contest(),
                'request': request,
                'now': timezone.now(),
                'can_edit': can_edit,
                'is_editor': can_edit,
                'is_tester': False,
                'is_in_contest': False,
                'has_joined': False,
                'live_participation': None,
                'has_moss_api_key': False,
                'perms': PermWrapper(user),
            })

        self.assertNotIn(resolver_url, render_tabs(self.normal_user, False))
        self.assertIn(resolver_url, render_tabs(self.editor, True))
        self.assertIn(resolver_url, render_tabs(self.spotlight_user, False))

        Contest.objects.filter(pk=self.contest.pk).update(
            start_time=timezone.now() - timezone.timedelta(hours=1),
            end_time=timezone.now() + timezone.timedelta(hours=1),
        )
        self.assertNotIn(resolver_url, render_tabs(self.spotlight_user, False))
        self.assertIn(resolver_url, render_tabs(self.editor, True))

    def test_legacy_allow_spotlight_is_not_presented_as_an_access_control(self):
        admin_fields = {
            field
            for _name, options in ContestAdmin.fieldsets
            for field in options.get('fields', ())
        }
        self.assertNotIn('allow_spotlight', admin_fields)
        self.assertNotIn('allow_spotlight', ContestAdmin.list_display)

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
        self.assertIn('id="resolver-autoplay"', source)
        self.assertIn('id="resolver-advanced"', source)
        self.assertNotIn('data-resolver-preset=', source)
        self.assertIn('resolver/resolver.css', source)
        self.assertIn('resolver/bootstrap.js', source)
        self.assertNotIn('resolver-debug-output', source)
        self.assertNotIn('Resolver Phase 1 semantic core loaded.', source)

    def test_vietnamese_resolver_template_translation_loads(self):
        self.client.force_login(self.editor)
        response = self.client.get(
            reverse('spotlight_ranking', args=[self.contest.key]),
            HTTP_ACCEPT_LANGUAGE='vi',
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bắt đầu trình diễn')
        self.assertContains(response, 'Trình diễn kết quả')
