"""
The background worker.

Two ways to run it, both supported deliberately:

    manage.py run_tasks            # long-running worker process
    manage.py run_tasks --once     # one tick, for a cron/scheduled job

`--once` matters because the cheapest deployments have no always-on worker
dyno. A five-minute cron running `--once` gives scheduled publishing a
five-minute granularity, which is plenty for a social post.
"""
import logging
import signal
import time

from django.core.management.base import BaseCommand

from apps.jobs import runner

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs queued background tasks."

    def add_arguments(self, parser):
        parser.add_argument(
            '--once', action='store_true',
            help="Drain the queue once and exit, for cron-style scheduling.",
        )
        parser.add_argument(
            '--interval', type=float, default=5.0,
            help="Seconds to wait between passes when running continuously.",
        )
        parser.add_argument(
            '--queue', default=None, help="Only process this queue.",
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help="Maximum tasks to run per pass.",
        )

    def handle(self, *args, **options):
        queue = options['queue']
        limit = options['limit']

        if options['once']:
            count = runner.run_once(queue_name=queue, limit=limit)
            self.stdout.write(self.style.SUCCESS(f"Ran {count} task(s)."))
            return

        # Finish the task in hand before exiting, rather than dying mid-publish
        # and leaving a job half-posted.
        self.stopping = False

        def stop(_signum, _frame):
            self.stopping = True
            self.stdout.write("Stopping after the current pass…")

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, stop)
            except (ValueError, OSError):
                # Not the main thread, or the platform lacks the signal.
                pass

        self.stdout.write(f"Worker started (queue={queue or 'all'}).")
        while not self.stopping:
            try:
                count = runner.run_once(queue_name=queue, limit=limit)
            except Exception:
                logger.exception("Worker pass failed")
                count = 0
            if count == 0:
                time.sleep(options['interval'])
