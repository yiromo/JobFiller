from django.core.management.base import BaseCommand, CommandError
from google_auth_oauthlib.flow import InstalledAppFlow

from apps.hunter import mail


class Command(BaseCommand):
    help = "Sign in to one Gmail account in your browser so the agent can read its job email."

    def add_arguments(self, parser):
        parser.add_argument("address")

    def handle(self, *args, **options):
        address = options["address"].strip().lower()
        try:
            flow = InstalledAppFlow.from_client_config(mail.client_config(), mail.GMAIL_SCOPES)
        except mail.GmailLoginNeeded as error:
            raise CommandError(str(error)) from error
        credentials = flow.run_local_server(
            port=0,
            login_hint=address,
            prompt="consent",
            authorization_prompt_message=f"Sign in as {address} in the browser: {{url}}",
            success_message="Signed in. You can close this tab and go back to the terminal.",
        )
        if not credentials.refresh_token:
            raise CommandError("Google returned no refresh token; run the command again.")
        profile = mail.gmail_get(mail.AuthorizedSession(credentials), "profile")
        signed_in = str(profile.get("emailAddress") or "").lower()
        if signed_in != address:
            raise CommandError(
                f"You signed in as {signed_in}, not {address}. Nothing was saved; run it again "
                f"and pick {address}."
            )
        mail.save_token(address, credentials)
        self.stdout.write(f"Signed in as {address}. The agent can now read its job email.")
