import time

from django.core.management.base import BaseCommand, CommandError
from playwright.sync_api import Error as PlaywrightError

from apps.hunter.browser import open_browser, save_session
from apps.hunter.sources import LOGIN_SITES, adapter_named


class Command(BaseCommand):
    help = "Open a visible browser on a job site's shared profile so you can log in once."

    def add_arguments(self, parser):
        parser.add_argument("site", choices=[adapter.SITE for adapter in LOGIN_SITES])

    def handle(self, *args, **options):
        adapter = adapter_named(options["site"])
        with open_browser(adapter.SITE, headless=False) as context:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(adapter.LOGIN_URL)
            self.stdout.write(
                f"Log in to {adapter.NAME} in the opened window; it closes once you are in."
            )
            logged_in = False
            while not logged_in:
                try:
                    if not context.pages:
                        break
                    if any(adapter.is_logged_in(tab) for tab in context.pages):
                        save_session(adapter.SITE, context)
                        logged_in = True
                        continue
                except PlaywrightError:
                    pass
                time.sleep(3)
        if not logged_in:
            raise CommandError(f"The window closed before {adapter.NAME} showed a logged-in page.")
        self.stdout.write(
            self.style.SUCCESS(f"{adapter.NAME} session saved to data/browser/{adapter.SITE}/")
        )
