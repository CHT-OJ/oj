from dataclasses import dataclass
from typing import Optional

from django.db import transaction

from judge.caching import finished_submission_ids


@dataclass(frozen=True)
class SubmissionPublication:
    submission_id: int
    user_id: int
    problem_id: int
    contest_id: Optional[int]
    participation_id: Optional[int]
    status: str
    result: Optional[str]
    authoritative: bool


def _get_submission_identity(submission_id):
    from judge.models import ContestSubmission, Submission

    submission = Submission.objects.filter(id=submission_id).values(
        'user_id', 'problem_id', 'contest_object_id', 'rejudged_date',
    ).first()
    if submission is None:
        return None

    contest_submission = ContestSubmission.objects.filter(submission_id=submission_id).values(
        'participation_id', 'participation__contest_id',
    ).first()
    submission['participation_id'] = contest_submission and contest_submission['participation_id']
    if contest_submission is not None:
        submission['contest_object_id'] = contest_submission['participation__contest_id']
    return submission


def _publication_for(submission, participation_id, authoritative):
    return SubmissionPublication(
        submission_id=submission.id,
        user_id=submission.user_id,
        problem_id=submission.problem_id,
        contest_id=submission.contest_object_id,
        participation_id=participation_id,
        status=submission.status,
        result=submission.result,
        authoritative=authoritative,
    )


def _register_after_commit(publication, callback):
    def publish():
        if publication.authoritative:
            finished_submission_ids(publication.user_id, publication.participation_id)
        if callback is not None:
            callback(publication)

    transaction.on_commit(publish)


def _update_contest_points(submission, participation):
    from judge.models import ContestSubmission

    contest_submission = ContestSubmission.objects.select_for_update().select_related(
        'problem__problem',
    ).get(submission_id=submission.id)
    contest_problem = contest_submission.problem
    contest_submission.points = round(
        submission.case_points / submission.case_total * contest_problem.points
        if submission.case_total > 0 else 0,
        3,
    )
    partial = contest_problem.partial and contest_problem.problem.partial
    if not partial and contest_submission.points != contest_problem.points:
        contest_submission.points = 0
    contest_submission.save(update_fields=['points'])
    participation.recompute_results(_locked=True)


def publish_authoritative_result(submission_id, updates, *, expected_statuses, callback=None,
                                 delete_testcases=False):
    from judge.models import ContestParticipation, Problem, Profile, Submission, SubmissionTestCase

    identity = _get_submission_identity(submission_id)
    if identity is None:
        return None

    with transaction.atomic():
        # Every authoritative finalizer uses this order. Submission comes first
        # to match deletion/rejudge paths; derived rows then serialize only jobs
        # sharing Profile, Problem, or participation state.
        submission = Submission.objects.select_for_update().get(id=submission_id)
        if submission.status not in expected_statuses:
            return None

        profile = Profile.objects.select_for_update().get(id=identity['user_id'])
        problem = Problem.objects.select_for_update().get(id=identity['problem_id'])

        participation = None
        participation_id = identity['participation_id']
        if participation_id is not None:
            participation = ContestParticipation.objects.select_for_update().select_related('contest').get(
                id=participation_id,
            )

        for field, value in updates.items():
            setattr(submission, field, value)
        submission.save(update_fields=list(updates))

        if delete_testcases:
            SubmissionTestCase.objects.filter(submission_id=submission_id).delete()

        if participation is not None:
            _update_contest_points(submission, participation)

        if problem.is_public and not problem.is_organization_private:
            profile._updating_stats_only = True
            profile.calculate_points()

        problem._updating_stats_only = True
        problem.update_stats()

        publication = _publication_for(submission, participation_id, authoritative=True)
        _register_after_commit(publication, callback)
        return publication


def publish_infrastructure_failure(submission_id, status, error, *, expected_statuses, callback=None):
    from judge.models import Submission

    with transaction.atomic():
        submission = Submission.objects.select_for_update().filter(id=submission_id).first()
        if submission is None or submission.status not in expected_statuses:
            return None

        submission.status = status
        submission.error = error
        submission.save(update_fields=['status', 'error'])

        contest_submission = submission.contest_or_none
        participation_id = contest_submission and contest_submission.participation_id
        publication = _publication_for(submission, participation_id, authoritative=False)
        _register_after_commit(publication, callback)
        return publication


def publish_aborted_result(submission_id, *, expected_statuses, callback=None):
    identity = _get_submission_identity(submission_id)
    if identity is None:
        return None

    if identity['rejudged_date'] is not None:
        return publish_infrastructure_failure(
            submission_id,
            'AB',
            None,
            expected_statuses=expected_statuses,
            callback=callback,
        )

    return publish_authoritative_result(
        submission_id,
        {
            'status': 'AB',
            'result': 'AB',
            'time': None,
            'memory': None,
            'points': 0,
            'case_points': 0,
            'case_total': 0,
            'current_testcase': 0,
            'batch': False,
            'is_pretested': False,
        },
        expected_statuses=expected_statuses,
        callback=callback,
        delete_testcases=True,
    )


def update_contest_from_submission(submission_id):
    from judge.models import ContestParticipation, Submission

    identity = _get_submission_identity(submission_id)
    if identity is None or identity['participation_id'] is None:
        return

    with transaction.atomic():
        submission = Submission.objects.select_for_update().get(id=submission_id)
        participation = ContestParticipation.objects.select_for_update().select_related('contest').get(
            id=identity['participation_id'],
        )
        _update_contest_points(submission, participation)
