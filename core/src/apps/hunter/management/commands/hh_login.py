from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Alias for `hunter_login hh`."

    def handle(self, *args, **options):
        call_command("hunter_login", "hh", stdout=self.stdout, stderr=self.stderr)
