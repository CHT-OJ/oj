import re
import sys
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from judge.models import Organization, Profile


class Command(BaseCommand):
    help = 'Add organization members from a list of usernames on standard input.'

    def add_arguments(self, parser):
        parser.add_argument('organization_url', help='CHTOJ organization page URL')

    def handle(self, *args, **options):
        url = urlsplit(options['organization_url'])
        match = re.fullmatch(r'/organization/(?:[0-9]+-)?([a-zA-Z0-9_-]+)/?', url.path)
        if url.scheme not in ('http', 'https') or not url.netloc or not match:
            raise CommandError('Use the organization home URL, such as https://example.com/organization/my-org.')

        try:
            organization = Organization.objects.get(slug=match[1])
        except Organization.DoesNotExist:
            raise CommandError(f'Organization not found: {match[1]}') from None

        usernames = [
            username for line in sys.stdin
            if (username := line.strip().lstrip('\ufeff')) and username != 'Tên đăng nhập CHTOJ'
        ]
        if any(len(username.split()) != 1 for username in usernames):
            raise CommandError('Paste only the username column, one username per line.')

        self.stdout.write(f'Organization: {organization.name} ({organization.slug})')
        added = skipped = failed = 0
        for username in usernames:
            try:
                with transaction.atomic():
                    org = Organization.objects.select_for_update().get(pk=organization.pk)
                    profile = Profile.objects.get(user__username=username)
                    if profile.organizations.filter(pk=org.pk).exists():
                        skipped += 1
                        continue
                    if org.slots is not None and not org.is_open and org.members.count() >= org.slots:
                        self.stderr.write(self.style.ERROR(f'{username}: organization is full'))
                        failed += 1
                        continue
                    profile.organizations.add(org)
            except Profile.DoesNotExist:
                self.stderr.write(self.style.ERROR(f'{username}: username not found'))
                failed += 1
            except DatabaseError:
                self.stderr.write(self.style.ERROR(f'{username}: database error while adding membership'))
                failed += 1
            else:
                added += 1

        self.stdout.write(f'Added: {added} | Skipped: {skipped} | Failed: {failed} | Total: {len(usernames)}')
