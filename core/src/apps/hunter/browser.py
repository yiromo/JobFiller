import json
import os
import time
from contextlib import contextmanager, suppress
from pathlib import Path

from camoufox.fingerprints import get_random_preset
from camoufox.pkgman import installed_verstr
from camoufox.sync_api import Camoufox
from django.conf import settings
from playwright.sync_api import Error as PlaywrightError

FINGERPRINT_FILE = "fingerprint.json"
SESSION_FILE = "session.json"


def profile_dir(site: str) -> Path:
    path = settings.DATA_DIR / "browser" / site
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_private(path: Path, text: str) -> None:
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(text)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def fingerprint_for(site: str) -> dict:
    path = profile_dir(site) / FINGERPRINT_FILE
    if path.exists():
        return json.loads(path.read_text())
    preset = get_random_preset(os="linux", ff_version=installed_verstr().split(".", 1)[0])
    if not preset:
        raise RuntimeError("Camoufox has no fingerprint presets; run `camoufox fetch`.")
    write_private(path, json.dumps(preset))
    return preset


def save_session(site: str, context) -> None:
    path = profile_dir(site) / SESSION_FILE
    write_private(path, json.dumps({"saved_at": int(time.time()), "cookies": context.cookies()}))


def restore_session(site: str, context) -> bool:
    path = profile_dir(site) / SESSION_FILE
    if not path.exists():
        return False
    cookies = json.loads(path.read_text()).get("cookies") or []
    if cookies:
        context.add_cookies(cookies)
    return bool(cookies)


def headless_mode(value: str):
    value = value.strip().lower()
    if value == "virtual":
        return "virtual"
    return value in {"1", "true", "yes"}


@contextmanager
def open_browser(site: str, headless=None):
    if headless is None:
        headless = headless_mode(settings.HUNTER_HEADLESS)
    with Camoufox(
        persistent_context=True,
        user_data_dir=str(profile_dir(site) / "firefox"),
        headless=headless,
        fingerprint_preset=fingerprint_for(site),
        locale=["ru-RU", "ru", "en-US"],
        humanize=True,
    ) as context:
        if not context.cookies():
            restore_session(site, context)
        try:
            yield context
        finally:
            with suppress(PlaywrightError):
                save_session(site, context)
