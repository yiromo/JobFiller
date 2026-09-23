import asyncio

from django.core.management.base import BaseCommand

from apps.opportunities.telegram import channel_for, client


class Command(BaseCommand):
    help = "Log in to Telegram interactively and verify access to the private channel."

    def handle(self, *args, **options):
        async def login():
            async with client() as tg:
                channel = await channel_for(tg)
                self.stdout.write(self.style.SUCCESS(f"Connected to {channel.title}"))

        asyncio.run(login())
