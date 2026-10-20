from django.core.management.base import BaseCommand, CommandError

from apps.hunter import mail


class Command(BaseCommand):
    help = "Sort every email in a Google Takeout Mail export (.mbox, .zip or .tgz)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="The Takeout archive, an .mbox file or a folder")
        parser.add_argument("--account", required=True, help="The Gmail address it came from")
        parser.add_argument("--limit", type=int, default=0, help="Stop after this many emails")

    def handle(self, *args, **options):
        try:
            saved = mail.import_mbox(
                options["path"], options["account"], self.stdout.write, options["limit"]
            )
        except (RuntimeError, *mail.MAIL_ERRORS) as error:
            raise CommandError(str(error)) from error
        line = mail.counts_line(saved)
        self.stdout.write(f"Sorted {len(saved)} emails{': ' + line if line else ''}.")
