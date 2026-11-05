import html
import random
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.utils import timezone

from ..posting import ago
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
TRY_LATER = ()
EMPLOYER_BOARDS = False
DISTINCT_UPLOAD_NAMES = True
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
GUEST_SEARCH = f"{BASE}/jobs-guest/jobs/api/seeMoreJobPostings/search"
GUEST_JOB = f"{BASE}/jobs-guest/jobs/api/jobPosting/{{id}}"
GUEST_PARAMS = {"keywords", "geoId", "location", "distance", "f_TPR", "f_WT", "f_AL", "f_E", "f_JT"}
GUEST_PAGE_SIZE = 10
GUEST_GAP = (3.0, 7.0)
GUEST_TEXT_GAP = (1.5, 3.0)
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0"
GUEST_CARD_RE = re.compile(r"<li>(.*?)</li>", re.DOTALL)
GUEST_ID_RE = re.compile(r"urn:li:jobPosting:(\d+)")
GUEST_TITLE_RE = re.compile(r'base-search-card__title">(.*?)</h3>', re.DOTALL)
GUEST_COMPANY_RE = re.compile(r'base-search-card__subtitle">(.*?)</h4>', re.DOTALL)
GUEST_PLACE_RE = re.compile(r'job-search-card__location">(.*?)</span>', re.DOTALL)
GUEST_TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"[^>]*>(.*?)</time>', re.DOTALL)
GUEST_TEXT_RE = re.compile(r"show-more-less-html__markup[^>]*>(.*?)</div>", re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")

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


def plain(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", markup or ""))).strip()


def guest_get(url: str) -> str | None:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
            final = response.geturl()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return None if CHECKPOINT_RE.search(final) else body


def guest_url(search_url: str, number: int) -> str:
    query = [(k, v) for k, v in parse_qsl(urlparse(search_url).query) if k in GUEST_PARAMS]
    query.append(("start", str(number * GUEST_PAGE_SIZE)))
    return f"{GUEST_SEARCH}?{urlencode(query)}"


def guest_cards(body: str) -> list[Listing]:
    cards = []
    for card in GUEST_CARD_RE.findall(body or ""):
        found = GUEST_ID_RE.search(card)
        title = GUEST_TITLE_RE.search(card)
        if not found or not title:
            continue
        company = GUEST_COMPANY_RE.search(card)
        place = GUEST_PLACE_RE.search(card)
        stamp = GUEST_TIME_RE.search(card)
        cards.append(
            Listing(
                external_id=found.group(1),
                url=job_url(found.group(1)),
                title=plain(title.group(1)),
                employer=plain(company.group(1)) if company else "",
                place=plain(place.group(1)) if place else "",
                posted_at=posted_on(stamp.group(1), plain(stamp.group(2))) if stamp else None,
            )
        )
    return cards


def posted_on(day: str, label: str) -> datetime | None:
    found = ago(label)
    if found:
        return found
    try:
        return timezone.make_aware(datetime.fromisoformat(day))
    except ValueError:
        return None


def guest_wait() -> None:
    time.sleep(random.uniform(*GUEST_GAP))


def guest_crawl(search_url: str, max_pages: int) -> list[Listing] | None:
    found: dict[str, Listing] = {}
    for number in range(max(1, max_pages) * 3):
        if number:
            guest_wait()
        body = guest_get(guest_url(search_url, number))
        if body is None:
            return list(found.values()) if found else None
        cards = guest_cards(body)
        if not cards:
            return list(found.values()) if found or number else None
        for card in cards:
            found.setdefault(card.external_id, card)
        if len(cards) < GUEST_PAGE_SIZE:
            break
    return list(found.values())


def guest_text(external_id: str) -> str | None:
    time.sleep(random.uniform(*GUEST_TEXT_GAP))
    body = guest_get(GUEST_JOB.format(id=external_id))
    if body is None:
        return None
    found = GUEST_TEXT_RE.search(body)
    return plain(found.group(1)) if found else ""


def crawl(page, search_url: str, max_pages: int) -> list[Listing]:
    listings = guest_crawl(search_url, max_pages)
    if listings is not None:
        return listings
    return browser_crawl(page, search_url, max_pages)


def browser_crawl(page, search_url: str, max_pages: int) -> list[Listing]:
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
