import asyncio
import shutil
import sqlite3
import subprocess
from contextlib import suppress

from django.conf import settings
from telethon.errors import RPCError

from apps.opportunities.telegram import client

APP_ID = "kz.jobfiller.Agent"
APP_NAME = "Job agent"
DESKTOP_LINES = 5
ANSWER = "answer"


def send(text: str) -> bool:
    if not settings.HUNTER_NOTIFY_TELEGRAM or not text:
        return False

    async def deliver() -> bool:
        telegram = client()
        await telegram.connect()
        try:
            if not await telegram.is_user_authorized():
                return False
            await telegram.send_message("me", text[:4000], link_preview=False)
            return True
        finally:
            await telegram.disconnect()

    try:
        return asyncio.run(deliver())
    except (OSError, RPCError, RuntimeError, sqlite3.Error):
        return False


def summary_text(summary, error: str = "", show_cap: bool = True) -> str:
    lines = []
    if summary.applied:
        lines.append(f"✅ Applied to {len(summary.applied)}")
        lines += [f"• [{v.source}] {v.title} — {v.employer}\n  {v.url}" for v in summary.applied]
    if summary.review:
        lines.append(f"👀 Needs your review: {len(summary.review)}")
        lines += [f"• {v.title} — {v.note or v.match_reason}\n  {v.url}" for v in summary.review]
    if summary.reconciled:
        lines.append(f"📬 Confirmed sent outside the agent: {len(summary.reconciled)}")
        lines += [f"• {v.title} — {v.employer}" for v in summary.reconciled]
    if summary.daily_cap_reached and show_cap:
        lines.append(f"⏸ Daily cap of {settings.HUNTER_MAX_APPLIES_PER_DAY} responses reached.")
    if error:
        lines.append(f"⚠️ {error}")
    return "\n".join(lines)


def desktop_text(summary, error: str = "", show_cap: bool = True) -> tuple[str, str]:
    parts = []
    if summary.applied:
        parts.append(f"Sent {len(summary.applied)}")
    if summary.review:
        parts.append(f"{len(summary.review)} need you")
    if not parts and error:
        parts.append("The agent hit a problem")
    if not parts and summary.daily_cap_reached and show_cap:
        parts.append("Daily cap reached")
    if not parts:
        return "", ""
    lines = [f"✓ {v.title} — {v.employer}" for v in summary.applied]
    lines += [f"• {v.title} — {v.employer}" for v in summary.review]
    if len(lines) > DESKTOP_LINES:
        lines = [*lines[: DESKTOP_LINES - 1], f"and {len(lines) - DESKTOP_LINES + 1} more"]
    if summary.daily_cap_reached and show_cap:
        lines.append(f"Daily cap of {settings.HUNTER_MAX_APPLIES_PER_DAY} responses reached.")
    if error:
        lines.append(error)
    return " · ".join(parts), "\n".join(lines)


def send_desktop(title: str, body: str) -> bool:
    command = shutil.which("notify-send")
    if not settings.HUNTER_NOTIFY_DESKTOP or not command or not title:
        return False
    try:
        subprocess.run(
            [
                command,
                f"--app-name={APP_NAME}",
                f"--icon={APP_ID}",
                f"--hint=string:desktop-entry:{APP_ID}",
                title,
                body,
            ],
            check=True,
            timeout=10,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def publish(summary, error: str = "", show_cap: bool = True) -> list[str]:
    channels = []
    if send_desktop(*desktop_text(summary, error, show_cap)):
        channels.append("the desktop")
    if settings.HUNTER_NOTIFY_TELEGRAM and send(summary_text(summary, error, show_cap)):
        channels.append("Telegram Saved Messages")
    return channels


def close_desktop(notification_id: str) -> None:
    command = shutil.which("gdbus")
    if not command or not notification_id.isdigit():
        return
    with suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            [
                command,
                "call",
                "--session",
                "--dest=org.freedesktop.Notifications",
                "--object-path=/org/freedesktop/Notifications",
                "--method=org.freedesktop.Notifications.CloseNotification",
                notification_id,
            ],
            check=False,
            timeout=10,
            capture_output=True,
        )


def ask_desktop(title: str, body: str, action: str, timeout_seconds: float) -> bool:
    command = shutil.which("notify-send")
    if not settings.HUNTER_NOTIFY_DESKTOP or not command or timeout_seconds <= 0:
        return False
    try:
        process = subprocess.Popen(
            [
                command,
                f"--app-name={APP_NAME}",
                f"--icon={APP_ID}",
                f"--hint=string:desktop-entry:{APP_ID}",
                "--urgency=critical",
                "--print-id",
                "--wait",
                f"--action={ANSWER}={action}",
                f"--action=default={action}",
                title,
                body,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return False
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
        words = (output or "").split()
        close_desktop(words[0] if words else "")
        return False
    return bool({ANSWER, "default"} & set((output or "").split()[1:]))
