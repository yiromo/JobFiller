import json
import re
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from apps.hunter import captcha, evidence, mail, review, state
from apps.hunter.models import MailMessage, Vacancy
from apps.hunter.sources import ADAPTERS, LOGIN_SITES

SENT_ROWS = 60
MAIL_ROWS = 50
MAIL_RECENT = timedelta(days=30)
AI_INTERVIEW = r"\bai[- ]?(powered |led |driven |video )?interview"
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


def mail_payload(message: MailMessage) -> dict:
    vacancy = message.vacancy
    return {
        "id": message.pk,
        "account": message.account,
        "kind": message.kind,
        "sender": message.sender,
        "subject": message.subject,
        "employer": message.employer,
        "summary": message.summary,
        "received_at": state.encode(message.received_at),
        "gmail_url": mail.gmail_url(message),
        "job_title": vacancy.title if vacancy else "",
        "job_url": vacancy.url if vacancy else "",
        "ai_interview": bool(
            re.search(AI_INTERVIEW, f"{message.subject} {message.summary}", re.IGNORECASE)
        ),
    }


def mail_listing() -> dict:
    shown = MailMessage.objects.filter(
        kind__in=mail.SHOWN,
        dismissed=False,
        received_at__gte=datetime.now(UTC) - MAIL_RECENT,
    ).select_related("vacancy")
    counts: dict = {}
    for group in shown.values("account", "kind").annotate(total=Count("id")).order_by():
        counts.setdefault(group["account"], {})[group["kind"]] = group["total"]
    ai_counts: dict = {}
    ai = shown.filter(Q(subject__iregex=AI_INTERVIEW) | Q(summary__iregex=AI_INTERVIEW))
    for group in ai.values("account", "kind").annotate(total=Count("id")).order_by():
        ai_counts.setdefault(group["account"], {})[group["kind"]] = group["total"]
    accounts = [account.address for account in mail.accounts()]
    accounts += sorted(set(counts) - set(accounts))
    rows = [
        mail_payload(message)
        for account in accounts
        for kind in mail.SHOWN
        if counts.get(account, {}).get(kind)
        for message in shown.filter(account=account, kind=kind)[:MAIL_ROWS]
    ]
    rows.sort(key=lambda row: row["received_at"] or "", reverse=True)
    return {
        "accounts": accounts,
        "sorted": MailMessage.objects.count(),
        "kinds": list(mail.SHOWN),
        "urgent": list(mail.URGENT),
        "counts": counts,
        "ai_counts": ai_counts,
        "rows": rows,
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
        "mail": mail_listing(),
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
        done = commands.add_parser("mail-done")
        done.add_argument("id", type=int)

    def handle(self, *args, **options):
        if options["command"] == "list":
            self.stdout.write(json.dumps(listing(), ensure_ascii=False))
            return
        if options["command"] == "mail-done":
            problem = mail.dismiss(options["id"])
            if problem:
                raise CommandError(problem)
            self.stdout.write(json.dumps({"ok": True}))
            return
        problem = review.resolve(options["id"], options["action"], options["not_sent"])
        if problem:
            raise CommandError(problem)
        self.stdout.write(json.dumps({"ok": True}))
