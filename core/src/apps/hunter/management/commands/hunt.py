import os
import random
import signal
import socket
import sys
import threading
import time
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.hunter import mail, notify
from apps.hunter.service import STOPPING, RunSummary, first_line, run_once
from apps.hunter.sources.hh import CaptchaError
from apps.hunter.state import Tracker

NETWORK_ERRORS = ("NS_ERROR_UNKNOWN_HOST", "NS_ERROR_NET_", "NS_ERROR_OFFLINE", "Connection error")
NETWORK_RETRY_MINUTES = 5
NETWORK_RETRIES = 3
NETWORK_POLL_SECONDS = 30
NETWORK_LOG_SECONDS = 300


def network_failure(error: str) -> bool:
    return any(marker in error for marker in NETWORK_ERRORS)


def online() -> bool:
    hosts = {urlparse(url).hostname for url in settings.JOB_SOURCE_URLS} - {None}
    for host in sorted(hosts):
        try:
            socket.getaddrinfo(host, 443)
        except OSError:
            continue
        return True
    return not hosts


def wait_for_network(limit_seconds: float, log) -> None:
    deadline = time.monotonic() + limit_seconds
    if online():
        return
    log("The network is down; waiting for it to come back.")
    told = time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(NETWORK_POLL_SECONDS)
        if online():
            log("The network is back.")
            return
        if time.monotonic() - told >= NETWORK_LOG_SECONDS:
            log("Still waiting for the network.")
            told = time.monotonic()


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
        network_retries = 0
        while True:
            if tracker:
                tracker.cycle_started()
            summary = RunSummary()
            error = ""
            if not options["vacancy"] and not options["headed"]:
                try:
                    mail.sync(log)
                except mail.SYNC_ERRORS as mail_error:
                    log(f"Mail: {type(mail_error).__name__}: {first_line(mail_error)}")
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
            network_retries = network_retries + 1 if network_failure(error) else 0
            retry_soon = 0 < network_retries <= NETWORK_RETRIES
            if retry_soon:
                wait_for_network(options["loop"] * 60, log)
                log(f"Network error; running again in {NETWORK_RETRY_MINUTES} min.")
            delay = (
                NETWORK_RETRY_MINUTES * 60
                if retry_soon
                else options["loop"] * 60 * random.uniform(0.85, 1.15)
            )
            if tracker:
                tracker.cycle_finished(summary, error, timezone.now() + timedelta(seconds=delay))
            time.sleep(delay)
