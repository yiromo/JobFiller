from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from .models import MailMessage, Outreach, Vacancy
from .outreach import skipped

HUMAN_KINDS = ("interview", "recruiter", "assessment")


def weekly(weeks: int = 8) -> list[dict]:
    since = timezone.now() - timedelta(weeks=weeks)
    sent = Vacancy.objects.filter(applied_at__gte=since).only(
        "id", "source", "employer", "applied_at"
    )
    linked = defaultdict(set)
    for vacancy_id, kind in (
        MailMessage.objects.filter(vacancy__applied_at__gte=since)
        .exclude(vacancy=None)
        .values_list("vacancy_id", "kind")
    ):
        linked[vacancy_id].add(kind)
    rows: dict[tuple, dict] = {}
    for vacancy in sent:
        year, week, _ = vacancy.applied_at.isocalendar()
        row = rows.setdefault(
            (year, week, vacancy.source),
            {
                "week": f"{year}-W{week:02d}",
                "source": vacancy.source,
                "sent": 0,
                "confirmed": 0,
                "rejected": 0,
                "human": 0,
            },
        )
        kinds = linked.get(vacancy.id, set())
        row["sent"] += 1
        row["confirmed"] += "confirmation" in kinds
        row["rejected"] += "rejection" in kinds
        row["human"] += bool(kinds & set(HUMAN_KINDS)) and not skipped(vacancy.employer)
    for row in rows.values():
        row["rate"] = round(100 * row["human"] / row["sent"], 1) if row["sent"] else 0.0
    return [rows[key] for key in sorted(rows)]


def outreach_counts(weeks: int = 8) -> dict:
    since = timezone.now() - timedelta(weeks=weeks)
    counts = dict.fromkeys(Outreach.Status.values, 0)
    for status in Outreach.objects.filter(created_at__gte=since).values_list("status", flat=True):
        counts[status] += 1
    answered = counts[Outreach.Status.REPLIED]
    reached = counts[Outreach.Status.SENT] + answered
    counts["reply_rate"] = round(100 * answered / reached, 1) if reached else 0.0
    return counts
