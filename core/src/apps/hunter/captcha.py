import json
import os
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from . import notify


def cooldown_path():
    return settings.DATA_DIR / "hunter" / "cooldown.json"


def read_cooldowns() -> dict:
    try:
        data = json.loads(cooldown_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_cooldowns(data: dict) -> None:
    path = cooldown_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data))
    os.replace(temporary, path)


def ladder() -> list[int]:
    rungs = []
    for part in str(settings.HUNTER_CAPTCHA_BACKOFF_MINUTES).split(","):
        try:
            rungs.append(max(1, int(part.strip())))
        except ValueError:
            continue
    return rungs


def site_state(site: str) -> dict:
    state = read_cooldowns().get(site)
    return state if isinstance(state, dict) else {}


def save_site(site: str, state: dict) -> None:
    data = read_cooldowns()
    if state:
        data[site] = state
    else:
        data.pop(site, None)
    write_cooldowns(data)


def cooling_until(site: str, now=None) -> datetime | None:
    try:
        until = datetime.fromisoformat(site_state(site).get("until", ""))
    except (TypeError, ValueError):
        return None
    return until if until > (now or timezone.now()) else None


def due_at(site: str) -> datetime | None:
    try:
        return datetime.fromisoformat(site_state(site).get("until", ""))
    except (TypeError, ValueError):
        return None


def active_cooldowns() -> dict:
    now = timezone.now()
    return {site: until for site in read_cooldowns() if (until := cooling_until(site, now))}


def attempt_of(site: str) -> tuple[int, int]:
    state = site_state(site)
    return int(state.get("step", 0)) + 1, len(ladder())


def start_cooldown(site: str) -> datetime | None:
    rungs = ladder()
    if not rungs:
        return None
    state = site_state(site)
    start = min(int(state.get("start", 0)), len(rungs) - 1)
    step = min(int(state["step"]) + 1, len(rungs) - 1) if "step" in state else start
    until = timezone.now() + timedelta(minutes=rungs[step])
    save_site(site, {"until": until.isoformat(), "step": step, "start": start})
    return until


def record_send(site: str) -> None:
    state = site_state(site)
    if not state:
        return
    if "step" in state:
        save_site(site, {"start": int(state["step"])} if state["step"] else {})
    elif state.get("start"):
        save_site(site, {"start": int(state["start"]) - 1} if state["start"] > 1 else {})


def clear_cooldown(site: str) -> None:
    state = site_state(site)
    if "until" in state or "step" in state:
        save_site(site, {"start": state["start"]} if state.get("start") else {})


def ask_to_solve(adapter, vacancy, log) -> bool:
    minutes = settings.HUNTER_CAPTCHA_WAIT_MINUTES
    if minutes <= 0:
        return False
    log(
        f"  {adapter.NAME} wants a captcha for {vacancy.title}; asking you on the desktop "
        f"for up to {minutes} min."
    )
    answered = notify.ask_desktop(
        f"{adapter.NAME} needs you to solve a captcha",
        f"{vacancy.title} — {vacancy.employer}\nClick to open the browser, solve it there, "
        "and the agent sends this application and continues.",
        "Open browser",
        minutes * 60,
    )
    log(
        f"  Opening a visible {adapter.NAME} browser for you."
        if answered
        else f"  No answer; {vacancy.title} goes back in the queue."
    )
    return answered
