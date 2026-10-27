import html
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse

from django.conf import settings
from django.utils import timezone

from .base import Listing, ResponseStatus, VacancyPage

SITE = "ats"
NAME = "Ashby/Greenhouse/Lever"
LOGIN_URL = ""
USES_RESUME_LINKS = False
SCRIPTED_APPLY = False
WANTS_LETTER = True
RECHECK_BATCH = 10
HEADED_CAPTCHA = False
EMPLOYER_BOARDS = True
DISTINCT_UPLOAD_NAMES = False
SEND_GAP = (15, 45)
MAX_SENDS_PER_RUN = 0
TRY_LATER = ()
NAVIGABLE = ()
TAVILY_URL = "https://api.tavily.com/search"
SEARCH_RESULTS = 20
CACHE_SECONDS = 600
MAX_BOARDS = 150
TEXT_LIMIT = 12000
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0"
HOSTS = {
    "jobs.ashbyhq.com": "ashby",
    "job-boards.greenhouse.io": "greenhouse",
    "boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
}
SEARCH_DOMAINS = {
    "ashby": ["jobs.ashbyhq.com"],
    "greenhouse": ["job-boards.greenhouse.io", "boards.greenhouse.io"],
    "lever": ["jobs.lever.co"],
}
UUID_PATH_RE = re.compile(
    r"^/([^/]+)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/|$)",
    re.IGNORECASE,
)
GREENHOUSE_PATH_RE = re.compile(r"^/([^/]+)/jobs/(\d+)(?:/|$)")
TAG_RE = re.compile(r"<[^>]+>")
BREAK_RE = re.compile(r"<(br|/p|/li|/h\d|/div)[^>]*>", re.IGNORECASE)
SPACES_RE = re.compile(r"[ \t\xa0]+")
LINES_RE = re.compile(r"\n\s*\n+")
CACHE: dict = {}
CACHE_LOCK = threading.Lock()


def handles(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in HOSTS


def origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def board_of(url: str) -> str:
    return HOSTS.get((urlparse(url).hostname or "").lower(), "")


def parse_job(url: str) -> tuple[str, str, str] | None:
    board = board_of(url)
    path = urlparse(url).path
    pattern = GREENHOUSE_PATH_RE if board == "greenhouse" else UUID_PATH_RE
    match = pattern.match(path) if board else None
    if not match:
        return None
    return board, match.group(1), match.group(2).lower()


def job_url(board: str, slug: str, job_id: str) -> str:
    if board == "ashby":
        return f"https://jobs.ashbyhq.com/{slug}/{job_id}"
    if board == "greenhouse":
        return f"https://job-boards.greenhouse.io/{slug}/jobs/{job_id}"
    return f"https://jobs.lever.co/{slug}/{job_id}"


def apply_url(url: str) -> str:
    job = parse_job(url)
    if not job:
        return url
    base = job_url(*job)
    return {"ashby": f"{base}/application", "lever": f"{base}/apply"}.get(job[0], base)


def external_id(board: str, job_id: str) -> str:
    return f"{board}:{job_id}"[:64]


def search_terms(search_url: str) -> tuple[str, str, str]:
    query = dict(parse_qsl(urlparse(search_url).query))
    return board_of(search_url), query.get("q", "").strip(), query.get("where", "Remote").strip()


def expand_source(url: str, resume_hashes: list[str]) -> list[str]:
    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query)
    where = next((value for key, value in pairs if key == "where"), "Remote")
    titles = [value.strip() for key, value in pairs if key == "q" and value.strip()]
    return [
        f"https://{parsed.hostname}/?{urlencode({'q': title, 'where': where})}" for title in titles
    ]


def is_logged_in(page) -> bool:
    return True


def check_captcha(page) -> None:
    return None


def pause(page, low: float = 0.8, high: float = 2.2) -> None:
    time.sleep(random.uniform(low, high) / 4)


def state_path():
    return settings.DATA_DIR / "hunter" / "ats.json"


def read_state() -> dict:
    try:
        data = json.loads(state_path().read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("searched", {})
    data.setdefault("boards", {})
    return data


def write_state(data: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data))
    os.replace(temporary, path)


def search_due(state: dict, search_url: str, now=None) -> bool:
    try:
        last = datetime.fromisoformat(state["searched"].get(search_url, ""))
    except (TypeError, ValueError):
        return True
    return (now or timezone.now()) - last >= timedelta(hours=settings.HUNTER_ATS_SEARCH_HOURS)


def get_json(url: str, body: dict | None = None, headers: dict | None = None):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        },
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def cached(key: str, load):
    now = time.monotonic()
    with CACHE_LOCK:
        hit = CACHE.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = load()
    with CACHE_LOCK:
        CACHE[key] = (now, value)
    return value


def search_place(where: str) -> str:
    if where.lower() == "remote":
        return "(Remote OR Worldwide OR Anywhere)"
    return where


def search(board: str, title: str, where: str) -> list[dict]:
    if not settings.TAVILY_API_KEY:
        raise ValueError("TAVILY_API_KEY is not set, so the job-board search cannot run.")
    payload = get_json(
        TAVILY_URL,
        {
            "query": f'"{title}" {search_place(where)}'.strip(),
            "include_domains": SEARCH_DOMAINS[board],
            "max_results": SEARCH_RESULTS,
        },
        {"Authorization": f"Bearer {settings.TAVILY_API_KEY}"},
    )
    return list((payload or {}).get("results") or [])


def hit_names(board: str, text: str, slug: str) -> tuple[str, str]:
    text = (text or "").strip()
    if board == "ashby" and " @ " in text:
        title, employer = text.rsplit(" @ ", 1)
        return title.strip(), employer.strip()
    if board == "lever" and " - " in text:
        employer, title = text.split(" - ", 1)
        return title.strip(), employer.strip()
    if board == "greenhouse":
        found = re.match(r"(?:Job Application for )?(.+?) at (.+)$", text)
        if found:
            return found.group(1).strip(), found.group(2).strip()
    return text, pretty(slug)


def pretty(slug: str) -> str:
    return re.sub(r"[-_.]+", " ", slug).strip().title()


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", (text or "").lower())


def title_matches(wanted: str, title: str) -> bool:
    squashed = "".join(words(title))
    tokens = words(wanted)
    return bool(tokens) and all(token in squashed for token in tokens)


def strip_html(markup: str) -> str:
    text = TAG_RE.sub(" ", BREAK_RE.sub("\n", html.unescape(markup or "")))
    text = SPACES_RE.sub(" ", html.unescape(text))
    return LINES_RE.sub("\n\n", "\n".join(line.strip() for line in text.splitlines())).strip()


def board_listing(board: str, slug: str) -> list:
    if board == "ashby":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false"
        return cached(url, lambda: list((get_json(url) or {}).get("jobs") or []))
    if board == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        return cached(url, lambda: list((get_json(url) or {}).get("jobs") or []))
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    return cached(url, lambda: list(get_json(url) or []))


def remote_of(board: str, job: dict) -> bool:
    if board == "ashby":
        place = (job.get("workplaceType") or "").lower()
        return place == "remote" if place else bool(job.get("isRemote"))
    if board == "greenhouse":
        return "remote" in ((job.get("location") or {}).get("name") or "").lower()
    place = (job.get("workplaceType") or "").lower()
    location = ((job.get("categories") or {}).get("location") or "").lower()
    return place == "remote" or "remote" in location


def board_jobs(board: str, slug: str) -> list[dict]:
    jobs = []
    for job in board_listing(board, slug):
        if board == "ashby" and job.get("isListed") is False:
            continue
        job_id = str(job.get("id") or "").lower()
        title = job.get("text") if board == "lever" else job.get("title")
        if job_id and title:
            jobs.append(
                {
                    "id": job_id,
                    "title": title,
                    "remote": remote_of(board, job),
                    "employer": job.get("company_name") or "",
                }
            )
    return jobs


def crawl(page, search_url: str, max_pages: int) -> list[Listing]:
    board, title, where = search_terms(search_url)
    if not board or not title:
        return []
    state = read_state()
    found: dict[str, Listing] = {}
    now = timezone.now()
    if search_due(state, search_url, now):
        for hit in search(board, title, where):
            job = parse_job(hit.get("url") or "")
            if not job or job[0] != board:
                continue
            _, slug, job_id = job
            name, employer = hit_names(board, hit.get("title") or "", slug)
            found[external_id(board, job_id)] = Listing(
                external_id=external_id(board, job_id),
                url=job_url(*job),
                title=name[:255],
                employer=employer[:255],
            )
            state["boards"][f"{board}:{slug}"] = {"seen": now.isoformat(), "name": employer}
        state["searched"][search_url] = now.isoformat()
        newest = sorted(state["boards"].items(), key=lambda item: item[1].get("seen", ""))
        state["boards"] = dict(newest[-MAX_BOARDS:])
        write_state(state)
    wants_remote = where.lower() == "remote"
    for key, info in state["boards"].items():
        kind, slug = key.split(":", 1)
        if kind != board:
            continue
        try:
            jobs = board_jobs(board, slug)
        except (OSError, ValueError):
            continue
        for job in jobs:
            if not title_matches(title, job["title"]) or wants_remote and not job["remote"]:
                continue
            found.setdefault(
                external_id(board, job["id"]),
                Listing(
                    external_id=external_id(board, job["id"]),
                    url=job_url(board, slug, job["id"]),
                    title=job["title"][:255],
                    employer=(job["employer"] or info.get("name") or pretty(slug))[:255],
                ),
            )
    return list(found.values())


def load_posting(board: str, slug: str, job_id: str) -> dict | None:
    if board == "ashby":
        job = next(
            (j for j in board_listing(board, slug) if str(j.get("id")).lower() == job_id), None
        )
        if job is None:
            return None
        lines = [
            job.get("title") or "",
            f"Location: {job.get('location') or ''}",
            f"Workplace: {job.get('workplaceType') or ('Remote' if job.get('isRemote') else '')}",
            f"Employment: {job.get('employmentType') or ''}",
            "",
            job.get("descriptionPlain") or strip_html(job.get("descriptionHtml") or ""),
        ]
        return {
            "title": job.get("title") or "",
            "employer": "",
            "text": "\n".join(lines),
            "remote": remote_of(board, job),
        }
    if board == "greenhouse":
        job = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}")
        if not job:
            return None
        location = (job.get("location") or {}).get("name") or ""
        lines = [
            job.get("title") or "",
            f"Company: {job.get('company_name') or ''}",
            f"Location: {location}",
            "",
            strip_html(job.get("content") or ""),
        ]
        return {
            "title": job.get("title") or "",
            "employer": job.get("company_name") or "",
            "text": "\n".join(lines),
            "remote": remote_of(board, job),
        }
    job = get_json(f"https://api.lever.co/v0/postings/{slug}/{job_id}")
    if not job or not job.get("text"):
        return None
    categories = job.get("categories") or {}
    lines = [
        job.get("text") or "",
        f"Location: {categories.get('location') or ''}",
        f"Workplace: {job.get('workplaceType') or ''}",
        f"Commitment: {categories.get('commitment') or ''}",
        "",
        job.get("descriptionPlain") or "",
    ]
    for block in job.get("lists") or []:
        lines += ["", block.get("text") or "", strip_html(block.get("content") or "")]
    lines += ["", job.get("additionalPlain") or ""]
    return {
        "title": job.get("text") or "",
        "employer": "",
        "text": "\n".join(lines),
        "remote": remote_of(board, job),
    }


def posting(url: str) -> dict | None:
    job = parse_job(url)
    if not job:
        return None
    return cached(f"posting:{job_url(*job)}", lambda: load_posting(*job))


def read_vacancy(page, url: str) -> VacancyPage:
    try:
        found = posting(url)
    except (OSError, ValueError):
        found = None
    if not found:
        return VacancyPage(title="", employer="", text="", has_respond_button=True)
    return VacancyPage(
        title=found["title"],
        employer=found["employer"],
        text=found["text"][:TEXT_LIMIT],
        has_respond_button=True,
    )


def response_status(page, url: str) -> ResponseStatus | None:
    try:
        found = posting(url)
    except (OSError, ValueError):
        return None
    return ResponseStatus(
        already_applied=False,
        impossible=found is None,
        letter_required=False,
        has_test=False,
        letter_max_length=4000,
        remote=bool(found and found["remote"]),
    )


def open_for_apply(page, url: str) -> None:
    page.goto(apply_url(url), wait_until="domcontentloaded")
    page.wait_for_timeout(2500)


def apply(
    page, url, resume_title, letter, status, notify=None, on_submit=None, applicant=None
) -> tuple:
    return False, "Job-board applications run through the navigator; it is off for this site."


def navigator_goal(title: str, resume_title: str, letter: str, status: ResponseStatus) -> str:
    lines = [
        f'Apply to the job "{title}" on this company job board (Ashby, Greenhouse or Lever).',
        (
            "If the page shows the job description, press 'Apply' or 'Apply for this job' to "
            "reach the form. Fill every field from the CV, candidate_contact and candidate_facts, "
            "and use the upload action for the résumé or CV file field."
        ),
        (
            "Never use 'Apply with LinkedIn', 'Autofill with MyGreenhouse', 'Apply with Indeed' or "
            "any sign-in or account option; if the form cannot be sent without signing in or "
            "creating an account, reply stuck."
        ),
        (
            "Submit the form. The application is sent only when the page confirms it (e.g. "
            "'Thank you for applying' or 'Application submitted')."
        ),
    ]
    if letter:
        lines.append(f"If there is a cover letter field, paste this letter:\n{letter}")
    return "\n".join(lines)
