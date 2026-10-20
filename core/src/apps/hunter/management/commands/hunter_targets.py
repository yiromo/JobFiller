from django.core.management.base import BaseCommand

from apps.hunter.service import referral_targets


class Command(BaseCommand):
    help = "List the best-matching employers of recent jobs, to ask someone there for a referral."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, **options):
        targets = referral_targets(options["limit"], options["days"])
        if not targets:
            self.stdout.write("No matching employers in that window.")
            return
        for item in targets:
            state = "sent" if item["sent"] else "not sent"
            self.stdout.write(
                f"{item['score']:>3}  {item['employer'][:32]:<32} {item['roles']:>2} roles  "
                f"{state:<8}  {item['title'][:50]}  {item['url']}"
            )
