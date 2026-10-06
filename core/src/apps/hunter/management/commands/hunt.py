import os
import random
import signal
import sys
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.hunter import notify
from apps.hunter.service import STOPPING, RunSummary, first_line, run_once
from apps.hunter.sources.hh import CaptchaError
from apps.hunter.state import Tracker


def stop(*_) -> None:
    STOPPING.set()
    sys.exit(0)


class Command(BaseCommand):
    help = "Find vacancies from JOB_SOURCE_URLS, score them against linked CVs, optionally apply."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Send responses (default: dry run)"
        )
        parser.add_argument("--limit", type=int, default=settings.HUNTER_MAX_APPLIES_PER_RUN)
        parser.add_argument("--max-pages", type=int, default=3)
        parser.add_argument(
            "--headed", action="store_true", help="Visible browser; wait for you on a captcha"
        )
        parser.add_argument("--vacancy", default="", help="Apply only to this vacancy id")
        parser.add_argument(
            "--rehearse",
            action="store_true",
            help="With --vacancy: let the navigator fill the response but stop before sending",
        )
        parser.add_argument("--loop", type=int, metavar="MINUTES", help="Repeat every N minutes")

    def handle(self, *args, **options):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        signal.signal(signal.SIGTERM, stop)
        if options["rehearse"] and not options["vacancy"]:
            raise CommandError("--rehearse needs --vacancy ID.")
        if options["rehearse"]:
            options["apply"] = True
        tracker = None
        if options["loop"]:
            tracker = Tracker(apply=options["apply"], loop_minutes=options["loop"])

        writing = threading.Lock()

        def log(line: str) -> None:
            with writing:
                self.stdout.write(line)
                if tracker:
                    tracker.log(line)

        try:
            self.run_loop(options, tracker, log)
        finally:
            if tracker:
                tracker.stopped()

    def run_loop(self, options, tracker, log) -> None:
        last_error = ""
        last_capped = False
        while True:
            if tracker:
                tracker.cycle_started()
            summary = RunSummary()
            error = ""
            try:
                run_once(
                    apply=options["apply"],
                    limit=options["limit"],
                    max_pages=options["max_pages"],
                    log=log,
                    only=options["vacancy"],
                    headed=options["headed"],
                    rehearse=options["rehearse"],
                    summary=summary,
                )
            except (CaptchaError, RuntimeError) as error_raised:
                error = str(error_raised)
            except Exception as error_raised:
                if not options["loop"]:
                    raise
                error = f"{type(error_raised).__name__}: {first_line(error_raised)}"
            if error:
                self.stderr.write(error)
                if tracker:
                    tracker.log(f"ERROR {error}")
            repeated = bool(error) and error == last_error
            if options["apply"]:
                channels = notify.publish(
                    summary,
                    "" if repeated else error,
                    show_cap=summary.daily_cap_reached and not last_capped,
                )
                if channels:
                    log(f"Sent the run summary to {' and '.join(channels)}.")
            last_error = error
            last_capped = summary.daily_cap_reached
            if not options["loop"]:
                if error:
                    raise CommandError(error)
                return
            delay = options["loop"] * 60 * random.uniform(0.85, 1.15)
            if tracker:
                tracker.cycle_finished(summary, error, timezone.now() + timedelta(seconds=delay))
            time.sleep(delay)
