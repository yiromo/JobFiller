from django.core.management.base import BaseCommand

from apps.hunter import mail


class Command(BaseCommand):
    help = "Link sorted job emails that have no job yet, by company and by job title."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30, help="Emails from the last N days")
        parser.add_argument(
            "--titles",
            action="store_true",
            help="First read each email's job title from its subject and summary (one model call)",
        )

    def handle(self, *args, **options):
        mail.relink(self.stdout.write, days=options["days"], classify_positions=options["titles"])
