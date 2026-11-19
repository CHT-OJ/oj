from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Prepare collected static files and JavaScript translations for local development.'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('prepare_dev_static is intended for local development with DEBUG=True.')
        if not settings.STATIC_ROOT:
            raise CommandError('STATIC_ROOT must be configured before preparing development static files.')

        verbosity = options.get('verbosity', 1)
        self.stdout.write('Collecting static files into the configured STATIC_ROOT...')
        call_command(
            'collectstatic',
            interactive=False,
            verbosity=verbosity,
        )
        self.stdout.write('Compiling JavaScript translation catalogs...')
        call_command(
            'compilejsi18n',
            verbosity=verbosity,
        )
        self.stdout.write(self.style.SUCCESS('Development static assets are ready.'))
