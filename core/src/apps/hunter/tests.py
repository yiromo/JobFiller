import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.cvs.models import Cv
from apps.hunter import evidence, navigator, notify, service, state
from apps.hunter.models import ResumeLink, Vacancy
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

    def test_remote_vacancy_in_another_region_needs_no_relocation(self):
        remote = {"shortVacancy": {"workFormats": [{"workFormatsElement": ["ON_SITE", "REMOTE"]}]}}
        office = {"shortVacancy": {"workFormats": [{"workFormatsElement": ["ON_SITE"]}]}}
        self.assertFalse(hh.parse_status(remote, {"show": True}).needs_relocation)
        self.assertTrue(hh.parse_status(office, {"show": True}).needs_relocation)
        self.assertFalse(hh.parse_status(office, {"show": False}).needs_relocation)

    def test_summary_text_is_empty_when_nothing_happened(self):
        self.assertEqual(notify.summary_text(RunSummary()), "")

    def test_summary_text_lists_applied_and_review(self):
        applied = SimpleNamespace(title="Dev", employer="Acme", url="https://x/1", note="")
        review = SimpleNamespace(title="Ops", employer="B", url="https://x/2", note="captcha")
        text = notify.summary_text(RunSummary(applied=[applied], review=[review]), "logged out")
        self.assertIn("applied to 1", text)
        self.assertIn("Ops — captcha", text)
        self.assertIn("logged out", text)


class AgentStateTests(SimpleTestCase):
    def test_running_agent_is_up_only_while_heartbeat_is_fresh(self):
        now = timezone.now()
        agent = {"phase": "running", "heartbeat_at": (now - timedelta(minutes=2)).isoformat()}
        self.assertTrue(state.is_up(agent, now))
        agent["heartbeat_at"] = (now - timedelta(minutes=30)).isoformat()
        self.assertFalse(state.is_up(agent, now))

    def test_sleeping_agent_is_up_until_its_next_cycle_is_overdue(self):
        now = timezone.now()
        agent = {"phase": "sleeping", "next_cycle_at": (now + timedelta(minutes=50)).isoformat()}
        self.assertTrue(state.is_up(agent, now))
        agent["next_cycle_at"] = (now - timedelta(minutes=30)).isoformat()
        self.assertFalse(state.is_up(agent, now))

    def test_stopped_or_missing_agent_is_down(self):
        self.assertFalse(state.is_up({"phase": "stopped"}))
        self.assertFalse(state.is_up(None))
        self.assertFalse(state.is_up({"phase": "running", "heartbeat_at": "garbage"}))

    def test_repeated_daily_cap_is_not_announced(self):
        summary = RunSummary(daily_cap_reached=True)
        self.assertIn("Daily cap", notify.summary_text(summary))
        self.assertEqual(notify.summary_text(summary, show_cap=False), "")


class FakeAdapter:
    SITE = "hh"

    def __init__(self, status):
        self.status = status
        self.applied = []

    def origin(self, url):
        return "https://astana.hh.kz"

    def response_status(self, page, base, external_id):
        return self.status

    def pause(self, page, low, high):
        pass

    def apply(self, page, url, resume_title, letter, status, notify=None, on_submit=None):
        on_submit()
        self.applied.append(url)
        return True, "Applied on hh.kz."


@override_settings(MIMO_API_KEY="", HUNTER_MAX_APPLIES_PER_DAY=50)
class LinkedCvCase(TestCase):
    def setUp(self):
        self.cv = Cv.objects.create(file="cvs/a.pdf", original_filename="a.pdf")
        self.link = ResumeLink.objects.create(cv=self.cv, resume_id="hash", title="Backend")

    def vacancy(self, external_id, status=Vacancy.Status.READY, cv=True):
        return Vacancy.objects.create(
            source="hh",
            external_id=external_id,
            url=f"https://astana.hh.kz/vacancy/{external_id}",
            title=external_id,
            cv=self.cv if cv else None,
            resume_id="hash",
            match_score=90,
            status=status,
        )


class ApplyReadyTests(LinkedCvCase):
    def run_apply(self, adapter, only=""):
        summary = RunSummary()
        with patch("apps.hunter.service.adapter_for", return_value=adapter):
            service.apply_ready(None, 10, [self.link], lambda line: None, summary, only)
        return summary

    def test_missing_response_info_requeues_and_stops(self):
        first = self.vacancy("1")
        second = self.vacancy("2")
        adapter = FakeAdapter(None)
        self.run_apply(adapter)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, Vacancy.Status.READY)
        self.assertEqual(second.status, Vacancy.Status.READY)
        self.assertEqual(adapter.applied, [])

    def test_vacancy_flag_resends_a_held_vacancy_and_counts_it(self):
        held = self.vacancy("3", status=Vacancy.Status.NEEDS_REVIEW)
        adapter = FakeAdapter(hh.parse_status({"resumes": {"1": {"hash": "hash"}}}))
        summary = self.run_apply(adapter, only="3")
        held.refresh_from_db()
        self.assertEqual(held.status, Vacancy.Status.APPLIED)
        self.assertIsNotNone(held.submitted_at)
        self.assertEqual(len(summary.applied), 1)
        self.assertEqual(state.sent_last_day(), 1)

    def test_rows_without_a_cv_are_never_claimed(self):
        orphan = self.vacancy("4", cv=False)
        self.run_apply(FakeAdapter(None))
        orphan.refresh_from_db()
        self.assertEqual(orphan.status, Vacancy.Status.READY)


class ReconcileTests(LinkedCvCase):
    def run_reconcile(self, adapter):
        summary = RunSummary()
        with patch("apps.hunter.service.adapter_for", return_value=adapter):
            service.reconcile(None, lambda line: None, summary)
        return summary

    def test_held_vacancy_sent_by_hand_becomes_applied_without_using_the_cap(self):
        held = self.vacancy("5", status=Vacancy.Status.NEEDS_REVIEW)
        summary = self.run_reconcile(FakeAdapter(hh.parse_status({"usedResumeIds": ["1"]})))
        held.refresh_from_db()
        self.assertEqual(held.status, Vacancy.Status.APPLIED)
        self.assertEqual(summary.reconciled, [held])
        self.assertEqual(state.sent_last_day(), 0)

    def test_closed_vacancy_is_skipped_and_open_one_stays_held(self):
        held = self.vacancy("6", status=Vacancy.Status.NEEDS_REVIEW)
        self.run_reconcile(FakeAdapter(hh.parse_status({"responseImpossible": True})))
        held.refresh_from_db()
        self.assertEqual(held.status, Vacancy.Status.SKIPPED)
        waiting = self.vacancy("7", status=Vacancy.Status.NEEDS_REVIEW)
        summary = self.run_reconcile(FakeAdapter(hh.parse_status({})))
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, Vacancy.Status.NEEDS_REVIEW)
        self.assertEqual(summary.reconciled, [])


class HunterStatusViewTests(TestCase):
    def test_snapshot_drives_visibility(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(DATA_DIR=Path(directory)),
        ):
            self.assertEqual(self.client.get("/api/v1/hunter/").json(), {"up": False})
            tracker = state.Tracker(apply=True, loop_minutes=60)
            tracker.log("hello")
            body = self.client.get("/api/v1/hunter/").json()
            self.assertTrue(body["up"])
            self.assertEqual(body["agent"]["phase"], "running")
            self.assertTrue(body["agent"]["recent_log"][0].endswith("hello"))
            self.assertIn("counts", body)
            tracker.stopped()
            self.assertFalse(self.client.get("/api/v1/hunter/").json()["up"])


class NavigatorGuardTests(SimpleTestCase):
    def element(self, **fields):
        base = {"ref": "1", "tag": "button", "type": "button", "text": "", "label": "", "group": ""}
        return {**base, **fields}

    def test_consent_and_demographic_answers_are_refused(self):
        consent = self.element(tag="input", type="checkbox", label="Я согласен на обработку")
        self.assertIn("refused", navigator.vet({"action": "check"}, consent, "hh.kz", False))
        gender = self.element(tag="label", text="Female", group="What is your gender?")
        self.assertIn("refused", navigator.vet({"action": "click"}, gender, "hh.kz", False))
        salary = self.element(tag="textarea", label="Желаемая зарплата")
        self.assertEqual(
            navigator.vet({"action": "fill", "value": "x"}, salary, "hh.kz", False), ""
        )

    def test_links_off_the_site_are_refused(self):
        link = self.element(tag="a", href="https://evil.example/login")
        self.assertIn("outside", navigator.vet({"action": "click"}, link, "hh.kz", False))
        inside = self.element(tag="a", href="https://astana.hh.kz/vacancy/1")
        self.assertEqual(navigator.vet({"action": "click"}, inside, "hh.kz", False), "")

    def test_rehearsal_stops_only_at_the_final_submit(self):
        opener = self.element(tag="a", text="Respond", qa="vacancy-response-link-top")
        confirm = self.element(text="Still apply", qa="relocation-warning-confirm", in_form=True)
        send = self.element(type="submit", text="Send application", submit=True, in_form=True)
        click = {"action": "click"}
        self.assertEqual(navigator.vet(click, opener, "hh.kz", True), "")
        self.assertEqual(navigator.vet(click, confirm, "hh.kz", True), "")
        self.assertEqual(navigator.vet(click, send, "hh.kz", True), "rehearsal")
        self.assertEqual(navigator.vet(click, send, "hh.kz", False), "")
        flagged = {"action": "click", "final_submit": True}
        self.assertEqual(navigator.vet(flagged, opener, "hh.kz", True), "rehearsal")

    def test_unknown_or_missing_targets_are_reported(self):
        self.assertIn("unknown", navigator.vet({"action": "hack"}, None, "hh.kz", False))
        self.assertIn("no element", navigator.vet({"action": "click", "ref": 9}, None, "hh", False))
        self.assertEqual(navigator.vet({"action": "done"}, None, "hh.kz", False), "")

    def test_host_of_folds_city_subdomains(self):
        self.assertEqual(navigator.host_of("https://astana.hh.kz/vacancy/1"), "hh.kz")
        self.assertEqual(navigator.host_of("https://hh.kz/"), "hh.kz")

    def test_navigator_needs_a_model_key(self):
        with override_settings(MIMO_API_KEY="", HUNTER_NAVIGATOR="on"):
            self.assertEqual(service.navigator_mode(), "off")
        with override_settings(MIMO_API_KEY="k", HUNTER_NAVIGATOR="Rehearse"):
            self.assertEqual(service.navigator_mode(), "rehearse")
        with override_settings(MIMO_API_KEY="k", HUNTER_NAVIGATOR="maybe"):
            self.assertEqual(service.navigator_mode(), "off")


class EvidenceViewTests(SimpleTestCase):
    def test_serves_only_known_files_from_safe_keys(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(DATA_DIR=Path(directory)),
        ):
            folder = evidence.folder("123")
            folder.mkdir(parents=True)
            (folder / "page.html").write_text("<script>alert(1)</script>")
            (folder / "secret.txt").write_text("no")
            self.assertEqual(evidence.available("123"), ["page.html"])
            response = self.client.get("/api/v1/hunter/evidence/123/page.html")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response["Content-Type"].startswith("text/plain"))
            self.assertIn("sandbox", response["Content-Security-Policy"])
            for url in (
                "/api/v1/hunter/evidence/123/secret.txt",
                "/api/v1/hunter/evidence/..%2F..%2Fbrowser/page.html",
                "/api/v1/hunter/evidence/456/page.html",
            ):
                self.assertEqual(self.client.get(url).status_code, 404, url)
            self.assertIsNone(evidence.folder("../browser"))
