import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.hunter import outreach
from apps.hunter.models import Outreach

MARKS = ("sent", "replied", "skipped", "draft")


class Command(BaseCommand):
    help = "Draft messages to hiring managers (never sends them), list drafts and record replies."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("draft", "signals", "list", "show", "mark"))
        parser.add_argument("id", nargs="?", type=int)
        parser.add_argument("status", nargs="?", choices=MARKS)
        parser.add_argument("--limit", type=int)
        parser.add_argument("--status", dest="only", choices=(*MARKS, "all"), default="draft")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        action = options["action"]
        if action == "draft":
            made = outreach.draft_due(self.stdout.write, options["limit"] or 3)
            self.stdout.write(f"{len(made)} outreach rows created.")
        elif action == "signals":
            try:
                made = outreach.run_signals(
                    self.stdout.write, options["limit"] or outreach.SIGNAL_LIMIT
                )
            except ValueError as error:
                raise CommandError(str(error)) from error
            drafted = sum(item.status == Outreach.Status.DRAFT for item in made)
            self.stdout.write(f"{len(made)} companies checked, {drafted} messages drafted.")
        elif action == "list":
            self.list(options["only"], options["json"])
        elif action == "show":
            self.show(self.item(options["id"]))
        else:
            item = self.item(options["id"])
            if not options["status"]:
                raise CommandError("Give the new status: sent, replied, skipped or draft.")
            item.status = options["status"]
            if item.status == Outreach.Status.SENT and not item.sent_at:
                item.sent_at = timezone.now()
            item.save(update_fields=["status", "sent_at", "updated_at"])
            self.stdout.write(f"{item.id}: {item.status}")

    def item(self, item_id) -> Outreach:
        if not item_id:
            raise CommandError("Give the outreach id.")
        try:
            return Outreach.objects.get(id=item_id)
        except Outreach.DoesNotExist as error:
            raise CommandError(f"No outreach row {item_id}.") from error

    def list(self, only: str, as_json: bool) -> None:
        rows = Outreach.objects.select_related("vacancy")
        if only != "all":
            rows = rows.filter(status=only)
        if as_json:
            self.stdout.write(json.dumps([row_json(item) for item in rows[:200]]))
            return
        for item in rows[:200]:
            self.stdout.write(
                f"{item.id:>4}  {item.status:<8} {item.kind:<8} {item.employer[:28]:<28} "
                f"{item.contact_name[:24]:<24} {item.role[:40]}"
            )

    def show(self, item: Outreach) -> None:
        for label, value in (
            ("Company", item.employer),
            ("Role", item.role),
            ("Job", item.vacancy.url if item.vacancy else ""),
            ("Signal", f"{item.signal} {item.signal_url}".strip()),
            ("To", f"{item.contact_name}, {item.contact_title}".strip(", ")),
            ("Found at", item.contact_url),
            ("Evidence", item.contact_quote),
            ("Status", item.status),
            ("Note", item.note),
        ):
            if value:
                self.stdout.write(f"{label}: {value}")
        if item.message:
            self.stdout.write(f"\n{item.message}")


def row_json(item: Outreach) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "status": item.status,
        "employer": item.employer,
        "role": item.role,
        "job_url": item.vacancy.url if item.vacancy else "",
        "signal": item.signal,
        "signal_url": item.signal_url,
        "contact_name": item.contact_name,
        "contact_title": item.contact_title,
        "contact_url": item.contact_url,
        "message": item.message,
        "note": item.note,
        "created_at": item.created_at.isoformat(),
    }
