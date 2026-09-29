import time

from django.core.management.base import BaseCommand
from playwright.sync_api import Error as PlaywrightError

from apps.hunter.browser import open_browser, save_session
from apps.hunter.sources import hh

LOGIN_URL = "https://hh.kz/account/login?backurl=%2F"


class Command(BaseCommand):
    help = "Open a visible hh.kz browser on the shared profile so you can log in once."

    def handle(self, *args, **options):
        with open_browser(hh.SITE, headless=False) as context:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(LOGIN_URL)
            self.stdout.write("Log in to hh.kz in the opened window; it closes once you are in.")
            while True:
                try:
                    if not context.pages:
                        break
                    if any(hh.is_logged_in(tab) for tab in context.pages):
                        save_session(hh.SITE, context)
                        break
                except PlaywrightError:
                    break
                time.sleep(3)
        self.stdout.write(self.style.SUCCESS("hh.kz session saved to data/browser/hh/"))
