import json
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from .base import CaptchaError, Listing, ResponseStatus, VacancyPage, pause

SITE = "hh"
NAME = "hh.kz"
LOGIN_URL = "https://hh.kz/account/login?backurl=%2F"
USES_RESUME_LINKS = True
SCRIPTED_APPLY = True
RECHECK_BATCH = 30
VACANCY_ID_RE = re.compile(r"/vacancy/(\d+)")
SUBMIT = '[data-qa="vacancy-response-submit-popup"]'
LETTER = '[data-qa="vacancy-response-popup-form-letter-input"]'
LETTER_TOGGLE = '[data-qa="vacancy-response-letter-toggle"]'
RESPOND = '[data-qa="vacancy-response-link-top"]'
RESUME_TITLE = '[data-qa="resume-title"]'
HIDDEN_RESUME_WARNING = '[data-qa="hidden-resume-warning"]'
CAPTCHA = '[data-qa^="account-captcha"]'
RELOCATION_CONFIRM = '[data-qa="relocation-warning-confirm"]'
HUMAN_CAPTCHA_WAIT_MS = 10 * 60 * 1000
NAVIGABLE = (
    "No hh.kz response button",
    "The response form did not open",
    "Could not select the hh résumé",
    "hh.kz opened an employer questionnaire",
)

SERP_JS = """
() => [...document.querySelectorAll('[data-qa="vacancy-serp__vacancy"]')].map(item => {
  const link = item.querySelector('a[data-qa="serp-item__title"]')
    || item.querySelector('a[href*="/vacancy/"]');
  return {
    title: (item.querySelector('[data-qa="serp-item__title-text"]') || link || {}).innerText || "",
    href: link ? link.href : "",
    employer: (item.querySelector('[data-qa="vacancy-serp__vacancy-employer-text"]') || {})
      .innerText || "",
  };
})
"""

RESUMES_JS = """
() => [...document.querySelectorAll('[data-qa="resume"]')].map(card => {
  const link = card.querySelector('[data-qa^="resume-card-link-"]');
  return {
    hash: link ? link.dataset.qa.replace("resume-card-link-", "") : "",
    title: (card.querySelector('[data-qa="resume-title"]') || {}).innerText || "",
    published: !!(link && link.getAttribute("href")),
  };
}).filter(resume => resume.hash)
"""


def handles(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "hh.kz" or host.endswith(".hh.kz")


def expand_source(url: str, resume_hashes: list[str]) -> list[str]:
    if urlparse(url).path not in {"", "/"}:
        return [url]
    base = origin(url)
    return [
        f"{base}/search/vacancy?{urlencode({'resume': resume_hash})}"
        for resume_hash in dict.fromkeys(resume_hashes)
    ]


def origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def vacancy_id(url: str) -> str | None:
    match = VACANCY_ID_RE.search(urlparse(url).path)
    return match.group(1) if match else None


def with_page_number(search_url: str, number: int) -> str:
    parsed = urlparse(search_url)
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k != "page"]
    if number:
        query.append(("page", str(number)))
    return urlunparse(parsed._replace(query=urlencode(query)))


def check_captcha(page) -> None:
    if "captcha" in page.url.lower() or page.locator('[data-qa*="captcha"]').count():
        raise CaptchaError(f"hh.kz is showing a captcha at {page.url}; solve it with hh_login.")


def is_logged_in(page) -> bool:
    return page.locator('[data-qa="mainmenu_applicantProfilePage"]').count() > 0


def crawl(page, search_url: str, max_pages: int) -> list[Listing]:
    found: dict[str, Listing] = {}
    base = origin(search_url)
    for number in range(max_pages):
        page.goto(with_page_number(search_url, number), wait_until="domcontentloaded")
        check_captcha(page)
        try:
            page.wait_for_selector('[data-qa="vacancy-serp__vacancy"]', timeout=15000)
        except PlaywrightTimeout:
            break
        before = len(found)
        for item in page.evaluate(SERP_JS):
            external_id = vacancy_id(item["href"])
            if not external_id or external_id in found:
                continue
            found[external_id] = Listing(
                external_id=external_id,
                url=f"{base}/vacancy/{external_id}",
                title=item["title"].strip(),
                employer=item["employer"].strip(),
            )
        if len(found) == before:
            break
        pause(page)
    return list(found.values())


def read_vacancy(page, url: str) -> VacancyPage:
    page.goto(url, wait_until="domcontentloaded")
    check_captcha(page)
    page.wait_for_selector('[data-qa="vacancy-title"]', timeout=20000)

    def text_of(selector: str) -> str:
        locator = page.locator(selector)
        return locator.first.inner_text().strip() if locator.count() else ""

    title = text_of('[data-qa="vacancy-title"]')
    employer = text_of('[data-qa="vacancy-company-name"]')
    parts = [
        title,
        employer,
        text_of('[data-qa="vacancy-salary"]'),
        text_of('[data-qa="vacancy-experience"]'),
        text_of('[data-qa="vacancy-view-raw-address"]'),
        text_of('[data-qa="vacancy-description"]'),
        ", ".join(page.locator('[data-qa="skills-element"]').all_inner_texts()),
    ]
    return VacancyPage(
        title=title,
        employer=employer,
        text="\n".join(part for part in parts if part)[:12000],
        has_respond_button=page.locator(RESPOND).count() > 0,
    )


def response_status(page, base: str, external_id: str) -> ResponseStatus | None:
    response = page.request.get(
        f"{base}/applicant/vacancy_response/popup",
        params={"vacancyId": external_id, "isTest": "no", "withoutTest": "no", "lux": "true"},
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    if response.status != 200:
        return None
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return None
    return parse_status(payload.get("responseStatus") or {}, payload.get("relocationWarning"))


def parse_status(status: dict, relocation: dict | None = None) -> ResponseStatus:
    vacancy = status.get("shortVacancy") or {}
    resumes = status.get("resumes") or {}
    return ResponseStatus(
        already_applied=bool(
            status.get("alreadyApplied")
            or (status.get("negotiations") or {}).get("topicList")
            or status.get("usedResumeIds")
        ),
        impossible=bool(status.get("responseImpossible")),
        letter_required=bool(vacancy.get("@responseLetterRequired")),
        has_test=bool((status.get("test") or {}).get("hasTests")),
        letter_max_length=int(status.get("letterMaxLength") or 4000),
        resume_hashes={
            str(resume.get("hash") or (resume.get("_attributes") or {}).get("hash"))
            for resume in resumes.values()
            if isinstance(resume, dict)
        },
        relocation_warning=bool((relocation or {}).get("show")),
        remote=any(
            "REMOTE" in (entry.get("workFormatsElement") or [])
            for entry in vacancy.get("workFormats") or []
            if isinstance(entry, dict)
        ),
    )


def navigator_goal(title: str, resume_title: str, letter: str, status: ResponseStatus) -> str:
    relocation = (
        "If hh.kz warns the job is in another region, reply stuck: this office job needs a move."
        if status.needs_relocation
        else "If hh.kz warns the job is in another region, confirm it: the job allows remote work."
    )
    lines = [
        f'Send a response (отклик) to the hh.kz vacancy "{title}" open in this tab.',
        "Press the vacancy's response button (Откликнуться) to open the response form.",
        f'Pick the résumé titled "{resume_title}" if the form offers a choice.',
        relocation,
        "Answer every employer question from the CV, then send the response.",
        (
            "The application is sent when hh.kz shows that the response was delivered "
            '(e.g. "Резюме доставлено" / "Вы откликнулись").'
        ),
    ]
    if letter:
        lines.append(f"Paste this cover letter into the letter field:\n{letter}")
    return "\n".join(lines)


def list_resumes(page, base: str) -> list[dict]:
    page.goto(f"{base}/applicant/resumes", wait_until="domcontentloaded")
    check_captcha(page)
    if not is_logged_in(page):
        raise RuntimeError("The hh.kz profile is not logged in; run hh_login.")
    page.wait_for_selector('[data-qa="resume"]', timeout=20000)
    return page.evaluate(RESUMES_JS)


def _dialog_text(page) -> str:
    dialog = page.locator('[data-qa="modal-content-scroll-container"]')
    return dialog.first.inner_text().strip()[:1500] if dialog.count() else ""


def _select_resume(page, title: str) -> bool:
    current = page.locator(RESUME_TITLE).first
    if current.inner_text().strip() == title:
        return True
    current.click()
    pause(page)
    options = page.get_by_text(title, exact=True)
    for index in range(options.count()):
        option = options.nth(index)
        if option.is_visible():
            option.click()
            break
    pause(page)
    return page.locator(RESUME_TITLE).first.inner_text().strip() == title


def _captcha_gate(page, notify) -> None:
    if notify is None or not page.locator('[data-qa*="captcha"]').count():
        check_captcha(page)
        return
    notify("hh.kz is showing a captcha: solve it in the browser window to continue.")
    try:
        page.locator('[data-qa*="captcha"]').first.wait_for(
            state="detached", timeout=HUMAN_CAPTCHA_WAIT_MS
        )
    except PlaywrightTimeout as error:
        raise CaptchaError("The captcha was not solved within 10 minutes.") from error


def _wait_after_submit(page, timeout_ms: int) -> str:
    for _ in range(timeout_ms // 500):
        if not page.locator(SUBMIT).count():
            return "closed"
        if page.locator(CAPTCHA).count():
            return "captcha"
        page.wait_for_timeout(500)
    return "timeout"


def apply(
    page,
    url: str,
    resume_title: str,
    letter: str,
    status: ResponseStatus,
    notify=None,
    on_submit=None,
) -> tuple:
    page.goto(url, wait_until="domcontentloaded")
    _captcha_gate(page, notify)
    button = page.locator(RESPOND)
    if not button.count():
        return False, "No hh.kz response button; the employer may take applications elsewhere."
    pause(page)
    button.first.click()
    try:
        page.wait_for_selector(f"{SUBMIT}, {RELOCATION_CONFIRM}", timeout=20000)
        if page.locator(RELOCATION_CONFIRM).count():
            if status.needs_relocation:
                return False, "hh.kz asks to confirm applying from another region to an office job."
            pause(page)
            page.locator(RELOCATION_CONFIRM).first.click()
            page.wait_for_selector(SUBMIT, timeout=20000)
    except PlaywrightTimeout:
        check_captcha(page)
        if "/applicant/vacancy_response" in page.url:
            return False, "hh.kz opened an employer questionnaire; answer it manually."
        return False, f"The response form did not open ({page.url})."
    if not _select_resume(page, resume_title):
        return False, f"Could not select the hh résumé '{resume_title}'."
    if page.locator(HIDDEN_RESUME_WARNING).first.is_visible():
        return False, page.locator(HIDDEN_RESUME_WARNING).first.inner_text().strip()
    if not page.locator(LETTER).count() and page.locator(LETTER_TOGGLE).count():
        page.locator(LETTER_TOGGLE).first.click()
        pause(page)
    if letter and page.locator(LETTER).count():
        page.locator(LETTER).first.fill(letter[: status.letter_max_length])
        pause(page)
    elif status.letter_required:
        return False, "This vacancy requires a cover letter and none was generated."
    if on_submit:
        on_submit()
    page.locator(SUBMIT).first.click()
    outcome = _wait_after_submit(page, 20000)
    if outcome == "captcha":
        if notify is None:
            raise CaptchaError("hh.kz asked for a captcha on submit; rerun with --headed.")
        notify("hh.kz asked for a captcha: solve it in the browser window to send the response.")
        try:
            page.wait_for_selector(SUBMIT, state="detached", timeout=HUMAN_CAPTCHA_WAIT_MS)
            outcome = "closed"
        except PlaywrightTimeout:
            outcome = "timeout"
    if outcome != "closed":
        return False, f"hh.kz did not accept the response: {_dialog_text(page)}"
    pause(page, 1.5, 3.0)
    confirmed = response_status(page, origin(url), vacancy_id(url) or "")
    if confirmed and confirmed.already_applied:
        return True, "Applied on hh.kz."
    return False, "The form closed but hh.kz does not report the response; check it manually."
