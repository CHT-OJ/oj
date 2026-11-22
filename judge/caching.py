from django.core.cache import cache


def finished_submission_ids(user_id, participation_id=None):
    keys = ['user_complete:%d' % user_id, 'user_attempted:%s' % user_id]
    if participation_id is not None:
        keys += ['contest_complete:%d' % participation_id]
        keys += ['contest_attempted:%d' % participation_id]
    cache.delete_many(keys)


def finished_submission(sub):
    participation_id = None
    if hasattr(sub, 'contest'):
        participation_id = sub.contest.participation_id
    finished_submission_ids(sub.user_id, participation_id)
