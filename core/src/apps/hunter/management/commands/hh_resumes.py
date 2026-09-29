from django.core.management.base import BaseCommand, CommandError

from apps.cvs.models import Cv
from apps.hunter.browser import open_browser
from apps.hunter.models import ResumeLink
from apps.hunter.sources import hh

BASE = "https://hh.kz"


class Command(BaseCommand):
    help = "List hh.kz résumés and link job-filler CVs to them (--link CV_ID=RESUME_HASH)."

    def add_arguments(self, parser):
        parser.add_argument("--link", action="append", default=[], metavar="CV_ID=RESUME_HASH")
        parser.add_argument("--unlink", action="append", default=[], type=int, metavar="CV_ID")

    def handle(self, *args, **options):
        for cv_id in options["unlink"]:
            ResumeLink.objects.filter(cv_id=cv_id).delete()
        with open_browser(hh.SITE) as context:
            page = context.pages[0] if context.pages else context.new_page()
            resumes = hh.list_resumes(page, BASE)
        by_hash = {resume["hash"]: resume for resume in resumes}
        for pair in options["link"]:
            cv_id, _, resume_hash = pair.partition("=")
            resume = by_hash.get(resume_hash.strip())
            if not cv_id.strip().isdigit() or resume is None:
                raise CommandError(f"Unknown CV or hh résumé in '{pair}'.")
            cv = Cv.objects.filter(pk=int(cv_id)).first()
            if cv is None:
                raise CommandError(f"CV {cv_id} does not exist.")
            ResumeLink.objects.update_or_create(
                cv=cv,
                defaults={"source": hh.SITE, "resume_id": resume["hash"], "title": resume["title"]},
            )
        self.stdout.write("hh.kz résumés:")
        for resume in resumes:
            state = "" if resume["published"] else "  (not published)"
            self.stdout.write(f"  {resume['hash']}  {resume['title']}{state}")
        links = {link.cv_id: link for link in ResumeLink.objects.all()}
        self.stdout.write("job-filler CVs:")
        for cv in Cv.objects.order_by("id"):
            link = links.get(cv.id)
            target = f"-> {link.title}" if link else "-> (not linked)"
            headline = " ".join(cv.raw_text.split())[:60]
            self.stdout.write(f"  {cv.id:>3}  {cv.original_filename[:40]:<40} {headline}  {target}")
