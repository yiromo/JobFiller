import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.hunter import mail


class Command(BaseCommand):
    help = "Read the Gmail accounts in HUNTER_MAIL_ACCOUNTS (read-only) and sort new email."

    def add_arguments(self, parser):
        parser.add_argument("--account", default="", help="Only this address")
        parser.add_argument(
            "--limit",
            type=int,
            default=settings.HUNTER_MAIL_PER_RUN,
            help="Emails per account to sort now, newest first; 0 sorts every new email",
        )

    def handle(self, *args, **options):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        if not mail.accounts():
            raise CommandError(
                "Set HUNTER_MAIL_ACCOUNTS in core/.env to address:days:app-password entries."
            )
        saved = mail.sync(self.stdout.write, limit=options["limit"], only=options["account"])
        self.stdout.write(f"Sorted {len(saved)} emails.")
