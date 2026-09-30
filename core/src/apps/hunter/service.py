import random
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from openai import OpenAIError
from playwright.sync_api import Error as PlaywrightError

from agent import cover_letter
from apps.opportunities.service import rank_jobs
from apps.opportunities.telegraph import TelegraphPage

from .browser import open_browser
from .models import ResumeLink, Vacancy
from .sources import adapter_for
from .sources.hh import CaptchaError
from .state import sent_last_day

SCORE_BATCH = 8
RECHECK_BATCH = 30
MODEL_ERRORS = (OpenAIError, ValueError, TypeError, AttributeError, KeyError)
UNSCORED_PREFIXES = ("Not scored", "Scoring failed")


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


def letter_language(text: str) -> str:
    return "Russian" if len(CYRILLIC_RE.findall(text)) > len(LATIN_RE.findall(text)) else ""


def score_vacancies(vacancies: list[Vacancy], links: list[ResumeLink]) -> None:
    cvs = [link.cv for link in links]
    resume_for = {link.cv_id: link.resume_id for link in links}
    for start in range(0, len(vacancies), SCORE_BATCH):
        batch = vacancies[start : start + SCORE_BATCH]
        try:
            ranked = rank_jobs(
                [(str(v.id), TelegraphPage(title=v.title, text=v.text, links=[])) for v in batch],
                cvs,
            )
        except MODEL_ERRORS as error:
            ranked = {}
            for vacancy in batch:
                vacancy.match_reason = f"Scoring failed: {error}"[:2000]
        for vacancy in batch:
            cv, score, reason = ranked.get(str(vacancy.id), (None, None, vacancy.match_reason))
            vacancy.cv = cv
            vacancy.resume_id = resume_for.get(cv.id, "") if cv else ""
            vacancy.match_score = score
            vacancy.match_reason = reason or f"{UNSCORED_PREFIXES[0]}; is MIMO_API_KEY set?"
            ready = score is not None and score >= settings.HUNTER_MIN_SCORE
            if not ready:
                vacancy.status = Vacancy.Status.BELOW_THRESHOLD
            elif vacancy.note:
                vacancy.status = Vacancy.Status.NEEDS_REVIEW
            else:
                vacancy.status = Vacancy.Status.READY
            vacancy.save()


def unscored() -> list[Vacancy]:
    reason_filter = Q(match_reason="")
    for prefix in UNSCORED_PREFIXES:
        reason_filter |= Q(match_reason__startswith=prefix)
    return list(
        Vacancy.objects.filter(
            reason_filter, status=Vacancy.Status.BELOW_THRESHOLD, match_score__isnull=True
        )
    )


def discover(page, adapter, search_url: str, max_pages: int, log, budget: int) -> list[Vacancy]:
    if budget <= 0:
        return []
    listings = adapter.crawl(page, search_url, max_pages)
    known = set(
        Vacancy.objects.filter(
            source=adapter.SITE, external_id__in=[item.external_id for item in listings]
        ).values_list("external_id", flat=True)
    )
    fresh = [item for item in listings if item.external_id not in known]
    log(f"{search_url}: {len(listings)} listed, {len(fresh)} new")
    base = adapter.origin(search_url)
    created = []
    for item in fresh[:budget]:
        try:
            details = adapter.read_vacancy(page, item.url)
            status = adapter.response_status(page, base, item.external_id)
        except PlaywrightError as error:
            log(f"  could not read {item.url}: {first_line(error)}")
            continue
        if status is None:
            if not adapter.is_logged_in(page):
                raise RuntimeError("The hh.kz session expired; run hh_login.")
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
            vacancy.status, vacancy.note = Vacancy.Status.APPLIED, "Already applied on hh.kz."
        elif status.impossible:
            vacancy.status, vacancy.note = (
                Vacancy.Status.SKIPPED,
                "hh.kz does not allow a response.",
            )
        elif not details.has_respond_button:
            vacancy.status = Vacancy.Status.SKIPPED
            vacancy.note = "No hh.kz response button; the employer takes applications elsewhere."
        elif status.has_test:
            vacancy.note = "Employer questionnaire required; answer it manually."
        elif status.needs_relocation:
            vacancy.note = "Office job in another region; hh.kz warns about relocation."
        vacancy.save()
        created.append(vacancy)
        adapter.pause(page, 1.5, 4.0)
    return created


def reconcile(page, log, summary: RunSummary) -> None:
    held = Vacancy.objects.filter(status=Vacancy.Status.NEEDS_REVIEW).order_by("updated_at")
    for vacancy in held[:RECHECK_BATCH]:
        adapter = adapter_for(vacancy.url)
        if adapter is None:
            continue
        try:
            status = adapter.response_status(page, adapter.origin(vacancy.url), vacancy.external_id)
        except PlaywrightError as error:
            log(f"  recheck failed for {vacancy.title}: {first_line(error)}")
            continue
        if status is None:
            continue
        if status.already_applied:
            finish(
                vacancy, True, "Sent outside the agent; confirmed in hh.kz responses.", sent=False
            )
            summary.reconciled.append(vacancy)
            log(f"  SENT    {vacancy.title}: confirmed in hh.kz responses")
        elif status.impossible:
            vacancy.status, vacancy.note = (
                Vacancy.Status.SKIPPED,
                "hh.kz no longer accepts responses.",
            )
            vacancy.save()
            log(f"  CLOSED  {vacancy.title}")
        else:
            Vacancy.objects.filter(pk=vacancy.pk).update(updated_at=timezone.now())
        adapter.pause(page, 0.5, 1.5)


def apply_ready(
    page,
    limit: int,
    links: list[ResumeLink],
    log,
    summary: RunSummary,
    only: str = "",
    headed: bool = False,
) -> None:
    titles = {link.resume_id: link.title for link in links}
    remaining = max(0, settings.HUNTER_MAX_APPLIES_PER_DAY - sent_last_day())
    if remaining < limit:
        summary.daily_cap_reached = remaining == 0
        limit = remaining
        log(f"Daily cap: {remaining} more responses allowed in the last 24 hours.")
    statuses = [Vacancy.Status.READY]
    queue = Vacancy.objects.select_related("cv")
    if only:
        statuses.append(Vacancy.Status.NEEDS_REVIEW)
        queue = queue.filter(external_id=only)
    queue = queue.filter(status__in=statuses).exclude(cv=None)
    attempted = False
    for vacancy in queue.order_by("-match_score", "id")[:limit]:
        adapter = adapter_for(vacancy.url)
        if adapter is None:
            continue
        if attempted:
            time.sleep(random.uniform(20, 60))
        claimed = Vacancy.objects.filter(pk=vacancy.pk, status__in=statuses).update(
            status=Vacancy.Status.APPLYING, updated_at=timezone.now()
        )
        if not claimed:
            continue
        try:
            result = apply_one(page, adapter, vacancy, titles, log, summary, headed)
        except (KeyboardInterrupt, SystemExit):
            finish(
                vacancy, False, "The agent stopped while applying; check hh.kz before resending."
            )
            raise
        if result is None:
            break
        attempted = attempted or result


def apply_one(page, adapter, vacancy, titles, log, summary, headed) -> bool | None:
    try:
        status = adapter.response_status(page, adapter.origin(vacancy.url), vacancy.external_id)
    except PlaywrightError as error:
        status = None
        log(f"  response info failed for {vacancy.title}: {first_line(error)}")
    if status is None:
        Vacancy.objects.filter(pk=vacancy.pk).update(status=Vacancy.Status.READY)
        log("  hh.kz returned no response info; stopping sends until the next run.")
        return None
    if status.already_applied or vacancy.resume_id not in status.resume_hashes:
        done = status.already_applied
        reason = (
            "Already applied on hh.kz."
            if done
            else "The linked hh résumé is not offered for this vacancy."
        )
        finish(vacancy, done, reason, sent=False)
        if not done:
            summary.review.append(vacancy)
        log(f"  {vacancy.title}: {reason}")
        return False
    letter = vacancy.cover_letter
    if not letter and settings.MIMO_API_KEY:
        try:
            letter = cover_letter.generate(
                vacancy.cv.raw_text,
                vacancy.text,
                vacancy.cv.full_name or "",
                language=letter_language(vacancy.text),
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

    try:
        applied, note = adapter.apply(
            page,
            vacancy.url,
            titles.get(vacancy.resume_id, ""),
            letter,
            status,
            notify=log if headed else None,
            on_submit=mark_submitted,
        )
    except CaptchaError:
        vacancy.status = Vacancy.Status.NEEDS_REVIEW
        vacancy.note = (
            "hh.kz asked for a captcha before sending; nothing was submitted. Stop the service "
            "(`systemctl --user stop job-filler-hunter`), then send it with "
            f"`hunt --apply --headed --vacancy {vacancy.external_id}`."
        )
        vacancy.save()
        summary.review.append(vacancy)
        raise
    except PlaywrightError as error:
        applied = False
        note = f"Browser error: {first_line(error)}"
        if submitted:
            note += " (after Submit; check hh.kz before resending)"
    finish(vacancy, applied, note)
    (summary.applied if applied else summary.review).append(vacancy)
    log(f"  {'APPLIED' if applied else 'REVIEW '} {vacancy.title}: {note}")
    return True


def finish(vacancy: Vacancy, applied: bool, note: str, sent: bool = True) -> None:
    vacancy.status = Vacancy.Status.APPLIED if applied else Vacancy.Status.NEEDS_REVIEW
    vacancy.note = note[:2000]
    if applied and sent:
        vacancy.applied_at = timezone.now()
    vacancy.save()


def run_once(
    *,
    apply: bool,
    limit: int,
    max_pages: int,
    log,
    only: str = "",
    headed: bool = False,
    summary: RunSummary | None = None,
) -> RunSummary:
    summary = summary if summary is not None else RunSummary()
    links = list(ResumeLink.objects.select_related("cv").filter(source="hh"))
    if not links:
        raise RuntimeError("Link at least one CV to an hh résumé first (hh_resumes --link).")
    sources = [url for url in settings.JOB_SOURCE_URLS if adapter_for(url)]
    if not sources:
        raise RuntimeError("Set JOB_SOURCE_URLS in core/.env to one or more hh.kz search URLs.")
    Vacancy.objects.filter(
        status=Vacancy.Status.APPLYING,
        updated_at__lt=timezone.now() - timedelta(hours=2),
    ).update(status=Vacancy.Status.NEEDS_REVIEW, note="Run stopped while applying; check hh.kz.")
    with open_browser("hh", headless=False if headed else None) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(adapter_for(sources[0]).origin(sources[0]), wait_until="domcontentloaded")
        if not adapter_for(sources[0]).is_logged_in(page):
            raise RuntimeError("The hh.kz profile is not logged in; run hh_login.")
        if not only:
            reconcile(page, log, summary)
            resume_hashes = [link.resume_id for link in links]
            created = []
            for url in sources:
                adapter = adapter_for(url)
                for search_url in adapter.expand_source(url, resume_hashes):
                    budget = settings.HUNTER_MAX_NEW_PER_RUN - len(created)
                    created += discover(page, adapter, search_url, max_pages, log, budget)
            summary.discovered = len(created)
            pending = unscored()
            score_vacancies(pending, links)
            summary.review += [v for v in pending if v.status == Vacancy.Status.NEEDS_REVIEW]
            report(list(Vacancy.objects.filter(pk__in=[v.pk for v in created])), log)
        if apply:
            apply_ready(page, limit, links, log, summary, only, headed)
        else:
            ready = Vacancy.objects.filter(status=Vacancy.Status.READY).count()
            log(f"Dry run: {ready} vacancies ready; rerun with --apply to send responses.")
    return summary


def report(vacancies: list[Vacancy], log) -> None:
    for vacancy in sorted(vacancies, key=lambda v: -(v.match_score or -1)):
        score = "--" if vacancy.match_score is None else f"{vacancy.match_score:>3}"
        log(
            f"{score} {vacancy.status:<15} {vacancy.title[:48]:<48} "
            f"{vacancy.employer[:24]:<24} CV {vacancy.cv_id or '-'} {vacancy.url}"
        )
        if vacancy.match_reason or vacancy.note:
            log(f"      {(vacancy.note or vacancy.match_reason)[:160]}")
