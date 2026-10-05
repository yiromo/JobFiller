import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .base import CaptchaError, Listing, ResponseStatus, VacancyPage, external_goal, pause

SITE = "indeed"
NAME = "Indeed"
LOGIN_URL = "https://secure.indeed.com/auth"
USES_RESUME_LINKS = False
SCRIPTED_APPLY = False
WANTS_LETTER = False
RECHECK_BATCH = 5
HEADED_CAPTCHA = False
SEND_GAP = (20, 60)
MAX_SENDS_PER_RUN = 0
NAVIGABLE = ()
SESSION_COOKIES = {"SOCK", "SHOE"}
PAGE_SIZE = 10
PANE = '.jobsearch-RightPane, #jobsearch-ViewjobPaneWrapper, [class*="RightPane"]'
INDEED_APPLY = '[data-testid="viewjob-indeed-apply"]'
COMPANY_APPLY = '[data-testid="viewjob-apply"]'
APPLIED_RE = re.compile(r"\bYou applied\b|\bApplied\b[^.\n]{0,40}\bago\b|Application submitted")
CLOSED_RE = re.compile(r"This job has expired|no longer available", re.IGNORECASE)
CHECK_RE = re.compile(r"Security Check|Additional Verification Required|Требуется дополнительная")

CARDS_JS = """
() => [...document.querySelectorAll("a[data-jk]")].filter(link => {
  const box = link.getBoundingClientRect();
  const style = getComputedStyle(link);
  return box.width > 1 && box.height > 1 && style.visibility !== "hidden"
    && style.display !== "none" && style.opacity !== "0";
}).map(link => {
  const card = link.closest("li, [class*='cardOutline'], [class*='job_seen_beacon']") || link;
  const company = card.querySelector('[data-testid="company-name"]');
  return {
    jk: link.getAttribute("data-jk"),
    title: (link.innerText || "").trim(),
    company: company ? company.innerText.trim() : "",
    text: (card.innerText || "").slice(0, 400),
  };
})
"""
PANE_JS = """
([pane, easy, company]) => {
  const node = document.querySelector(pane);
  const text = node ? node.innerText : "";
  return {
    lines: text.split("\\n").map(line => line.trim()).filter(Boolean).slice(0, 4),
    text: text.replace(/[ \\t]+/g, " ").trim(),
    easy: !!document.querySelector(easy),
    external: !!document.querySelector(company),
    title: document.title,
  };
}
"""


def handles(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "indeed.com" or host.endswith(".indeed.com")


def origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def with_params(url: str, drop: set[str], extra: dict) -> str:
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k not in drop]
    query += list(extra.items())
    return urlunparse(parsed._replace(query=urlencode(query)))


def expand_source(url: str, resume_hashes: list[str]) -> list[str]:
    return [with_params(url, {"vjk", "start"}, {})]


def job_url(search_url: str, jk: str) -> str:
    return with_params(search_url, {"vjk", "start"}, {"vjk": jk})


def is_logged_in(page) -> bool:
    cookies = page.context.cookies("https://secure.indeed.com")
    return any(cookie["name"] in SESSION_COOKIES and cookie["value"] for cookie in cookies)


def check_captcha(page) -> None:
    if CHECK_RE.search(page.title()) or "/viewjob" in page.url and "Security" in page.title():
        raise CaptchaError(f"Indeed is showing a security check at {page.url}.")


def crawl(page, search_url: str, max_pages: int) -> list[Listing]:
    found: dict[str, Listing] = {}
    for number in range(max_pages):
        extra = {"start": str(number * PAGE_SIZE)} if number else {}
        page.goto(with_params(search_url, {"start", "vjk"}, extra), wait_until="domcontentloaded")
        check_captcha(page)
        pause(page, 2.0, 4.0)
        before = len(found)
        for item in page.evaluate(CARDS_JS):
            if not item["jk"] or item["jk"] in found:
                continue
            found[item["jk"]] = Listing(
                external_id=item["jk"],
                url=job_url(search_url, item["jk"]),
                title=item["title"],
                employer=item["company"],
            )
        if len(found) == before:
            break
        pause(page)
    return list(found.values())


def open_pane(page, url: str) -> dict:
    if page.url != url:
        page.goto(url, wait_until="domcontentloaded")
        check_captcha(page)
        for _ in range(12):
            if page.evaluate(
                "(s) => !!document.querySelector(s)", INDEED_APPLY + "," + COMPANY_APPLY
            ):
                break
            page.wait_for_timeout(1000)
        pause(page, 1.0, 2.0)
    return page.evaluate(PANE_JS, [PANE, INDEED_APPLY, COMPANY_APPLY])


def read_vacancy(page, url: str) -> VacancyPage:
    pane = open_pane(page, url)
    lines = pane["lines"] + ["", ""]
    return VacancyPage(
        title=lines[0],
        employer=lines[1].split("·")[0].strip(),
        text=pane["text"][:12000],
        has_respond_button=pane["easy"],
        external_apply=pane["external"] and not pane["easy"],
    )


def response_status(page, url: str) -> ResponseStatus | None:
    pane = open_pane(page, url)
    head = pane["text"][:1500]
    if not head:
        return None
    return ResponseStatus(
        already_applied=bool(APPLIED_RE.search(head)),
        impossible=bool(CLOSED_RE.search(head)) or not (pane["easy"] or pane["external"]),
        letter_required=False,
        has_test=False,
        letter_max_length=4000,
        external_apply=pane["external"] and not pane["easy"],
    )


def open_for_apply(page, url: str) -> None:
    open_pane(page, url)


def apply(
    page, url, resume_title, letter, status, notify=None, on_submit=None, applicant=None
) -> tuple:
    return False, "Indeed Apply runs through the navigator; it is off for Indeed."


def navigator_goal(title: str, resume_title: str, letter: str, status: ResponseStatus) -> str:
    if status.external_apply:
        return external_goal(
            f'the Indeed job "{title}" shown in the right-hand panel',
            "Apply on company site",
            letter,
        )
    lines = [
        f'Apply to the Indeed job "{title}" shown in the right-hand panel of this search page.',
        (
            "Press 'Apply now' (Indeed Apply). It opens the application in a new tab; work through "
            "each step with Continue, answering questions from the CV."
        ),
        (
            "Keep the contact details and résumé Indeed already has, filling empty required ones "
            "from candidate_contact; use the upload action if a step needs the CV file."
        ),
        (
            "The final button is 'Submit your application'. The application is sent when Indeed "
            "shows that it was submitted."
        ),
    ]
    if letter:
        lines.append(f"If there is a cover letter field, paste this letter:\n{letter}")
    return "\n".join(lines)
