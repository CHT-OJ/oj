from django.core.management.base import BaseCommand

from judge.models import ProblemDataUpload


class Command(BaseCommand):
    help = 'Remove test upload sessions that have been inactive for 24 hours.'

    def handle(self, *args, **options):
        deleted = 0
        while count := ProblemDataUpload.purge_expired():
            deleted += count
        self.stdout.write(str(deleted))
