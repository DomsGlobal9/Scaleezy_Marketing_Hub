from django.core.management.base import BaseCommand, CommandError

from apps.ai.catalogue import sync_provider_catalogue


class Command(BaseCommand):
    help = "Synchronise the global AI provider catalogue with installed adapters."

    def add_arguments(self, parser):
        parser.add_argument(
            '--check',
            action='store_true',
            help='Report drift and exit non-zero without changing the database.',
        )

    def handle(self, *args, **options):
        check_only = options['check']
        results = sync_provider_catalogue(apply=not check_only)
        changed = [row for row in results if row['action'] != 'unchanged']

        for row in results:
            fields = f" ({', '.join(row['fields'])})" if row['fields'] else ''
            self.stdout.write(f"{row['key']}: {row['action']}{fields}")

        if check_only and changed:
            raise CommandError(
                f"AI provider catalogue is out of sync ({len(changed)} adapter(s))."
            )

        if changed:
            self.stdout.write(self.style.SUCCESS(
                f"AI provider catalogue synchronised ({len(changed)} change(s))."
            ))
        else:
            self.stdout.write(self.style.SUCCESS("AI provider catalogue already in sync."))
