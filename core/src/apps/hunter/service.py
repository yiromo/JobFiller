import copy
import math
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Case, IntegerField, Q, When
from django.utils import timezone
from openai import OpenAIError
from playwright.sync_api import Error as PlaywrightError

from agent import cover_letter, cv_reviewer
from agent.cv_writer import CvGenerationError
from apps.cvs.container import CvsContainer
from apps.cvs.models import Cv
from apps.opportunities.service import rank_jobs
from apps.opportunities.telegraph import TelegraphPage

from . import captcha, evidence, inbox, mail, review
from .browser import open_browser
from .models import MailMessage, ResumeLink, Vacancy
from .navigator import CONFIRMED_RE, PAGE_TEXT_JS, REHEARSED, Navigator, host_of
from .sources import adapter_for, dsml
from .sources.base import CaptchaError
from .state import sent_last_day

SCORE_BATCH = 8
RETRY_WAIT = timedelta(minutes=35)
RETRY_PASSES = 2
WAIT_LOG_SECONDS = 300
DUPLICATE_DAYS = 60
MODEL_ERRORS = (OpenAIError, ValueError, TypeError, AttributeError, KeyError)
UNSCORED_PREFIXES = ("Not scored", "Scoring failed")
BOARD_MISSES = 3
STOPPING = threading.Event()
REFUSALS_RE = re.compile(r"(?:refused|got stuck on) this job (\d+) times?")
RETRIED_NOTES = ("refused this job", "got stuck on this job")
REFUSAL_LIMIT = 3


@dataclass
class RunSummary:
    discovered: int = 0
    applied: list = field(default_factory=list)
    review: list = field(default_factory=list)
    reconciled: list = field(default_factory=list)
    daily_cap_reached: bool = False


CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)


def first_line(error: BaseException) -> str:
    return (str(error).strip().splitlines() or [type(error).__name__])[0]


TAILOR_INSTRUCTIONS = (
    "Tailor this CV for the position below. Reorder and reword the existing experience, projects "
    "and skills so the parts relevant to this role come first. Keep every employer, job title, "
    "date and number exactly as in the source CV, and do not add any technology, tool, language "
    "or skill that the source CV does not already list."
)
TAILOR_REJECT_WARNINGS = ("Employment title", 'Dropped "(')
FLAGSHIP_INSTRUCTIONS = (
    "Write this CV for the position below at {employer} so that it matches the posting 100%. "
    "Add every technology, tool, skill and practice the posting asks for: list them in the skills "
    "section and use them in the bullets of the experiences where they fit the work. In the "
    "candidate's own words: {stack} Add a programming language only if those words name it, and "
    "never add {excluded}. The headline is the posting's role and level, such as \"Senior "
    "Backend Engineer (Go)\", without team, product or employer names. Describe the scope of each role in the posting's terms. Skills lines hold "
    "technology and tool names only. Bullets describe work done and its result, never personal "
    "traits. Never copy a phrase of more than four words from the posting; write plainly, like "
    "an engineer describing their own work. Keep every employer, employment title, date and "
    "number exactly as in the source CV, and never state more total years of experience than "
    "the dates show."
)
FLAGSHIP_SHORTER = (
    "The last draft did not fit on one page: use at most 2 bullets per experience, each under 22 "
    "words, a 2 sentence summary and at most 5 skill lines."
)
FLAGSHIP_DRAFTS = 3
FLAGSHIP_MARK = "Flagship CV:"
FLAGSHIP_HELD = review.CV_NOTE


def navigator_mode(site: str = "") -> str:
    mode = (
        (settings.HUNTER_NAVIGATOR_BY_SITE.get(site) or settings.HUNTER_NAVIGATOR).strip().lower()
    )
    if not settings.MIMO_API_KEY or mode not in {"on", "rehearse"}:
        return "off"
    return mode


def external_mode() -> str:
    mode = str(settings.HUNTER_EXTERNAL_APPLY).strip().lower()
    if mode in {"1", "true", "yes"}:
        mode = "on"
    if not settings.MIMO_API_KEY or mode not in {"on", "rehearse"}:
        return "off"
    return mode


def role_key(text: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", " ", (text or "").lower()).strip()


def duplicate_of(vacancy: Vacancy) -> Vacancy | None:
    if not vacancy.employer or not vacancy.title:
        return None
    since = timezone.now() - timedelta(days=DUPLICATE_DAYS)
    sent = Vacancy.objects.filter(
        Q(applied_at__gte=since) | Q(submitted_at__gte=since) | Q(status=Vacancy.Status.APPLIED),
        employer__iexact=vacancy.employer,
    ).exclude(pk=vacancy.pk)
    key = role_key(vacancy.title)
    return next((other for other in sent if role_key(other.title) == key), None)


def employer_in(vacancy: Vacancy, names: list[str]) -> str:
    employer = vacancy.employer or ""
    for name in names:
        if name.strip() and re.search(rf"\b{re.escape(name.strip())}\b", employer, re.IGNORECASE):
            return name.strip()
    return ""


def skipped_employer(vacancy: Vacancy) -> str:
    return employer_in(vacancy, settings.HUNTER_SKIP_EMPLOYERS)


def skipped_title(vacancy: Vacancy) -> str:
    title = vacancy.title or ""
    for phrase in settings.HUNTER_SKIP_TITLES:
        phrase = phrase.strip()
        if phrase and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", title, re.IGNORECASE):
            return phrase
    return ""


def excluded_skills(skills: list[str]) -> list[str]:
    banned = {name.strip().lower() for name in settings.HUNTER_EXCLUDED_SKILLS if name.strip()}
    return [
        skill
        for skill in skills
        if banned & {part for part in re.split(r"[\s/,()]+", skill.lower()) if part}
    ]


def recent_rejection(vacancy: Vacancy) -> MailMessage | None:
    if not vacancy.employer or settings.HUNTER_REJECTION_COOLDOWN_DAYS <= 0:
        return None
    since = timezone.now() - timedelta(days=settings.HUNTER_REJECTION_COOLDOWN_DAYS)
    return (
        MailMessage.objects.filter(kind="rejection", received_at__gte=since)
        .filter(
            Q(employer__iexact=vacancy.employer) | Q(vacancy__employer__iexact=vacancy.employer)
        )
        .order_by("-received_at")
        .first()
    )


def skip_reason(vacancy: Vacancy) -> str:
    twin = duplicate_of(vacancy)
    if twin:
        return f"Same role at {vacancy.employer} already applied: {twin.url}"
    name = skipped_employer(vacancy)
    if name:
        return f"{vacancy.employer} matches the skip list ({name})."
    phrase = skipped_title(vacancy)
    if phrase:
        return f'The title "{vacancy.title}" is not an engineering role ({phrase}).'
    rejection = recent_rejection(vacancy)
    if rejection:
        return (
            f"{vacancy.employer} sent a rejection on {rejection.received_at:%Y-%m-%d}; "
            f"no new sends for {settings.HUNTER_REJECTION_COOLDOWN_DAYS} days."
        )
    return ""


def referral_targets(limit: int = 20, days: int = 30) -> list[dict]:
    since = timezone.now() - timedelta(days=days)
    rows = Vacancy.objects.filter(
        created_at__gte=since, match_score__gte=settings.HUNTER_MIN_SCORE
    ).exclude(employer="")
    best: dict[str, dict] = {}
    for vacancy in rows.order_by("-match_score", "-created_at"):
        key = vacancy.employer.casefold()
        if key in best:
            best[key]["roles"] += 1
            continue
        if skipped_employer(vacancy) or recent_rejection(vacancy):
            best[key] = {"skip": True, "roles": 0}
            continue
        best[key] = {
            "employer": vacancy.employer,
            "score": vacancy.match_score,
            "title": vacancy.title,
            "url": vacancy.url,
            "sent": bool(vacancy.applied_at or vacancy.submitted_at),
            "roles": 1,
        }
    targets = [item for item in best.values() if not item.get("skip")]
    targets.sort(key=lambda item: (-item["score"], -item["roles"]))
    return targets[:limit]


def needs_tailoring(adapter, vacancy) -> bool:
    return (
        bool(settings.MIMO_API_KEY)
        and not adapter.USES_RESUME_LINKS
        and vacancy.match_score is not None
        and vacancy.match_score < settings.HUNTER_MIN_SCORE
        and ResumeLink.objects.filter(cv_id=vacancy.cv_id).exists()
    )


def first_words(text: str, count: int) -> str:
    return " ".join(re.findall(r"[A-Za-z0-9+#]+", text)[:count])


def tailor_cv(vacancy, log) -> None:
    service = CvsContainer.cv_service()
    try:
        result = service.generate_from(
            vacancy.cv_id,
            TAILOR_INSTRUCTIONS,
            position_text=vacancy.text,
        )
    except CvGenerationError as error:
        log(f"  tailored CV failed for {vacancy.title}: {first_line(error)}; using the original")
        return
    if result is None:
        return
    tailored, added, warnings = result
    invented = added or [w for w in warnings if w.startswith(TAILOR_REJECT_WARNINGS)]
    if invented:
        service.delete(tailored.id)
        log(f"  tailored CV for {vacancy.title} changed facts ({invented[0]}); using the original")
        return
    original = vacancy.cv.original_filename
    vacancy.cv = Cv.objects.get(pk=tailored.id)
    vacancy.match_reason = (
        f"{vacancy.match_reason} Tailored CV: {tailored.original_filename} (from {original})."
    )[:2000]
    vacancy.save(update_fields=["cv", "match_reason", "updated_at"])
    log(f"  tailored CV for {vacancy.title}: {tailored.original_filename}")


def is_flagship(adapter, vacancy) -> bool:
    return (
        bool(settings.MIMO_API_KEY)
        and not adapter.USES_RESUME_LINKS
        and FLAGSHIP_MARK not in vacancy.match_reason
        and bool(employer_in(vacancy, settings.HUNTER_FLAGSHIP_EMPLOYERS))
    )


def flagship_instructions(employer: str) -> str:
    return FLAGSHIP_INSTRUCTIONS.format(
        employer=employer or "the employer",
        stack=settings.HUNTER_STACK or "",
        excluded=", ".join(settings.HUNTER_EXCLUDED_SKILLS) or "nothing",
    )


def names_employer(cv_text: str, employer: str) -> bool:
    name = first_words(employer, 1)
    header = " ".join((cv_text or "").splitlines()[1:3])
    return bool(name) and bool(re.search(rf"\b{re.escape(name)}\b", header, re.IGNORECASE))


def draft_rank(outcome: dict) -> tuple:
    return len(outcome["partial"]), -outcome["fit_score"]


def write_flagship_cv(source, posting: str, employer: str, title: str, log) -> tuple:
    service = CvsContainer.cv_service()
    base = flagship_instructions(employer)
    instructions = base
    findings: list[str] = []
    outcome = None
    best = None
    for _ in range(FLAGSHIP_DRAFTS):
        try:
            result = service.generate_from(
                source.id,
                instructions,
                position_text=posting,
            )
        except CvGenerationError as error:
            findings = [f"the CV writer failed: {first_line(error)}"]
            instructions = f"{base} {FLAGSHIP_SHORTER}"
            continue
        if result is None:
            return None, None, ["the source CV no longer exists"], []
        draft, added, warnings = result
        banned = excluded_skills(added)
        changed = [w for w in warnings if w.startswith(TAILOR_REJECT_WARNINGS)]
        if names_employer(draft.raw_text, employer):
            changed.append(f"the headline names {employer}")
        if banned or changed:
            service.delete(draft.id)
            findings = [f"the writer added {', '.join(banned)}" if banned else changed[0]]
            instructions = f"{base} Do not list {', '.join(banned)}." if banned else base
            continue
        try:
            outcome = cv_reviewer.review(
                source.raw_text,
                draft.raw_text,
                posting,
                employer,
                settings.HUNTER_EXCLUDED_SKILLS,
            )
        except cv_reviewer.CvReviewError as error:
            service.delete(draft.id)
            findings = [first_line(error)]
            break
        log(
            f"  flagship CV review for {title}: fit {outcome['fit_score']}, "
            f"{len(outcome['problems'])} problems, {len(outcome['partial'])} partial"
        )
        if not outcome["passed"]:
            service.delete(draft.id)
            findings = outcome["problems"]
            instructions = f"{base} {cv_reviewer.revision(outcome)}"
            continue
        if best and draft_rank(best[1]) <= draft_rank(outcome):
            service.delete(draft.id)
        else:
            if best:
                service.delete(best[0].id)
            best = (draft, outcome, added)
        if not outcome["partial"]:
            break
        instructions = f"{base} {cv_reviewer.revision(outcome)}"
    if best:
        return best[0], best[1], [], best[2]
    return None, outcome, findings, []


def flagship_cv(vacancy, log) -> bool:
    original = vacancy.cv.original_filename
    draft, outcome, findings, added = write_flagship_cv(
        vacancy.cv, vacancy.text, vacancy.employer, vacancy.title, log
    )
    if draft is None:
        finish(vacancy, False, f"{FLAGSHIP_HELD}: " + "; ".join(findings or ["no draft passed"]))
        log(f"  REVIEW  {vacancy.title}: {vacancy.note}")
        return False
    extra = f" Added for this job: {', '.join(added)}." if added else ""
    gaps = f" Cannot be written in: {', '.join(outcome['gaps'])}." if outcome["gaps"] else ""
    vacancy.cv = Cv.objects.get(pk=draft.id)
    vacancy.match_reason = (
        f"{vacancy.match_reason} {FLAGSHIP_MARK} {draft.original_filename} (from {original}), "
        f"reviewer fit {outcome['fit_score']}.{extra}{gaps}"
    )[:2000]
    vacancy.save(update_fields=["cv", "match_reason", "updated_at"])
    log(f"  flagship CV for {vacancy.title}: {draft.original_filename}")
    return True


def tailored_note(vacancy) -> str:
    if ResumeLink.objects.filter(cv_id=vacancy.cv_id).exists():
        return ""
    return (
        "\nThe upload file is a CV tailored to this job: replace any preselected résumé with it "
        "using the upload action."
    )


def letter_size(status) -> str:
    size = inbox.read_letter_size()
    if size == cover_letter.OFF and status.letter_required:
        return "very_short"
    return size


def letter_language(text: str) -> str:
    return "Russian" if len(CYRILLIC_RE.findall(text)) > len(LATIN_RE.findall(text)) else ""


def scoring_preferences() -> str:
    if not settings.HUNTER_FACTS and not settings.HUNTER_STACK:
        return ""
    stack = (
        f" In the candidate's own words: {settings.HUNTER_STACK} Count these as skills the "
        "candidate has even where the CV does not list them."
        if settings.HUNTER_STACK
        else ""
    )
    return (
        f"{settings.HUNTER_FACTS}{stack} Backend, fullstack and software developer roles fit best. "
        "Roles that are not hands-on software engineering (project, product, program or delivery "
        "management, scrum master, business analyst, no-code or low-code building, manual QA, "
        "support, AI data labelling or training) are a major mismatch, and so are roles built "
        f"mainly around {', '.join(settings.HUNTER_EXCLUDED_SKILLS) or 'nothing'}. The "
        "candidate applies to remote roles even when they are limited to US or EU residents; do "
        "not lower the score for that. Roles open worldwide, anywhere, "
        "or to contractors and employer-of-record hires in any country fit the candidate's "
        "location best; score them higher. A posting that requires at least 2 more years of "
        "experience than the candidate's stated years for its main language or skill is a major "
        "mismatch. On-site or hybrid roles are a major mismatch."
    )


def score_vacancies(vacancies: list[Vacancy], links: list[ResumeLink]) -> None:
    cvs = list({link.cv_id: link.cv for link in links}.values())
    resume_for = {(link.source, link.cv_id): link.resume_id for link in links}
    threshold = inbox.min_score()
    for start in range(0, len(vacancies), SCORE_BATCH):
        batch = vacancies[start : start + SCORE_BATCH]
        try:
            ranked = rank_jobs(
                [(str(v.id), TelegraphPage(title=v.title, text=v.text, links=[])) for v in batch],
                cvs,
                preferences=scoring_preferences(),
            )
        except MODEL_ERRORS as error:
            ranked = {}
            for vacancy in batch:
                vacancy.match_reason = f"Scoring failed: {error}"[:2000]
        for vacancy in batch:
            cv, score, reason = ranked.get(str(vacancy.id), (None, None, vacancy.match_reason))
            if cv is None and str(vacancy.id) in ranked and threshold == 0 and cvs:
                cv, score = cvs[0], 0
            vacancy.cv = cv
            vacancy.resume_id = resume_for.get((vacancy.source, cv.id), "") if cv else ""
            vacancy.match_score = score
            vacancy.match_reason = reason or f"{UNSCORED_PREFIXES[0]}; is MIMO_API_KEY set?"
            ready = score is not None and score >= threshold
            if not ready:
                vacancy.status = Vacancy.Status.BELOW_THRESHOLD
            elif vacancy.note:
                vacancy.status = Vacancy.Status.NEEDS_REVIEW
            else:
                vacancy.status = Vacancy.Status.READY
            vacancy.save()


def apply_scope_threshold(log=None) -> None:
    threshold = inbox.min_score()
    unsent = Vacancy.objects.filter(
        applied_at__isnull=True,
        submitted_at__isnull=True,
        note="",
        match_score__isnull=False,
        cv__isnull=False,
    )
    promoted = unsent.filter(
        status=Vacancy.Status.BELOW_THRESHOLD, match_score__gte=threshold
    ).update(status=Vacancy.Status.READY, updated_at=timezone.now())
    demoted = unsent.filter(status=Vacancy.Status.READY, match_score__lt=threshold).update(
        status=Vacancy.Status.BELOW_THRESHOLD, updated_at=timezone.now()
    )
    if log and (promoted or demoted):
        log(
            f"Apply scope {inbox.read_apply_scope()} (score >= {threshold}): "
            f"{promoted} now ready, {demoted} held back."
        )


def unscored(source: str) -> list[Vacancy]:
    reason_filter = Q(match_reason="")
    for prefix in UNSCORED_PREFIXES:
        reason_filter |= Q(match_reason__startswith=prefix)
    return list(
        Vacancy.objects.filter(
            reason_filter,
            source=source,
            status=Vacancy.Status.BELOW_THRESHOLD,
            match_score__isnull=True,
        )
    )


def discover(page, adapter, search_url: str, max_pages: int, log, budget: int) -> list[Vacancy]:
    if budget <= 0:
        return []
    try:
        listings = adapter.crawl(page, search_url, max_pages)
    except (OSError, ValueError) as error:
        log(f"{search_url}: search failed: {first_line(error)}")
        return []
    known = set(
        Vacancy.objects.filter(
            source=adapter.SITE, external_id__in=[item.external_id for item in listings]
        ).values_list("external_id", flat=True)
    )
    fresh = [item for item in listings if item.external_id not in known]
    log(f"{search_url}: {len(listings)} listed, {len(fresh)} new")
    created = []
    if external_mode() == "off":
        external = [item for item in fresh if item.external_apply]
        fresh = [item for item in fresh if not item.external_apply]
        if external:
            log(f"  {len(external)} apply on the employer's site; external applying is off")
    for item in fresh[:budget]:
        try:
            details = adapter.read_vacancy(page, item.url)
            status = adapter.response_status(page, item.url)
        except PlaywrightError as error:
            log(f"  could not read {item.url}: {first_line(error)}")
            continue
        if status is None:
            if not adapter.is_logged_in(page):
                raise RuntimeError(
                    f"The {adapter.NAME} session expired; run hunter_login {adapter.SITE}."
                )
            log(f"  no response info for {item.url}; retrying next run")
            continue
        vacancy = Vacancy(
            source=adapter.SITE,
            external_id=item.external_id,
            url=item.url,
            title=(details.title or item.title)[:255],
            employer=(details.employer or item.employer)[:255],
            text=details.text,
            status=Vacancy.Status.BELOW_THRESHOLD,
        )
        if status.already_applied:
            vacancy.status = Vacancy.Status.APPLIED
            vacancy.note = f"Already applied on {adapter.NAME}."
        elif status.impossible:
            vacancy.status = Vacancy.Status.SKIPPED
            vacancy.note = f"{adapter.NAME} does not allow a response."
        elif details.external_apply and external_mode() == "off":
            vacancy.status = Vacancy.Status.SKIPPED
            vacancy.note = "Applies on the employer's site; external applying is off."
        elif not details.has_respond_button and navigator_mode(adapter.SITE) == "off":
            vacancy.status = Vacancy.Status.SKIPPED
            vacancy.note = (
                f"No {adapter.NAME} response button; the employer takes applications elsewhere."
            )
        elif status.has_test and navigator_mode(adapter.SITE) == "off":
            vacancy.note = "Employer questionnaire required; answer it manually."
        elif status.needs_relocation:
            vacancy.note = f"Office job in another region; {adapter.NAME} warns about relocation."
        vacancy.save()
        created.append(vacancy)
        adapter.pause(page, 1.5, 4.0)
    return created


def reconcile(page, adapter, log, summary: RunSummary) -> None:
    held = Vacancy.objects.filter(source=adapter.SITE, status=Vacancy.Status.NEEDS_REVIEW).order_by(
        "updated_at"
    )
    for vacancy in held[: adapter.RECHECK_BATCH]:
        try:
            status = adapter.response_status(page, vacancy.url)
        except PlaywrightError as error:
            log(f"  recheck failed for {vacancy.title}: {first_line(error)}")
            continue
        if status is None:
            continue
        if status.already_applied:
            note = f"Sent outside the agent; confirmed on {adapter.NAME}."
            finish(vacancy, True, note, sent=False)
            summary.reconciled.append(vacancy)
            log(f"  SENT    {vacancy.title}: confirmed on {adapter.NAME}")
        elif status.impossible:
            vacancy.status = Vacancy.Status.SKIPPED
            vacancy.note = f"{adapter.NAME} no longer accepts responses."
            vacancy.save()
            log(f"  CLOSED  {vacancy.title}")
        else:
            Vacancy.objects.filter(pk=vacancy.pk).update(updated_at=timezone.now())
        adapter.pause(page, 0.5, 1.5)


def apply_ready(
    page,
    adapter,
    limit: int,
    links: list[ResumeLink],
    log,
    summary: RunSummary,
    only: str = "",
    headed: bool = False,
    rehearse: bool = False,
) -> None:
    titles = {link.resume_id: link.title for link in links}
    remaining = max(0, settings.HUNTER_MAX_APPLIES_PER_DAY - sent_last_day())
    if remaining < limit and not rehearse:
        summary.daily_cap_reached = remaining == 0
        limit = remaining
        log(f"Daily cap: {remaining} more responses allowed in the last 24 hours.")
    statuses = [Vacancy.Status.READY]
    queue = Vacancy.objects.select_related("cv").filter(source=adapter.SITE)
    if not only and not rehearse and navigator_mode(adapter.SITE) == "on":
        queue = queue.filter(
            Q(status=Vacancy.Status.READY)
            | Q(status=Vacancy.Status.NEEDS_REVIEW, note__startswith=REHEARSED)
        )
        statuses.append(Vacancy.Status.NEEDS_REVIEW)
    if only:
        statuses.append(Vacancy.Status.NEEDS_REVIEW)
        queue = queue.filter(external_id=only)
    queue = queue.filter(status__in=statuses).exclude(cv=None)
    if adapter.MAX_SENDS_PER_RUN and not only and not rehearse:
        limit = min(limit, adapter.MAX_SENDS_PER_RUN)
    retried = Case(
        *[When(note__contains=marker, then=1) for marker in RETRIED_NOTES],
        default=0,
        output_field=IntegerField(),
    )
    queue = queue.annotate(retried=retried).defer("text").order_by("retried", "-match_score", "id")
    attempted = False
    misses = 0
    tried = 0
    for vacancy in queue:
        if tried >= limit:
            break
        reason = "" if only else skip_reason(vacancy)
        if reason:
            vacancy.status = Vacancy.Status.SKIPPED
            vacancy.note = reason
            vacancy.save()
            log(f"  SKIP    {vacancy.title}: {vacancy.note}")
            continue
        if attempted:
            time.sleep(random.uniform(*adapter.SEND_GAP))
        if STOPPING.is_set():
            break
        if not rehearse and sent_last_day() >= settings.HUNTER_MAX_APPLIES_PER_DAY:
            summary.daily_cap_reached = True
            log("Daily cap reached; stopping sends until the next run.")
            break
        claimed = Vacancy.objects.filter(pk=vacancy.pk, status__in=statuses).update(
            status=Vacancy.Status.APPLYING, updated_at=timezone.now()
        )
        if not claimed:
            continue
        tried += 1
        try:
            result = apply_one(
                page, adapter, vacancy, titles, log, summary, headed, rehearse, forced=bool(only)
            )
        except CaptchaError as error:
            if not adapter.EMPLOYER_BOARDS or only or rehearse:
                raise
            log(f"  REVIEW  {vacancy.title}: {error}")
            attempted = True
            continue
        except (KeyboardInterrupt, SystemExit):
            finish(
                vacancy,
                False,
                f"The agent stopped while applying; check {adapter.NAME} before resending.",
            )
            raise
        if result is None:
            misses += 1
            if not adapter.EMPLOYER_BOARDS or only or misses >= BOARD_MISSES:
                log(f"  {adapter.NAME}: stopping sends until the next run.")
                break
            continue
        misses = 0
        attempted = attempted or result


def apply_one(
    page, adapter, vacancy, titles, log, summary, headed, rehearse=False, forced=False
) -> bool | None:
    original_status = vacancy.status
    try:
        status = adapter.response_status(page, vacancy.url)
    except PlaywrightError as error:
        status = None
        log(f"  response info failed for {vacancy.title}: {first_line(error)}")
    if status is None:
        Vacancy.objects.filter(pk=vacancy.pk).update(status=Vacancy.Status.READY)
        log(f"  {adapter.NAME} returned no response info for {vacancy.title}.")
        return None
    resume_missing = adapter.USES_RESUME_LINKS and vacancy.resume_id not in status.resume_hashes
    if status.impossible and not status.already_applied:
        vacancy.status = Vacancy.Status.SKIPPED
        vacancy.note = f"{adapter.NAME} no longer accepts applications for this job."
        vacancy.save()
        log(f"  SKIP    {vacancy.title}: {vacancy.note}")
        return False
    if status.already_applied or resume_missing:
        done = status.already_applied
        reason = (
            f"Already applied on {adapter.NAME}."
            if done
            else f"The linked {adapter.NAME} résumé is not offered for this vacancy."
        )
        finish(vacancy, done, reason, sent=False)
        if not done:
            summary.review.append(vacancy)
        log(f"  {vacancy.title}: {reason}")
        return False
    if not rehearse and is_flagship(adapter, vacancy):
        if not flagship_cv(vacancy, log):
            summary.review.append(vacancy)
            return False
    elif needs_tailoring(adapter, vacancy):
        tailor_cv(vacancy, log)
    letter = vacancy.cover_letter
    size = letter_size(status)
    if not letter and settings.MIMO_API_KEY and adapter.WANTS_LETTER and size != cover_letter.OFF:
        try:
            letter = cover_letter.generate(
                vacancy.cv.raw_text,
                vacancy.text,
                vacancy.cv.full_name or "",
                language=letter_language(vacancy.text),
                size=size,
                max_chars=status.letter_max_length,
            )
        except MODEL_ERRORS as error:
            log(f"  cover letter failed for {vacancy.title}: {error}")
            letter = ""
        vacancy.cover_letter = letter

    submitted = []

    def mark_submitted() -> None:
        submitted.append(True)
        vacancy.submitted_at = timezone.now()
        vacancy.save(update_fields=["submitted_at", "cover_letter", "updated_at"])

    resume_title = titles.get(vacancy.resume_id, "")
    mode = "rehearse" if rehearse else navigator_mode(adapter.SITE)
    if status.external_apply:
        mode = "rehearse" if rehearse else external_mode()
        if mode == "off":
            finish(vacancy, False, "Applies on the employer's site; external applying is off.")
            summary.review.append(vacancy)
            return False
    if forced and not rehearse and mode != "off":
        mode = "on"
    try:
        needs_navigator = status.has_test or status.external_apply or not adapter.SCRIPTED_APPLY
        if rehearse or (mode != "off" and needs_navigator):
            applied, note = navigate(
                page,
                adapter,
                vacancy,
                status,
                resume_title,
                letter,
                log,
                mode == "rehearse",
                mark_submitted,
            )
        else:
            applied, note = adapter.apply(
                page,
                vacancy.url,
                resume_title,
                letter,
                status,
                notify=log if headed else None,
                on_submit=mark_submitted,
                applicant=applicant_for(vacancy.cv),
            )
            if not applied and not submitted:
                evidence.capture(page, evidence.key_for(vacancy))
                if mode != "off" and note.startswith(adapter.NAVIGABLE):
                    log(f"  scripted apply failed ({note}); handing over to the navigator")
                    applied, note = navigate(
                        page,
                        adapter,
                        vacancy,
                        status,
                        resume_title,
                        letter,
                        log,
                        mode == "rehearse",
                        mark_submitted,
                    )
    except CaptchaError as error:
        if rehearse:
            Vacancy.objects.filter(pk=vacancy.pk).update(status=original_status)
            raise
        vacancy.status = Vacancy.Status.NEEDS_REVIEW
        vacancy.submitted_at = None
        vacancy.note = (
            f"{adapter.NAME} asked for a captcha before sending; nothing was submitted. Use "
            "Send in the Job agent app to send it in a visible browser."
        )
        vacancy.save()
        summary.review.append(vacancy)
        error.vacancy = vacancy
        raise
    except PlaywrightError as error:
        applied = False
        note = f"Browser error: {first_line(error)}"
        if submitted:
            note += f" (after Submit; check {adapter.NAME} before resending)"
        with suppress(PlaywrightError):
            evidence.capture(page, evidence.key_for(vacancy))
    if rehearse:
        Vacancy.objects.filter(pk=vacancy.pk).update(
            status=original_status, cover_letter=vacancy.cover_letter
        )
        log(f"  REHEARSAL {vacancy.title}: {note}")
        return False
    refused = bool(adapter.TRY_LATER) and note.startswith(adapter.TRY_LATER)
    if not applied and (refused or not submitted and only_stuck(vacancy, note)):
        found = REFUSALS_RE.search(vacancy.note or "")
        refusals = (int(found.group(1)) if found else 0) + 1
        times = "1 time" if refusals == 1 else f"{refusals} times"
        if refused:
            note = f"{adapter.NAME} refused this job {times}; nothing was saved. {note}"
        else:
            note = f"The agent got stuck on this job {times}; nothing was submitted. {note}"
        vacancy.submitted_at = None
        if refusals < REFUSAL_LIMIT:
            Vacancy.objects.filter(pk=vacancy.pk).update(
                status=Vacancy.Status.READY,
                note=note[:2000],
                submitted_at=None,
                cover_letter=vacancy.cover_letter,
                updated_at=timezone.now(),
            )
            log(f"  LATER   {vacancy.title}: {note}")
            return True
    finish(vacancy, applied, note)
    if applied:
        captcha.record_send(adapter.SITE)
    (summary.applied if applied else summary.review).append(vacancy)
    log(f"  {'APPLIED' if applied else 'REVIEW '} {vacancy.title}: {note}")
    return True


def only_stuck(vacancy: Vacancy, note: str) -> bool:
    held = copy.copy(vacancy)
    held.note = note
    return review.kind_of(held) == review.STUCK


def navigate(
    page, adapter, vacancy, status, resume_title, letter, log, rehearse, on_submit
) -> tuple:
    adapter.open_for_apply(page, vacancy.url)
    navigator = Navigator(
        page,
        goal=adapter.navigator_goal(vacancy.title, resume_title, letter, status)
        + ("" if adapter.EMPLOYER_BOARDS else tailored_note(vacancy)),
        cv_text=vacancy.cv.raw_text or "",
        job_text=vacancy.text,
        log=log,
        rehearse=rehearse,
        on_submit=on_submit,
        upload_path=cv_file_path(vacancy.cv),
        upload_name=upload_name_for(adapter, vacancy.cv),
        contact=contact_for(vacancy.cv),
        facts=settings.HUNTER_FACTS,
        external_hops=1 if status.external_apply else 0,
        eeo=inbox.answered_eeo(),
        max_steps=settings.HUNTER_NAVIGATOR_EXTERNAL_STEPS if adapter.EMPLOYER_BOARDS else 0,
        code_reader=code_reader_for(vacancy),
    )
    result = navigator.run()
    evidence.capture(navigator.page, evidence.key_for(vacancy), result.trace)
    on_page = status.external_apply or adapter.EMPLOYER_BOARDS
    external_note = ""
    if on_page and (result.status == "done" or result.submitted):
        external_note = confirm_external(navigator)
    navigator.close_opened()
    if result.status == "captcha" and not result.submitted:
        raise CaptchaError(result.note)
    if result.status == "rehearsed":
        return False, result.note
    if on_page and (result.status == "done" or result.submitted):
        if external_note:
            return True, external_note
        return False, (
            f"Navigator {result.status}: {result.note} The employer's page did not confirm the "
            "application; check it before resending."
        )
    if result.status == "done" or result.submitted:
        page.wait_for_timeout(2000)
        page.goto("about:blank")
        confirmed = adapter.response_status(page, vacancy.url)
        if confirmed and confirmed.already_applied:
            return True, f"Applied on {adapter.NAME} by the navigator."
        return False, (
            f"Navigator {result.status}: {result.note} {adapter.NAME} does not report the "
            "response; check it before resending."
        )
    return False, f"Navigator {result.status}: {result.note}"


def confirm_external(navigator) -> str:
    try:
        navigator.page.wait_for_timeout(2500)
        text = navigator.page.evaluate(PAGE_TEXT_JS)
    except PlaywrightError:
        return ""
    match = CONFIRMED_RE.search(text)
    if not match:
        return ""
    hosts = ", ".join(navigator.external_hosts) or host_of(navigator.page.url)
    return f'Applied on the employer\'s site ({hosts}): "{match.group(0)}".'


def code_reader_for(vacancy):
    address = vacancy.cv.email or ""
    if not address or mail.code_account(address) is None:
        return None
    return lambda since: mail.email_code(address, since, vacancy.employer)


def contact_for(cv) -> dict:
    return {
        "name": cv.full_name or "",
        "email": cv.email or "",
        "phone": cv.phone or settings.HUNTER_CONTACT_PHONE,
        "city": settings.HUNTER_CONTACT_CITY,
    }


def applicant_for(cv) -> dict:
    return {
        **contact_for(cv),
        "cv_path": cv_file_path(cv),
        "linkedin": dsml.linkedin_url(cv.raw_text or ""),
    }


def upload_name_for(adapter, cv) -> str:
    if not adapter.DISTINCT_UPLOAD_NAMES:
        return ""
    if not Cv.objects.filter(original_filename=cv.original_filename).exclude(pk=cv.pk).exists():
        return ""
    stem, dot, suffix = cv.original_filename.rpartition(".")
    return f"{stem}_{cv.id}.{suffix}" if dot else f"{cv.original_filename}_{cv.id}"


def cv_file_path(cv) -> str:
    try:
        return cv.file.path if cv.file else ""
    except (ValueError, NotImplementedError):
        return ""


def finish(vacancy: Vacancy, applied: bool, note: str, sent: bool = True) -> None:
    vacancy.status = Vacancy.Status.APPLIED if applied else Vacancy.Status.NEEDS_REVIEW
    vacancy.note = note[:2000]
    if applied and sent:
        vacancy.applied_at = timezone.now()
    vacancy.save()


def site_groups(only: str) -> list[tuple]:
    if only:
        urls = Vacancy.objects.filter(external_id=only).values_list("url", flat=True)
    else:
        urls = settings.JOB_SOURCE_URLS
    groups: dict = {}
    for url in urls:
        adapter = adapter_for(url)
        if adapter is not None:
            groups.setdefault(adapter.SITE, (adapter, []))[1].append(url)
    order = settings.HUNTER_SITE_PRIORITY
    return sorted(
        groups.values(),
        key=lambda group: order.index(group[0].SITE) if group[0].SITE in order else len(order),
    )


def run_once(
    *,
    apply: bool,
    limit: int,
    max_pages: int,
    log,
    only: str = "",
    headed: bool = False,
    rehearse: bool = False,
    summary: RunSummary | None = None,
) -> RunSummary:
    summary = summary if summary is not None else RunSummary()
    links = list(ResumeLink.objects.select_related("cv"))
    if not links:
        raise RuntimeError("Link at least one CV to an hh résumé first (hh_resumes --link).")
    groups = site_groups(only)
    if not groups:
        if only:
            raise RuntimeError(f"No known vacancy {only} on a supported site.")
        raise RuntimeError("Set JOB_SOURCE_URLS in core/.env to one or more job search URLs.")
    Vacancy.objects.filter(
        status=Vacancy.Status.APPLYING,
        updated_at__lt=timezone.now() - timedelta(hours=2),
    ).update(status=Vacancy.Status.NEEDS_REVIEW, note="Run stopped while applying; check the site.")
    apply_scope_threshold(log)
    errors: dict = {}
    unattended = apply and not only and not rehearse and not headed
    lanes = 1 if only or headed or rehearse else min(settings.HUNTER_PARALLEL_SITES, len(groups))
    if lanes <= 1:
        for adapter, urls in groups:
            if STOPPING.is_set():
                break
            problem = try_site(
                adapter, urls, links, apply, limit, max_pages, log, only, headed, rehearse, summary
            )
            if problem:
                errors[adapter.SITE] = (adapter, problem)
    else:
        with ThreadPoolExecutor(max_workers=lanes, thread_name_prefix="site") as pool:
            futures = [
                (
                    adapter,
                    pool.submit(
                        lane, adapter, urls, links, apply, limit, max_pages, log, only, rehearse
                    ),
                )
                for adapter, urls in groups
            ]
        failure = None
        for adapter, future in futures:
            if future.exception():
                failure = failure or future.exception()
                continue
            part, problem = future.result()
            merge(summary, part)
            if problem:
                errors[adapter.SITE] = (adapter, problem)
        if failure:
            raise failure
    if unattended and not STOPPING.is_set():
        retry_paused(groups, links, limit, max_pages, log, summary, errors)
    if errors:
        raise RuntimeError(
            "; ".join(
                f"{adapter.NAME}: {problem}" if len(groups) > 1 else problem
                for adapter, problem in errors.values()
            )
        )
    return summary


def lane(adapter, urls, links, apply, limit, max_pages, log, only, rehearse) -> tuple:
    summary = RunSummary()
    if STOPPING.is_set():
        return summary, ""
    try:
        problem = try_site(
            adapter,
            urls,
            links,
            apply,
            limit,
            max_pages,
            lambda line: log(f"[{adapter.SITE}] {line}"),
            only,
            False,
            rehearse,
            summary,
        )
    finally:
        connection.close()
    return summary, problem


def merge(summary: RunSummary, part: RunSummary) -> None:
    summary.discovered += part.discovered
    summary.applied += part.applied
    summary.review += part.review
    summary.reconciled += part.reconciled
    summary.daily_cap_reached = summary.daily_cap_reached or part.daily_cap_reached


def try_site(
    adapter, urls, links, apply, limit, max_pages, log, only, headed, rehearse, summary, crawl=True
) -> str:
    unattended = apply and not only and not rehearse and not headed and adapter.HEADED_CAPTCHA
    try:
        try:
            run_site(
                adapter,
                urls,
                links,
                apply,
                limit,
                max_pages,
                log,
                only,
                headed,
                rehearse,
                summary,
                crawl=crawl,
            )
        except CaptchaError as error:
            held = getattr(error, "vacancy", None)
            if not (unattended and held and captcha.ask_to_solve(adapter, held, log)):
                raise
            try:
                assisted_apply(adapter, links, held, limit, log, summary)
            except PlaywrightError as failure:
                log(f"{adapter.NAME}: the visible browser did not open: {failure}")
                if any(v.pk == held.pk for v in summary.applied):
                    return ""
                raise error from failure
    except CaptchaError as error:
        held = getattr(error, "vacancy", None)
        if not (unattended and held):
            log(f"{adapter.NAME}: {error}")
            return str(error)
        requeue(held, summary)
        until = captcha.start_cooldown(adapter.SITE)
        attempt, total = captcha.attempt_of(adapter.SITE)
        again = (
            f" Trying again at {timezone.localtime(until):%H:%M %Z} (wait {attempt} of {total})."
            if until
            else ""
        )
        log(f"{adapter.NAME}: {error}{again}")
        return str(error)
    except RuntimeError as error:
        log(f"{adapter.NAME}: {error}")
        return str(error)
    return ""


def requeue(vacancy, summary) -> None:
    Vacancy.objects.filter(pk=vacancy.pk, status=Vacancy.Status.NEEDS_REVIEW).update(
        status=Vacancy.Status.READY, note="", submitted_at=None, updated_at=timezone.now()
    )
    summary.review = [v for v in summary.review if v.pk != vacancy.pk]


def wait_until(until, adapter, log) -> None:
    while (remaining := (until - timezone.now()).total_seconds()) > 0:
        log(f"Waiting {math.ceil(remaining / 60)} min before trying {adapter.NAME} again.")
        time.sleep(min(remaining, WAIT_LOG_SECONDS))


def retry_paused(groups, links, limit, max_pages, log, summary, errors) -> None:
    for _ in range(RETRY_PASSES):
        due = []
        for adapter, urls in groups:
            until = captcha.due_at(adapter.SITE) if adapter.HEADED_CAPTCHA else None
            waiting = Vacancy.objects.filter(source=adapter.SITE, status=Vacancy.Status.READY)
            capped = sent_last_day() >= settings.HUNTER_MAX_APPLIES_PER_DAY
            soon = until and until - timezone.now() <= RETRY_WAIT
            if soon and not capped and waiting.exclude(cv=None).exists():
                due.append((until, adapter, urls))
        if not due:
            return
        until, adapter, urls = min(due, key=lambda item: item[0])
        wait_until(until, adapter, log)
        problem = try_site(
            adapter,
            urls,
            links,
            True,
            limit,
            max_pages,
            log,
            "",
            False,
            False,
            summary,
            crawl=False,
        )
        if problem:
            errors[adapter.SITE] = (adapter, problem)
        else:
            errors.pop(adapter.SITE, None)


def run_site(
    adapter, urls, links, apply, limit, max_pages, log, only, headed, rehearse, summary, crawl=True
):
    with open_browser(adapter.SITE, headless=False if headed else None) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(adapter.origin(urls[0]), wait_until="domcontentloaded")
        if not adapter.is_logged_in(page):
            raise RuntimeError(
                f"The {adapter.NAME} profile is not logged in; run hunter_login {adapter.SITE}."
            )
        if not only and crawl:
            reconcile(page, adapter, log, summary)
            resume_hashes = [link.resume_id for link in links if link.source == adapter.SITE]
            created = []
            for url in urls:
                for search_url in adapter.expand_source(url, resume_hashes):
                    budget = settings.HUNTER_MAX_NEW_PER_RUN - len(created)
                    created += discover(page, adapter, search_url, max_pages, log, budget)
            summary.discovered += len(created)
            pending = unscored(adapter.SITE)
            score_vacancies(pending, links)
            summary.review += [v for v in pending if v.status == Vacancy.Status.NEEDS_REVIEW]
            report(list(Vacancy.objects.filter(pk__in=[v.pk for v in created])), log)
        cooling = None if only or rehearse or headed else captcha.cooling_until(adapter.SITE)
        if STOPPING.is_set():
            return
        if apply and cooling:
            log(
                f"{adapter.NAME} asked for a captcha recently; trying again at "
                f"{timezone.localtime(cooling):%H:%M %Z}."
            )
        elif apply:
            apply_ready(page, adapter, limit, links, log, summary, only, headed, rehearse)
        else:
            ready = Vacancy.objects.filter(source=adapter.SITE, status=Vacancy.Status.READY).count()
            log(f"Dry run: {ready} {adapter.NAME} vacancies ready; rerun with --apply to send.")


def assisted_apply(adapter, links, vacancy, limit, log, summary) -> None:
    sent_before = {v.pk for v in summary.applied}
    with open_browser(adapter.SITE, headless=False) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(adapter.origin(vacancy.url), wait_until="domcontentloaded")
        if not adapter.is_logged_in(page):
            raise RuntimeError(
                f"The {adapter.NAME} profile is not logged in; run hunter_login {adapter.SITE}."
            )
        apply_ready(page, adapter, 1, links, log, summary, vacancy.external_id, headed=True)
        if not any(v.pk == vacancy.pk for v in summary.applied):
            return
        summary.review = [v for v in summary.review if v.pk != vacancy.pk]
        captcha.clear_cooldown(adapter.SITE)
        tried = sum(1 for v in [*summary.applied, *summary.review] if v.source == adapter.SITE)
        remaining = max(0, min(limit, adapter.MAX_SENDS_PER_RUN or limit) - tried)
        if remaining:
            apply_ready(page, adapter, remaining, links, log, summary, headed=True)
    log(
        f"{adapter.NAME}: sent {len([v for v in summary.applied if v.pk not in sent_before])} "
        "with your help."
    )


def report(vacancies: list[Vacancy], log) -> None:
    for vacancy in sorted(vacancies, key=lambda v: -(v.match_score or -1)):
        score = "--" if vacancy.match_score is None else f"{vacancy.match_score:>3}"
        log(
            f"{score} {vacancy.status:<15} {vacancy.title[:48]:<48} "
            f"{vacancy.employer[:24]:<24} CV {vacancy.cv_id or '-'} {vacancy.url}"
        )
        if vacancy.match_reason or vacancy.note:
            log(f"      {(vacancy.note or vacancy.match_reason)[:160]}")
