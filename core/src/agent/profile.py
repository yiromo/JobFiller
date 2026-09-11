import re
from dataclasses import dataclass
from pathlib import Path

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_NAME_STRIP_RE = re.compile(r"^(cv|resume)[_\- ]*", re.IGNORECASE)
_LINKEDIN_RE = re.compile(r"(https?://)?(www\.)?linkedin\.com/in/[\w\-]+/?", re.IGNORECASE)
_GIT_RE = re.compile(r"(https?://)?(www\.)?(github|gitlab)\.com/[\w\-]+/?", re.IGNORECASE)


@dataclass(frozen=True)
class Profile:
    full_name: str
    email: str
    phone: str
    linkedin_url: str
    git_url: str


def extract_profile(raw_text: str, filename: str) -> Profile:
    email_match = _EMAIL_RE.search(raw_text)
    phone_match = _PHONE_RE.search(raw_text)
    linkedin_match = _LINKEDIN_RE.search(raw_text)
    git_match = _GIT_RE.search(raw_text)
    return Profile(
        full_name=_guess_name(raw_text, filename),
        email=email_match.group(0) if email_match else "",
        phone=phone_match.group(0).strip() if phone_match else "",
        linkedin_url=linkedin_match.group(0) if linkedin_match else "",
        git_url=git_match.group(0) if git_match else "",
    )


def _guess_name(raw_text: str, filename: str) -> str:
    first_line = next((line.strip() for line in raw_text.splitlines() if line.strip()), "")
    looks_like_a_name = (
        first_line and len(first_line) <= 60 and "@" not in first_line
        and not any(ch.isdigit() for ch in first_line)
    )
    if looks_like_a_name:
        return first_line

    # CV headers vary too much to parse reliably — the filename is a crude
    # but honest fallback rather than guessing wrong from the header text.
    stem = _NAME_STRIP_RE.sub("", Path(filename).stem)
    return stem.replace("_", " ").replace("-", " ").strip()
