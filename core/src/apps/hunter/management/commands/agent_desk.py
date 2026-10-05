import json
from datetime import UTC, datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.hunter import captcha, evidence, review, state
from apps.hunter.models import Vacancy
from apps.hunter.sources import ADAPTERS, LOGIN_SITES

SENT_ROWS = 60
LOG_ROWS = 80
LOG_STAMP = "%Y-%m-%d %H:%M:%S UTC"


def site_names() -> dict:
    return {adapter.SITE: adapter.NAME for adapter in ADAPTERS}


def held_payload(vacancy: Vacancy, names: dict) -> dict:
    kind = review.kind_of(vacancy)
    shot = evidence.folder(evidence.key_for(vacancy))
    return {
        "id": vacancy.pk,
        "external_id": vacancy.external_id,
        "site": vacancy.source,
        "site_name": names.get(vacancy.source, vacancy.source),
        "title": vacancy.title,
        "employer": vacancy.employer,
        "url": vacancy.url,
        "score": vacancy.match_score,
        "note": vacancy.note,
        "kind": kind,
        "send_visible": kind == review.CAPTCHA and vacancy.source == "hh",
        "screenshot": str(shot / "page.jpg") if shot and (shot / "page.jpg").is_file() else "",
        "updated_at": state.encode(vacancy.updated_at),
    }


def sent_payload(vacancy: Vacancy, names: dict) -> dict:
    return {
        "id": vacancy.pk,
        "site_name": names.get(vacancy.source, vacancy.source),
        "title": vacancy.title,
        "employer": vacancy.employer,
        "url": vacancy.url,
        "note": vacancy.note,
        "applied_at": state.encode(vacancy.applied_at),
    }


def reported_at(agent: dict, marker: str) -> datetime | None:
    for line in reversed(agent.get("recent_log", [])):
        if marker in line:
            try:
                return datetime.strptime(line[:23], LOG_STAMP).replace(tzinfo=UTC)
            except ValueError:
                return None
    if marker in agent.get("last_error", ""):
        return state.parse_time(agent.get("cycle_finished_at")) or datetime.now(UTC)
    return None


def logged_out(agent: dict) -> list[str]:
    sites = []
    for adapter in LOGIN_SITES:
        reported = reported_at(agent, f"The {adapter.NAME} profile is not logged in")
        if reported is None:
            continue
        saved = state.session_saved_at(adapter.SITE)
        if saved and saved > reported.timestamp():
            continue
        sites.append(adapter.SITE)
    return sites


def listing() -> dict:
    names = site_names()
    cooldowns = captcha.active_cooldowns()
    snapshot = state.read_snapshot() or {}
    agent = snapshot.get("agent") or {}
    held = Vacancy.objects.filter(status=Vacancy.Status.NEEDS_REVIEW).order_by("-updated_at")
    sent = Vacancy.objects.filter(status=Vacancy.Status.APPLIED).exclude(applied_at=None)
    counts = {
        status: Vacancy.objects.filter(status=status).count()
        for status in (Vacancy.Status.READY, Vacancy.Status.NEEDS_REVIEW)
    }
    return {
        "agent": {
            "up": state.is_up(agent),
            "phase": agent.get("phase", ""),
            "cycle_started_at": agent.get("cycle_started_at"),
            "cycle_finished_at": agent.get("cycle_finished_at"),
            "next_cycle_at": agent.get("next_cycle_at"),
            "last_error": agent.get("last_error", ""),
            "recent_log": agent.get("recent_log", [])[-LOG_ROWS:],
        },
        "sent_last_day": state.sent_last_day(),
        "daily_cap": settings.HUNTER_MAX_APPLIES_PER_DAY,
        "counts": counts,
        "sites": [
            {
                "site": adapter.SITE,
                "name": adapter.NAME,
                "saved_at": state.session_saved_at(adapter.SITE),
                "paused_until": state.encode(until)
                if (until := cooldowns.get(adapter.SITE))
                else None,
                "attempt": list(captcha.attempt_of(adapter.SITE)) if until else None,
            }
            for adapter in LOGIN_SITES
        ],
        "logged_out": logged_out(agent),
        "kinds": list(review.KINDS),
        "held": [held_payload(vacancy, names) for vacancy in held],
        "sent": [
            sent_payload(vacancy, names) for vacancy in sent.order_by("-applied_at")[:SENT_ROWS]
        ],
    }


class Command(BaseCommand):
    help = "JSON bridge for the desktop app: list held jobs or resolve one."

    def add_arguments(self, parser):
        commands = parser.add_subparsers(dest="command", required=True)
        commands.add_parser("list")
        resolve = commands.add_parser("resolve")
        resolve.add_argument("id", type=int)
        resolve.add_argument("action", choices=review.ACTIONS)
        resolve.add_argument("--not-sent", action="store_true")

    def handle(self, *args, **options):
        if options["command"] == "list":
            self.stdout.write(json.dumps(listing(), ensure_ascii=False))
            return
        problem = review.resolve(options["id"], options["action"], options["not_sent"])
        if problem:
            raise CommandError(problem)
        self.stdout.write(json.dumps({"ok": True}))
