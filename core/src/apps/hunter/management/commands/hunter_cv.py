from django.core.management.base import BaseCommand, CommandError

from apps.cvs.models import Cv
from apps.hunter.models import Vacancy
from apps.hunter.service import write_flagship_cv


class Command(BaseCommand):
    help = "Write a CV for one job and have the reviewer check it. Sends nothing."

    def add_arguments(self, parser):
        parser.add_argument("--vacancy", type=int, required=True, metavar="ID")
        parser.add_argument("--source", type=int, metavar="CV_ID")

    def handle(self, *args, **options):
        vacancy = Vacancy.objects.filter(pk=options["vacancy"]).first()
        if vacancy is None:
            raise CommandError(f"Job {options['vacancy']} does not exist.")
        source = Cv.objects.filter(pk=options["source"] or vacancy.cv_id).first()
        if source is None:
            raise CommandError("No source CV: pass --source CV_ID.")
        self.stdout.write(f"{vacancy.employer}: {vacancy.title}\nSource CV: {source}")
        draft, outcome, findings, added = write_flagship_cv(
            source, vacancy.text, vacancy.employer, vacancy.title, self.stdout.write
        )
        if outcome:
            self.stdout.write(f"\nFit score: {outcome['fit_score']}")
            for item in outcome["must_haves"]:
                self.stdout.write(f"  {item['status']:<22} {item['requirement']}  {item['note']}")
            for item in outcome["contradictions"]:
                self.stdout.write(f'  CONTRADICTS  "{item["quote"]}"  {item["why"]}')
            for item in outcome["red_flags"]:
                self.stdout.write(f"  {item['severity'].upper():<6} {item['text']}")
        if draft is None:
            self.stdout.write("\nNo draft passed: " + "; ".join(findings))
            return
        if added:
            self.stdout.write(f"\nAdded for this job: {', '.join(added)}")
        self.stdout.write(f"\nPassed. CV {draft.id}: {draft.file_path}")
