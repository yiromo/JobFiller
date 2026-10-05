import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .base import CaptchaError, Listing, ResponseStatus, VacancyPage, external_goal, pause

SITE = "linkedin"
NAME = "LinkedIn"
LOGIN_URL = "https://www.linkedin.com/login"
USES_RESUME_LINKS = False
SCRIPTED_APPLY = False
WANTS_LETTER = False
RECHECK_BATCH = 5
HEADED_CAPTCHA = False
SEND_GAP = (20, 60)
MAX_SENDS_PER_RUN = 0
NAVIGABLE = ()
SESSION_COOKIE = "li_at"
PAGE_SIZE = 25
BASE = "https://www.linkedin.com"
CARD = '[role="button"][componentkey^="job-card-component-ref-"]'
EASY_APPLY = 'button[aria-label^="Easy Apply"]'
ABOUT = '[componentkey^="JobDetails_AboutTheJob_"]'
JOB_ID_RE = re.compile(r"/jobs/view/(\d+)")
APPLIED_RE = re.compile(r"\bApplied\b[^.\n]{0,40}\bago\b|Application submitted|Application sent")
CLOSED_RE = re.compile(r"No longer accepting applications", re.IGNORECASE)
CHECKPOINT_RE = re.compile(r"/checkpoint/|/authwall|captcha", re.IGNORECASE)

CARDS_JS = """
(card) => [...document.querySelectorAll(card)].map(node => {
  const lines = (node.innerText || "").split("\\n").map(line => line.trim()).filter(Boolean);
  return {
    id: node.getAttribute("componentkey").replace("job-card-component-ref-", ""),
    lines: lines.slice(0, 8),
    easy: lines.includes("Easy Apply"),
    applied: lines.some(line => /^Applied\b/.test(line)),
  };
}).filter(item => item.id)
"""
SCROLL_JS = """
(selector) => {
  const cards = document.querySelectorAll(selector);
  if (cards.length) cards[cards.length - 1].scrollIntoView({block: "end", behavior: "smooth"});
}
"""
JOB_JS = """
([about, easy]) => {
  const clean = text => (text || "").replace(/\\s+/g, " ").trim();
  const buttons = [...document.querySelectorAll("button, a")];
  const apply = buttons.find(el => {
    const label = clean(el.getAttribute("aria-label") || el.innerText);
    return /^apply\\b/i.test(label) && !/easy apply/i.test(label);
  });
  const main = document.querySelector("main") || document.body;
  const company = [...main.querySelectorAll('a[href*="/company/"]')]
    .map(link => clean(link.innerText))
    .find(Boolean);
  return {
    title: document.title,
    company: company || "",
    about: clean((document.querySelector(about) || {}).innerText || ""),
    top: clean(main.innerText).slice(0, 6000),
    easy: !!document.querySelector(easy),
    external: !!apply,
  };
}
"""


def handles(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def origin(url: str) -> str:
    return BASE


def expand_source(url: str, resume_hashes: list[str]) -> list[str]:
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k not in {"currentJobId", "start"}]
    return [urlunparse(parsed._replace(query=urlencode(query)))]


def with_page_number(search_url: str, number: int) -> str:
    parsed = urlparse(search_url)
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k != "start"]
    if number:
        query.append(("start", str(number * PAGE_SIZE)))
    return urlunparse(parsed._replace(query=urlencode(query)))


def job_url(external_id: str) -> str:
    return f"{BASE}/jobs/view/{external_id}/"


def vacancy_id(url: str) -> str | None:
    match = JOB_ID_RE.search(urlparse(url).path)
    return match.group(1) if match else None


def is_logged_in(page) -> bool:
    cookies = page.context.cookies(BASE)
    return any(cookie["name"] == SESSION_COOKIE and cookie["value"] for cookie in cookies)


def check_captcha(page) -> None:
    if CHECKPOINT_RE.search(page.url):
        raise CaptchaError(f"LinkedIn is asking for a security check at {page.url}.")


def wait_for(page, selector: str, timeout_ms: int = 25000) -> bool:
    for _ in range(timeout_ms // 1000):
        if page.evaluate("(s) => document.querySelectorAll(s).length", selector):
            return True
        page.wait_for_timeout(1000)
    return False


def crawl(page, search_url: str, max_pages: int) -> list[Listing]:
    found: dict[str, Listing] = {}
    for number in range(max_pages):
        page.goto(with_page_number(search_url, number), wait_until="domcontentloaded")
        check_captcha(page)
        if not wait_for(page, CARD):
            break
        for _ in range(6):
            page.evaluate(SCROLL_JS, CARD)
            pause(page, 0.6, 1.4)
        before = len(found)
        for item in page.evaluate(CARDS_JS, CARD):
            if item["id"] in found or item["applied"]:
                continue
            lines = item["lines"] + ["", "", ""]
            if lines[1] and lines[0].startswith(lines[1]):
                lines = lines[1:]
            found[item["id"]] = Listing(
                external_id=item["id"],
                url=job_url(item["id"]),
                title=lines[0],
                employer=lines[1],
                external_apply=not item["easy"],
            )
        if len(found) == before:
            break
        pause(page)
    return list(found.values())


def open_job(page, external_id: str) -> dict:
    target = job_url(external_id)
    if page.url.split("?")[0] != target:
        page.goto(target, wait_until="domcontentloaded")
        check_captcha(page)
        if not wait_for(page, ABOUT, 15000):
            page.mouse.wheel(0, 1200)
            wait_for(page, ABOUT, 8000)
        pause(page, 1.0, 2.0)
    return page.evaluate(JOB_JS, [ABOUT, EASY_APPLY])


def read_vacancy(page, url: str) -> VacancyPage:
    job = open_job(page, vacancy_id(url) or "")
    parts = [part.strip() for part in job["title"].split("|")]
    title = parts[0] if parts else ""
    employer = job.get("company") or (parts[-2] if len(parts) > 2 else "")
    body = job["about"] or job["top"]
    text = "\n".join(part for part in (title, employer, job["top"][:600], body) if part)
    return VacancyPage(
        title=title,
        employer=employer,
        text=text[:12000],
        has_respond_button=job["easy"],
        external_apply=job["external"] and not job["easy"],
    )


def response_status(page, url: str) -> ResponseStatus | None:
    job = open_job(page, vacancy_id(url) or "")
    if not job["top"]:
        return None
    return ResponseStatus(
        already_applied=bool(APPLIED_RE.search(job["top"][:1500])),
        impossible=bool(CLOSED_RE.search(job["top"][:1500]))
        or not (job["easy"] or job["external"]),
        letter_required=False,
        has_test=False,
        letter_max_length=4000,
        external_apply=job["external"] and not job["easy"],
    )


def open_for_apply(page, url: str) -> None:
    open_job(page, vacancy_id(url) or "")


def apply(
    page, url, resume_title, letter, status, notify=None, on_submit=None, applicant=None
) -> tuple:
    return False, "LinkedIn Easy Apply runs through the navigator; it is off for LinkedIn."


def navigator_goal(title: str, resume_title: str, letter: str, status: ResponseStatus) -> str:
    if status.external_apply:
        return external_goal(f'the LinkedIn job "{title}" open in this tab', "Apply", letter)
    lines = [
        f'Apply to the LinkedIn job "{title}" open in this tab with Easy Apply.',
        (
            "Press the Easy Apply button, then work through every step of the dialog with Next, "
            "Continue or Review, answering each question from the CV."
        ),
        (
            "Keep contact details LinkedIn already filled in and fill empty required ones from "
            "candidate_contact. If a step asks for a résumé, keep the one already selected or use "
            "the upload action to attach the CV."
        ),
        "Leave the 'Follow company' box as it is.",
        (
            "The final button is 'Submit application'. The application is sent when LinkedIn "
            "shows that it was sent (e.g. 'Your application was sent')."
        ),
    ]
    if letter:
        lines.append(f"If there is a cover letter field, paste this letter:\n{letter}")
    return "\n".join(lines)
