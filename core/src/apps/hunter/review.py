import json
import re

from django.utils import timezone

from . import evidence
from .models import Vacancy

CAPTCHA = "captcha"
ACCOUNT = "account"
QUESTION = "question"
UNCONFIRMED = "unconfirmed"
STUCK = "stuck"
OTHER = "other"
KINDS = (CAPTCHA, UNCONFIRMED, QUESTION, ACCOUNT, STUCK, OTHER)

APPLIED = "applied"
SKIPPED = "skipped"
RETRY = "retry"
ACTIONS = (APPLIED, SKIPPED, RETRY)

CAPTCHA_NOTE = "asked for a captcha before sending"
UNCONFIRMED_NOTES = ("before resending", "Run stopped while applying")
REFUSAL_KINDS = (
    ("legal consent", QUESTION),
    ("saved answer", QUESTION),
    ("saved EEO answers", QUESTION),
    ("work authorization", QUESTION),
    ("never creates accounts", ACCOUNT),
    ("never types passwords", ACCOUNT),
)
ACCOUNT_NOTE = re.compile(
    r"sign[- ]?up|sign[- ]?in|log ?in|create (your|an) .*account|register|password", re.IGNORECASE
)
NOTE_KINDS = (
    (
        re.compile(r"captcha|cloudflare|human[- ]verification|verify you are human", re.IGNORECASE),
        CAPTCHA,
    ),
    (
        re.compile(
            r"attestation|consent|non-compete|demographic|EEO|certif|authori[sz]ation",
            re.IGNORECASE,
        ),
        QUESTION,
    ),
)
STUCK_NOTES = ("Navigator", "Browser error")


def last_refusal(vacancy: Vacancy) -> str:
    folder = evidence.folder(evidence.key_for(vacancy))
    if folder is None:
        return ""
    try:
        trace = json.loads((folder / "trace.json").read_text())
    except (OSError, ValueError):
        return ""
    if not isinstance(trace, list) or not trace or trace[-1].get("action") != "stuck":
        return ""
    for step in reversed(trace):
        result = str(step.get("result", ""))
        if result.startswith("refused"):
            return result
    return ""


def kind_of(vacancy: Vacancy) -> str:
    note = vacancy.note or ""
    if CAPTCHA_NOTE in note:
        return CAPTCHA
    if any(marker in note for marker in UNCONFIRMED_NOTES):
        return UNCONFIRMED
    if ACCOUNT_NOTE.search(note):
        return ACCOUNT
    refusal = last_refusal(vacancy)
    for marker, kind in REFUSAL_KINDS:
        if marker in refusal:
            return kind
    for pattern, kind in NOTE_KINDS:
        if pattern.search(note):
            return kind
    if note.startswith(STUCK_NOTES):
        return STUCK
    return OTHER


def resolve(vacancy_id: int, action: str, not_sent: bool = False) -> str:
    vacancy = Vacancy.objects.filter(pk=vacancy_id).first()
    if vacancy is None:
        return "No such job."
    if vacancy.status != Vacancy.Status.NEEDS_REVIEW:
        return f"This job is no longer waiting for you (it is {vacancy.status})."
    held = Vacancy.objects.filter(pk=vacancy.pk, status=Vacancy.Status.NEEDS_REVIEW)
    if action == APPLIED:
        held.update(
            status=Vacancy.Status.APPLIED,
            applied_at=vacancy.applied_at or timezone.now(),
            note="Applied by you.",
            updated_at=timezone.now(),
        )
        return ""
    if action == SKIPPED:
        held.update(
            status=Vacancy.Status.SKIPPED, note="Skipped by you.", updated_at=timezone.now()
        )
        return ""
    if action == RETRY:
        maybe_sent = vacancy.submitted_at is not None and kind_of(vacancy) != CAPTCHA
        if maybe_sent and not not_sent:
            return "The agent pressed Submit on this one; confirm it was not sent first."
        held.update(
            status=Vacancy.Status.READY,
            note="",
            submitted_at=None,
            updated_at=timezone.now(),
        )
        return ""
    return f"Unknown action {action!r}."
