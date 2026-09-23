from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.cvs.models import Cv

from .models import Opportunity
from .service import application_urls, ingest_message
from .telegraph import TelegraphPage, _ArticleParser, application_link


def message(text, *, message_id=123, entities=None, buttons=None):
    return SimpleNamespace(
        id=message_id,
        date=datetime(2026, 9, 24, tzinfo=UTC),
        raw_text=text,
        entities=entities or [],
        buttons=buttons or [],
    )


class OpportunityTests(TestCase):
    def setUp(self):
        self.cv = Cv.objects.create(
            file="cvs/example.pdf",
            original_filename="example.pdf",
            raw_text="Python Django",
        )

    def test_links_include_hidden_entity_and_ignore_telegram_bot(self):
        post = message(
            "Apply via https://t.me/apply_jobs_bot",
            entities=[SimpleNamespace(url="https://jobs.example.com/123")],
        )
        self.assertEqual(application_urls(post), ["https://jobs.example.com/123"])
        self.assertEqual(application_urls(message("https://127.0.0.1/admin/")), [])

    @patch("apps.opportunities.service.best_cv_for_post")
    def test_ingest_is_idempotent_and_ready_jobs_can_be_claimed_once(self, match):
        match.return_value = (self.cv, 91, "Relevant Python experience")
        post = message("Python role https://jobs.example.com/123")
        first = ingest_message(post)[0]
        ingest_message(post)
        self.assertEqual(Opportunity.objects.count(), 1)
        self.assertEqual(first.status, Opportunity.Status.READY)
        client = APIClient()
        claimed = client.post("/api/v1/opportunities/next/")
        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(claimed.json()["cv_id"], self.cv.id)
        self.assertEqual(client.post("/api/v1/opportunities/next/").status_code, 204)
        finished = client.post(
            f"/api/v1/opportunities/{first.id}/",
            {"status": "needs_review", "note": "Site needs login"},
            format="json",
        )
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(Opportunity.objects.get(pk=first.pk).attempt_note, "Site needs login")

    def test_telegram_only_post_is_unactionable(self):
        post = ingest_message(message("Jobs today https://t.me/apply_jobs_bot"))[0]
        self.assertEqual(post.status, Opportunity.Status.UNACTIONABLE)
        self.assertEqual(post.url, "")
        self.assertEqual(post.source_links, ["https://t.me/apply_jobs_bot"])

    def test_stale_claim_requires_review_instead_of_automatic_retry(self):
        item = Opportunity.objects.create(
            message_id=456,
            posted_at=timezone.now(),
            source_text="Job",
            url="https://jobs.example.com/456",
            status=Opportunity.Status.APPLYING,
        )
        Opportunity.objects.filter(pk=item.pk).update(
            updated_at=timezone.now() - timedelta(hours=3)
        )
        self.assertEqual(APIClient().post("/api/v1/opportunities/next/").status_code, 204)
        item.refresh_from_db()
        self.assertEqual(item.status, Opportunity.Status.NEEDS_REVIEW)

    @patch("apps.opportunities.service.best_cv_for_post")
    def test_roundup_does_not_apply_to_an_unrelated_external_link(self, match):
        post = ingest_message(
            message(
                "100% remote jobs from the last 24 hours. All jobs in @apply_jobs_bot "
                "https://example.com/advert"
            )
        )[0]
        self.assertEqual(post.status, Opportunity.Status.NEEDS_REVIEW)
        match.assert_not_called()

    @patch("apps.opportunities.service.rank_jobs")
    @patch("apps.opportunities.service.fetch_page")
    @patch("apps.opportunities.service.select_job_pages")
    @patch("apps.opportunities.service.category_jobs")
    def test_roundup_uses_individual_job_details(
        self, category_jobs, select_job_pages, fetch_page, match
    ):
        job = ("https://graph.org/Python-Engineer-09-23", "Python Engineer")
        category_jobs.return_value = [job]
        select_job_pages.return_value = [job]
        fetch_page.return_value = TelegraphPage(
            "Python Engineer",
            "Python Django backend role at Example Co.",
            [("https://jobs.example.com/apply/123", "Apply now")],
        )
        match.return_value = {job[0]: (self.cv, 91, "Python and Django match")}
        result = ingest_message(
            message(
                "100% remote jobs from the last 24 hours https://graph.org/Back-end-Python-Global-09-23"
            )
        )[0]
        self.assertEqual(result.url, "https://jobs.example.com/apply/123")
        self.assertEqual(result.status, Opportunity.Status.READY)
        self.assertIn("Django backend role", result.source_text)
        match.assert_called_once()

    def test_telegraph_article_parser_extracts_nested_job_links(self):
        parser = _ArticleParser()
        parser.feed(
            '<article><h1>Python jobs<br></h1><p><a href="/Role-09-23">Python <b>Engineer</b></a></p></article>'
        )
        self.assertEqual(parser.links, [("/Role-09-23", "Python Engineer")])
        page = TelegraphPage(
            "Python Engineer", "Role", [("https://jobs.example.com/apply", "Apply now")]
        )
        self.assertEqual(application_link(page), "https://jobs.example.com/apply")
