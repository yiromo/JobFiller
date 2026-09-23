import asyncio
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.opportunities.models import Opportunity
from apps.opportunities.service import ingest_message
from apps.opportunities.telegram import channel_for, client


class Command(BaseCommand):
    help = "Read new posts from the subscribed private channel and match jobs to CVs."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=2, help="First-run lookback in days")
        parser.add_argument("--message-id", type=int, help="Process one channel post by ID")

    def handle(self, *args, **options):
        async def sync():
            last_id = await sync_to_async(
                lambda: (
                    Opportunity.objects.order_by("-message_id")
                    .values_list("message_id", flat=True)
                    .first()
                )
            )()
            cutoff = timezone.now() - timedelta(days=max(1, options["days"]))
            count = 0
            tg = client()
            await tg.connect()
            try:
                if not await tg.is_user_authorized():
                    raise RuntimeError(
                        "Telegram session is not logged in; run telegram_login first"
                    )
                channel = await channel_for(tg)
                if options["message_id"]:
                    message = await tg.get_messages(channel, ids=options["message_id"])
                    if not message:
                        raise RuntimeError("Channel message was not found")
                    count = len(await sync_to_async(ingest_message)(message))
                else:
                    async for message in tg.iter_messages(channel, min_id=last_id or 0):
                        if not last_id and message.date < cutoff:
                            break
                        if not message.raw_text:
                            continue
                        items = await sync_to_async(ingest_message)(message)
                        count += len(items)
            finally:
                await tg.disconnect()
            self.stdout.write(self.style.SUCCESS(f"Processed {count} opportunity records"))

        asyncio.run(sync())
