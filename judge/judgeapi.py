import json
import logging
import socket
import struct
import zlib

from django.conf import settings
from django.utils import timezone

from judge import event_poster as event
from judge.judge_priority import BATCH_REJUDGE_PRIORITY, CONTEST_SUBMISSION_PRIORITY, DEFAULT_PRIORITY, REJUDGE_PRIORITY
from judge.submission_finalization import publish_aborted_result, publish_infrastructure_failure

logger = logging.getLogger('judge.judgeapi')
size_pack = struct.Struct('!I')


def _post_update_submission(submission, done=False):
    from .models import Submission

    if not isinstance(submission, Submission):
        submission = Submission.objects.select_related('problem', 'user', 'language', 'contest_object').get(
            id=submission,
        )
    else:
        submission.refresh_from_db()
    if submission.problem.is_public:
        event.post('submissions', {'type': 'done-submission' if done else 'update-submission',
                                   'id': submission.id,
                                   'contest': submission.contest_key,
                                   'user': submission.user_id, 'problem': submission.problem_id,
                                   'status': submission.status, 'language': submission.language.key,
                                   'organizations':
                                   [x[0] for x in submission.user.organizations.get_queryset().values_list('id')],
                                   })


def _publish_judging_failure(publication):
    from .models import Submission

    event.post(
        'sub_%s' % Submission.get_id_secret(publication.submission_id),
        {'type': 'internal-error'},
    )
    _post_update_submission(publication.submission_id, done=True)


def judge_request(packet, reply=True):
    sock = socket.create_connection(settings.BRIDGED_DJANGO_CONNECT or
                                    settings.BRIDGED_DJANGO_ADDRESS[0])

    output = json.dumps(packet, separators=(',', ':'))
    output = zlib.compress(output.encode('utf-8'))
    writer = sock.makefile('wb')
    writer.write(size_pack.pack(len(output)))
    writer.write(output)
    writer.close()

    if reply:
        reader = sock.makefile('rb', -1)
        input = reader.read(size_pack.size)
        if not input:
            raise ValueError('Judge did not respond')
        length = size_pack.unpack(input)[0]
        input = reader.read(length)
        if not input:
            raise ValueError('Judge did not respond')
        reader.close()
        sock.close()

        result = json.loads(zlib.decompress(input).decode('utf-8'))
        return result


def judge_submission(submission, rejudge=False, batch_rejudge=False, judge_id=None):
    from .models import ContestSubmission, Submission

    # Preserve the last authoritative result while a rejudge is queued. Operational
    # status tells readers that the result is unsettled until a new publication wins.
    updates = {
        'error': None,
        'rejudged_date': timezone.now() if rejudge or batch_rejudge else None,
        'status': 'QU',
        'current_testcase': 0,
        'batch': False,
        'judged_on': None,
    }
    try:
        # This is set proactively; it might get unset in judgecallback's on_grading_begin if the problem doesn't
        # actually have pretests stored on the judge.
        updates['is_pretested'] = all(ContestSubmission.objects.filter(submission=submission)
                                      .values_list('problem__contest__run_pretests_only', 'problem__is_pretested')[0])
    except IndexError:
        priority = DEFAULT_PRIORITY
    else:
        priority = CONTEST_SUBMISSION_PRIORITY

    # This prevents a rejudge from replacing a result that is already processing or grading.
    # The bridge queue is also idempotent, so scheduling the same queued submission twice is safe.
    # Previous authoritative metrics and testcase rows remain until grading actually begins.
    # It is worth noting that this mechanism does not prevent a new rejudge from being scheduled
    # while already queued, but that does not lead to data corruption.
    if not Submission.objects.filter(id=submission.id).exclude(status__in=('P', 'G')).update(**updates):
        return False

    banned_judges = []
    if hasattr(submission, 'contest'):
        # This is not an actual contest, this is a ContestSubmission
        contest = submission.contest
        # ContestParticipation
        participation = contest.participation
        if participation.live or participation.spectate:
            banned_judges = list(participation.contest.banned_judges.values_list('name', flat=True))

    try:
        response = judge_request({
            'name': 'submission-request',
            'submission-id': submission.id,
            'problem-id': submission.problem.code,
            'language': submission.language.key,
            'source': submission.source.source,
            'judge-id': judge_id,
            'banned-judges': banned_judges,
            'priority': BATCH_REJUDGE_PRIORITY if batch_rejudge else (REJUDGE_PRIORITY if rejudge else priority),
        })
    except Exception:
        logger.exception('Failed to send request to judge')
        publish_infrastructure_failure(
            submission.id,
            'IE',
            None,
            expected_statuses=Submission.IN_PROGRESS_GRADING_STATUS,
            callback=_publish_judging_failure,
        )
        success = False
    else:
        if response.get('name') != 'submission-received' or response.get('submission-id') != submission.id:
            publish_infrastructure_failure(
                submission.id,
                'IE',
                None,
                expected_statuses=Submission.IN_PROGRESS_GRADING_STATUS,
                callback=_publish_judging_failure,
            )
            success = False
        else:
            _post_update_submission(submission.id)
            success = True
    return success


def disconnect_judge(judge, force=False):
    judge_request({'name': 'disconnect-judge', 'judge-id': judge.name, 'force': force}, reply=False)


def update_disable_judge(judge):
    judge_request({'name': 'disable-judge', 'judge-id': judge.name, 'is-disabled': judge.is_disabled})


def abort_submission(submission):
    from .models import Submission
    # We only want to try to abort a submission if it's still grading, otherwise this can lead to fully graded
    # submissions marked as aborted.
    if submission.status == 'D':
        return
    response = judge_request({'name': 'terminate-submission', 'submission-id': submission.id})
    # This defaults to true, so that in the case the JudgeList fails to remove the submission from the queue,
    # and returns a bad-request, the submission is not falsely shown as "Aborted" when it will still be judged.
    if not response.get('judge-aborted', True):
        def publish(publication):
            event.post('sub_%s' % Submission.get_id_secret(publication.submission_id), {'type': 'aborted'})
            if publication.authoritative and publication.contest_id is not None:
                event.post('contest_%d' % publication.contest_id, {'type': 'update'})
            _post_update_submission(publication.submission_id, done=True)

        publish_aborted_result(
            submission.id,
            expected_statuses=Submission.IN_PROGRESS_GRADING_STATUS,
            callback=publish,
        )
