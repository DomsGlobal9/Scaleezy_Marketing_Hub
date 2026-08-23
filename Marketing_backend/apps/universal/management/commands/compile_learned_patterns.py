from django.core.management.base import BaseCommand

from apps.universal.aggregation import compile_learned_patterns


class Command(BaseCommand):
    help = 'Compile deterministic cross-client learned patterns.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        result = compile_learned_patterns(dry_run=options['dry_run'])
        self.stdout.write(self.style.SUCCESS(
            f"pattern_version={result['pattern_version']} "
            f"patterns={result['pattern_count']} "
            f"mode={'DRY_RUN' if options['dry_run'] else 'COMPILED'}"
        ))
