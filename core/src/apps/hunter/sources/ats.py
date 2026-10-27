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
from xml.etree import ElementTree

from django.conf import settings
from django.utils import timezone

from .base import Listing, ResponseStatus, VacancyPage

SITE = "ats"
NAME = "Company job boards"
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
MAX_BOARDS = 300
LISTING_PAGES = 5
PAGE_SIZE = 100
TEXT_LIMIT = 12000
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0"
HOSTS = {
    "jobs.ashbyhq.com": "ashby",
    "job-boards.greenhouse.io": "greenhouse",
    "boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "apply.workable.com": "workable",
    "jobs.smartrecruiters.com": "smartrecruiters",
    "ats.rippling.com": "rippling",
}
COMPANY_HOSTS = {
    "recruitee.com": "recruitee",
    "jobs.personio.de": "personio",
    "jobs.personio.com": "personio",
    "bamboohr.com": "bamboohr",
}
SEARCH_DOMAINS = {
    "ashby": ["jobs.ashbyhq.com"],
    "greenhouse": ["job-boards.greenhouse.io", "boards.greenhouse.io"],
    "lever": ["jobs.lever.co"],
    "workable": ["apply.workable.com"],
    "recruitee": ["recruitee.com"],
    "personio": ["jobs.personio.de", "jobs.personio.com"],
    "bamboohr": ["bamboohr.com"],
    "smartrecruiters": ["jobs.smartrecruiters.com"],
    "rippling": ["ats.rippling.com"],
}
COMPANY_SCOPED = {"recruitee", "personio", "bamboohr"}
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UUID_PATH_RE = re.compile(rf"^/([^/]+)/({UUID})(?:/|$)", re.IGNORECASE)
GREENHOUSE_PATH_RE = re.compile(r"^/([^/]+)/jobs/(\d+)(?:/|$)")
PATH_RES = {
    "ashby": UUID_PATH_RE,
    "lever": UUID_PATH_RE,
    "greenhouse": GREENHOUSE_PATH_RE,
    "workable": re.compile(r"^/([^/]+)/j/([0-9a-z]+)(?:/|$)", re.IGNORECASE),
    "smartrecruiters": re.compile(r"^/([^/]+)/(\d+)(?:[-/]|$)"),
    "rippling": re.compile(
        rf"^/(?:[a-z]{{2}}-[a-z]{{2}}/)?([^/]+)/jobs/({UUID})(?:/|$)", re.IGNORECASE
    ),
}
COMPANY_PATH_RES = {
    "recruitee": re.compile(r"^/o/([^/]+)"),
    "personio": re.compile(r"^/job/(\d+)(?:/|$)"),
    "bamboohr": re.compile(r"^/careers/(\d+)(?:/|$)"),
}
JOB_URLS = {
    "ashby": "https://jobs.ashbyhq.com/{slug}/{id}",
    "greenhouse": "https://job-boards.greenhouse.io/{slug}/jobs/{id}",
    "lever": "https://jobs.lever.co/{slug}/{id}",
    "workable": "https://apply.workable.com/{slug}/j/{id}/",
    "recruitee": "https://{slug}.recruitee.com/o/{id}",
    "personio": "https://{slug}.jobs.personio.de/job/{id}?language=en",
    "bamboohr": "https://{slug}.bamboohr.com/careers/{id}",
    "smartrecruiters": "https://jobs.smartrecruiters.com/{slug}/{id}",
    "rippling": "https://ats.rippling.com/{slug}/jobs/{id}",
}
APPLY_URLS = {
    "ashby": "https://jobs.ashbyhq.com/{slug}/{id}/application",
    "lever": "https://jobs.lever.co/{slug}/{id}/apply",
    "workable": "https://apply.workable.com/{slug}/j/{id}/apply/",
    "recruitee": "https://{slug}.recruitee.com/o/{id}/c/new",
    "personio": "https://{slug}.jobs.personio.de/job/{id}/apply?language=en",
    "rippling": "https://ats.rippling.com/{slug}/jobs/{id}/apply",
}
ID_FIELDS = {"workable": "shortcode", "recruitee": "slug"}
TITLE_FIELDS = {
    "lever": "text",
    "personio": "name",
    "bamboohr": "jobOpeningName",
    "smartrecruiters": "name",
    "rippling": "name",
}
TAG_RE = re.compile(r"<[^>]+>")
BREAK_RE = re.compile(r"<(br|/p|/li|/h\d|/div)[^>]*>", re.IGNORECASE)
SPACES_RE = re.compile(r"[ \t\xa0]+")
LINES_RE = re.compile(r"\n\s*\n+")
CACHE: dict = {}
CACHE_LOCK = threading.Lock()


def handles(url: str) -> bool:
    return bool(board_of(url))


def origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def company_host(host: str) -> tuple[str, str]:
    for suffix, board in COMPANY_HOSTS.items():
        if host == suffix:
            return board, ""
        if host.endswith(f".{suffix}"):
            return board, host[: -len(suffix) - 1]
    return "", ""


def board_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return HOSTS.get(host) or company_host(host)[0]


def normal_id(board: str, job_id: str) -> str:
    return job_id.upper() if board == "workable" else job_id.lower()


def parse_job(url: str) -> tuple[str, str, str] | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    board = HOSTS.get(host, "")
    if board:
        match = PATH_RES[board].match(parsed.path)
        if not match:
            return None
        return board, match.group(1), normal_id(board, match.group(2))
    board, slug = company_host(host)
    match = COMPANY_PATH_RES[board].match(parsed.path) if board else None
    if not match or slug in ("", "www"):
        return None
    return board, slug, normal_id(board, match.group(1))


def job_url(board: str, slug: str, job_id: str) -> str:
    return JOB_URLS[board].format(slug=slug, id=job_id)


def apply_url(url: str) -> str:
    job = parse_job(url)
    if not job:
        return url
    board, slug, job_id = job
    return APPLY_URLS.get(board, JOB_URLS[board]).format(slug=slug, id=job_id)


def external_id(board: str, slug: str, job_id: str) -> str:
    key = f"{slug}/{job_id}" if board in COMPANY_SCOPED else job_id
    return f"{board}:{key}"[:64]


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


def fetch(url: str, body: dict | None = None, headers: dict | None = None) -> bytes | None:
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
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def get_json(url: str, body: dict | None = None, headers: dict | None = None):
    raw = fetch(url, body, headers)
    return None if raw is None else json.loads(raw)


def get_xml(url: str):
    raw = fetch(url, headers={"Accept": "application/xml"})
    if raw is None:
        return None
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise ValueError(f"Unreadable XML from {url}: {error}") from error


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
    if board in ("lever", "recruitee") and " - " in text:
        employer, title = text.split(" - ", 1)
        return title.strip(), employer.strip()
    if board == "workable" and " - " in text:
        title, employer = text.rsplit(" - ", 1)
        return title.strip(), employer.strip()
    if board == "rippling" and " | " in text:
        title, employer = text.rsplit(" | ", 1)
        return title.strip(), employer.strip()
    if board == "greenhouse":
        found = re.match(r"(?:Job Application for )?(.+?) at (.+)$", text)
        if found:
            return found.group(1).strip(), found.group(2).strip()
    if board == "personio":
        found = re.match(r"(.+?) \| Jobs at (.+)$", text)
        if found:
            return found.group(1).strip(), found.group(2).strip()
    if board == "smartrecruiters":
        text = re.sub(r"\s*\|\s*SmartRecruiters$", "", text)
        company = pretty(slug)
        if text.lower().startswith(f"{company.lower()} "):
            text = text[len(company) :].strip()
        return text, company
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
    if board == "workable":
        url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
        return cached(url, lambda: workable_jobs(get_json(url) or {}))
    if board == "recruitee":
        url = f"https://{slug}.recruitee.com/api/offers/"
        return cached(url, lambda: list((get_json(url) or {}).get("offers") or []))
    if board == "personio":
        url = f"https://{slug}.jobs.personio.de/xml?language=en"
        return cached(url, lambda: personio_positions(get_xml(url)))
    if board == "bamboohr":
        url = f"https://{slug}.bamboohr.com/careers/list"
        return cached(url, lambda: list((get_json(url) or {}).get("result") or []))
    if board == "smartrecruiters":
        url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
        return cached(url, lambda: paged(url, "offset", "content", "totalFound", PAGE_SIZE))
    if board == "rippling":
        url = f"https://api.rippling.com/platform/api/ats/v2/board/{slug}/jobs"
        return cached(url, lambda: paged(url, "page", "items", "totalPages", 1))
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    return cached(url, lambda: list(get_json(url) or []))


def paged(url: str, cursor: str, items: str, total: str, step: int) -> list:
    jobs = []
    size = "limit" if cursor == "offset" else "pageSize"
    for number in range(LISTING_PAGES):
        payload = get_json(f"{url}?{urlencode({cursor: number * step, size: PAGE_SIZE})}") or {}
        jobs += payload.get(items) or []
        if (number + 1) * step >= (payload.get(total) or 0):
            break
    return jobs


def workable_jobs(payload: dict) -> list:
    company = payload.get("name") or ""
    return [{**job, "company_name": company} for job in payload.get("jobs") or []]


def personio_positions(root) -> list:
    if root is None:
        return []
    positions = []
    for node in root.iter("position"):
        offices = [node.findtext("office") or ""]
        offices += [office.text or "" for office in node.iterfind("additionalOffices/office")]
        positions.append(
            {
                "id": node.findtext("id") or "",
                "name": node.findtext("name") or "",
                "offices": [office for office in offices if office],
                "schedule": node.findtext("schedule") or "",
                "employmentType": node.findtext("employmentType") or "",
                "seniority": node.findtext("seniority") or "",
                "experience": node.findtext("yearsOfExperience") or "",
                "keywords": node.findtext("keywords") or "",
                "sections": [
                    (part.findtext("name") or "", part.findtext("value") or "")
                    for part in node.iterfind("jobDescriptions/jobDescription")
                ],
            }
        )
    return positions


def remote_of(board: str, job: dict) -> bool:
    if board == "ashby":
        place = (job.get("workplaceType") or "").lower()
        return place == "remote" if place else bool(job.get("isRemote"))
    if board == "greenhouse":
        return "remote" in ((job.get("location") or {}).get("name") or "").lower()
    if board == "workable":
        place = (job.get("workplace") or "").lower()
        return bool(job.get("telecommuting") or job.get("remote")) or place == "remote"
    if board == "recruitee":
        return bool(job.get("remote"))
    if board == "personio":
        return any("remote" in office.lower() for office in job.get("offices") or [])
    if board == "bamboohr":
        return job.get("isRemote") is True or str(job.get("locationType")) == "1"
    if board == "smartrecruiters":
        return bool((job.get("location") or {}).get("remote"))
    if board == "rippling":
        places = [place.get("workplaceType") or "" for place in job.get("locations") or []]
        places += job.get("workLocations") or []
        return any("remote" in str(place).lower() for place in places)
    place = (job.get("workplaceType") or "").lower()
    location = ((job.get("categories") or {}).get("location") or "").lower()
    return place == "remote" or "remote" in location


def employer_of(board: str, job: dict) -> str:
    if board == "smartrecruiters":
        return (job.get("company") or {}).get("name") or ""
    return job.get("company_name") or ""


def board_jobs(board: str, slug: str) -> list[dict]:
    jobs = []
    for job in board_listing(board, slug):
        if board == "ashby" and job.get("isListed") is False:
            continue
        if board == "recruitee" and job.get("status") not in (None, "published"):
            continue
        job_id = normal_id(board, str(job.get(ID_FIELDS.get(board, "id")) or ""))
        title = job.get(TITLE_FIELDS.get(board, "title"))
        if job_id and title:
            jobs.append(
                {
                    "id": job_id,
                    "title": title,
                    "remote": remote_of(board, job),
                    "employer": employer_of(board, job),
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
            found[external_id(board, slug, job_id)] = Listing(
                external_id=external_id(board, slug, job_id),
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
                external_id(board, slug, job["id"]),
                Listing(
                    external_id=external_id(board, slug, job["id"]),
                    url=job_url(board, slug, job["id"]),
                    title=job["title"][:255],
                    employer=(job["employer"] or info.get("name") or pretty(slug))[:255],
                ),
            )
    return list(found.values())


def found_posting(title: str, employer: str, lines: list[str], remote: bool) -> dict:
    return {"title": title, "employer": employer, "text": "\n".join(lines), "remote": remote}


def listed(board: str, slug: str, job_id: str) -> dict | None:
    field = ID_FIELDS.get(board, "id")
    return next(
        (
            job
            for job in board_listing(board, slug)
            if normal_id(board, str(job.get(field))) == job_id
        ),
        None,
    )


def place_name(location) -> str:
    if isinstance(location, dict):
        parts = [location.get(key) for key in ("city", "region", "state", "country")]
        return ", ".join(str(part) for part in parts if part)
    return str(location or "")


def label_of(value) -> str:
    return str((value.get("label") or "") if isinstance(value, dict) else (value or ""))


def workable_posting(slug: str, job_id: str) -> dict | None:
    job = get_json(f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{job_id}")
    if not job or not job.get("title"):
        return None
    lines = [
        job["title"],
        f"Location: {place_name(job.get('location'))}",
        f"Workplace: {job.get('workplace') or ('remote' if job.get('remote') else '')}",
        "",
        strip_html(job.get("description") or ""),
        "",
        strip_html(job.get("requirements") or ""),
        "",
        strip_html(job.get("benefits") or ""),
    ]
    return found_posting(job["title"], "", lines, remote_of("workable", job))


def recruitee_posting(slug: str, job_id: str) -> dict | None:
    offer = (get_json(f"https://{slug}.recruitee.com/api/offers/{job_id}") or {}).get("offer")
    if not offer or not offer.get("title") or offer.get("status") not in (None, "published"):
        return None
    lines = [
        offer["title"],
        f"Company: {offer.get('company_name') or ''}",
        f"Location: {offer.get('location') or ''}",
        f"Remote: {'yes' if offer.get('remote') else 'no'}",
        "",
        strip_html(offer.get("description") or ""),
        "",
        strip_html(offer.get("requirements") or ""),
    ]
    return found_posting(
        offer["title"], offer.get("company_name") or "", lines, remote_of("recruitee", offer)
    )


def personio_posting(slug: str, job_id: str) -> dict | None:
    job = listed("personio", slug, job_id)
    if job is None:
        return None
    lines = [
        job["name"],
        f"Location: {', '.join(job['offices'])}",
        f"Schedule: {job['schedule']} {job['employmentType']}".strip(),
        f"Seniority: {job['seniority']}, {job['experience']} years".strip(", "),
        f"Keywords: {job['keywords']}",
    ]
    for name, value in job["sections"] or native_sections(slug, job_id):
        lines += ["", name, strip_html(value)]
    return found_posting(job["name"], "", lines, remote_of("personio", job))


def native_sections(slug: str, job_id: str) -> list:
    url = f"https://{slug}.jobs.personio.de/xml"
    jobs = cached(url, lambda: personio_positions(get_xml(url)))
    return next((job["sections"] for job in jobs if job["id"] == job_id), [])


def bamboohr_posting(slug: str, job_id: str) -> dict | None:
    payload = get_json(f"https://{slug}.bamboohr.com/careers/{job_id}/detail") or {}
    job = (payload.get("result") or {}).get("jobOpening") or {}
    status = (job.get("jobOpeningStatus") or "open").lower()
    if not job.get("jobOpeningName") or status != "open":
        return None
    lines = [
        job["jobOpeningName"],
        f"Location: {place_name(job.get('location'))}",
        f"Remote: {'yes' if remote_of('bamboohr', job) else 'no'}",
        "",
        strip_html(job.get("description") or ""),
    ]
    return found_posting(job["jobOpeningName"], "", lines, remote_of("bamboohr", job))


def smartrecruiters_posting(slug: str, job_id: str) -> dict | None:
    job = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{job_id}")
    if not job or not job.get("name") or job.get("active") is False:
        return None
    location = job.get("location") or {}
    lines = [
        job["name"],
        f"Company: {employer_of('smartrecruiters', job)}",
        f"Location: {location.get('fullLocation') or place_name(location)}",
        f"Remote: {'yes' if location.get('remote') else 'no'}",
    ]
    for section in ((job.get("jobAd") or {}).get("sections") or {}).values():
        lines += ["", section.get("title") or "", strip_html(section.get("text") or "")]
    return found_posting(
        job["name"], employer_of("smartrecruiters", job), lines, remote_of("smartrecruiters", job)
    )


def rippling_posting(slug: str, job_id: str) -> dict | None:
    job = get_json(f"https://api.rippling.com/platform/api/ats/v2/board/{slug}/jobs/{job_id}")
    if not job or not job.get("name"):
        return None
    description = job.get("description") or {}
    lines = [
        job["name"],
        f"Company: {job.get('companyName') or ''}",
        f"Location: {'; '.join(str(place) for place in job.get('workLocations') or [])}",
        f"Employment: {label_of(job.get('employmentType'))}",
        "",
        strip_html(description.get("role") or ""),
        "",
        strip_html(description.get("company") or ""),
    ]
    remote = remote_of("rippling", job) or remote_of(
        "rippling", listed("rippling", slug, job_id) or {}
    )
    return found_posting(job["name"], job.get("companyName") or "", lines, remote)


POSTINGS = {
    "workable": workable_posting,
    "recruitee": recruitee_posting,
    "personio": personio_posting,
    "bamboohr": bamboohr_posting,
    "smartrecruiters": smartrecruiters_posting,
    "rippling": rippling_posting,
}


def load_posting(board: str, slug: str, job_id: str) -> dict | None:
    if board in POSTINGS:
        return POSTINGS[board](slug, job_id)
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
        f'Apply to the job "{title}" on this company job board.',
        (
            "If the page shows the job description, press 'Apply' or 'Apply for this job' to "
            "reach the form. Fill every field from the CV, candidate_contact and candidate_facts, "
            "and use the upload action for the résumé or CV file field."
        ),
        (
            "Never use 'Apply with LinkedIn', 'Autofill with MyGreenhouse', 'Apply with Indeed', "
            "'Continue with Google' or any sign-in or account option; if the form cannot be sent "
            "without signing in or creating an account, reply stuck."
        ),
        (
            "Submit the form. The application is sent only when the page confirms it (e.g. "
            "'Thank you for applying' or 'Application submitted')."
        ),
    ]
    if letter:
        lines.append(f"If there is a cover letter field, paste this letter:\n{letter}")
    return "\n".join(lines)
