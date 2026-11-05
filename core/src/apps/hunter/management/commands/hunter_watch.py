from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.hunter import posting
from apps.hunter.models import Vacancy
from apps.hunter.outreach import skipped
from apps.hunter.sources import ats


class Command(BaseCommand):
    help = "Company job boards read on every run without a search: add, remove, list or seed."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("add", "remove", "list", "seed"))
        parser.add_argument("target", nargs="?")
        parser.add_argument("--name", default="")
        parser.add_argument("--limit", type=int, default=30)

    def handle(self, *args, **options):
        action = options["action"]
        if action == "add":
            if not options["target"]:
                raise CommandError("Give the board URL, e.g. https://jobs.ashbyhq.com/elevenlabs")
            try:
                key, count = ats.watch(options["target"], options["name"])
            except (OSError, ValueError) as error:
                raise CommandError(str(error)) from error
            self.stdout.write(f"Watching {key} ({count} open jobs listed).")
        elif action == "remove":
            if not ats.unwatch(options["target"] or ""):
                raise CommandError(f"{options['target']} is not on the watchlist.")
            self.stdout.write(f"Removed {options['target']}.")
        elif action == "seed":
            self.seed(options["limit"])
        else:
            for key, info in sorted(ats.read_watchlist().items()):
                self.stdout.write(f"{key:<48} {info.get('name', '')}")

    def seed(self, limit: int) -> None:
        watched = ats.read_watchlist()
        added = 0
        rows = (
            Vacancy.objects.filter(source="ats", match_score__gte=settings.HUNTER_MIN_SCORE)
            .exclude(employer="")
            .order_by("-match_score", "-created_at")
        )
        for vacancy in rows.iterator():
            if added >= limit:
                break
            job = ats.parse_job(vacancy.url)
            if not job or posting.lock(vacancy) or skipped(vacancy.employer):
                continue
            key = f"{job[0]}:{job[1]}"
            if key in watched:
                continue
            watched[key] = {"name": vacancy.employer, "added": vacancy.created_at.isoformat()}
            added += 1
            self.stdout.write(f"+ {key:<48} {vacancy.employer}")
        ats.write_watchlist(watched)
        self.stdout.write(f"{added} boards added; {len(watched)} on the watchlist.")
