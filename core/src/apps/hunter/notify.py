import asyncio

from django.conf import settings
from telethon.errors import RPCError

from apps.opportunities.telegram import client


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
    except (OSError, RPCError, RuntimeError):
        return False


def summary_text(summary, error: str = "") -> str:
    lines = []
    if summary.applied:
        lines.append(f"✅ hh.kz: applied to {len(summary.applied)}")
        lines += [f"• {v.title} — {v.employer}\n  {v.url}" for v in summary.applied]
    if summary.review:
        lines.append(f"👀 Needs your review: {len(summary.review)}")
        lines += [f"• {v.title} — {v.note or v.match_reason}\n  {v.url}" for v in summary.review]
    if summary.daily_cap_reached:
        lines.append(f"⏸ Daily cap of {settings.HUNTER_MAX_APPLIES_PER_DAY} responses reached.")
    if error:
        lines.append(f"⚠️ {error}")
    return "\n".join(lines)
