import base64
import binascii
import email
import hashlib
import html
import imaplib
import json
import mailbox
import re
import shutil
import tarfile
import tempfile
import time
import unicodedata
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, timedelta
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Q
from django.utils import timezone
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from openai import OpenAI, OpenAIError

from agent import mimo

from . import notify, review
from .models import MailMessage, Vacancy

HOST = "imap.gmail.com"
IMPORTED = 0
GMAIL_API = 1
OAUTH = "oauth"
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_PAGE = 500
UID_MASK = (1 << 63) - 1
SKIPPED_LABELS = {"sent", "draft", "drafts", "spam", "trash", "chat", "chats"}
IMPORT_LOG_EVERY = 10
IMPORT_RETRY_SECONDS = 30
TIMEOUT_SECONDS = 60
CLASSIFY_BATCH = 15
TEXT_CHARS = 1200
PARTIAL_BYTES = 200_000
NOTIFY_WITHIN = timedelta(days=2)
LINK_SLACK = timedelta(days=1)
TITLE_MATCH_WORDS = 3
TITLE_MATCH_SHARE = 0.8
RELINK_BATCH = 30
BOARD_SENDERS = {"hh": ("hh.kz", "hh.ru")}
EXCLUDE = "-in:sent -in:drafts -in:chats"
MODEL_ERRORS = (OpenAIError, ValueError, TypeError, AttributeError, KeyError)
MAIL_ERRORS = (imaplib.IMAP4.error, OSError, DatabaseError, GoogleAuthError)
PARSE_ERRORS = (ValueError, TypeError, AttributeError, LookupError, AssertionError)
SYNC_ERRORS = (*MAIL_ERRORS, *MODEL_ERRORS, *PARSE_ERRORS, RuntimeError)

KINDS = {
    "interview": "an invitation to interview, or scheduling or rescheduling one",
    "offer": "a job offer or offer details",
    "assessment": "a test, take-home task, coding challenge or questionnaire to complete",
    "action_needed": (
        "the applicant must do something else for an application: confirm an email, finish or "
        "fix an application, answer a recruiter's question, send documents; requests that have "
        "nothing to do with a job application are personal or other"
    ),
    "rejection": "an employer declining the application or closing the position",
    "confirmation": "an automatic receipt that an application was received",
    "recruiter": "a recruiter or hiring manager reaching out about a role, not yet an interview",
    "job_alert": "a digest or alert listing job openings",
    "account": "account, security, login code, billing or service notices",
    "newsletter": "newsletters, marketing and promotions",
    "personal": "personal or work correspondence unrelated to job hunting",
    "other": "anything else",
}
URGENT = ("interview", "offer", "assessment", "action_needed")
SHOWN = (*URGENT, "rejection", "confirmation", "recruiter")
REPLY_KINDS = ("interview", "offer", "assessment", "rejection", "confirmation")

SYSTEM_PROMPT = (
    "You sort a job seeker's email. Kinds:\n"
    + "\n".join(f"- {kind}: {meaning}" for kind, meaning in KINDS.items())
    + "\nFor every email return its kind, the company the email is from or about (empty if "
    "none or if it is only a job board or recruiting tool such as LinkedIn, hh.ru, Greenhouse, "
    "Ashby or Lever), and one short English sentence under 140 characters saying what it "
    "asks of the applicant or tells them, and the job title the email is about exactly as "
    "written in it (empty if it names none). Reply with JSON only: "
    '{"emails": [{"id": "...", "kind": "...", "employer": "...", "summary": "...", '
    '"position": "..."}]}, one entry per email given, using the exact ids given.'
)
POSITION_PROMPT = (
    "Each item is a job seeker's email: sender, subject and a one-sentence summary. Return the "
    "job title each one is about, exactly as written there, or an empty string if none is "
    'named. Reply with JSON only: {"emails": [{"id": "...", "position": "..."}]}, one entry '
    "per item, using the exact ids given."
)

TAG_RE = re.compile(r"<[^>]+>")
HIDDEN_RE = re.compile(r"<(style|script|head)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
SPACE_RE = re.compile(r"\s+")
UID_RE = re.compile(rb"\bUID (\d+)")
COMPANY_SUFFIX_RE = re.compile(
    r"\b(inc|llc|ltd|limited|gmbh|corp|corporation|co|company|plc|sa|bv|ag|ab|oy|тоо|ооо|ао)\b"
)
WORD_RE = re.compile(r"\w+")


@dataclass(frozen=True)
class Account:
    address: str
    password: str
    days: int | None


def accounts() -> list[Account]:
    parsed = []
    for entry in settings.HUNTER_MAIL_ACCOUNTS.split(","):
        parts = entry.strip().split(":", 2)
        if len(parts) != 3:
            continue
        address, window, password = (part.strip() for part in parts)
        password = password.replace(" ", "")
        if not address or not password:
            continue
        if window.lower() in ("", "all"):
            days = None
        elif window.isdigit() and int(window) > 0:
            days = int(window)
        else:
            continue
        parsed.append(Account(address=address, password=password, days=days))
    return parsed


def squash(text: str) -> str:
    return SPACE_RE.sub(" ", text).strip()


def strip_html(text: str) -> str:
    return html.unescape(TAG_RE.sub(" ", HIDDEN_RE.sub(" ", text)))


def header(message, name: str) -> str:
    try:
        return squash(str(message.get(name, "") or ""))
    except (ValueError, TypeError, AttributeError, IndexError):
        return ""


def body_text(message) -> str:
    try:
        part = message.get_body(preferencelist=("plain", "html"))
        if part is None:
            return ""
        content = part.get_content()
        subtype = part.get_content_subtype()
    except (LookupError, ValueError, TypeError, AttributeError, AssertionError):
        return ""
    if not isinstance(content, str):
        return ""
    if subtype == "html":
        content = strip_html(content)
    return squash(content)[:TEXT_CHARS]


def received_at(message):
    try:
        moment = parsedate_to_datetime(header(message, "Date"))
    except (TypeError, ValueError, IndexError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


def parse(raw: bytes) -> dict:
    message = email.message_from_bytes(raw, policy=policy.default)
    return {
        "message_id": header(message, "Message-ID")[:998],
        "sender": header(message, "From")[:255],
        "subject": header(message, "Subject")[:500],
        "received_at": received_at(message),
        "labels": {
            label.strip().lower()
            for label in header(message, "X-Gmail-Labels").split(",")
            if label.strip()
        },
        "text": body_text(message),
    }


def quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def all_mail_folder(imap) -> str:
    status, rows = imap.list()
    if status != "OK":
        return "INBOX"
    for row in rows or []:
        line = row.decode("utf-8", "replace") if isinstance(row, bytes) else str(row)
        if "\\All" not in line:
            continue
        match = re.search(r'("(?:[^"\\]|\\.)*"|\S+)\s*$', line)
        if match:
            return match.group(1)
    return "INBOX"


def fetched(data) -> dict[int, bytes]:
    messages = {}
    for index, item in enumerate(data or []):
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        match = UID_RE.search(item[0])
        if not match and index + 1 < len(data) and isinstance(data[index + 1], bytes):
            match = UID_RE.search(data[index + 1])
        if match:
            messages[int(match.group(1))] = item[1]
    return messages


def blank_mail() -> dict:
    return {
        "message_id": "",
        "sender": "",
        "subject": "",
        "received_at": None,
        "labels": set(),
        "text": "",
    }


def fetch(imap, uids: list[int]) -> dict[int, dict]:
    status, data = imap.uid(
        "FETCH", ",".join(str(uid) for uid in uids), f"(BODY.PEEK[]<0.{PARTIAL_BYTES}>)"
    )
    if status != "OK":
        raise imaplib.IMAP4.error(f"fetch failed: {status}")
    emails = {}
    for uid, raw in fetched(data).items():
        try:
            emails[uid] = parse(raw)
        except PARSE_ERRORS:
            emails[uid] = blank_mail()
    return emails


def classify(emails: dict[int, dict]) -> dict[int, dict]:
    client = OpenAI(api_key=settings.MIMO_API_KEY, base_url=settings.MIMO_BASE_URL)
    payload = [
        {
            "id": str(uid),
            "from": mail["sender"],
            "subject": mail["subject"],
            "date": mail["received_at"].isoformat() if mail["received_at"] else "",
            "text": mail["text"],
        }
        for uid, mail in emails.items()
    ]
    response = mimo.chat(
        client,
        model=settings.MIMO_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"emails": payload}, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
        timeout=TIMEOUT_SECONDS,
    )
    rows = json.loads(response.choices[0].message.content).get("emails", [])
    sorted_rows = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            uid = int(str(row.get("id", "")).strip())
        except ValueError:
            continue
        if uid not in emails:
            continue
        kind = str(row.get("kind", "")).strip().lower()
        sorted_rows[uid] = {
            "kind": kind if kind in KINDS else "other",
            "employer": squash(str(row.get("employer") or ""))[:255],
            "summary": squash(str(row.get("summary") or ""))[:500],
            "position": squash(str(row.get("position") or ""))[:255],
        }
    return sorted_rows


def extract_positions(messages: list[MailMessage]) -> dict[int, str]:
    client = OpenAI(api_key=settings.MIMO_API_KEY, base_url=settings.MIMO_BASE_URL)
    payload = [
        {
            "id": str(message.pk),
            "from": message.sender,
            "subject": message.subject,
            "summary": message.summary,
        }
        for message in messages
    ]
    response = mimo.chat(
        client,
        model=settings.MIMO_MODEL,
        messages=[
            {"role": "system", "content": POSITION_PROMPT},
            {"role": "user", "content": json.dumps({"emails": payload}, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
        timeout=TIMEOUT_SECONDS,
    )
    known = {message.pk for message in messages}
    positions = {}
    for row in json.loads(response.choices[0].message.content).get("emails", []):
        if not isinstance(row, dict):
            continue
        try:
            key = int(str(row.get("id", "")).strip())
        except ValueError:
            continue
        position = squash(str(row.get("position") or ""))[:255]
        if key in known and position:
            positions[key] = position
    return positions


def company_key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name.lower())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return "".join(WORD_RE.findall(COMPANY_SUFFIX_RE.sub(" ", folded))).replace("_", "")


def same_company(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= 4 and longer.startswith(shorter)


def sent_at(vacancy: Vacancy):
    return vacancy.applied_at or vacancy.submitted_at or vacancy.created_at


def candidates() -> list[tuple[str, Vacancy]]:
    rows = Vacancy.objects.exclude(employer="").filter(
        Q(applied_at__isnull=False)
        | Q(submitted_at__isnull=False)
        | Q(status=Vacancy.Status.NEEDS_REVIEW)
    )
    return [(company_key(vacancy.employer), vacancy) for vacancy in rows]


def title_words(text: str) -> set[str]:
    return set(WORD_RE.findall(text.lower()))


def board_source(sender: str) -> str:
    domain = sender.rsplit("@", 1)[-1].lower().strip(' >"')
    return next((site for site, hosts in BOARD_SENDERS.items() if domain in hosts), "")


def title_fits(wanted: set[str], subject: str, position: str) -> bool:
    if len(wanted) < TITLE_MATCH_WORDS:
        return False
    if position:
        named = title_words(position)
        return len(wanted & named) / len(wanted | named) >= TITLE_MATCH_SHARE
    return wanted <= title_words(subject)


def match_by_title(subject: str, position: str, moment, pool, source: str) -> Vacancy | None:
    found = []
    for _key, vacancy in pool:
        if source and vacancy.source != source:
            continue
        if moment and sent_at(vacancy) and moment < sent_at(vacancy) - LINK_SLACK:
            continue
        if title_fits(title_words(vacancy.title), subject, position):
            found.append(vacancy)
    return found[0] if len(found) == 1 else None


def match_vacancy(
    employer: str, subject: str, moment, pool, sender: str = "", position: str = ""
) -> Vacancy | None:
    key = company_key(employer)
    if not key:
        return match_by_title(subject, position, moment, pool, board_source(sender))
    if len(key) < 3:
        return None
    words = title_words(f"{subject} {position}")
    best = None
    best_rank = None
    for vacancy_key, vacancy in pool:
        if not same_company(key, vacancy_key):
            continue
        if moment and sent_at(vacancy) and moment < sent_at(vacancy) - LINK_SLACK:
            continue
        overlap = len(words & title_words(vacancy.title))
        rank = (overlap, sent_at(vacancy))
        if best_rank is None or rank > best_rank:
            best, best_rank = vacancy, rank
    return best


def relink(log, days: int = 30, classify_positions: bool = False) -> int:
    since = timezone.now() - timedelta(days=days)
    rows = list(
        MailMessage.objects.filter(
            kind__in=SHOWN, vacancy__isnull=True, received_at__gte=since
        ).order_by("received_at")
    )
    if classify_positions and settings.MIMO_API_KEY:
        missing = [message for message in rows if not message.position]
        for start in range(0, len(missing), RELINK_BATCH):
            batch = missing[start : start + RELINK_BATCH]
            try:
                positions = extract_positions(batch)
            except MODEL_ERRORS as error:
                log(f"Mail relink: reading job titles failed ({type(error).__name__}).")
                continue
            for message in batch:
                if message.pk in positions:
                    message.position = positions[message.pk]
                    MailMessage.objects.filter(pk=message.pk).update(position=message.position)
    pool = candidates()
    linked = 0
    for message in rows:
        vacancy = match_vacancy(
            message.employer,
            message.subject,
            message.received_at,
            pool,
            message.sender,
            message.position,
        )
        if vacancy is None:
            continue
        MailMessage.objects.filter(pk=message.pk).update(vacancy=vacancy)
        message.vacancy = vacancy
        confirm_sent(message, log)
        linked += 1
    log(f"Mail relink: linked {linked} of {len(rows)} unlinked emails to a job.")
    return linked


def confirm_sent(message: MailMessage, log) -> None:
    vacancy = message.vacancy
    if vacancy is None or message.kind not in REPLY_KINDS:
        return
    if vacancy.status != Vacancy.Status.NEEDS_REVIEW or vacancy.submitted_at is None:
        return
    if review.kind_of(vacancy) != review.UNCONFIRMED:
        return
    if message.received_at and message.received_at < vacancy.submitted_at - timedelta(minutes=10):
        return
    updated = Vacancy.objects.filter(pk=vacancy.pk, status=Vacancy.Status.NEEDS_REVIEW).update(
        status=Vacancy.Status.APPLIED,
        applied_at=vacancy.submitted_at,
        note=f"Confirmed by a {message.kind.replace('_', ' ')} email.",
        updated_at=timezone.now(),
    )
    if updated:
        log(f"Mail: an email confirmed job {vacancy.pk} was sent.")


def store(account: Account, uidvalidity: int, emails, sorted_rows, pool, log) -> list:
    saved = []
    for uid, mail in emails.items():
        row = sorted_rows.get(uid) or {"kind": "other", "employer": "", "summary": ""}
        position = row.get("position", "")
        vacancy = None
        if row["kind"] in SHOWN:
            vacancy = match_vacancy(
                row["employer"],
                mail["subject"],
                mail["received_at"],
                pool,
                mail["sender"],
                position,
            )
        message, created = MailMessage.objects.get_or_create(
            account=account.address,
            uidvalidity=uidvalidity,
            uid=uid,
            defaults={
                "message_id": mail["message_id"],
                "received_at": mail["received_at"],
                "sender": mail["sender"],
                "subject": mail["subject"],
                "kind": row["kind"],
                "employer": row["employer"],
                "summary": row["summary"],
                "position": position,
                "vacancy": vacancy,
            },
        )
        if created:
            confirm_sent(message, log)
            saved.append(message)
    return saved


def adopt_imported(account: Account, uidvalidity: int, emails: dict) -> dict:
    by_id = {mail["message_id"]: uid for uid, mail in emails.items() if mail["message_id"]}
    if not by_id:
        return emails
    adopted = set()
    imported = MailMessage.objects.filter(
        account=account.address, uidvalidity=IMPORTED, message_id__in=list(by_id)
    )
    for message in imported:
        uid = by_id[message.message_id]
        MailMessage.objects.filter(pk=message.pk).update(uidvalidity=uidvalidity, uid=uid)
        adopted.add(uid)
    return {uid: mail for uid, mail in emails.items() if uid not in adopted}


def sync_account(account: Account, log, limit: int, connect=None) -> list:
    imap = (connect or imaplib.IMAP4_SSL)(HOST, timeout=TIMEOUT_SECONDS)
    try:
        imap.login(account.address, account.password)
        folder = all_mail_folder(imap)
        status, _ = imap.select(folder, readonly=True)
        if status != "OK":
            raise imaplib.IMAP4.error(f"cannot open {folder}")
        validity = (imap.response("UIDVALIDITY")[1] or [None])[0]
        if not validity or not str(validity, "ascii", "replace").strip().isdigit():
            raise imaplib.IMAP4.error(f"no UIDVALIDITY for {folder}")
        uidvalidity = int(validity)
        query = EXCLUDE + (f" newer_than:{account.days}d" if account.days else "")
        status, data = imap.uid("SEARCH", "X-GM-RAW", quoted(query))
        if status != "OK":
            raise imaplib.IMAP4.error(f"search failed: {status}")
        found = sorted({int(uid) for uid in (data[0] or b"").split()}, reverse=True)
        known = set(
            MailMessage.objects.filter(
                account=account.address, uidvalidity=uidvalidity
            ).values_list("uid", flat=True)
        )
        pending = [uid for uid in found if uid not in known]
        waiting = len(pending)
        if limit:
            pending = pending[:limit]
        if not pending:
            return []
        log(f"Mail {account.address}: sorting {len(pending)} of {waiting} new emails.")
        pool = candidates()
        saved = []
        for start in range(0, len(pending), CLASSIFY_BATCH):
            emails = adopt_imported(
                account, uidvalidity, fetch(imap, pending[start : start + CLASSIFY_BATCH])
            )
            if not emails:
                continue
            try:
                sorted_rows = classify(emails)
            except MODEL_ERRORS as error:
                log(f"Mail {account.address}: sorting failed ({type(error).__name__}).")
                break
            saved += store(account, uidvalidity, emails, sorted_rows, pool, log)
        return saved
    finally:
        with suppress(imaplib.IMAP4.error, OSError):
            imap.logout()


class GmailLoginNeeded(GoogleAuthError):
    pass


def token_path(address: str) -> Path:
    return Path(settings.DATA_DIR) / "gmail" / f"{address.lower()}.json"


def client_config() -> dict:
    if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
        raise GmailLoginNeeded("GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET are not set in core/.env.")
    return {
        "installed": {
            "client_id": settings.GMAIL_CLIENT_ID,
            "client_secret": settings.GMAIL_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def save_token(address: str, credentials) -> None:
    path = token_path(address)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(credentials.to_json(strip=["client_secret"]))
    path.chmod(0o600)


def gmail_session(address: str) -> AuthorizedSession:
    path = token_path(address)
    if not path.exists():
        raise GmailLoginNeeded(f"not signed in; run mail_login {address}")
    info = json.loads(path.read_text())
    info["client_secret"] = client_config()["installed"]["client_secret"]
    return AuthorizedSession(Credentials.from_authorized_user_info(info, GMAIL_SCOPES))


def gmail_get(session, path: str, params: dict | None = None) -> dict:
    response = session.get(f"{GMAIL_BASE}/{path}", params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def gmail_uid(message_id: str) -> int:
    return int(message_id, 16) & UID_MASK


def gmail_ids(session, query: str) -> list[str]:
    ids, token = [], None
    while True:
        params = {"q": query, "maxResults": GMAIL_PAGE}
        if token:
            params["pageToken"] = token
        page = gmail_get(session, "messages", params)
        ids += [item["id"] for item in page.get("messages") or [] if item.get("id")]
        token = page.get("nextPageToken")
        if not token:
            return ids


def gmail_fetch(session, ids: list[str]) -> dict[int, dict]:
    emails = {}
    for message_id in ids:
        raw = gmail_get(session, f"messages/{message_id}", {"format": "raw"}).get("raw") or ""
        try:
            emails[gmail_uid(message_id)] = parse(
                base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))[:PARTIAL_BYTES]
            )
        except (*PARSE_ERRORS, binascii.Error):
            emails[gmail_uid(message_id)] = blank_mail()
    return emails


def sync_gmail(account: Account, log, limit: int, session=None) -> list:
    session = session or gmail_session(account.address)
    query = EXCLUDE + (f" newer_than:{account.days}d" if account.days else "")
    known = set(
        MailMessage.objects.filter(account=account.address, uidvalidity=GMAIL_API).values_list(
            "uid", flat=True
        )
    )
    pending = [mid for mid in gmail_ids(session, query) if gmail_uid(mid) not in known]
    waiting = len(pending)
    if limit:
        pending = pending[:limit]
    if not pending:
        return []
    log(f"Mail {account.address}: sorting {len(pending)} of {waiting} new emails.")
    pool = candidates()
    saved = []
    for start in range(0, len(pending), CLASSIFY_BATCH):
        emails = adopt_imported(
            account, GMAIL_API, gmail_fetch(session, pending[start : start + CLASSIFY_BATCH])
        )
        if not emails:
            continue
        try:
            sorted_rows = classify(emails)
        except MODEL_ERRORS as error:
            log(f"Mail {account.address}: sorting failed ({type(error).__name__}).")
            break
        saved += store(account, GMAIL_API, emails, sorted_rows, pool, log)
    return saved


def message_key(mail: dict) -> int:
    basis = mail["message_id"] or "|".join(
        (mail["sender"], mail["subject"], str(mail["received_at"]), mail["text"][:200])
    )
    return int(hashlib.sha1(basis.encode()).hexdigest()[:15], 16)


def classify_with_retry(emails: dict, log) -> dict | None:
    for attempt in range(2):
        try:
            return classify(emails)
        except MODEL_ERRORS as error:
            log(f"Mail import: sorting failed ({type(error).__name__}).")
            if attempt == 0:
                time.sleep(IMPORT_RETRY_SECONDS)
    return None


def mbox_files(path: Path, workdir: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.rglob("*.mbox"))
    if path.suffix == ".mbox":
        return [path]
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".mbox")]
            for name in names:
                target = workdir / Path(name).name
                with archive.open(name) as source, target.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
        return sorted(workdir.glob("*.mbox"))
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if member.isfile() and member.name.endswith(".mbox"):
                    source = archive.extractfile(member)
                    target = workdir / Path(member.name).name
                    with source, target.open("wb") as sink:
                        shutil.copyfileobj(source, sink)
        return sorted(workdir.glob("*.mbox"))
    return []


def import_mbox(path, address: str, log, limit: int = 0) -> list:
    if not settings.MIMO_API_KEY:
        raise RuntimeError("MIMO_API_KEY is not set, so email cannot be sorted.")
    account = Account(address=address, password="", days=None)
    rows = MailMessage.objects.filter(account=address)
    known_keys = set(rows.filter(uidvalidity=IMPORTED).values_list("uid", flat=True))
    known_ids = set(rows.exclude(message_id="").values_list("message_id", flat=True))
    pool = candidates()
    saved = []
    batches = 0
    skipped = 0
    with tempfile.TemporaryDirectory(dir=settings.DATA_DIR) as workdir:
        files = mbox_files(Path(path), Path(workdir))
        if not files:
            raise RuntimeError(f"No .mbox file found in {path}.")
        for file in files:
            box = mailbox.mbox(file, create=False)
            batch = {}
            for key in box.iterkeys():
                try:
                    mail = parse(box.get_bytes(key)[:PARTIAL_BYTES])
                except PARSE_ERRORS:
                    mail = blank_mail()
                own = parseaddr(mail["sender"])[1].lower() == address.lower()
                if own or mail["labels"] & SKIPPED_LABELS:
                    skipped += 1
                    continue
                uid = message_key(mail)
                if uid in known_keys or (mail["message_id"] and mail["message_id"] in known_ids):
                    continue
                known_keys.add(uid)
                batch[uid] = mail
                if len(batch) < CLASSIFY_BATCH:
                    continue
                sorted_rows = classify_with_retry(batch, log)
                if sorted_rows is None:
                    log("Mail import: stopped; run it again to continue where it left off.")
                    return saved
                saved += store(account, IMPORTED, batch, sorted_rows, pool, log)
                batch = {}
                batches += 1
                if batches % IMPORT_LOG_EVERY == 0:
                    log(f"Mail import: {len(saved)} sorted so far ({counts_line(saved)}).")
                if limit and len(saved) >= limit:
                    return saved
            if batch:
                sorted_rows = classify_with_retry(batch, log)
                if sorted_rows is None:
                    log("Mail import: stopped; run it again to continue where it left off.")
                    return saved
                saved += store(account, IMPORTED, batch, sorted_rows, pool, log)
    if skipped:
        log(f"Mail import: left out {skipped} sent, draft, spam, trash and chat messages.")
    return saved


def counts_line(messages: list) -> str:
    totals = {}
    for message in messages:
        totals[message.kind] = totals.get(message.kind, 0) + 1
    return ", ".join(
        f"{totals[kind]} {kind.replace('_', ' ')}" for kind in KINDS if totals.get(kind)
    )


def notify_urgent(messages: list) -> None:
    recent = timezone.now() - NOTIFY_WITHIN
    urgent = [
        message
        for message in messages
        if message.kind in URGENT and message.received_at and message.received_at >= recent
    ]
    if not urgent:
        return
    lines = [
        f"• {message.kind.replace('_', ' ').capitalize()}: {message.employer or message.sender}"
        for message in urgent[: notify.DESKTOP_LINES]
    ]
    if len(urgent) > notify.DESKTOP_LINES:
        lines.append(f"and {len(urgent) - notify.DESKTOP_LINES} more")
    title = "1 email needs you" if len(urgent) == 1 else f"{len(urgent)} emails need you"
    notify.send_desktop(title, "\n".join(lines))


def sync(log, limit: int | None = None, only: str = "") -> list:
    chosen = [account for account in accounts() if not only or account.address == only]
    if not chosen:
        return []
    if not settings.MIMO_API_KEY:
        log("Mail: MIMO_API_KEY is not set, so email is not sorted.")
        return []
    cap = settings.HUNTER_MAIL_PER_RUN if limit is None else limit
    saved = []
    for account in chosen:
        try:
            if account.password == OAUTH:
                new = sync_gmail(account, log, cap)
            else:
                new = sync_account(account, log, cap)
        except GoogleAuthError as error:
            log(
                f"Mail {account.address}: Gmail sign-in failed ({str(error)[:120]}); "
                f"run mail_login {account.address} again."
            )
            continue
        except MAIL_ERRORS as error:
            log(f"Mail {account.address}: {type(error).__name__}: {str(error)[:200]}")
            continue
        if new:
            log(f"Mail {account.address}: {counts_line(new)}.")
        saved += new
    notify_urgent(saved)
    return saved


def gmail_url(message: MailMessage) -> str:
    base = f"https://mail.google.com/mail/u/{quote(message.account)}/"
    if message.message_id:
        search = f"rfc822msgid:{message.message_id.strip('<>')}"
    else:
        search = message.subject
    return f"{base}#search/{quote(search, safe='')}"


def dismiss(message_id: int) -> str:
    updated = MailMessage.objects.filter(pk=message_id).update(dismissed=True)
    return "" if updated else "No such email."
