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

from . import evidence
from .browser import open_browser
from .models import ResumeLink, Vacancy
from .navigator import Navigator
from .sources import adapter_for
from .sources.base import CaptchaError
from .state import sent_last_day

SCORE_BATCH = 8
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


def navigator_mode(site: str = "") -> str:
    mode = (
        (settings.HUNTER_NAVIGATOR_BY_SITE.get(site) or settings.HUNTER_NAVIGATOR).strip().lower()
    )
    if not settings.MIMO_API_KEY or mode not in {"on", "rehearse"}:
        return "off"
    return mode


def letter_language(text: str) -> str:
    return "Russian" if len(CYRILLIC_RE.findall(text)) > len(LATIN_RE.findall(text)) else ""


def score_vacancies(vacancies: list[Vacancy], links: list[ResumeLink]) -> None:
    cvs = list({link.cv_id: link.cv for link in links}.values())
    resume_for = {(link.source, link.cv_id): link.resume_id for link in links}
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
            vacancy.resume_id = resume_for.get((vacancy.source, cv.id), "") if cv else ""
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
    if not settings.HUNTER_EXTERNAL_APPLY:
        external = [item for item in fresh if item.external_apply]
        fresh = [item for item in fresh if not item.external_apply]
        if external:
            log(f"  {len(external)} apply on the employer's site; external applying is off")
    for item in fresh[:budget]:
        try:
            details = adapter.read_vacancy(page, item.url)
            status = adapter.response_status(page, base, item.external_id)
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
        elif details.external_apply and not settings.HUNTER_EXTERNAL_APPLY:
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
            status = adapter.response_status(page, adapter.origin(vacancy.url), vacancy.external_id)
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
    if only:
        statuses.append(Vacancy.Status.NEEDS_REVIEW)
        queue = queue.filter(external_id=only)
    queue = queue.filter(status__in=statuses).exclude(cv=None)
    attempted = False
    for vacancy in queue.order_by("-match_score", "id")[:limit]:
        if attempted:
            time.sleep(random.uniform(20, 60))
        claimed = Vacancy.objects.filter(pk=vacancy.pk, status__in=statuses).update(
            status=Vacancy.Status.APPLYING, updated_at=timezone.now()
        )
        if not claimed:
            continue
        try:
            result = apply_one(
                page, adapter, vacancy, titles, log, summary, headed, rehearse, forced=bool(only)
            )
        except (KeyboardInterrupt, SystemExit):
            finish(
                vacancy,
                False,
                f"The agent stopped while applying; check {adapter.NAME} before resending.",
            )
            raise
        if result is None:
            break
        attempted = attempted or result


def apply_one(
    page, adapter, vacancy, titles, log, summary, headed, rehearse=False, forced=False
) -> bool | None:
    original_status = vacancy.status
    try:
        status = adapter.response_status(page, adapter.origin(vacancy.url), vacancy.external_id)
    except PlaywrightError as error:
        status = None
        log(f"  response info failed for {vacancy.title}: {first_line(error)}")
    if status is None:
        Vacancy.objects.filter(pk=vacancy.pk).update(status=Vacancy.Status.READY)
        log(f"  {adapter.NAME} returned no response info; stopping sends until the next run.")
        return None
    resume_missing = adapter.USES_RESUME_LINKS and vacancy.resume_id not in status.resume_hashes
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

    resume_title = titles.get(vacancy.resume_id, "")
    mode = "rehearse" if rehearse else navigator_mode(adapter.SITE)
    if forced and not rehearse and mode != "off":
        mode = "on"
    try:
        if rehearse or (mode != "off" and (status.has_test or not adapter.SCRIPTED_APPLY)):
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
    except CaptchaError:
        if rehearse:
            Vacancy.objects.filter(pk=vacancy.pk).update(status=original_status)
            raise
        vacancy.status = Vacancy.Status.NEEDS_REVIEW
        vacancy.note = (
            f"{adapter.NAME} asked for a captcha before sending; nothing was submitted. Stop the "
            "service (`systemctl --user stop job-filler-hunter`), then send it with "
            f"`hunt --apply --headed --vacancy {vacancy.external_id}`."
        )
        vacancy.save()
        summary.review.append(vacancy)
        raise
    except PlaywrightError as error:
        applied = False
        note = f"Browser error: {first_line(error)}"
        if submitted:
            note += f" (after Submit; check {adapter.NAME} before resending)"
    if rehearse:
        Vacancy.objects.filter(pk=vacancy.pk).update(
            status=original_status, cover_letter=vacancy.cover_letter
        )
        log(f"  REHEARSAL {vacancy.title}: {note}")
        return False
    finish(vacancy, applied, note)
    (summary.applied if applied else summary.review).append(vacancy)
    log(f"  {'APPLIED' if applied else 'REVIEW '} {vacancy.title}: {note}")
    return True


def navigate(
    page, adapter, vacancy, status, resume_title, letter, log, rehearse, on_submit
) -> tuple:
    page.goto(vacancy.url, wait_until="domcontentloaded")
    navigator = Navigator(
        page,
        goal=adapter.navigator_goal(vacancy.title, resume_title, letter, status),
        cv_text=vacancy.cv.raw_text or "",
        job_text=vacancy.text,
        log=log,
        rehearse=rehearse,
        on_submit=on_submit,
        upload_path=cv_file_path(vacancy.cv),
        contact=contact_for(vacancy.cv),
    )
    result = navigator.run()
    evidence.capture(navigator.page, evidence.key_for(vacancy), result.trace)
    if result.status == "captcha" and not result.submitted:
        raise CaptchaError(result.note)
    if result.status == "rehearsed":
        return False, result.note
    if result.status == "done" or result.submitted:
        page.wait_for_timeout(2000)
        confirmed = adapter.response_status(page, adapter.origin(vacancy.url), vacancy.external_id)
        if confirmed and confirmed.already_applied:
            return True, f"Applied on {adapter.NAME} by the navigator."
        return False, (
            f"Navigator {result.status}: {result.note} {adapter.NAME} does not report the "
            "response; check it before resending."
        )
    return False, f"Navigator {result.status}: {result.note}"


def contact_for(cv) -> dict:
    return {
        "name": cv.full_name or "",
        "email": cv.email or "",
        "phone": cv.phone or settings.HUNTER_CONTACT_PHONE,
        "city": settings.HUNTER_CONTACT_CITY,
    }


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
    return list(groups.values())


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
    errors = []
    for adapter, urls in groups:
        try:
            run_site(
                adapter, urls, links, apply, limit, max_pages, log, only, headed, rehearse, summary
            )
        except RuntimeError as error:
            log(f"{adapter.NAME}: {error}")
            errors.append(f"{adapter.NAME}: {error}" if len(groups) > 1 else str(error))
    if errors:
        raise RuntimeError("; ".join(errors))
    return summary


def run_site(adapter, urls, links, apply, limit, max_pages, log, only, headed, rehearse, summary):
    with open_browser(adapter.SITE, headless=False if headed else None) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(adapter.origin(urls[0]), wait_until="domcontentloaded")
        if not adapter.is_logged_in(page):
            raise RuntimeError(
                f"The {adapter.NAME} profile is not logged in; run hunter_login {adapter.SITE}."
            )
        if not only:
            reconcile(page, adapter, log, summary)
            resume_hashes = [link.resume_id for link in links if link.source == adapter.SITE]
            created = []
            for url in urls:
                for search_url in adapter.expand_source(url, resume_hashes):
                    budget = settings.HUNTER_MAX_NEW_PER_RUN - len(created)
                    created += discover(page, adapter, search_url, max_pages, log, budget)
            summary.discovered += len(created)
            pending = unscored()
            score_vacancies(pending, links)
            summary.review += [v for v in pending if v.status == Vacancy.Status.NEEDS_REVIEW]
            report(list(Vacancy.objects.filter(pk__in=[v.pk for v in created])), log)
        if apply:
            apply_ready(page, adapter, limit, links, log, summary, only, headed, rehearse)
        else:
            ready = Vacancy.objects.filter(source=adapter.SITE, status=Vacancy.Status.READY).count()
            log(f"Dry run: {ready} {adapter.NAME} vacancies ready; rerun with --apply to send.")


def report(vacancies: list[Vacancy], log) -> None:
    for vacancy in sorted(vacancies, key=lambda v: -(v.match_score or -1)):
        score = "--" if vacancy.match_score is None else f"{vacancy.match_score:>3}"
        log(
            f"{score} {vacancy.status:<15} {vacancy.title[:48]:<48} "
            f"{vacancy.employer[:24]:<24} CV {vacancy.cv_id or '-'} {vacancy.url}"
        )
        if vacancy.match_reason or vacancy.note:
            log(f"      {(vacancy.note or vacancy.match_reason)[:160]}")
