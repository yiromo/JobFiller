import json
import os
import socket
import time
from collections import Counter
from datetime import datetime, timedelta

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Q
from django.utils import timezone

from . import evidence
from .models import ResumeLink, SiteLesson, Vacancy

RUNNING = "running"
SLEEPING = "sleeping"
STOPPED = "stopped"
RUNNING_GRACE = timedelta(minutes=15)
SLEEPING_GRACE = timedelta(minutes=10)
LOG_LINES = 150
SNAPSHOT_VACANCIES = 500
DATA_REFRESH_SECONDS = 15


def encode(value):
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return str(value)


def snapshot_path():
    return settings.DATA_DIR / "hunter" / "status.json"


def sent_last_day() -> int:
    since = timezone.now() - timedelta(days=1)
    return Vacancy.objects.filter(Q(applied_at__gte=since) | Q(submitted_at__gte=since)).count()


def read_snapshot() -> dict | None:
    try:
        return json.loads(snapshot_path().read_text())
    except (OSError, ValueError):
        return None


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def is_up(agent: dict | None, now=None) -> bool:
    if not agent:
        return False
    now = now or timezone.now()
    if agent.get("phase") == RUNNING:
        heartbeat = parse_time(agent.get("heartbeat_at"))
        return bool(heartbeat and now - heartbeat < RUNNING_GRACE)
    if agent.get("phase") == SLEEPING:
        next_cycle = parse_time(agent.get("next_cycle_at"))
        return bool(next_cycle and now < next_cycle + SLEEPING_GRACE)
    return False


def vacancy_brief(vacancy: Vacancy) -> dict:
    return {
        "external_id": vacancy.external_id,
        "title": vacancy.title,
        "employer": vacancy.employer,
        "url": vacancy.url,
        "note": vacancy.note or vacancy.match_reason,
    }


def vacancy_payload(vacancy: Vacancy, cv_names: dict) -> dict:
    return {
        "source": vacancy.source,
        "external_id": vacancy.external_id,
        "url": vacancy.url,
        "title": vacancy.title,
        "employer": vacancy.employer,
        "cv_name": cv_names.get(vacancy.cv_id, ""),
        "resume_id": vacancy.resume_id,
        "match_score": vacancy.match_score,
        "match_reason": vacancy.match_reason,
        "status": vacancy.status,
        "note": vacancy.note,
        "cover_letter": vacancy.cover_letter,
        "applied_at": vacancy.applied_at,
        "created_at": vacancy.created_at,
        "updated_at": vacancy.updated_at,
        "evidence": evidence.available(vacancy.external_id),
    }


def session_saved_at(site: str = "hh") -> int | None:
    try:
        path = settings.DATA_DIR / "browser" / site / "session.json"
        return json.loads(path.read_text()).get("saved_at")
    except (OSError, ValueError, AttributeError):
        return None


def data_snapshot() -> dict:
    links = list(ResumeLink.objects.select_related("cv").order_by("cv_id"))
    cv_names = {link.cv_id: link.cv.original_filename for link in links}
    counts = Counter(Vacancy.objects.values_list("status", flat=True))
    recent = Vacancy.objects.order_by("-updated_at", "-id")[:SNAPSHOT_VACANCIES]
    return {
        "config": {
            "sources": list(settings.JOB_SOURCE_URLS),
            "headless": settings.HUNTER_HEADLESS,
            "min_score": settings.HUNTER_MIN_SCORE,
            "max_applies_per_run": settings.HUNTER_MAX_APPLIES_PER_RUN,
            "max_new_per_run": settings.HUNTER_MAX_NEW_PER_RUN,
            "max_applies_per_day": settings.HUNTER_MAX_APPLIES_PER_DAY,
            "notify_telegram": settings.HUNTER_NOTIFY_TELEGRAM,
            "navigator": settings.HUNTER_NAVIGATOR,
            "navigator_steps": settings.HUNTER_NAVIGATOR_STEPS,
        },
        "sent_last_day": sent_last_day(),
        "counts": {status: counts.get(status, 0) for status in Vacancy.Status.values},
        "total": sum(counts.values()),
        "resumes": [
            {"cv_name": link.cv.original_filename, "resume_id": link.resume_id, "title": link.title}
            for link in links
        ],
        "session_saved_at": session_saved_at(),
        "lessons": [
            {
                "host": lesson.host,
                "text": lesson.text,
                "successes": lesson.successes,
                "failures": lesson.failures,
                "updated_at": lesson.updated_at,
            }
            for lesson in SiteLesson.objects.order_by("host")
        ],
        "vacancies": [vacancy_payload(vacancy, cv_names) for vacancy in recent],
    }


class Tracker:
    def __init__(self, *, apply: bool, loop_minutes: int | None):
        now = timezone.now()
        self.agent = {
            "phase": RUNNING,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "apply": apply,
            "loop_minutes": loop_minutes,
            "started_at": now,
            "heartbeat_at": now,
            "cycle_started_at": None,
            "cycle_finished_at": None,
            "next_cycle_at": None,
            "cycles": 0,
            "last_error": "",
            "last_summary": {},
            "recent_log": [],
        }
        self.data: dict = {}
        self.data_at = 0.0
        self.publish(refresh=True)

    def publish(self, refresh: bool = False) -> None:
        self.agent["heartbeat_at"] = timezone.now()
        if refresh or time.monotonic() - self.data_at > DATA_REFRESH_SECONDS:
            try:
                self.data = data_snapshot()
                self.data_at = time.monotonic()
            except DatabaseError:
                pass
        path = snapshot_path()
        payload = {"generated_at": timezone.now(), "agent": self.agent, **self.data}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, default=encode, ensure_ascii=False))
            os.replace(temporary, path)
        except OSError:
            pass

    def log(self, line: str) -> None:
        stamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        self.agent["recent_log"] = [*self.agent["recent_log"], f"{stamp} {line}"][-LOG_LINES:]
        self.publish()

    def cycle_started(self) -> None:
        self.agent.update(phase=RUNNING, cycle_started_at=timezone.now(), next_cycle_at=None)
        self.publish(refresh=True)

    def cycle_finished(self, summary, error: str, next_cycle_at) -> None:
        self.agent.update(
            phase=SLEEPING if next_cycle_at else STOPPED,
            cycle_finished_at=timezone.now(),
            next_cycle_at=next_cycle_at,
            cycles=self.agent["cycles"] + 1,
            last_error=error,
            last_summary={
                "discovered": summary.discovered,
                "applied": [vacancy_brief(v) for v in summary.applied],
                "review": [vacancy_brief(v) for v in summary.review],
                "reconciled": [vacancy_brief(v) for v in summary.reconciled],
                "daily_cap_reached": summary.daily_cap_reached,
            },
        )
        self.publish(refresh=True)

    def stopped(self) -> None:
        self.agent.update(phase=STOPPED, next_cycle_at=None)
        self.publish(refresh=True)
