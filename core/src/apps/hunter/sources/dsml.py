import base64
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse, urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ..navigator import CONFIRMED_RE
from .base import CaptchaError, Listing, ResponseStatus, VacancyPage, pause

SITE = "dsml"
NAME = "DSML.kz"
LOGIN_URL = "https://dsml.kz/auth/signin?next=%2Fjobs"
USES_RESUME_LINKS = False
SCRIPTED_APPLY = True
WANTS_LETTER = True
RECHECK_BATCH = 5
HEADED_CAPTCHA = False
SEND_GAP = (20, 60)
MAX_SENDS_PER_RUN = 0
TRY_LATER = ("DSML.kz answered: Failed to save",)
EMPLOYER_BOARDS = False
NAVIGABLE = ("The DSML guest form did not open",)
BASE = "https://dsml.kz"
COVER_LIMIT = 1200
NOTE_LIMIT = 500
JOB_RE = re.compile(r"^(?:/(?:ru|kk|en))?/jobs/([0-9a-f-]{36})")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w%-]+/?", re.IGNORECASE)
APPLIED_RE = re.compile(
    r"\byou (have )?(already )?applied\b|application (was |has been )?(sent|submitted|received)|"
    r"вы (уже )?откликнулись|отклик отправлен|заявка отправлена",
    re.IGNORECASE,
)
CLOSED_RE = re.compile(r"\b(closed|no longer accepting|archived)\b|вакансия закрыта", re.IGNORECASE)
CHALLENGE_RE = re.compile(r"Just a moment|Attention Required|Security Check", re.IGNORECASE)
GUEST = "[id^='guest-apply-email-']"
MIN_PAGES = 6

CARDS_JS = r"""
() => [...document.querySelectorAll("article")].map(card => {
  const link = card.querySelector('a[href*="/jobs/"][href$="#apply"]');
  const heading = card.querySelector("h1, h2, h3, h4");
  return {
    href: link ? link.getAttribute("href") : "",
    heading: heading ? heading.innerText.trim() : "",
  };
}).filter(item => item.href)
"""
JOB_JS = r"""
(guest) => {
  const clean = text => (text || "").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
  const main = document.querySelector("main") || document.body;
  const heading = main.querySelector("h1");
  const stop = [...main.querySelectorAll("h2, h3, section")].find(node =>
    /^(Related open jobs|Похожие|Comments|Комментарии|Пікірлер)/i.test((node.innerText || "").trim()));
  let text = main.innerText || "";
  if (stop) {
    const cut = text.indexOf((stop.innerText || "").trim().split("\n")[0]);
    if (cut > 0) text = text.slice(0, cut);
  }
  const email = document.querySelector(guest);
  const form = email ? email.closest("form") : null;
  const card = form ? (form.closest("details") || form.parentElement) : null;
  return {
    heading: heading ? heading.innerText.trim() : "",
    text: clean(text),
    guest: !!email,
    profile: !!document.querySelector('a[href*="#apply"], [id*="apply"]'),
    status: clean(card ? card.innerText : "").slice(0, 600),
    head: clean(main.innerText || "").slice(0, 2500),
  };
}
"""
OPEN_FORM_JS = r"""
(guest) => {
  const email = document.querySelector(guest);
  if (!email) return false;
  const details = email.closest("details");
  if (details && !details.open) {
    const summary = details.querySelector("summary");
    if (summary) summary.click();
    details.open = true;
  }
  email.scrollIntoView({block: "center"});
  return true;
}
"""
OUTCOME_JS = r"""
(guest) => {
  const email = document.querySelector(guest);
  const form = email ? email.closest("form") : null;
  const live = form ? form.querySelector("[aria-live]") : null;
  const card = form ? (form.closest("details") || form.parentElement) : null;
  const scope = document.querySelector("main") || document.body;
  return {
    form: !!form,
    busy: !!(form && form.querySelector("button[type=submit][disabled], [aria-busy=true]")),
    live: live ? live.innerText.trim() : "",
    card: card ? card.innerText.trim().slice(0, 600) : "",
    page: (scope.innerText || "").slice(0, 4000),
  };
}
"""


def handles(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "dsml.kz" or host.endswith(".dsml.kz")


def origin(url: str) -> str:
    return BASE


def expand_source(url: str, resume_hashes: list[str]) -> list[str]:
    return [url]


def vacancy_id(url: str) -> str | None:
    match = JOB_RE.match(urlparse(url).path)
    return match.group(1) if match else None


def job_url(external_id: str) -> str:
    return f"{BASE}/jobs/{external_id}"


def split_heading(heading: str) -> tuple[str, str]:
    title, _, employer = heading.partition(" at ")
    if not employer:
        title, _, employer = heading.partition(" в ")
    return title.strip(), employer.strip()


def is_logged_in(page) -> bool:
    cookies = page.context.cookies(BASE)
    return any(
        cookie["name"].startswith("sb-") and "auth-token" in cookie["name"] and cookie["value"]
        for cookie in cookies
    )


def check_captcha(page) -> None:
    if CHALLENGE_RE.search(page.title()):
        raise CaptchaError(f"DSML.kz is showing a browser check at {page.url}.")


def wait_for(page, selector: str, timeout_ms: int = 20000) -> bool:
    for _ in range(timeout_ms // 1000):
        if page.evaluate("(s) => !!document.querySelector(s)", selector):
            return True
        page.wait_for_timeout(1000)
    return False


def page_url(search_url: str, number: int) -> str:
    parts = urlsplit(search_url)
    path = re.sub(r"/page/\d+/?$", "", parts.path).rstrip("/")
    if number > 1:
        path = f"{path}/page/{number}"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def crawl(page, search_url: str, max_pages: int) -> list[Listing]:
    found: dict[str, Listing] = {}
    for number in range(1, max(max_pages, MIN_PAGES) + 1):
        page.goto(page_url(search_url, number), wait_until="domcontentloaded")
        check_captcha(page)
        wait_for(page, "article")
        pause(page, 1.5, 3.0)
        cards = page.evaluate(CARDS_JS)
        if not cards:
            break
        for item in cards:
            external_id = vacancy_id(item["href"].split("#")[0])
            if not external_id or external_id in found:
                continue
            title, employer = split_heading(item["heading"])
            found[external_id] = Listing(
                external_id=external_id, url=job_url(external_id), title=title, employer=employer
            )
    return list(found.values())


def open_job(page, url: str, fresh: bool = False) -> dict:
    target = job_url(vacancy_id(url) or "")
    if fresh or page.url.split("#")[0] != target:
        page.goto(target, wait_until="domcontentloaded")
        check_captcha(page)
        wait_for(page, f"{GUEST}, main h1", 20000)
        pause(page, 1.0, 2.0)
    return page.evaluate(JOB_JS, GUEST)


def read_vacancy(page, url: str) -> VacancyPage:
    job = open_job(page, url)
    title, employer = split_heading(job["heading"])
    return VacancyPage(
        title=title,
        employer=employer,
        text=job["text"][:12000],
        has_respond_button=job["guest"],
    )


def response_status(page, url: str) -> ResponseStatus | None:
    job = open_job(page, url)
    if not job["head"]:
        return None
    return ResponseStatus(
        already_applied=bool(APPLIED_RE.search(job["status"])),
        impossible=bool(CLOSED_RE.search(job["head"][:600]))
        or not (job["guest"] or job["profile"]),
        letter_required=False,
        has_test=False,
        letter_max_length=COVER_LIMIT,
    )


def open_for_apply(page, url: str) -> None:
    open_job(page, url)
    page.evaluate(OPEN_FORM_JS, GUEST)


def linkedin_url(cv_text: str) -> str:
    match = LINKEDIN_RE.search(cv_text or "")
    if not match:
        return ""
    found = match.group(0)
    return found if found.startswith("http") else f"https://{found}"


def contact_note(applicant: dict) -> str:
    parts = []
    if applicant.get("phone"):
        parts.append(f"Phone: {applicant['phone']}")
    if applicant.get("city"):
        parts.append(f"Based in {applicant['city']} (UTC+5)")
    return ". ".join(parts)[:NOTE_LIMIT]


FIRST_NAME = "[id^='guest-apply-first-name-']"
LAST_NAME = "[id^='guest-apply-last-name-']"
RESUME = "input[type=file][id^='guest-apply-resume-']"
LINKEDIN = "[id^='guest-apply-linkedin-']"
COVER = "[id^='guest-apply-cover-']"
CONTACT = "[id^='guest-apply-contact-note-']"
FOCUS_JS = r"""
(selector) => {
  const field = document.querySelector(selector);
  if (!field) return false;
  field.scrollIntoView({block: "center", behavior: "instant"});
  field.focus();
  return document.activeElement === field;
}
"""
VALUE_JS = r"""
(selector) => {
  const field = document.querySelector(selector);
  return field ? field.value : null;
}
"""
ATTACH_JS = r"""
([selector, name, type, data]) => {
  const input = document.querySelector(selector);
  if (!input) return "";
  const bytes = Uint8Array.from(atob(data), c => c.charCodeAt(0));
  const transfer = new DataTransfer();
  transfer.items.add(new File([bytes], name, {type}));
  input.files = transfer.files;
  input.dispatchEvent(new Event("input", {bubbles: true}));
  input.dispatchEvent(new Event("change", {bubbles: true}));
  return input.files.length ? input.files[0].name : "";
}
"""
SUBMIT_SCROLL_JS = r"""
(guest) => {
  const email = document.querySelector(guest);
  const form = email ? email.closest("form") : null;
  const button = form ? form.querySelector("button[type=submit]") : null;
  if (!button) return false;
  button.scrollIntoView({block: "center", behavior: "instant"});
  return true;
}
"""
SUBMIT_POINT_JS = r"""
(guest) => {
  const email = document.querySelector(guest);
  const form = email ? email.closest("form") : null;
  const button = form ? form.querySelector("button[type=submit]") : null;
  if (!button) return null;
  const box = button.getBoundingClientRect();
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  const hit = document.elementFromPoint(x, y);
  return {x, y, clear: !!hit && button.contains(hit)};
}
"""
REQUEST_SUBMIT_JS = r"""
(guest) => {
  const email = document.querySelector(guest);
  const form = email ? email.closest("form") : null;
  if (!form) return false;
  form.requestSubmit();
  return true;
}
"""


def type_into(page, selector: str, value: str, paste: bool = False) -> bool:
    if not value:
        return True
    if not page.evaluate(FOCUS_JS, selector):
        return False
    if paste:
        page.keyboard.insert_text(value)
    else:
        page.keyboard.type(value, delay=35)
    pause(page, 0.3, 0.9)
    return page.evaluate(VALUE_JS, selector) == value


def attach_cv(page, path: str) -> bool:
    file = Path(path)
    kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    data = base64.b64encode(file.read_bytes()).decode()
    return page.evaluate(ATTACH_JS, [RESUME, file.name, kind, data]) == file.name


def press_submit(page) -> None:
    point = page.evaluate(SUBMIT_POINT_JS, GUEST)
    if point and point["clear"]:
        page.mouse.click(point["x"], point["y"])
    else:
        page.evaluate(REQUEST_SUBMIT_JS, GUEST)


def server_answer(responses: list) -> str:
    posts = [response for response in responses if response.request.method != "GET"][-2:]
    answers = []
    for response in posts:
        try:
            body = " ".join(response.text().split())[:200]
        except PlaywrightError:
            body = ""
        answers.append(f"{response.status} {urlparse(response.url).path} {body}".strip())
    return f" (server: {' | '.join(answers)})" if answers else ""


def apply(
    page,
    url: str,
    resume_title: str,
    letter: str,
    status: ResponseStatus,
    notify=None,
    on_submit=None,
    applicant=None,
) -> tuple:
    applicant = applicant or {}
    if not applicant.get("cv_path"):
        return False, "The CV has no stored file to upload to DSML.kz."
    if not applicant.get("email"):
        return False, "The CV has no email address for the DSML.kz contact field."
    open_job(page, url, fresh=True)
    wait_for(page, GUEST, 15000)
    if not page.evaluate(OPEN_FORM_JS, GUEST):
        return False, "The DSML guest form did not open ('Apply without profile' is missing)."
    pause(page)
    name = applicant.get("name", "").split()
    first, last = (name[0], " ".join(name[1:])) if name else ("", "")
    type_into(page, FIRST_NAME, first)
    type_into(page, LAST_NAME, last)
    if not type_into(page, GUEST, applicant["email"]):
        return False, "The DSML.kz email field did not take the address."
    if not attach_cv(page, applicant["cv_path"]):
        return False, "The DSML.kz form did not take the CV file."
    pause(page)
    type_into(page, LINKEDIN, applicant.get("linkedin", ""))
    if letter:
        type_into(page, COVER, letter[:COVER_LIMIT], paste=True)
        pause(page)
    type_into(page, CONTACT, contact_note(applicant), paste=True)
    if not page.evaluate(SUBMIT_SCROLL_JS, GUEST):
        return False, "The DSML.kz guest form has no send button."
    pause(page, 0.5, 1.0)
    if on_submit:
        on_submit()
    sent = []

    def watch(response) -> None:
        sent.append(response)

    page.on("response", watch)
    try:
        press_submit(page)
        applied, note = wait_for_outcome(page)
    finally:
        page.remove_listener("response", watch)
    if not applied:
        note += server_answer(sent)
    return applied, note


def confirmation(text: str) -> str:
    match = APPLIED_RE.search(text or "") or CONFIRMED_RE.search(text or "")
    return match.group(0) if match else ""


def wait_for_outcome(page, timeout_ms: int = 30000) -> tuple:
    outcome = {}
    for _ in range(timeout_ms // 1000):
        page.wait_for_timeout(1000)
        try:
            outcome = page.evaluate(OUTCOME_JS, GUEST)
        except PlaywrightTimeout:
            continue
        check_captcha(page)
        confirmed = confirmation(outcome["live"]) or confirmation(outcome["card"])
        if confirmed:
            return True, f'Applied on DSML.kz: "{confirmed}".'
        if not outcome["form"]:
            found = confirmation(outcome["page"])
            if found:
                return True, f'Applied on DSML.kz: "{found}".'
            shown = " ".join((outcome["card"] or outcome["page"]).split())[:200]
            return True, f'Applied on DSML.kz: the guest form was replaced by "{shown}".'
        if outcome["live"] and not outcome["busy"]:
            return False, f"DSML.kz answered: {outcome['live'][:300]}"
    return False, (
        "DSML.kz showed no confirmation after Send quick apply; check the job page before resending."
    )


def navigator_goal(title: str, resume_title: str, letter: str, status: ResponseStatus) -> str:
    lines = [
        f'Apply to the DSML.kz job "{title}" open in this tab without a DSML profile.',
        (
            "Open the 'Apply without profile' section, fill first and last name and the email from "
            "candidate_contact, upload the CV with the upload action, add the LinkedIn profile "
            "from the CV, and put the phone and city into the contact note."
        ),
        "Leave Telegram empty. Do not use 'Apply with DSML profile'.",
        "The final button is 'Send quick apply'. The application is sent when the page confirms it.",
    ]
    if letter:
        lines.append(f"Paste this into the Cover note field:\n{letter[:COVER_LIMIT]}")
    return "\n".join(lines)
