from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.hunter import notify
from apps.hunter.service import RunSummary, letter_language
from apps.hunter.sources import adapter_for, hh


class HhParsingTests(SimpleTestCase):
    def test_sent_response_counts_as_applied_even_when_flag_is_false(self):
        status = hh.parse_status(
            {
                "alreadyApplied": False,
                "negotiations": {"topicList": [{"id": 1}]},
                "usedResumeIds": ["226043071"],
                "resumes": {"226043071": {"hash": "abc"}},
                "shortVacancy": {"@responseLetterRequired": True},
                "test": {"hasTests": False},
                "letterMaxLength": 10000,
            }
        )
        self.assertTrue(status.already_applied)
        self.assertTrue(status.letter_required)
        self.assertEqual(status.resume_hashes, {"abc"})

    def test_fresh_vacancy_is_not_applied(self):
        status = hh.parse_status(
            {"negotiations": {"topicList": []}, "usedResumeIds": [], "test": {"hasTests": True}}
        )
        self.assertFalse(status.already_applied)
        self.assertTrue(status.has_test)

    def test_page_number_replaces_existing_page_param(self):
        url = hh.with_page_number("https://astana.hh.kz/search/vacancy?text=go&page=4", 2)
        self.assertEqual(url, "https://astana.hh.kz/search/vacancy?text=go&page=2")

    def test_vacancy_id_and_adapter_lookup(self):
        self.assertEqual(
            hh.vacancy_id("https://astana.hh.kz/vacancy/133866105?query=x"), "133866105"
        )
        self.assertIs(adapter_for("https://astana.hh.kz/search/vacancy?text=go"), hh)
        self.assertIsNone(adapter_for("https://example.com/jobs"))

    def test_letter_language_follows_the_posting(self):
        self.assertEqual(letter_language("Ищем Python разработчика в команду"), "Russian")
        self.assertEqual(letter_language("We are hiring a Python developer"), "")


class HunterWorkflowTests(SimpleTestCase):
    def test_homepage_expands_to_recommendations_per_resume(self):
        urls = hh.expand_source(
            "https://astana.hh.kz/?hhtmFromLabel=header&hhtmFrom=vacancy_response",
            ["abc", "abc", "def"],
        )
        self.assertEqual(
            urls,
            [
                "https://astana.hh.kz/search/vacancy?resume=abc",
                "https://astana.hh.kz/search/vacancy?resume=def",
            ],
        )

    def test_search_url_is_kept_as_is(self):
        url = "https://astana.hh.kz/search/vacancy?text=go&area=159"
        self.assertEqual(hh.expand_source(url, ["abc"]), [url])

    def test_relocation_warning_comes_from_the_top_level_payload(self):
        self.assertTrue(hh.parse_status({}, {"show": True}).relocation_warning)
        self.assertFalse(hh.parse_status({}, {"show": False}).relocation_warning)

    def test_summary_text_is_empty_when_nothing_happened(self):
        self.assertEqual(notify.summary_text(RunSummary()), "")

    def test_summary_text_lists_applied_and_review(self):
        applied = SimpleNamespace(title="Dev", employer="Acme", url="https://x/1", note="")
        review = SimpleNamespace(title="Ops", employer="B", url="https://x/2", note="captcha")
        text = notify.summary_text(RunSummary(applied=[applied], review=[review]), "logged out")
        self.assertIn("applied to 1", text)
        self.assertIn("Ops — captcha", text)
        self.assertIn("logged out", text)
