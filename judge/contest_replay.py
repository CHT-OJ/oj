from collections import defaultdict
from itertools import groupby
from operator import itemgetter

from django.db.models import Min

from judge.models import ContestParticipation, ContestSubmission

REPLAY_FORMATS = {'default', 'ioi', 'ioi16', 'vnoj', 'atcoder', 'ecoo'}


def can_replay(contest, user):
    return (contest.format_name in REPLAY_FORMATS and contest.ended and not contest.is_frozen and
            contest.can_see_full_submission_list(user))


class ProblemScore:
    def __init__(self):
        self.points = self.time = self.attempts = self.penalty = 0
        self.batches = {}

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
            self.time = max((t for _, t in self.batches.values()), default=0)
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
            return
        points = max(points for points, verdict in attempts)
        self.attempts += sum(verdict not in (None, 'IE', 'CE') for _, verdict in attempts)
        if points > self.points:
            self.points, self.time = points, seconds
            self.penalty = (self.attempts - 1) * config.get('penalty', 0) * 60
        if fmt == 'default':
            self.time = seconds


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


def replay_data(contest, virtual=None, personal_only=False):
    parts = contest.users.filter(pk=virtual.pk) if personal_only and virtual else contest.users.filter(
        virtual=ContestParticipation.LIVE,
    )
    if virtual and not personal_only:
        parts = parts | contest.users.filter(pk=virtual.pk)
    parts = {p.pk: p for p in parts.select_related('user__user', 'contest').order_by('id')}
    problems = dict(contest.contest_problems.order_by('order', 'id').values_list('id', 'points'))
    indices = {pid: i for i, pid in enumerate(problems)}
    rows = {pk: {'name': p.user.username, 'virtual': p.virtual, 'dq': p.is_disqualified, 'events': []}
            for pk, p in parts.items()}
    qs = ContestSubmission.objects.filter(participation_id__in=parts, problem_id__in=problems)
    keys = ('participation_id', 'submission__date', 'problem_id')
    if contest.format_name == 'ioi16':
        qs = (qs.filter(submission__status='D', submission__test_cases__isnull=False)
              .values_list(*keys, 'submission_id', 'submission__result', 'submission__test_cases__batch')
              .annotate(batch_points=Min('submission__test_cases__points')).order_by(*keys, 'submission_id'))
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
            cell.update(contest, elapsed, [row[3:] for row in group], duration, problems[pid])
            score, cumtime, tie = totals(contest, state.values())
            events.append([elapsed, indices[pid], cell.points, score, cumtime, tie])
    duration = (contest.time_limit or contest.end_time - contest.start_time).total_seconds()
    return {'rows': rows, 'problems': [contest.get_label_for_problem(i) for i in range(len(problems))],
            'duration': duration, 'elapsed': min(duration, max(0, (contest._now - virtual.start).total_seconds()))
            if virtual else None}
