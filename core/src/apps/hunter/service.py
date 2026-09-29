import random
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from openai import OpenAIError

from agent import cover_letter
from apps.opportunities.service import rank_jobs
from apps.opportunities.telegraph import TelegraphPage

from .browser import open_browser
from .models import ResumeLink, Vacancy
from .sources import adapter_for
from .sources.hh import CaptchaError

SCORE_BATCH = 8
UNSCORED_PREFIXES = ("Not scored", "Scoring failed")


@dataclass
class RunSummary:
    discovered: int = 0
    applied: list = field(default_factory=list)
    review: list = field(default_factory=list)
    daily_cap_reached: bool = False


CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)


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
        except (OpenAIError, ValueError) as error:
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


def discover(page, adapter, search_url: str, max_pages: int, log) -> list[Vacancy]:
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
    for item in fresh[: settings.HUNTER_MAX_NEW_PER_RUN]:
        details = adapter.read_vacancy(page, item.url)
        status = adapter.response_status(page, base, item.external_id)
        vacancy = Vacancy(
            source=adapter.SITE,
            external_id=item.external_id,
            url=item.url,
            title=(details.title or item.title)[:255],
            employer=(details.employer or item.employer)[:255],
            text=details.text,
            status=Vacancy.Status.BELOW_THRESHOLD,
        )
        if status is None:
            vacancy.status, vacancy.note = (
                Vacancy.Status.SKIPPED,
                "hh.kz response info unavailable.",
            )
        elif status.already_applied:
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
        elif status.relocation_warning:
            vacancy.note = "hh.kz warns this vacancy is in another region; check before applying."
        vacancy.save()
        created.append(vacancy)
        adapter.pause(page, 1.5, 4.0)
    return created


def sent_last_day() -> int:
    return Vacancy.objects.filter(applied_at__gte=timezone.now() - timedelta(days=1)).count()


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
        summary.daily_cap_reached = True
        limit = remaining
        log(f"Daily cap: {remaining} more responses allowed in the last 24 hours.")
    queue = Vacancy.objects.filter(status=Vacancy.Status.READY).select_related("cv")
    if only:
        queue = queue.filter(external_id=only)
    for index, vacancy in enumerate(queue.order_by("-match_score", "id")[:limit]):
        adapter = adapter_for(vacancy.url)
        claimed = Vacancy.objects.filter(pk=vacancy.pk, status=Vacancy.Status.READY).update(
            status=Vacancy.Status.APPLYING, updated_at=timezone.now()
        )
        if not claimed or adapter is None or vacancy.cv is None:
            continue
        if index:
            time.sleep(random.uniform(20, 60))
        status = adapter.response_status(page, adapter.origin(vacancy.url), vacancy.external_id)
        if (
            status is None
            or status.already_applied
            or vacancy.resume_id not in status.resume_hashes
        ):
            reason = (
                "Already applied on hh.kz."
                if status and status.already_applied
                else "The linked hh résumé is not offered for this vacancy."
            )
            done = bool(status and status.already_applied)
            finish(vacancy, done, reason, sent=False)
            if not done:
                summary.review.append(vacancy)
            log(f"  {vacancy.title}: {reason}")
            continue
        letter = vacancy.cover_letter
        if not letter and settings.MIMO_API_KEY:
            try:
                letter = cover_letter.generate(
                    vacancy.cv.raw_text,
                    vacancy.text,
                    vacancy.cv.full_name or "",
                    language=letter_language(vacancy.text),
                )
            except OpenAIError as error:
                log(f"  cover letter failed for {vacancy.title}: {error}")
                letter = ""
            vacancy.cover_letter = letter
        try:
            applied, note = adapter.apply(
                page,
                vacancy.url,
                titles.get(vacancy.resume_id, ""),
                letter,
                status,
                notify=log if headed else None,
            )
        except CaptchaError:
            vacancy.status = Vacancy.Status.NEEDS_REVIEW
            vacancy.note = (
                "hh.kz asked for a captcha before sending; nothing was submitted. Send it with "
                f"`hunt --apply --headed --vacancy {vacancy.external_id}`."
            )
            vacancy.save()
            summary.review.append(vacancy)
            raise
        finish(vacancy, applied, note)
        (summary.applied if applied else summary.review).append(vacancy)
        log(f"  {'APPLIED' if applied else 'REVIEW '} {vacancy.title}: {note}")


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
        resume_hashes = [link.resume_id for link in links]
        created = []
        for url in sources:
            adapter = adapter_for(url)
            for search_url in adapter.expand_source(url, resume_hashes):
                created += discover(page, adapter, search_url, max_pages, log)
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
