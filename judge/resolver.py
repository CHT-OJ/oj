from django.conf import settings
from django.db.models import Count, Prefetch

from judge.jinja2.gravatar import fallback as gravatar_fallback, gravatar
from judge.models import ContestParticipation, Organization


SUPPORTED_RESOLVER_FORMATS = frozenset(('default', 'icpc', 'vnoj'))
FROZEN_RESOLVER_FORMATS = frozenset(('icpc', 'vnoj'))


class ResolverPayloadError(ValueError):
    pass


class ResolverUnsupportedFormat(ResolverPayloadError):
    def __init__(self, format_name):
        super().__init__('Contest format "%s" is not supported by Resolver.' % format_name)
        self.format_name = format_name


def _number(data, key, default=0):
    value = data.get(key, default)
    return default if value is None else value


def _serialize_default_cell(problem_id, data, official_freeze_available):
    return {
        'problem_id': problem_id,
        'attempted': True,
        'final': {
            'points': _number(data, 'points'),
            'time': _number(data, 'time'),
        },
        'frozen': None,
    }


def _serialize_icpc_cell(problem_id, data, official_freeze_available):
    frozen = None
    if official_freeze_available:
        frozen = {
            'points': _number(data, 'frozen_points'),
            # The Python format stores one solve time and uses it for both final and frozen displays.
            'time': _number(data, 'time'),
            'tries': _number(data, 'frozen_tries'),
            'pending': bool(data.get('is_frozen', False)),
        }

    return {
        'problem_id': problem_id,
        'attempted': True,
        'final': {
            'points': _number(data, 'points'),
            'time': _number(data, 'time'),
            'tries': _number(data, 'tries'),
        },
        'frozen': frozen,
    }


def _serialize_vnoj_cell(problem_id, data, official_freeze_available):
    pending = _number(data, 'pending')
    frozen = None
    if official_freeze_available:
        frozen = {
            'points': _number(data, 'frozen_points'),
            'time': _number(data, 'frozen_time'),
            'penalty': _number(data, 'frozen_penalty'),
            'pending': pending,
        }

    return {
        'problem_id': problem_id,
        'attempted': True,
        'final': {
            'points': _number(data, 'points'),
            'time': _number(data, 'time'),
            'penalty': _number(data, 'penalty'),
            'pending': pending,
        },
        'frozen': frozen,
    }


CELL_SERIALIZERS = {
    'default': _serialize_default_cell,
    'icpc': _serialize_icpc_cell,
    'vnoj': _serialize_vnoj_cell,
}


def _serialize_avatar(profile):
    if profile.avt_url:
        try:
            return profile.avt_url.url
        except ValueError:
            pass
    if settings.DEBUG:
        return gravatar(profile.user, 64)
    return gravatar_fallback(profile.user.email, 64, None)


def _serialize_rank_logo(profile):
    if not profile.user_rank_logo:
        return None
    try:
        return profile.user_rank_logo.image.url
    except ValueError:
        return None


def _serialize_organizations(profile):
    return [
        {
            'name': organization.name,
            'short_name': organization.short_name,
            'url': organization.get_absolute_url(),
        }
        for organization in profile.organizations.all()
    ]


def _serialize_participation(participation, problems, format_name, official_freeze_available,
                             final_order, frozen_order):
    profile = participation.user
    format_data = participation.format_data or {}
    if not isinstance(format_data, dict):
        raise ResolverPayloadError(
            'Participation %s has invalid resolver format data.' % participation.id,
        )

    cells = {}
    serializer = CELL_SERIALIZERS[format_name]
    for problem in problems:
        problem_id = str(problem.id)
        data = format_data.get(problem_id)
        if data is None:
            continue
        if not isinstance(data, dict):
            raise ResolverPayloadError(
                'Participation %s has invalid resolver data for problem %s.' %
                (participation.id, problem.id),
            )
        cells[problem_id] = serializer(problem.id, data, official_freeze_available)

    frozen = None
    if official_freeze_available:
        frozen = {
            'score': participation.frozen_score,
            'cumtime': participation.frozen_cumtime,
            'tiebreaker': participation.frozen_tiebreaker,
        }

    return {
        'participation_id': participation.id,
        'profile_id': profile.id,
        'username': profile.username,
        'display_name': profile.display_name,
        'full_name': profile.user.first_name,
        'user_css_class': profile.css_class,
        'profile_url': profile.get_absolute_url(),
        'avatar_url': _serialize_avatar(profile),
        'rank_logo_url': _serialize_rank_logo(profile),
        'organizations': _serialize_organizations(profile),
        'is_disqualified': participation.is_disqualified,
        'submission_count': participation.submission_count,
        'final_order': final_order,
        'frozen_order': frozen_order,
        'final': {
            'score': participation.score,
            'cumtime': participation.cumtime,
            'tiebreaker': participation.tiebreaker,
        },
        'frozen': frozen,
        'problems': cells,
    }


def build_resolver_payload(contest):
    format_name = contest.format_name
    if format_name not in SUPPORTED_RESOLVER_FORMATS:
        raise ResolverUnsupportedFormat(format_name)

    problems = list(
        contest.contest_problems.select_related('problem').defer('problem__description').order_by('order'),
    )
    ranking_queryset = contest.users.filter(virtual=ContestParticipation.LIVE).annotate(
        submission_count=Count('submission'),
    )
    final_participation_ids = list(
        ranking_queryset
        .order_by('is_disqualified', '-score', 'cumtime', 'tiebreaker', '-submission_count')
        .values_list('id', flat=True),
    )
    frozen_participation_ids = list(
        ranking_queryset
        .order_by(
            'is_disqualified', '-frozen_score', 'frozen_cumtime', 'frozen_tiebreaker', '-submission_count',
        )
        .values_list('id', flat=True),
    )

    participation_by_id = {
        participation.id: participation
        for participation in (
            contest.users.filter(id__in=final_participation_ids)
            .select_related('user__user', 'user__user_rank_logo', 'rating')
            .defer('user__about', 'user__organizations__about')
            .prefetch_related(Prefetch(
                'user__organizations',
                queryset=Organization.objects.filter(is_unlisted=False),
            ))
            .annotate(submission_count=Count('submission'))
        )
    }
    participations = [participation_by_id[participation_id] for participation_id in final_participation_ids]

    final_order = {
        participation.id: index
        for index, participation in enumerate(participations)
    }
    frozen_order = {
        participation_id: index
        for index, participation_id in enumerate(frozen_participation_ids)
    }

    official_freeze_available = (
        format_name in FROZEN_RESOLVER_FORMATS and contest.frozen_last_minutes > 0
    )
    format_config = contest.format.config or {}
    first_solves, total_ac = contest.format.get_first_solves_and_total_ac(
        problems,
        participations,
        frozen=False,
    )

    return {
        'schema_version': 1,
        'contest': {
            'id': contest.id,
            'key': contest.key,
            'name': contest.name,
            'format': format_name,
            'format_config': format_config,
            'rank_display_options': contest.rank_display_options,
            'points_precision': contest.points_precision,
            'frozen_last_minutes': contest.frozen_last_minutes,
            'official_freeze_available': official_freeze_available,
        },
        'problems': [
            {
                'id': problem.id,
                'code': problem.problem.code,
                'label': contest.get_label_for_problem(index),
                'name': problem.problem.name,
                'order': problem.order,
                'max_score': problem.points,
                'first_solve_participation_id': first_solves.get(str(problem.id)),
                'final_total_ac': total_ac.get(str(problem.id), 0),
            }
            for index, problem in enumerate(problems)
        ],
        'contestants': [
            _serialize_participation(
                participation,
                problems,
                format_name,
                official_freeze_available,
                final_order[participation.id],
                frozen_order[participation.id],
            )
            for participation in participations
        ],
    }
