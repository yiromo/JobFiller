import re
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.utils import timezone

GATED_SOURCES = ("linkedin", "ats", "indeed")
ACCOUNT_NOTE = (
    "Applying needs an account on the employer's site, which the agent never creates; apply "
    "yourself or use the outreach draft."
)
AGE_RE = re.compile(
    r"^(?P<place>.*?) · (?:Reposted )?(?P<count>\d+|an?|a few) "
    r"(?P<unit>second|minute|hour|day|week|month)s? ago",
    re.IGNORECASE,
)
AGO_RE = re.compile(
    r"(?P<count>\d+|an?|a few) (?P<unit>second|minute|hour|day|week|month)s? ago", re.IGNORECASE
)
LOCATION_RE = re.compile(r"^Location: *(?P<place>.*)$", re.MULTILINE)
POSTED_RE = re.compile(r"^Posted: *(?P<when>\S+)$", re.MULTILINE)
UNIT_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 7 * 86400,
    "month": 30 * 86400,
}
PLAIN_REMOTE_RE = re.compile(r"^[\s(]*(fully )?remote[\s)]*(job)?$", re.IGNORECASE)
COUNTRIES = (
    r"us|u\.s\.|usa|united states|uk|united kingdom|eu|european union|europe|canada|latam|"
    r"germany|poland|spain|portugal|france|india|brazil|mexico|australia|netherlands|ireland"
)
LOCKED_TEXT_RE = re.compile(
    r"\b(must|need to|required to|should)( currently)?( be)? "
    r"(located|based|reside|residing|living) in\b"
    rf"|\b({COUNTRIES})[- ]only\b"
    rf"|\b({COUNTRIES})[- ]based (candidates|applicants|residents|engineers|developers)\b"
    r"|\b(legally )?(authori[sz]ed|eligible|permitted) to work in\b"
    r"|\bright to work in\b"
    r"|\b(us|u\.s\.) citizen(ship)?\b"
    r"|\bsecurity clearance\b"
    r"|\b(not|unable to|cannot|can't|do not|don't|won't) (provide |offer |support )?"
    r"(visa )?sponsor(ship)?\b"
    r"|\bwithout (the need for )?(visa )?sponsorship\b"
    rf"|\bwithin the ({COUNTRIES})\b",
    re.IGNORECASE,
)
OPEN_TEXT_RE = re.compile(
    r"\b(anywhere in the world|any country|any location|kazakhstan|central asia|"
    r"employer of record|eor|deel|remote\.com|oyster|b2b contract)\b"
    r"|\b(work|working|hire|hiring|candidates|remote)\s+(from\s+)?(anywhere|worldwide)\b"
    rf"(?!\s+(in|within|across)\s+(the\s+)?({COUNTRIES}|americas)\b)",
    re.IGNORECASE,
)


def open_re() -> re.Pattern:
    words = [re.escape(word.strip()) for word in settings.HUNTER_OPEN_LOCATIONS if word.strip()]
    return re.compile(rf"\b({'|'.join(words) or '(?!)'})\b", re.IGNORECASE)


def linkedin_header(vacancy):
    lines = (vacancy.text or "").split("\n")
    if len(lines) < 3:
        return None
    line = lines[2]
    prefix = f"{vacancy.employer} {vacancy.title} "
    return AGE_RE.match(line.removeprefix(prefix))


def location(vacancy) -> str | None:
    if vacancy.source == "linkedin":
        found = linkedin_header(vacancy)
        return found["place"].strip() if found else None
    if vacancy.source == "ats":
        found = LOCATION_RE.search(vacancy.text or "")
        return found["place"].strip() if found else None
    return None


def place_lock(place: str | None, text: str = "") -> str:
    if not settings.HUNTER_LOCATION_GATE or not place or PLAIN_REMOTE_RE.match(place):
        return ""
    if open_re().search(place) or OPEN_TEXT_RE.search(text or ""):
        return ""
    return f"the job is limited to {place}"


def lock(vacancy) -> str:
    if not settings.HUNTER_LOCATION_GATE or vacancy.source not in GATED_SOURCES:
        return ""
    text = vacancy.text or ""
    place = location(vacancy)
    if place and not PLAIN_REMOTE_RE.match(place):
        return place_lock(place, text)
    found = LOCKED_TEXT_RE.search(text)
    if found and not OPEN_TEXT_RE.search(text):
        return f'the posting says "{found.group(0)}"'
    return ""


def lock_note(reason: str) -> str:
    return f"Location-locked: {reason}; {settings.HUNTER_ELIGIBILITY}"


def posted_at(vacancy, now: datetime | None = None) -> datetime | None:
    found = POSTED_RE.search(vacancy.text or "")
    if found:
        try:
            when = datetime.fromisoformat(found["when"])
        except ValueError:
            when = None
        if when:
            return when if timezone.is_aware(when) else timezone.make_aware(when)
    if vacancy.source != "linkedin":
        return None
    header = linkedin_header(vacancy)
    return ago(header, now) if header else None


def ago(found, now: datetime | None = None) -> datetime | None:
    if isinstance(found, str):
        found = AGO_RE.search(found)
    if not found:
        return None
    count = found["count"].lower()
    amount = 1 if count in ("a", "an") else 3 if count == "a few" else int(count)
    seconds = amount * UNIT_SECONDS[found["unit"].lower()]
    return (now or timezone.now()) - timedelta(seconds=seconds)


def posted_line(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        stamp = value / 1000 if value > 10**11 else value
        return f"Posted: {datetime.fromtimestamp(stamp, tz=UTC).isoformat()}"
    text = str(value).strip()
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return ""
    return f"Posted: {text}"
