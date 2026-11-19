from collections import defaultdict
from itertools import groupby
from operator import itemgetter

from django.db.models import Min, Prefetch, Q
from django.urls import reverse

from judge.models import ContestParticipation, ContestSubmission, Organization

REPLAY_FORMATS = {'default', 'ioi', 'ioi16', 'vnoj', 'atcoder', 'ecoo'}


def can_replay(contest, user):
    return (contest.format_name in REPLAY_FORMATS and contest.ended and not contest.is_frozen and
            contest.can_see_full_submission_list(user))


class ProblemScore:
    def __init__(self):
        self.points = self.time = self.attempts = self.penalty = 0
        self.batches = {}
        self.entry = None

    def update(self, contest, seconds, attempts, duration, maximum):
        fmt = contest.format_name
        config = contest.format.config if fmt != 'default' else {}
        if fmt == 'ioi16':
            # The native IOI scorer takes the minimum case score in each submitted batch,
            # then the best score for that batch across all finished submissions.
            for _, _, batch, points in attempts:
                if points is not None and (batch not in self.batches or points > self.batches[batch][0]):
                    self.batches[batch] = (points, seconds)
            self.points = sum(score for score, _ in self.batches.values())
            self.time = max((t for _, t in self.batches.values()), default=0) if config['cumtime'] else 0
            if self.batches:
                self.entry = {'points': self.points, 'time': self.time}
            return
        if fmt == 'ecoo':
            valid = [points for points, verdict in attempts if verdict not in ('IE', 'CE')]
            if valid:
                self.attempts += len(valid)
                self.time = seconds
                points = max(valid)
                bonus = config['first_ac_bonus'] if self.attempts == 1 and points == maximum else 0
                if config['time_bonus']:
                    bonus += (duration - seconds) // 60 // config['time_bonus']
                self.points = points + (bonus if points > 0 else 0)
                self.entry = {'points': points, 'time': seconds, 'bonus': self.points - points}
            return
        points = max(points for points, verdict in attempts)
        self.attempts += sum(verdict not in (None, 'IE', 'CE') for _, verdict in attempts)
        if self.entry is None and fmt in ('atcoder', 'vnoj'):
            self.time = seconds
        if points > self.points:
            self.points, self.time = points, seconds
            self.penalty = (self.attempts - 1) * config.get('penalty', 0) * 60
        if fmt == 'default':
            self.time = seconds
        self.entry = {'points': self.points, 'time': self.time}
        if fmt in ('atcoder', 'vnoj'):
            unit = config['penalty'] * 60
            self.entry['penalty'] = (self.penalty // unit if self.points else self.attempts) if unit else 0


def totals(contest, cells):
    fmt = contest.format_name
    config = contest.format_config or {}
    score = round(sum(cell.points for cell in cells), contest.points_precision)
    times = [cell.time for cell in cells if cell.points or fmt == 'ecoo']
    last = max(times, default=0)
    cumtime, tie = sum(times), 0
    if fmt in ('vnoj', 'atcoder'):
        if fmt == 'atcoder' or config.get('LSO'):
            cumtime = last
        cumtime += sum(cell.penalty for cell in cells)
        tie = last if fmt == 'vnoj' else 0
    elif fmt in ('ioi', 'ioi16', 'ecoo'):
        tie = last if fmt == 'ioi' and config.get('last_score_altering') else 0
        if not config.get('cumtime'):
            cumtime = tie
    return score, max(0, int(cumtime)), tie


def current_virtual(contest, profile):
    virtual = profile.current_contest if profile else None
    if virtual and virtual.contest_id == contest.pk and virtual.virtual > 0 and not virtual.ended:
        return virtual
    return None


def replay_data(contest, virtual=None, personal_only=False):
    parts = contest.users.filter(pk=virtual.pk) if personal_only and virtual else contest.users.filter(
        virtual=ContestParticipation.LIVE,
    )
    if virtual and not personal_only:
        parts = parts | contest.users.filter(pk=virtual.pk)
    orgs = Organization.objects.filter(is_unlisted=False).only('short_name', 'slug')
    parts = {p.pk: p for p in parts.select_related('user__user').only(
        'contest_id', 'virtual', 'real_start', 'is_disqualified', 'user__user__username', 'user__user__first_name',
        'user__display_rank', 'user__rating', 'user__username_display_override',
    ).prefetch_related(Prefetch('user__organizations', queryset=orgs)).order_by('id')}
    problems = list(contest.contest_problems.order_by('order', 'id').values(
        'id', 'points', 'problem__code', 'is_pretested',
    ))
    maximum = {prob['id']: prob['points'] for prob in problems}
    rows = {}
    for pk, part in parts.items():
        part.contest = contest
        profile = part.user
        org = profile.organization
        rows[pk] = {'id': pk, 'name': profile.username, 'display_name': profile.display_name,
                    'full_name': profile.user.first_name, 'css_class': profile.css_class,
                    'user_url': reverse('user_page', args=[profile.username]),
                    'org': {'name': org.short_name, 'url': org.get_absolute_url()} if org else None,
                    'virtual': part.virtual, 'is_disqualified': part.is_disqualified, 'events': []}
    qs = ContestSubmission.objects.filter(participation_id__in=parts, problem_id__in=maximum)
    keys = ('participation_id', 'submission__date', 'problem_id')
    if contest.format_name == 'ioi16':
        qs = (qs.values_list(*keys, 'submission_id', 'submission__result', 'submission__test_cases__batch')
              .annotate(batch_points=Min('submission__test_cases__points', filter=Q(submission__status='D')))
              .order_by(*keys, 'submission_id'))
    else:
        qs = qs.order_by(*keys, 'submission_id').values_list(*keys, 'points', 'submission__result')
    for pk, submissions in groupby(qs.iterator(), itemgetter(0)):
        part = parts[pk]
        start = part.start
        duration = (part.end_time - start).total_seconds()
        state = defaultdict(ProblemScore)
        events = rows[pk]['events']
        for (date, pid), group in groupby(submissions, itemgetter(1, 2)):
            elapsed = (date - start).total_seconds()
            cell = state[pid]
            attempts = [row[3:] for row in group]
            before = cell.attempts
            cell.update(contest, elapsed, attempts, duration, maximum[pid])
            score, cumtime, tie = totals(contest, state.values())
            event = [elapsed, pid, cell.entry, score, cumtime, tie]
            count = len({row[0] for row in attempts}) if contest.format_name == 'ioi16' else len(attempts)
            if contest.format_name == 'vnoj' or count > 1:
                event.append(cell.attempts - before)  # pending attempts in a simulated VNOJ freeze
            if count > 1:
                event.append(count)  # distinct submissions sharing a problem and timestamp
            events.append(event)
    duration = (contest.time_limit or contest.end_time - contest.start_time).total_seconds()
    data = {'rows': rows, 'duration': duration,
            'elapsed': min(duration, max(0, (contest._now - virtual.start).total_seconds())) if virtual else None}
    if not personal_only:
        data['contest'] = {
            'format': contest.format_name, 'format_config': contest.format_config or {},
            'points_precision': contest.points_precision, 'run_pretests_only': contest.run_pretests_only,
            'has_rating': contest.ratings.exists(),
            'url_templates': {
                'all_submissions': reverse('contest_all_user_submissions', args=[contest.key, '__USERNAME__']),
                'problem_submissions': reverse('contest_user_submissions',
                                               args=[contest.key, '__USERNAME__', '__PROBLEM__']),
            },
        }
        data['problems'] = [{'id': prob['id'], 'code': prob['problem__code'], 'points': prob['points'],
                             'is_pretested': prob['is_pretested'], 'label': contest.get_label_for_problem(i)}
                            for i, prob in enumerate(problems)]
    return data
