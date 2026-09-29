import os
import random
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.hunter import notify
from apps.hunter.service import RunSummary, run_once
from apps.hunter.sources.hh import CaptchaError


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
        parser.add_argument("--loop", type=int, metavar="MINUTES", help="Repeat every N minutes")

    def handle(self, *args, **options):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        last_error = ""
        while True:
            summary = RunSummary()
            error = ""
            try:
                run_once(
                    apply=options["apply"],
                    limit=options["limit"],
                    max_pages=options["max_pages"],
                    log=self.stdout.write,
                    only=options["vacancy"],
                    headed=options["headed"],
                    summary=summary,
                )
            except (CaptchaError, RuntimeError) as error_raised:
                error = str(error_raised)
                self.stderr.write(error)
            repeated = bool(error) and error == last_error
            text = notify.summary_text(summary, "" if repeated else error)
            if options["apply"] and notify.send(text):
                self.stdout.write("Sent the run summary to Telegram Saved Messages.")
            last_error = error
            if not options["loop"]:
                if error:
                    raise CommandError(error)
                return
            time.sleep(options["loop"] * 60 * random.uniform(0.85, 1.15))
