import json
import re
import shutil
from contextlib import suppress

from django.conf import settings
from playwright.sync_api import Error as PlaywrightError

KEEP = 200
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
FILES = {
    "page.html": "text/plain; charset=utf-8",
    "page.jpg": "image/jpeg",
    "trace.json": "application/json",
}


def key_for(vacancy) -> str:
    if vacancy.source == "hh":
        return vacancy.external_id
    return f"{vacancy.source}-{vacancy.external_id}"


def pages_dir():
    return settings.DATA_DIR / "hunter" / "pages"


def folder(key: str):
    if not KEY_RE.match(key):
        return None
    return pages_dir() / key


def capture(page, key: str, trace: list | None = None) -> bool:
    target = folder(key)
    if target is None:
        return False
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    saved = False
    with suppress(PlaywrightError, OSError):
        (target / "page.html").write_text(page.content())
        saved = True
    with suppress(PlaywrightError, OSError):
        page.screenshot(path=str(target / "page.jpg"), type="jpeg", quality=60, full_page=True)
        saved = True
    if trace is not None:
        with suppress(OSError):
            (target / "trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=1))
            saved = True
    prune()
    return saved


def available(key: str) -> list[str]:
    target = folder(key)
    if target is None or not target.is_dir():
        return []
    return [name for name in FILES if (target / name).is_file()]


def prune() -> None:
    root = pages_dir()
    if not root.is_dir():
        return
    folders = sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in folders[KEEP:]:
        shutil.rmtree(path, ignore_errors=True)
