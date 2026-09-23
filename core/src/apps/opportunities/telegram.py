from django.conf import settings
from telethon import TelegramClient


def client():
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in core/.env")
    session_path = settings.DATA_DIR / "telegram"
    return TelegramClient(str(session_path), settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)


async def channel_for(client_instance):
    # The invite URL has no public username. Find the subscribed channel in the
    # authenticated account's dialogs; do not join an arbitrary invite silently.
    async for dialog in client_instance.iter_dialogs():
        if dialog.name == settings.TELEGRAM_CHANNEL_TITLE and dialog.is_channel:
            return dialog.entity
    raise RuntimeError(
        f"Channel '{settings.TELEGRAM_CHANNEL_TITLE}' is not in this Telegram account's dialogs. "
        "Join it in Telegram first."
    )
