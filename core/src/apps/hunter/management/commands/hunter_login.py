import re
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.core.management.base import BaseCommand, CommandError
from playwright.sync_api import Error as PlaywrightError

from apps.hunter.browser import open_browser, save_session
from apps.hunter.sources import LOGIN_SITES, adapter_named
from apps.hunter.sources.base import CaptchaError

CHALLENGE_RE = re.compile(r"Just a moment|Security Check|Attention Required", re.IGNORECASE)


def without_challenge(url: str) -> str:
    parts = urlparse(url)
    query = [(key, value) for key, value in parse_qsl(parts.query) if not key.startswith("__cf_")]
    return urlunparse(parts._replace(query=urlencode(query)))


def check_passed(adapter, page) -> bool:
    if "__cf_chl" in page.url or not page.title() or CHALLENGE_RE.search(page.title()):
        return False
    try:
        adapter.check_captcha(page)
    except CaptchaError:
        return False
    return True


class Command(BaseCommand):
    help = "Open a visible browser on a job site's shared profile so you can log in once."

    def add_arguments(self, parser):
        parser.add_argument("site", choices=[adapter.SITE for adapter in LOGIN_SITES])
        parser.add_argument(
            "--url", default="", help="Open this page and wait until its security check is passed."
        )

    def handle(self, *args, **options):
        adapter = adapter_named(options["site"])
        target = without_challenge(options["url"]) if options["url"] else ""
        if target and urlparse(target).scheme != "https":
            raise CommandError("--url must be an https address.")
        with open_browser(adapter.SITE, headless=False) as context:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(target or adapter.LOGIN_URL)
            if target:
                self.stdout.write(
                    f"Pass the {adapter.NAME} security check in the opened window yourself; "
                    "it closes once the page loads normally."
                )
            else:
                self.stdout.write(
                    f"Log in to {adapter.NAME} in the opened window; it closes once you are in."
                )
            done = False
            while not done:
                try:
                    if not context.pages:
                        break
                    if target:
                        done = any(check_passed(adapter, tab) for tab in context.pages)
                    else:
                        done = any(adapter.is_logged_in(tab) for tab in context.pages)
                    if done:
                        time.sleep(3)
                        save_session(adapter.SITE, context)
                        continue
                except PlaywrightError:
                    pass
                time.sleep(3)
        if not done:
            if target:
                raise CommandError(f"The window closed before the {adapter.NAME} check was passed.")
            raise CommandError(f"The window closed before {adapter.NAME} showed a logged-in page.")
        if target:
            self.stdout.write(self.style.SUCCESS(f"{adapter.NAME} check passed; session saved."))
            return
        self.stdout.write(
            self.style.SUCCESS(f"{adapter.NAME} session saved to data/browser/{adapter.SITE}/")
        )
