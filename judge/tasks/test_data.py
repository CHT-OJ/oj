import logging
import zlib
from lzma import LZMAError
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from kombu.exceptions import OperationalError

from judge.models import ProblemDataUpload

CHUNK_BYTES = 8 * 1024 * 1024
INLINE_EXPANDED_BYTES = 64 * 1024 * 1024
ZIP_ERRORS = (BadZipFile, OSError, EOFError, RuntimeError, ValueError, zlib.error, LZMAError)
logger = logging.getLogger(__name__)


def member_names(archive):
    return [entry.filename for entry in archive.infolist() if not entry.is_dir()]


def verify_members(archive):
    for entry in archive.infolist():
        with archive.open(entry) as stream:
            while stream.read(64 * 1024):
                pass


def fits_web_worker(archive):
    return (all(entry.compress_type in (ZIP_STORED, ZIP_DEFLATED) for entry in archive.infolist()) and
            sum(entry.file_size for entry in archive.infolist()) <= INLINE_EXPANDED_BYTES)


def finish_upload(upload, state):
    checking = ProblemDataUpload.objects.filter(pk=upload.pk, state='checking')
    updated = checking.update(state=state, updated=timezone.now())
    if updated and state != 'ready':
        upload.remove_file_after_commit()


@shared_task(acks_late=True)
def verify_test_upload(upload_id):
    upload = ProblemDataUpload.objects.select_related('owner').filter(pk=upload_id, state='checking').first()
    if upload is None:
        return
    try:
        with ZipFile(upload.path) as archive:
            expanded = sum(entry.file_size for entry in archive.infolist())
            if not upload.owner.is_superuser and expanded > settings.CHTOJ_EDITOR_ZIP_MAX_EXPANDED_BYTES:
                finish_upload(upload, 'too_large')
                return
            verify_members(archive)
    except ZIP_ERRORS:
        finish_upload(upload, 'invalid')
    else:
        finish_upload(upload, 'ready')


def schedule_verification(upload):
    if upload.size <= CHUNK_BYTES:
        try:
            with ZipFile(upload.path) as archive:
                inline = fits_web_worker(archive)
        except ZIP_ERRORS:
            finish_upload(upload, 'invalid')
            return
        if inline:
            verify_test_upload(str(upload.pk))
            return
    try:
        verify_test_upload.delay(str(upload.pk))
    except OperationalError:
        logger.exception('Could not queue ZIP verification for %s', upload.pk)
        finish_upload(upload, 'unavailable')
