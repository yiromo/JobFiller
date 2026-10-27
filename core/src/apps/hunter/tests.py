import base64
import json
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from agent import cv_reviewer, mimo
from apps.cvs.models import Cv
from apps.hunter import (
    captcha,
    evidence,
    inbox,
    mail,
    navigator,
    notify,
    review,
    service,
    state,
)
from apps.hunter.management.commands import agent_desk
from apps.hunter.models import MailMessage, ResumeLink, Vacancy
from apps.hunter.service import RunSummary, letter_language
from apps.hunter.sources import (
    ADAPTERS,
    adapter_for,
    ats,
    dsml,
    hh,
    indeed,
    linkedin,
    missing_contract,
)
from apps.hunter.sources.base import CaptchaError


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
        applied = SimpleNamespace(
            source="hh", title="Dev", employer="Acme", url="https://x/1", note=""
        )
        review = SimpleNamespace(title="Ops", employer="B", url="https://x/2", note="captcha")
        text = notify.summary_text(RunSummary(applied=[applied], review=[review]), "logged out")
        self.assertIn("Applied to 1", text)
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
    NAME = "hh.kz"
    USES_RESUME_LINKS = True
    SCRIPTED_APPLY = True
    WANTS_LETTER = True
    RECHECK_BATCH = 30
    NAVIGABLE = hh.NAVIGABLE
    HEADED_CAPTCHA = True
    SEND_GAP = (0, 0)
    MAX_SENDS_PER_RUN = 0
    TRY_LATER = ()
    EMPLOYER_BOARDS = False
    DISTINCT_UPLOAD_NAMES = False

    def __init__(self, status, outcome=(True, "Applied on hh.kz.")):
        self.status = status
        self.outcome = outcome
        self.applied = []

    def origin(self, url):
        return "https://astana.hh.kz"

    def response_status(self, page, url):
        return self.status

    def pause(self, page, low, high):
        pass

    def apply(
        self, page, url, resume_title, letter, status, notify=None, on_submit=None, applicant=None
    ):
        self.applicant = applicant
        if isinstance(self.outcome, Exception):
            on_submit()
            raise self.outcome
        if not self.outcome[0]:
            return self.outcome
        on_submit()
        self.applied.append(url)
        return self.outcome


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
    def run_apply(self, adapter, only="", rehearse=False):
        summary = RunSummary()
        with patch("apps.hunter.service.adapter_for", return_value=adapter):
            service.apply_ready(
                None, adapter, 10, [self.link], lambda line: None, summary, only, rehearse=rehearse
            )
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

    def test_the_same_role_at_the_same_employer_is_sent_once(self):
        first = self.vacancy("20")
        second = self.vacancy("21")
        Vacancy.objects.filter(pk__in=[first.pk, second.pk]).update(
            employer="Alpaca", title="Software Engineer - Market Data"
        )
        Vacancy.objects.filter(pk=second.pk).update(match_score=80)
        adapter = FakeAdapter(hh.parse_status({"resumes": {"1": {"hash": "hash"}}}))
        with patch("apps.hunter.service.time.sleep"):
            self.run_apply(adapter)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(adapter.applied, ["https://astana.hh.kz/vacancy/20"])
        self.assertEqual(second.status, Vacancy.Status.SKIPPED)
        self.assertIn("already applied", second.note)

    def test_skip_list_employers_are_skipped_by_whole_word(self):
        aggregator = self.vacancy("30")
        maker = self.vacancy("31")
        Vacancy.objects.filter(pk=aggregator.pk).update(employer="Prolific Academic Ltd")
        Vacancy.objects.filter(pk=maker.pk).update(employer="Hexagon Manufacturing Intelligence")
        adapter = FakeAdapter(hh.parse_status({"resumes": {"1": {"hash": "hash"}}}))
        with patch("apps.hunter.service.time.sleep"):
            self.run_apply(adapter)
        aggregator.refresh_from_db()
        self.assertEqual(aggregator.status, Vacancy.Status.SKIPPED)
        self.assertIn("skip list (Prolific)", aggregator.note)
        self.assertEqual(adapter.applied, ["https://astana.hh.kz/vacancy/31"])

    def test_an_employer_that_rejected_recently_is_skipped_and_others_are_not(self):
        rejected = self.vacancy("40")
        again = self.vacancy("41")
        Vacancy.objects.filter(pk__in=[rejected.pk, again.pk]).update(employer="Prima")
        Vacancy.objects.filter(pk=again.pk).update(employer="2GIS")
        MailMessage.objects.create(
            account="a@example.com",
            uidvalidity=1,
            uid=1,
            kind="rejection",
            employer="prima",
            received_at=timezone.now() - timedelta(days=3),
        )
        MailMessage.objects.create(
            account="a@example.com",
            uidvalidity=1,
            uid=2,
            kind="rejection",
            employer="2GIS",
            received_at=timezone.now() - timedelta(days=45),
        )
        adapter = FakeAdapter(hh.parse_status({"resumes": {"1": {"hash": "hash"}}}))
        with patch("apps.hunter.service.time.sleep"):
            self.run_apply(adapter)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, Vacancy.Status.SKIPPED)
        self.assertIn("sent a rejection on", rejected.note)
        self.assertEqual(adapter.applied, ["https://astana.hh.kz/vacancy/41"])

    def test_referral_targets_rank_employers_and_leave_out_skipped_ones(self):
        for external_id, employer, score in [
            ("50", "Acme", 92),
            ("51", "Acme", 80),
            ("52", "Jobgether", 99),
            ("53", "Globex", 85),
            ("54", "Initech", 60),
        ]:
            row = self.vacancy(external_id)
            Vacancy.objects.filter(pk=row.pk).update(employer=employer, match_score=score)
        targets = service.referral_targets()
        self.assertEqual([item["employer"] for item in targets], ["Acme", "Globex"])
        self.assertEqual(targets[0]["roles"], 2)
        self.assertEqual(targets[0]["score"], 92)

    def test_rows_without_a_cv_are_never_claimed(self):
        orphan = self.vacancy("4", cv=False)
        self.run_apply(FakeAdapter(None))
        orphan.refresh_from_db()
        self.assertEqual(orphan.status, Vacancy.Status.READY)


class ReconcileTests(LinkedCvCase):
    def run_reconcile(self, adapter):
        summary = RunSummary()
        with patch("apps.hunter.service.adapter_for", return_value=adapter):
            service.reconcile(None, adapter, lambda line: None, summary)
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


OFFERED = {"resumes": {"1": {"hash": "hash"}}}


class NavigatorGuardTests(SimpleTestCase):
    def element(self, **fields):
        base = {"ref": "1", "tag": "button", "type": "button", "text": "", "label": "", "group": ""}
        return {**base, **fields}

    def test_consent_and_demographic_answers_are_refused(self):
        consent = self.element(tag="input", type="checkbox", label="Я согласен на обработку")
        self.assertIn("refused", navigator.vet({"action": "check"}, consent, {"hh.kz"}, False))
        gender = self.element(tag="label", text="Female", group="What is your gender?")
        self.assertIn("refused", navigator.vet({"action": "click"}, gender, {"hh.kz"}, False))
        salary = self.element(tag="textarea", label="Желаемая зарплата")
        self.assertEqual(
            navigator.vet({"action": "fill", "value": "x"}, salary, {"hh.kz"}, False), ""
        )

    def test_links_off_the_site_are_refused(self):
        link = self.element(tag="a", href="https://evil.example/login")
        self.assertIn("outside", navigator.vet({"action": "click"}, link, {"hh.kz"}, False))
        inside = self.element(tag="a", href="https://astana.hh.kz/vacancy/1")
        self.assertEqual(navigator.vet({"action": "click"}, inside, {"hh.kz"}, False), "")

    def test_rehearsal_stops_only_at_the_final_submit(self):
        opener = self.element(tag="a", text="Respond", qa="vacancy-response-link-top")
        confirm = self.element(text="Still apply", qa="relocation-warning-confirm", in_form=True)
        send = self.element(type="submit", text="Send application", submit=True, in_form=True)
        click = {"action": "click"}
        self.assertEqual(navigator.vet(click, opener, {"hh.kz"}, True), "")
        self.assertEqual(navigator.vet(click, confirm, {"hh.kz"}, True), "")
        self.assertEqual(navigator.vet(click, send, {"hh.kz"}, True), "rehearsal")
        self.assertEqual(navigator.vet(click, send, {"hh.kz"}, False), "")
        flagged = {"action": "click", "final_submit": True}
        self.assertEqual(navigator.vet(flagged, opener, {"hh.kz"}, True), "rehearsal")

    def test_unknown_or_missing_targets_are_reported(self):
        self.assertIn("unknown", navigator.vet({"action": "hack"}, None, {"hh.kz"}, False))
        self.assertIn(
            "no element", navigator.vet({"action": "click", "ref": 9}, None, {"hh.kz"}, False)
        )
        self.assertEqual(navigator.vet({"action": "done"}, None, {"hh.kz"}, False), "")

    def test_passwords_account_creation_and_uploads_without_a_file_are_refused(self):
        password = self.element(tag="input", type="password", label="Password")
        self.assertIn("password", navigator.vet({"action": "fill"}, password, {"hh.kz"}, False))
        signup = self.element(text="Create account")
        self.assertIn("accounts", navigator.vet({"action": "click"}, signup, {"hh.kz"}, False))
        upload = self.element(tag="input", type="file")
        self.assertIn("no CV", navigator.vet({"action": "upload"}, upload, {"hh.kz"}, False))
        self.assertEqual(navigator.vet({"action": "upload"}, upload, {"hh.kz"}, False, True), "")

    def test_host_of_folds_city_subdomains(self):
        self.assertEqual(navigator.host_of("https://astana.hh.kz/vacancy/1"), "hh.kz")
        self.assertEqual(navigator.host_of("https://hh.kz/"), "hh.kz")

    def test_site_setting_overrides_the_global_navigator_mode(self):
        sites = {"hh": "", "linkedin": "rehearse"}
        with override_settings(
            MIMO_API_KEY="k", HUNTER_NAVIGATOR="on", HUNTER_NAVIGATOR_BY_SITE=sites
        ):
            self.assertEqual(service.navigator_mode("hh"), "on")
            self.assertEqual(service.navigator_mode("linkedin"), "rehearse")
            self.assertEqual(service.navigator_mode(), "on")

    def test_every_adapter_meets_the_contract(self):
        for adapter in ADAPTERS:
            self.assertEqual(missing_contract(adapter), [], adapter.SITE)

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


@override_settings(MIMO_API_KEY="key", HUNTER_NAVIGATOR="on", HUNTER_MAX_APPLIES_PER_DAY=50)
class NavigatorRoutingTests(LinkedCvCase):
    def run_apply(self, adapter, navigate_result, only="", rehearse=False):
        summary = RunSummary()
        with (
            patch("apps.hunter.service.adapter_for", return_value=adapter),
            patch("apps.hunter.service.navigate", return_value=navigate_result) as navigate,
            patch("apps.hunter.service.evidence.capture"),
            patch("apps.hunter.service.cover_letter.generate", return_value="Letter"),
        ):
            service.apply_ready(
                None, adapter, 10, [self.link], lambda line: None, summary, only, rehearse=rehearse
            )
        return navigate

    def test_scripted_failure_that_sent_nothing_is_handed_to_the_navigator(self):
        vacancy = self.vacancy("8")
        adapter = FakeAdapter(
            hh.parse_status(OFFERED), outcome=(False, "The response form did not open (x).")
        )
        navigate = self.run_apply(adapter, (True, "Applied on hh.kz by the navigator."))
        vacancy.refresh_from_db()
        navigate.assert_called_once()
        self.assertFalse(navigate.call_args.args[7])
        self.assertEqual(vacancy.status, Vacancy.Status.APPLIED)

    def test_policy_holds_are_not_handed_over(self):
        vacancy = self.vacancy("9")
        adapter = FakeAdapter(
            hh.parse_status(OFFERED),
            outcome=(False, "hh.kz asks to confirm applying from another region to an office job."),
        )
        navigate = self.run_apply(adapter, (True, "x"))
        vacancy.refresh_from_db()
        navigate.assert_not_called()
        self.assertEqual(vacancy.status, Vacancy.Status.NEEDS_REVIEW)
        self.assertEqual(
            set(adapter.applicant), {"name", "email", "phone", "city", "cv_path", "linkedin"}
        )

    def test_questionnaire_goes_straight_to_the_navigator(self):
        self.vacancy("10")
        status = hh.parse_status({**OFFERED, "test": {"hasTests": True}})
        adapter = FakeAdapter(status)
        navigate = self.run_apply(adapter, (False, "Navigator stuck: x"))
        navigate.assert_called_once()
        self.assertEqual(adapter.applied, [])

    def test_rehearsal_restores_the_row_and_sends_nothing(self):
        vacancy = self.vacancy("11", status=Vacancy.Status.NEEDS_REVIEW)
        navigate = self.run_apply(
            FakeAdapter(hh.parse_status(OFFERED)),
            (False, "Rehearsal reached the final submit: Send"),
            only="11",
            rehearse=True,
        )
        vacancy.refresh_from_db()
        self.assertTrue(navigate.call_args.args[7])
        self.assertEqual(vacancy.status, Vacancy.Status.NEEDS_REVIEW)
        self.assertIsNone(vacancy.submitted_at)

    def test_rehearsed_rows_are_sent_once_the_site_is_switched_on(self):
        held = self.vacancy("13", status=Vacancy.Status.NEEDS_REVIEW)
        Vacancy.objects.filter(pk=held.pk).update(note="Rehearsal reached the final submit: Send")
        other = self.vacancy("14", status=Vacancy.Status.NEEDS_REVIEW)
        adapter = FakeAdapter(hh.parse_status(OFFERED))
        self.run_apply(adapter, (True, "Applied"))
        held.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(adapter.applied, ["https://astana.hh.kz/vacancy/13"])
        self.assertEqual(other.status, Vacancy.Status.NEEDS_REVIEW)

    def test_vacancy_flag_sends_for_real_while_the_service_rehearses(self):
        self.vacancy("12", status=Vacancy.Status.NEEDS_REVIEW)
        status = hh.parse_status({**OFFERED, "test": {"hasTests": True}})
        with override_settings(HUNTER_NAVIGATOR="rehearse"):
            navigate = self.run_apply(FakeAdapter(status), (True, "Applied"), only="12")
        self.assertFalse(navigate.call_args.args[7])


class LinkedInAndIndeedParsingTests(SimpleTestCase):
    def test_linkedin_search_drops_the_open_job_and_pages_by_25(self):
        url = "https://www.linkedin.com/jobs/search-results/?currentJobId=1&keywords=go&start=50"
        search = linkedin.expand_source(url, [])[0]
        self.assertEqual(search, "https://www.linkedin.com/jobs/search-results/?keywords=go")
        self.assertTrue(linkedin.with_page_number(search, 2).endswith("keywords=go&start=50"))
        self.assertEqual(
            linkedin.vacancy_id("https://www.linkedin.com/jobs/view/4471778435/"), "4471778435"
        )
        self.assertIs(adapter_for(url), linkedin)

    def test_linkedin_applied_and_closed_markers(self):
        self.assertTrue(linkedin.APPLIED_RE.search("Applied 3 days ago · See application"))
        self.assertTrue(linkedin.APPLIED_RE.search("Application submitted"))
        self.assertFalse(linkedin.APPLIED_RE.search("Over 100 people clicked apply"))
        self.assertTrue(linkedin.CLOSED_RE.search("No longer accepting applications"))

    def test_indeed_job_url_keeps_the_search_and_selects_the_job(self):
        url = "https://www.indeed.com/jobs?q=backend&l=Remote&start=10&vjk=abc"
        search = indeed.expand_source(url, [])[0]
        self.assertEqual(search, "https://www.indeed.com/jobs?q=backend&l=Remote")
        self.assertEqual(
            indeed.job_url(search, "7e9d"),
            "https://www.indeed.com/jobs?q=backend&l=Remote&vjk=7e9d",
        )
        self.assertIs(adapter_for(url), indeed)
        self.assertTrue(indeed.APPLIED_RE.search("You applied to this job"))
        self.assertTrue(indeed.CLOSED_RE.search("This job has expired on Indeed"))


class EligibilityGuardTests(SimpleTestCase):
    def test_visa_questions_need_facts(self):
        radio = {
            "ref": "1",
            "tag": "input",
            "type": "radio",
            "text": "Yes",
            "label": "Yes",
            "group": "Will you now or in the future require visa sponsorship?",
        }
        self.assertIn("HUNTER_FACTS", navigator.vet({"action": "click"}, radio, {"x.com"}, False))
        self.assertEqual(
            navigator.vet({"action": "click"}, radio, {"x.com"}, False, has_facts=True), ""
        )


class ExternalApplyTests(SimpleTestCase):
    def test_leaving_the_site_needs_an_external_hop_and_sign_in_is_refused(self):
        link = {
            "ref": "1",
            "tag": "a",
            "text": "Apply",
            "label": "",
            "group": "",
            "href": "https://jobs.lever.co/acme/1",
        }
        self.assertIn("outside", navigator.vet({"action": "click"}, link, {"linkedin.com"}, False))
        self.assertEqual(
            navigator.vet({"action": "click"}, link, {"linkedin.com"}, False, may_leave=True), ""
        )
        sign_in = {
            "ref": "2",
            "tag": "button",
            "text": "Sign in to apply",
            "label": "",
            "group": "",
        }
        self.assertIn("accounts", navigator.vet({"action": "click"}, sign_in, {"lever.co"}, False))

    def test_confirmation_phrases(self):
        for text in (
            "Thank you for applying to Acme!",
            "Your application has been submitted.",
            "We have received your application",
            "Application received",
        ):
            self.assertTrue(navigator.CONFIRMED_RE.search(text), text)
        self.assertFalse(navigator.CONFIRMED_RE.search("Submit your application"))

    def test_external_mode_parsing(self):
        with override_settings(MIMO_API_KEY="k", HUNTER_EXTERNAL_APPLY="True"):
            self.assertEqual(service.external_mode(), "on")
        with override_settings(MIMO_API_KEY="k", HUNTER_EXTERNAL_APPLY="rehearse"):
            self.assertEqual(service.external_mode(), "rehearse")
        with override_settings(MIMO_API_KEY="", HUNTER_EXTERNAL_APPLY="on"):
            self.assertEqual(service.external_mode(), "off")


@override_settings(MIMO_API_KEY="key", HUNTER_NAVIGATOR="on", HUNTER_MAX_APPLIES_PER_DAY=50)
class ExternalRoutingTests(LinkedCvCase):
    def run_external(self, mode):
        vacancy = self.vacancy(f"x{mode}")
        status = hh.parse_status(OFFERED)
        status.external_apply = True
        adapter = FakeAdapter(status)
        with (
            override_settings(HUNTER_EXTERNAL_APPLY=mode),
            patch("apps.hunter.service.navigate", return_value=(False, "Navigator stuck")) as nav,
            patch("apps.hunter.service.evidence.capture"),
            patch("apps.hunter.service.cover_letter.generate", return_value="Letter"),
        ):
            service.apply_ready(None, adapter, 10, [self.link], lambda line: None, RunSummary())
        vacancy.refresh_from_db()
        return vacancy, nav, adapter

    def test_external_jobs_wait_while_external_applying_is_off(self):
        vacancy, nav, adapter = self.run_external("off")
        nav.assert_not_called()
        self.assertEqual(adapter.applied, [])
        self.assertEqual(vacancy.status, Vacancy.Status.NEEDS_REVIEW)

    def test_external_rehearsal_never_sends(self):
        _, nav, adapter = self.run_external("rehearse")
        nav.assert_called_once()
        self.assertTrue(nav.call_args.args[7])
        self.assertEqual(adapter.applied, [])


class PrivacyAndEeoRuleTests(SimpleTestCase):
    def box(self, text, group=""):
        return {
            "ref": "1",
            "tag": "input",
            "type": "checkbox",
            "text": "",
            "label": text,
            "group": group,
        }

    def test_privacy_notice_acknowledgments_are_allowed_but_not_certifications(self):
        allowed = self.box("I acknowledge receipt of the Applicant Privacy Notice.")
        self.assertEqual(navigator.vet({"action": "check"}, allowed, {"x.com"}, False), "")
        data = self.box("Я даю согласие на обработку персональных данных")
        self.assertEqual(navigator.vet({"action": "check"}, data, {"hh.kz"}, False), "")
        certify = self.box(
            "I certify that the information in this application is true and complete"
        )
        self.assertIn("refused", navigator.vet({"action": "check"}, certify, {"x.com"}, False))
        bare_terms = self.box("Agree", group="By applying you accept our Terms of Service. Agree")
        self.assertIn("refused", navigator.vet({"action": "check"}, bare_terms, {"x.com"}, False))
        bare_privacy = self.box("Agree", group="I have read the Applicant Privacy Notice. Agree")
        self.assertEqual(navigator.vet({"action": "check"}, bare_privacy, {"x.com"}, False), "")
        bare_other = self.box("Agree", group="Agree")
        self.assertIn("refused", navigator.vet({"action": "check"}, bare_other, {"x.com"}, False))
        terms = self.box("I agree to the Terms and Conditions")
        self.assertIn("refused", navigator.vet({"action": "check"}, terms, {"x.com"}, False))

    def test_eeo_options_must_match_the_saved_answer(self):
        eeo = [{"match": "gender", "answer": "Decline to self-identify"}]
        group = "What is your gender? Male Female Decline to self-identify"
        decline = {
            "ref": "1",
            "tag": "div",
            "role": "option",
            "text": "Decline To Self Identify",
            "label": "",
            "group": group,
        }
        female = {**decline, "text": "Female"}
        click = {"action": "click"}
        self.assertEqual(navigator.vet(click, decline, {"x.com"}, False, eeo=eeo), "")
        self.assertIn("does not match", navigator.vet(click, female, {"x.com"}, False, eeo=eeo))
        veteran = {**decline, "text": "I am not a veteran", "group": "Veteran status"}
        self.assertIn("saved EEO", navigator.vet(click, veteran, {"x.com"}, False, eeo=eeo))


class EeoInboxViewTests(SimpleTestCase):
    def test_answers_round_trip_through_the_inbox(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(DATA_DIR=Path(directory)),
        ):
            self.assertEqual(self.client.get("/api/v1/hunter/eeo/").json(), {"answers": []})
            body = {
                "answers": [{"match": "gender", "answer": "Decline"}, {"match": "", "answer": "x"}]
            }
            response = self.client.put("/api/v1/hunter/eeo/", body, content_type="application/json")
            self.assertEqual(response.json()["answers"], [{"match": "gender", "answer": "Decline"}])
            self.assertEqual(inbox.answered_eeo(), [{"match": "gender", "answer": "Decline"}])
            bad = self.client.put(
                "/api/v1/hunter/eeo/", {"answers": "nope"}, content_type="application/json"
            )
            self.assertEqual(bad.status_code, 400)


class LetterSizeInboxTests(SimpleTestCase):
    def test_size_round_trips_and_rejects_unknown_values(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(DATA_DIR=Path(directory)),
        ):
            self.assertEqual(self.client.get("/api/v1/hunter/letter/").json(), {"size": "medium"})
            response = self.client.put(
                "/api/v1/hunter/letter/", {"size": "short"}, content_type="application/json"
            )
            self.assertEqual(response.json(), {"size": "short"})
            self.assertEqual(inbox.read_letter_size(), "short")
            bad = self.client.put(
                "/api/v1/hunter/letter/", {"size": "huge"}, content_type="application/json"
            )
            self.assertEqual(bad.status_code, 400)
            self.assertEqual(inbox.read_letter_size(), "short")

    def test_off_still_writes_a_very_short_letter_when_one_is_required(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(DATA_DIR=Path(directory)),
        ):
            inbox.write_letter_size("off")
            self.assertEqual(service.letter_size(SimpleNamespace(letter_required=False)), "off")
            self.assertEqual(
                service.letter_size(SimpleNamespace(letter_required=True)), "very_short"
            )


class DsmlAdapterTests(SimpleTestCase):
    def test_job_urls_with_a_language_prefix_resolve_to_one_id(self):
        uuid = "22d5af9c-fe3c-4c5f-8335-f7d69590581b"
        self.assertTrue(dsml.handles("https://dsml.kz/jobs"))
        self.assertFalse(dsml.handles("https://notdsml.kz/jobs"))
        for path in (f"/jobs/{uuid}", f"/ru/jobs/{uuid}", f"/kk/jobs/{uuid}"):
            self.assertEqual(dsml.vacancy_id(f"https://dsml.kz{path}#apply"), uuid)
        self.assertIsNone(dsml.vacancy_id("https://dsml.kz/jobs"))

    def test_heading_splits_into_title_and_employer(self):
        self.assertEqual(
            dsml.split_heading("Data Scientist/Senior at Institute of AI (ISSAI)"),
            ("Data Scientist/Senior", "Institute of AI (ISSAI)"),
        )
        self.assertEqual(dsml.split_heading("AI Engineer"), ("AI Engineer", ""))

    def test_applicant_details_come_from_the_cv_and_settings(self):
        self.assertEqual(
            dsml.linkedin_url("see linkedin.com/in/jane-doe for more"),
            "https://linkedin.com/in/jane-doe",
        )
        self.assertEqual(dsml.linkedin_url("no profile"), "")
        note = dsml.contact_note({"phone": "+7 700", "city": "Astana, Kazakhstan"})
        self.assertEqual(note, "Phone: +7 700. Based in Astana, Kazakhstan (UTC+5)")

    def test_scripted_apply_refuses_without_a_cv_file_or_email(self):
        status = SimpleNamespace(letter_max_length=1200)
        self.assertIn("no stored file", dsml.apply(None, "", "", "", status, applicant={})[1])
        missing_email = {"cv_path": "/x.pdf", "email": ""}
        self.assertIn("no email", dsml.apply(None, "", "", "", status, applicant=missing_email)[1])

    def test_confirmation_accepts_site_and_generic_success_phrases(self):
        self.assertEqual(
            dsml.confirmation("Application sent to the hiring contact"), "Application sent"
        )
        self.assertTrue(dsml.confirmation("Thank you for your application!"))
        self.assertEqual(dsml.confirmation("Please add an email or Telegram"), "")


@override_settings(MIMO_API_KEY="key", HUNTER_MIN_SCORE=75, HUNTER_BROAD_MIN_SCORE=60)
class ApplyScopeTests(LinkedCvCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.data = override_settings(DATA_DIR=Path(self.directory.name))
        self.data.enable()

    def tearDown(self):
        self.data.disable()
        self.directory.cleanup()

    def test_scope_round_trips_and_sets_the_threshold(self):
        self.assertEqual(self.client.get("/api/v1/hunter/scope/").json(), {"scope": "broad"})
        self.assertEqual(inbox.min_score(), 60)
        for scope, threshold in (("relevant", 75), ("all", 0)):
            response = self.client.put(
                "/api/v1/hunter/scope/", {"scope": scope}, content_type="application/json"
            )
            self.assertEqual(response.json(), {"scope": scope})
            self.assertEqual(inbox.min_score(), threshold)
        bad = self.client.put(
            "/api/v1/hunter/scope/", {"scope": "every"}, content_type="application/json"
        )
        self.assertEqual(bad.status_code, 400)

    def test_unsent_rows_follow_the_threshold_both_ways(self):
        held = self.vacancy("30", status=Vacancy.Status.BELOW_THRESHOLD)
        Vacancy.objects.filter(pk=held.pk).update(match_score=65)
        sent = self.vacancy("31", status=Vacancy.Status.BELOW_THRESHOLD)
        Vacancy.objects.filter(pk=sent.pk).update(match_score=65, submitted_at=timezone.now())
        service.apply_scope_threshold()
        held.refresh_from_db()
        sent.refresh_from_db()
        self.assertEqual(held.status, Vacancy.Status.READY)
        self.assertEqual(sent.status, Vacancy.Status.BELOW_THRESHOLD)
        inbox.write_apply_scope("relevant")
        service.apply_scope_threshold()
        held.refresh_from_db()
        self.assertEqual(held.status, Vacancy.Status.BELOW_THRESHOLD)

    def test_apply_to_all_falls_back_to_a_cv_only_when_scoring_answered(self):
        inbox.write_apply_scope("all")
        poor = self.vacancy("32", status=Vacancy.Status.BELOW_THRESHOLD, cv=False)
        failed = self.vacancy("33", status=Vacancy.Status.BELOW_THRESHOLD, cv=False)
        ranked = {str(poor.id): (None, None, "Unrelated role.")}
        with patch("apps.hunter.service.rank_jobs", return_value=ranked):
            service.score_vacancies([poor, failed], [self.link])
        poor.refresh_from_db()
        failed.refresh_from_db()
        self.assertEqual((poor.cv_id, poor.match_score, poor.status), (self.cv.id, 0, "ready"))
        self.assertIsNone(failed.cv_id)
        self.assertEqual(failed.status, Vacancy.Status.BELOW_THRESHOLD)

    def tailoring_case(self, score=65, uses_links=False, external_id="34"):
        vacancy = self.vacancy(external_id)
        Vacancy.objects.filter(pk=vacancy.pk).update(match_score=score)
        vacancy.refresh_from_db()
        return vacancy, SimpleNamespace(USES_RESUME_LINKS=uses_links)

    def test_tailoring_runs_only_for_scope_matches_on_upload_sites(self):
        vacancy, adapter = self.tailoring_case()
        self.assertTrue(service.needs_tailoring(adapter, vacancy))
        self.assertFalse(service.needs_tailoring(SimpleNamespace(USES_RESUME_LINKS=True), vacancy))
        strong, _ = self.tailoring_case(score=80, external_id="35")
        self.assertFalse(service.needs_tailoring(adapter, strong))
        unlinked = Cv.objects.create(file="cvs/b.pdf", original_filename="Tailored b.pdf")
        vacancy.cv = unlinked
        self.assertFalse(service.needs_tailoring(adapter, vacancy))

    def test_a_tailored_cv_that_adds_skills_is_discarded(self):
        vacancy, _ = self.tailoring_case()
        tailored = Cv.objects.create(file="cvs/t.pdf", original_filename="Tailored.pdf")
        cv_service = SimpleNamespace(
            generate_from=lambda *args, **kwargs: (tailored, ["Kubernetes"], []),
            delete=lambda cv_id: Cv.objects.filter(pk=cv_id).delete(),
        )
        with patch("apps.hunter.service.CvsContainer.cv_service", return_value=cv_service):
            service.tailor_cv(vacancy, lambda line: None)
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.cv_id, self.cv.id)
        self.assertFalse(Cv.objects.filter(pk=tailored.pk).exists())

    def test_an_accepted_tailored_cv_replaces_the_vacancy_cv(self):
        vacancy, _ = self.tailoring_case()
        tailored = Cv.objects.create(file="cvs/t.pdf", original_filename="Tailored.pdf")
        cv_service = SimpleNamespace(
            generate_from=lambda *args, **kwargs: (tailored, [], ["Wording not found"])
        )
        with patch("apps.hunter.service.CvsContainer.cv_service", return_value=cv_service):
            service.tailor_cv(vacancy, lambda line: None)
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.cv_id, tailored.id)
        self.assertIn("Tailored CV: Tailored.pdf (from a.pdf)", vacancy.match_reason)

    def test_linkedin_gets_the_cv_id_only_when_another_cv_shares_its_name(self):
        linkedin_site = SimpleNamespace(DISTINCT_UPLOAD_NAMES=True)
        first = Cv.objects.create(
            file="cvs/x1/CV_AI_Engineer.pdf", original_filename="CV_AI_Engineer.pdf"
        )
        self.assertEqual(service.upload_name_for(linkedin_site, first), "")
        second = Cv.objects.create(
            file="cvs/x2/CV_AI_Engineer.pdf", original_filename="CV_AI_Engineer.pdf"
        )
        self.assertEqual(
            service.upload_name_for(linkedin_site, second), f"CV_AI_Engineer_{second.id}.pdf"
        )
        self.assertEqual(
            service.upload_name_for(SimpleNamespace(DISTINCT_UPLOAD_NAMES=False), second), ""
        )

    def test_the_navigator_is_told_to_upload_a_tailored_cv(self):
        vacancy, _ = self.tailoring_case()
        self.assertEqual(service.tailored_note(vacancy), "")
        vacancy.cv = Cv.objects.create(file="cvs/t.pdf", original_filename="Tailored.pdf")
        self.assertIn("replace any preselected résumé", service.tailored_note(vacancy))

    def test_a_closed_posting_is_skipped_without_applying(self):
        vacancy, _ = self.tailoring_case(score=90, external_id="36")
        adapter = FakeAdapter(
            SimpleNamespace(impossible=True, already_applied=False, resume_hashes={"hash"})
        )
        result = service.apply_one(
            None, adapter, vacancy, {}, lambda line: None, RunSummary(), False
        )
        vacancy.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(vacancy.status, Vacancy.Status.SKIPPED)
        self.assertEqual(adapter.applied, [])


class AgentDeskTests(LinkedCvCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.data = override_settings(DATA_DIR=Path(self.directory.name))
        self.data.enable()

    def tearDown(self):
        self.data.disable()
        self.directory.cleanup()

    def held(self, external_id, note, source="hh", submitted=False):
        vacancy = self.vacancy(external_id, status=Vacancy.Status.NEEDS_REVIEW)
        Vacancy.objects.filter(pk=vacancy.pk).update(
            note=note, source=source, submitted_at=timezone.now() if submitted else None
        )
        vacancy.refresh_from_db()
        return vacancy

    def trace(self, vacancy, steps):
        folder = evidence.folder(evidence.key_for(vacancy))
        folder.mkdir(parents=True)
        (folder / "trace.json").write_text(json.dumps(steps))

    def test_holds_are_sorted_by_what_the_user_has_to_do(self):
        captcha = self.held(
            "40", "hh.kz asked for a captcha before sending; nothing was submitted."
        )
        unsure = self.held(
            "41",
            "Navigator done: ok. LinkedIn does not report the response; check it before resending.",
            source="linkedin",
        )
        wall = self.held(
            "42", "Navigator stuck: a 'Create your free account' wall.", source="linkedin"
        )
        legal = self.held("43", "Navigator stuck: cannot go on.", source="linkedin")
        self.trace(
            legal,
            [
                {
                    "action": "click",
                    "result": "refused: legal consent and attestation boxes are "
                    "the candidate's own click",
                },
                {"action": "stuck", "result": ""},
            ],
        )
        stuck = self.held("44", "Navigator stuck: No result after 60 steps.", source="linkedin")
        office = self.held("45", "Office job in another region; hh.kz warns about relocation.")
        kinds = [review.kind_of(v) for v in (captcha, unsure, wall, legal, stuck, office)]
        self.assertEqual(
            kinds,
            [
                review.CAPTCHA,
                review.UNCONFIRMED,
                review.ACCOUNT,
                review.QUESTION,
                review.STUCK,
                review.OTHER,
            ],
        )

    def test_resolving_moves_only_rows_still_held(self):
        vacancy = self.held("50", "Navigator stuck: No result after 60 steps.")
        self.assertEqual(review.resolve(vacancy.pk, review.APPLIED), "")
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.status, Vacancy.Status.APPLIED)
        self.assertIsNotNone(vacancy.applied_at)
        self.assertIn("no longer waiting", review.resolve(vacancy.pk, review.SKIPPED))
        other = self.held("51", "Navigator stuck: No result after 60 steps.")
        self.assertEqual(review.resolve(other.pk, review.SKIPPED), "")
        other.refresh_from_db()
        self.assertEqual(other.status, Vacancy.Status.SKIPPED)

    def test_retry_after_submit_needs_the_user_to_say_it_was_not_sent(self):
        unsure = self.held("60", "Navigator stuck: x check it before resending.", submitted=True)
        self.assertIn("confirm it was not sent", review.resolve(unsure.pk, review.RETRY))
        self.assertEqual(review.resolve(unsure.pk, review.RETRY, not_sent=True), "")
        unsure.refresh_from_db()
        self.assertEqual(unsure.status, Vacancy.Status.READY)
        self.assertIsNone(unsure.submitted_at)
        self.assertEqual(unsure.note, "")
        captcha = self.held(
            "61", "hh.kz asked for a captcha before sending; nothing was submitted.", submitted=True
        )
        self.assertEqual(review.resolve(captcha.pk, review.RETRY), "")

    def test_listing_marks_only_hh_captchas_as_sendable(self):
        self.held("70", "hh.kz asked for a captcha before sending; nothing was submitted.")
        self.held(
            "71",
            "LinkedIn asked for a captcha before sending; nothing was submitted.",
            source="linkedin",
        )
        rows = {row["external_id"]: row for row in agent_desk.listing()["held"]}
        self.assertTrue(rows["70"]["send_visible"])
        self.assertFalse(rows["71"]["send_visible"])
        self.assertEqual(rows["71"]["kind"], review.CAPTCHA)

    def test_logged_out_sites_come_from_the_agent_log(self):
        line = "2026-10-05 18:51:34 UTC Indeed: The Indeed profile is not logged in; run it."
        agent = {"recent_log": [line], "last_error": line[24:]}
        self.assertEqual(agent_desk.logged_out(agent), ["indeed"])
        self.assertEqual(agent_desk.logged_out({}), [])
        session = settings.DATA_DIR / "browser" / "indeed" / "session.json"
        session.parent.mkdir(parents=True)
        later = datetime(2026, 10, 5, 19, 0, tzinfo=UTC).timestamp()
        session.write_text(json.dumps({"saved_at": later}))
        self.assertEqual(agent_desk.logged_out(agent), [])


class DesktopNotifyTests(SimpleTestCase):
    def test_title_counts_sent_and_held(self):
        sent = SimpleNamespace(title="Dev", employer="Acme")
        held = SimpleNamespace(title="Ops", employer="B")
        title, body = notify.desktop_text(RunSummary(applied=[sent], review=[held, held]))
        self.assertEqual(title, "Sent 1 · 2 need you")
        self.assertIn("✓ Dev — Acme", body)
        self.assertEqual(notify.desktop_text(RunSummary()), ("", ""))

    def test_long_runs_are_cut_to_a_few_lines(self):
        jobs = [SimpleNamespace(title=f"Job {n}", employer="E") for n in range(9)]
        _, body = notify.desktop_text(RunSummary(applied=jobs))
        self.assertEqual(len(body.splitlines()), notify.DESKTOP_LINES)
        self.assertIn("and 5 more", body)

    @override_settings(HUNTER_NOTIFY_DESKTOP=True, HUNTER_NOTIFY_TELEGRAM=False)
    def test_publish_calls_notify_send_with_the_app_entry(self):
        sent = SimpleNamespace(title="Dev", employer="Acme")
        with (
            patch("apps.hunter.notify.shutil.which", return_value="/usr/bin/notify-send"),
            patch("apps.hunter.notify.subprocess.run") as run,
        ):
            self.assertEqual(notify.publish(RunSummary(applied=[sent])), ["the desktop"])
        argv = run.call_args.args[0]
        self.assertIn(f"--hint=string:desktop-entry:{notify.APP_ID}", argv)
        self.assertIn("Sent 1", argv)

    @override_settings(HUNTER_NOTIFY_DESKTOP=False, HUNTER_NOTIFY_TELEGRAM=False)
    def test_nothing_is_sent_when_both_channels_are_off(self):
        with patch("apps.hunter.notify.subprocess.run") as run:
            self.assertEqual(
                notify.publish(RunSummary(applied=[SimpleNamespace(title="Dev", employer="Acme")])),
                [],
            )
        run.assert_not_called()


class CaptchaHelpTests(LinkedCvCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.data = override_settings(DATA_DIR=Path(self.directory.name))
        self.data.enable()
        self.status = hh.parse_status({"resumes": {"1": {"hash": "hash"}}})

    def tearDown(self):
        self.data.disable()
        self.directory.cleanup()

    def test_a_captcha_hold_names_the_vacancy_and_is_not_counted_as_sent(self):
        vacancy = self.vacancy("80")
        adapter = FakeAdapter(self.status, CaptchaError("hh.kz asked for a captcha on submit."))
        with self.assertRaises(CaptchaError) as caught:
            service.apply_ready(None, adapter, 10, [self.link], lambda line: None, RunSummary())
        vacancy.refresh_from_db()
        self.assertEqual(caught.exception.vacancy.pk, vacancy.pk)
        self.assertEqual(vacancy.status, Vacancy.Status.NEEDS_REVIEW)
        self.assertIsNone(vacancy.submitted_at)
        self.assertIn(review.CAPTCHA_NOTE, vacancy.note)
        self.assertEqual(state.sent_last_day(), 0)

    def run_once_with(self, error, answered):
        adapter = FakeAdapter(self.status)
        error.vacancy = self.vacancy("81", status=Vacancy.Status.NEEDS_REVIEW)
        with (
            patch("apps.hunter.service.site_groups", return_value=[(adapter, ["u"])]),
            patch("apps.hunter.service.run_site", side_effect=error),
            patch("apps.hunter.service.captcha.ask_to_solve", return_value=answered) as ask,
            patch("apps.hunter.service.assisted_apply") as assisted,
            patch("apps.hunter.service.retry_paused"),
        ):
            try:
                service.run_once(apply=True, limit=5, max_pages=1, log=lambda line: None)
                failed = None
            except RuntimeError as raised:
                failed = raised
        return ask, assisted, failed

    def test_an_answered_ask_opens_the_assisted_send(self):
        ask, assisted, failed = self.run_once_with(CaptchaError("captcha"), answered=True)
        ask.assert_called_once()
        assisted.assert_called_once()
        self.assertIsNone(failed)
        self.assertIsNone(captcha.cooling_until("hh"))

    def test_an_unanswered_ask_pauses_the_site(self):
        _, assisted, failed = self.run_once_with(CaptchaError("captcha"), answered=False)
        assisted.assert_not_called()
        self.assertIsNotNone(failed)
        self.assertIsNotNone(captcha.cooling_until("hh"))

    def test_a_captcha_on_an_employer_page_does_not_pause_the_site(self):
        error = CaptchaError("captcha")
        error.vacancy = self.vacancy("84", status=Vacancy.Status.NEEDS_REVIEW)
        adapter = FakeAdapter(self.status)
        adapter.HEADED_CAPTCHA = False
        with (
            patch("apps.hunter.service.site_groups", return_value=[(adapter, ["u"])]),
            patch("apps.hunter.service.run_site", side_effect=error),
            patch("apps.hunter.service.captcha.ask_to_solve") as ask,
            self.assertRaises(RuntimeError),
        ):
            service.run_once(apply=True, limit=5, max_pages=1, log=lambda line: None)
        ask.assert_not_called()
        self.assertIsNone(captcha.cooling_until("hh"))

    def assisted(self, adapter, held, summary):
        browser = MagicMock()
        browser.__enter__.return_value.pages = [MagicMock()]
        adapter.is_logged_in = lambda page: True
        with patch("apps.hunter.service.open_browser", return_value=browser) as opened:
            service.assisted_apply(adapter, [self.link], held, 3, lambda line: None, summary)
        self.assertEqual(opened.call_args.kwargs, {"headless": False})

    def test_assisted_send_clears_the_hold_and_keeps_going(self):
        held = self.vacancy("85", status=Vacancy.Status.NEEDS_REVIEW)
        Vacancy.objects.filter(pk=held.pk).update(match_score=95)
        for number in ("86", "87", "88"):
            self.vacancy(number)
        captcha.start_cooldown("hh")
        summary = RunSummary(review=[held])
        adapter = FakeAdapter(self.status)
        with patch("apps.hunter.service.time.sleep"):
            self.assisted(adapter, held, summary)
        held.refresh_from_db()
        self.assertEqual(held.status, Vacancy.Status.APPLIED)
        self.assertNotIn(held.pk, [v.pk for v in summary.review])
        self.assertIsNone(captcha.cooling_until("hh"))
        self.assertEqual(len(adapter.applied), 3)
        self.assertEqual(adapter.applied[0], held.url)

    def test_an_unsolved_assisted_send_raises_for_the_pause(self):
        held = self.vacancy("89", status=Vacancy.Status.NEEDS_REVIEW)
        adapter = FakeAdapter(self.status, CaptchaError("The captcha was not solved."))
        with self.assertRaises(CaptchaError):
            self.assisted(adapter, held, RunSummary())

    def run_site_with(self, only=""):
        adapter = FakeAdapter(self.status)
        adapter.is_logged_in = lambda page: True
        adapter.expand_source = lambda url, hashes: []
        browser = MagicMock()
        browser.__enter__.return_value.pages = [MagicMock()]
        with (
            patch("apps.hunter.service.open_browser", return_value=browser),
            patch("apps.hunter.service.reconcile"),
            patch("apps.hunter.service.unscored", return_value=[]),
            patch("apps.hunter.service.score_vacancies"),
            patch("apps.hunter.service.report"),
            patch("apps.hunter.service.apply_ready") as apply_ready,
        ):
            service.run_site(
                adapter,
                ["u"],
                [self.link],
                True,
                5,
                1,
                lambda line: None,
                only,
                False,
                False,
                RunSummary(),
            )
        return apply_ready

    def test_a_paused_site_still_crawls_but_does_not_send(self):
        captcha.start_cooldown("hh")
        self.run_site_with().assert_not_called()
        self.run_site_with(only="81").assert_called_once()
        captcha.clear_cooldown("hh")
        self.run_site_with().assert_called_once()

    @override_settings(HUNTER_CAPTCHA_BACKOFF_MINUTES="")
    def test_an_empty_ladder_never_pauses(self):
        self.assertIsNone(captcha.start_cooldown("hh"))
        self.assertIsNone(captcha.cooling_until("hh"))

    def test_sends_per_run_follow_the_site_limit(self):
        self.vacancy("82")
        self.vacancy("83")
        adapter = FakeAdapter(self.status)
        adapter.MAX_SENDS_PER_RUN = 1
        service.apply_ready(None, adapter, 10, [self.link], lambda line: None, RunSummary())
        self.assertEqual(len(adapter.applied), 1)


class DesktopAskTests(SimpleTestCase):
    def ask(self, output="", timeout=False):
        process = MagicMock()
        if timeout:
            process.communicate.side_effect = [
                notify.subprocess.TimeoutExpired("notify-send", 1),
                ("17\n", None),
            ]
        else:
            process.communicate.return_value = (output, None)
        with (
            override_settings(HUNTER_NOTIFY_DESKTOP=True),
            patch("apps.hunter.notify.shutil.which", return_value="/usr/bin/tool"),
            patch("apps.hunter.notify.subprocess.Popen", return_value=process),
            patch("apps.hunter.notify.close_desktop") as close,
        ):
            answered = notify.ask_desktop("t", "b", "Open browser", 1)
        return answered, close

    def test_only_a_click_counts_as_yes(self):
        self.assertTrue(self.ask("17\nanswer\n")[0])
        self.assertTrue(self.ask("17\ndefault\n")[0])
        self.assertFalse(self.ask("17\n")[0])

    def test_an_unanswered_ask_is_withdrawn(self):
        answered, close = self.ask(timeout=True)
        self.assertFalse(answered)
        close.assert_called_once_with("17")


class DsmlPagingTests(SimpleTestCase):
    def test_page_links_keep_the_language_prefix_and_filters(self):
        self.assertEqual(dsml.page_url("https://dsml.kz/jobs", 1), "https://dsml.kz/jobs")
        self.assertEqual(
            dsml.page_url("https://dsml.kz/ru/jobs/", 3), "https://dsml.kz/ru/jobs/page/3"
        )
        self.assertEqual(
            dsml.page_url("https://dsml.kz/jobs/page/4#jobs-results?x", 2),
            "https://dsml.kz/jobs/page/2",
        )
        self.assertEqual(
            dsml.page_url("https://dsml.kz/jobs?type=remote", 2),
            "https://dsml.kz/jobs/page/2?type=remote",
        )

    def test_crawl_stops_at_the_first_page_without_quick_apply(self):
        page = MagicMock()
        page.title.return_value = "Jobs"
        cards = [
            [{"href": "/jobs/11111111-1111-1111-1111-111111111111#apply", "heading": "A at B"}],
            [],
        ]
        page.evaluate.side_effect = lambda script, *args: (
            cards.pop(0) if script == dsml.CARDS_JS else True
        )
        with patch("apps.hunter.sources.dsml.pause"):
            found = dsml.crawl(page, "https://dsml.kz/jobs", 1)
        self.assertEqual([item.title for item in found], ["A"])
        self.assertEqual(page.goto.call_count, 2)

    def test_apply_reloads_a_page_left_idle_and_waits_for_the_form(self):
        uuid = "11111111-1111-1111-1111-111111111111"
        page = MagicMock()
        page.title.return_value = "Senior AI Engineer"
        page.url = dsml.job_url(uuid)
        calls = []

        def evaluate(script, *args):
            calls.append(script)
            if script == dsml.JOB_JS:
                return {"heading": "", "text": "", "guest": False, "status": "", "head": ""}
            return script != dsml.OPEN_FORM_JS

        page.evaluate.side_effect = evaluate
        applicant = {"cv_path": "/tmp/cv.pdf", "email": "a@b.c"}
        with patch("apps.hunter.sources.dsml.pause"):
            applied, note = dsml.apply(page, page.url, "", "", None, applicant=applicant)
        self.assertFalse(applied)
        self.assertIn("did not open", note)
        page.goto.assert_called_once()
        waits = [index for index, script in enumerate(calls) if script.startswith("(s)")]
        self.assertTrue(waits)
        self.assertLess(waits[-1], calls.index(dsml.OPEN_FORM_JS))

    def test_apply_fills_the_form_without_element_handles(self):
        uuid = "11111111-1111-1111-1111-111111111111"
        page = MagicMock()
        page.title.return_value = "Senior AI Engineer"
        typed = {}
        page.keyboard.type.side_effect = lambda value, delay: typed.update(last=value)
        page.keyboard.insert_text.side_effect = lambda value: typed.update(last=value)

        def evaluate(script, *args):
            if script == dsml.JOB_JS:
                return {"heading": "", "text": "", "guest": True, "status": "", "head": ""}
            if script == dsml.VALUE_JS:
                return typed.get("last")
            if script == dsml.ATTACH_JS:
                return args[0][1]
            if script == dsml.SUBMIT_POINT_JS:
                return {"x": 10, "y": 20, "clear": True}
            return True

        page.evaluate.side_effect = evaluate
        submitted = []
        with tempfile.NamedTemporaryFile(suffix=".pdf") as cv:
            applicant = {"cv_path": cv.name, "email": "a@b.c", "name": "Jane Doe"}
            with (
                patch("apps.hunter.sources.dsml.pause"),
                patch(
                    "apps.hunter.sources.dsml.wait_for_outcome",
                    return_value=(True, "Applied on DSML.kz."),
                ),
            ):
                result = dsml.apply(
                    page,
                    dsml.job_url(uuid),
                    "",
                    "A short letter.",
                    None,
                    on_submit=lambda: submitted.append(True),
                    applicant=applicant,
                )
        self.assertEqual(result, (True, "Applied on DSML.kz."))
        page.locator.assert_not_called()
        page.evaluate_handle.assert_not_called()
        page.keyboard.type.assert_any_call("a@b.c", delay=35)
        page.keyboard.insert_text.assert_any_call("A short letter.")
        page.mouse.click.assert_called_once_with(10, 20)
        self.assertEqual(submitted, [True])


class NavigatorBudgetTests(TestCase):
    def element(self, **fields):
        base = {"ref": "1", "tag": "button", "type": "button", "text": "", "label": "", "group": ""}
        return {**base, **fields}

    def test_submit_buttons_are_judged_by_their_own_text(self):
        footer = "By submitting I certify that the information above is true and I agree."
        send = self.element(type="submit", text="Submit application", submit=True, group=footer)
        self.assertEqual(navigator.vet({"action": "click"}, send, {"x.com"}, False), "")
        box = self.element(tag="input", type="checkbox", label="Yes", group=footer)
        self.assertIn("refused", navigator.vet({"action": "check"}, box, {"x.com"}, False))
        agree = self.element(text="I agree to the terms")
        self.assertIn("refused", navigator.vet({"action": "click"}, agree, {"x.com"}, False))
        terms = "Terms of service: you agree to binding arbitration."
        proceed = self.element(text="Continue", group=terms)
        self.assertIn("refused", navigator.vet({"action": "click"}, proceed, {"x.com"}, False))
        apply = self.element(text="Apply now", group=terms)
        self.assertEqual(navigator.vet({"action": "click"}, apply, {"x.com"}, False), "")

    def picker(self, counts):
        page = MagicMock()
        options = {}

        def by_role(role, name, exact=False):
            found = MagicMock()
            found.count.return_value = counts.get(exact, 0)
            options[exact] = found
            return found

        page.get_by_role.side_effect = by_role
        nav = navigator.Navigator.__new__(navigator.Navigator)
        nav.page = page
        return nav, page, options

    def test_a_dropdown_without_the_option_fails_without_pressing_enter(self):
        nav, page, _ = self.picker({True: 0, False: 3})
        result = nav.pick_option(MagicMock(), "No")
        self.assertTrue(result.startswith("failed: no option named"))
        pressed = [call.args[0] for call in page.keyboard.press.call_args_list]
        self.assertNotIn("Enter", pressed)
        self.assertIn("Escape", pressed)

    def test_a_dropdown_picks_the_exact_option(self):
        nav, _, options = self.picker({True: 1})
        self.assertEqual(nav.pick_option(MagicMock(), "No"), "ok")
        options[True].first.click.assert_called_once()

    def test_required_fields_are_recognised_by_star_or_flag(self):
        self.assertTrue(navigator.is_required({"label": "First Name*"}))
        self.assertTrue(navigator.is_required({"label": "School", "required": True}))
        self.assertFalse(navigator.is_required({"label": "School"}))
        same = navigator.field_key({"tag": "input", "label": "*", "group": "Phone"})
        other = navigator.field_key({"tag": "input", "label": "*", "group": "City"})
        self.assertNotEqual(same, other)

    def run_navigator(self, elements, decisions):
        page = MagicMock()
        page.url = "https://jobs.example.com/apply"
        page.context.pages = [page]
        page.evaluate.side_effect = lambda script, *args: (
            [dict(e) for e in elements] if script == navigator.OUTLINE_JS else ""
        )
        seen = []

        def decide(nav, shown):
            seen.append([e["label"] for e in shown])
            return decisions.pop(0) if decisions else {"action": "stuck", "thought": "end"}

        with (
            override_settings(MIMO_API_KEY="k"),
            patch.object(navigator.Navigator, "decide", autospec=True, side_effect=decide),
            patch.object(navigator.Navigator, "act", return_value="ok"),
        ):
            nav = navigator.Navigator(
                page, goal="apply", cv_text="", job_text="", log=lambda line: None
            )
            nav.max_steps = 10
            nav.loop()
        return seen

    def test_an_optional_field_gets_one_try_and_a_required_one_three(self):
        elements = [
            self.element(ref="1", tag="input", type="text", label="School"),
            self.element(ref="2", tag="input", type="text", label="First Name*"),
        ]
        decisions = [
            {"action": "fill", "ref": "1", "value": "AITU"},
            {"action": "fill", "ref": "2", "value": "A"},
            {"action": "fill", "ref": "2", "value": "B"},
            {"action": "fill", "ref": "2", "value": "C"},
        ]
        seen = self.run_navigator(elements, decisions)
        self.assertEqual(seen[0], ["School", "First Name*"])
        self.assertEqual(seen[1], ["First Name*"])
        self.assertEqual(seen[4], [])

    def test_a_refused_field_is_hidden_from_the_model(self):
        elements = [self.element(ref="1", tag="input", type="password", label="Password")]
        seen = self.run_navigator(elements, [{"action": "fill", "ref": "1", "value": "x"}])
        self.assertEqual(seen, [["Password"], []])


class LinkedInEmployerTests(SimpleTestCase):
    def read(self, title, company):
        job = {"title": title, "company": company, "about": "", "top": "", "easy": True}
        job["external"] = False
        with patch("apps.hunter.sources.linkedin.open_job", return_value=job):
            return linkedin.read_vacancy(None, "https://www.linkedin.com/jobs/view/1/")

    def test_the_company_link_wins_over_pipes_in_the_title(self):
        title = (
            "Mid Product Engineer (Backend) | Python, SQL, RAG, AWS | UK remote | Owen | LinkedIn"
        )
        self.assertEqual(self.read(title, "Owen Thomas").employer, "Owen Thomas")
        self.assertEqual(self.read(title, "").employer, "Owen")
        self.assertEqual(self.read(title, "").title, "Mid Product Engineer (Backend)")


@override_settings(HUNTER_CAPTCHA_BACKOFF_MINUTES="5,30,60,180,480")
class CaptchaLadderTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.data = override_settings(DATA_DIR=Path(self.directory.name))
        self.data.enable()

    def tearDown(self):
        self.data.disable()
        self.directory.cleanup()

    def minutes(self):
        return round((captcha.due_at("hh") - timezone.now()).total_seconds() / 60)

    def test_ignored_captchas_climb_the_ladder_and_stop_at_the_top(self):
        waits = []
        for _ in range(7):
            captcha.start_cooldown("hh")
            waits.append(self.minutes())
        self.assertEqual(waits, [5, 30, 60, 180, 480, 480, 480])
        self.assertEqual(captcha.attempt_of("hh"), (5, 5))

    def test_a_send_remembers_the_wait_that_worked_and_slowly_forgets_it(self):
        captcha.start_cooldown("hh")
        captcha.start_cooldown("hh")
        captcha.record_send("hh")
        self.assertIsNone(captcha.due_at("hh"))
        captcha.start_cooldown("hh")
        self.assertEqual(self.minutes(), 30)
        captcha.record_send("hh")
        captcha.record_send("hh")
        captcha.start_cooldown("hh")
        self.assertEqual(self.minutes(), 5)

    def test_a_solved_captcha_clears_the_wait_but_keeps_the_lesson(self):
        captcha.write_cooldowns({"hh": {"start": 2}})
        captcha.start_cooldown("hh")
        self.assertEqual(self.minutes(), 60)
        captcha.clear_cooldown("hh")
        self.assertIsNone(captcha.due_at("hh"))
        self.assertEqual(captcha.site_state("hh"), {"start": 2})


class CaptchaRetryTests(LinkedCvCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.data = override_settings(
            DATA_DIR=Path(self.directory.name), HUNTER_CAPTCHA_BACKOFF_MINUTES="5,30,60"
        )
        self.data.enable()
        self.adapter = FakeAdapter(hh.parse_status({"resumes": {"1": {"hash": "hash"}}}))

    def tearDown(self):
        self.data.disable()
        self.directory.cleanup()

    def test_an_ignored_captcha_puts_the_job_back_in_the_queue(self):
        error = CaptchaError("captcha")
        error.vacancy = self.vacancy("90", status=Vacancy.Status.NEEDS_REVIEW)
        summary = RunSummary(review=[error.vacancy])
        with (
            patch("apps.hunter.service.run_site", side_effect=error),
            patch("apps.hunter.service.captcha.ask_to_solve", return_value=False),
        ):
            problem = service.try_site(
                self.adapter,
                ["u"],
                [self.link],
                True,
                5,
                1,
                lambda line: None,
                "",
                False,
                False,
                summary,
            )
        error.vacancy.refresh_from_db()
        self.assertEqual(problem, "captcha")
        self.assertEqual(error.vacancy.status, Vacancy.Status.READY)
        self.assertEqual(summary.review, [])
        self.assertIsNotNone(captcha.cooling_until("hh"))

    def test_a_manual_headed_send_that_fails_stays_held(self):
        error = CaptchaError("captcha")
        error.vacancy = self.vacancy("91", status=Vacancy.Status.NEEDS_REVIEW)
        with patch("apps.hunter.service.run_site", side_effect=error):
            service.try_site(
                self.adapter,
                ["u"],
                [self.link],
                True,
                5,
                1,
                lambda line: None,
                "91",
                True,
                False,
                RunSummary(),
            )
        error.vacancy.refresh_from_db()
        self.assertEqual(error.vacancy.status, Vacancy.Status.NEEDS_REVIEW)
        self.assertIsNone(captcha.due_at("hh"))

    def retry(self, errors):
        groups = [(self.adapter, ["u"])]
        with (
            patch("apps.hunter.service.try_site", return_value="") as attempt,
            patch("apps.hunter.service.time.sleep") as sleep,
        ):
            service.retry_paused(groups, [self.link], 5, 1, lambda line: None, RunSummary(), errors)
        return attempt, sleep

    def test_a_due_site_with_jobs_waiting_is_retried_and_its_error_cleared(self):
        self.vacancy("92")
        due = (timezone.now() - timedelta(minutes=1)).isoformat()
        captcha.write_cooldowns({"hh": {"until": due, "step": 0, "start": 0}})
        errors = {"hh": (self.adapter, "captcha")}
        attempt, sleep = self.retry(errors)
        attempt.assert_called()
        sleep.assert_not_called()
        self.assertEqual(attempt.call_args.kwargs, {"crawl": False})
        self.assertEqual(errors, {})

    def test_nothing_waiting_or_a_long_wait_means_no_retry(self):
        captcha.start_cooldown("hh")
        attempt, _ = self.retry({})
        attempt.assert_not_called()
        self.vacancy("93")
        with override_settings(HUNTER_MAX_APPLIES_PER_DAY=0):
            attempt, _ = self.retry({})
        attempt.assert_not_called()
        captcha.write_cooldowns(
            {"hh": {"until": (timezone.now() + timedelta(hours=2)).isoformat(), "step": 2}}
        )
        attempt, _ = self.retry({})
        attempt.assert_not_called()


class SitePriorityTests(LinkedCvCase):
    @override_settings(
        JOB_SOURCE_URLS=[
            "https://astana.hh.kz/search/vacancy?text=python",
            "https://www.linkedin.com/jobs/search/?keywords=python",
            "https://kz.indeed.com/jobs?q=python",
            "https://dsml.kz/jobs",
        ],
        HUNTER_SITE_PRIORITY=["dsml", "indeed", "linkedin", "hh"],
    )
    def test_sites_run_in_priority_order(self):
        sites = [adapter.SITE for adapter, _ in service.site_groups("")]
        self.assertEqual(sites, ["dsml", "indeed", "linkedin", "hh"])

    def lanes(self, problems):
        first, second = FakeAdapter(None), FakeAdapter(None)
        first.SITE, first.NAME, second.SITE, second.NAME = "dsml", "DSML.kz", "indeed", "Indeed"
        threads = {}

        def try_site(adapter, urls, links, apply, limit, max_pages, log, *rest, **kwargs):
            summary = rest[-1]
            threads[adapter.SITE] = threading.current_thread().name
            summary.discovered += 2
            summary.applied.append(SimpleNamespace(pk=adapter.SITE, source=adapter.SITE))
            log("sent")
            return problems.get(adapter.SITE, "")

        lines = []
        summary = RunSummary()
        with (
            patch(
                "apps.hunter.service.site_groups",
                return_value=[(first, ["a"]), (second, ["b"])],
            ),
            patch("apps.hunter.service.try_site", side_effect=try_site),
            patch("apps.hunter.service.retry_paused"),
        ):
            try:
                service.run_once(
                    apply=True, limit=5, max_pages=1, log=lines.append, summary=summary
                )
                failed = None
            except RuntimeError as raised:
                failed = raised
        return summary, threads, lines, failed

    @override_settings(HUNTER_PARALLEL_SITES=2)
    def test_two_sites_run_in_parallel_lanes_and_their_results_merge(self):
        summary, threads, lines, failed = self.lanes({"indeed": "not logged in"})
        self.assertTrue(all(name.startswith("site") for name in threads.values()))
        self.assertEqual(summary.discovered, 4)
        self.assertEqual(sorted(item.pk for item in summary.applied), ["dsml", "indeed"])
        self.assertEqual(sorted(lines), ["[dsml] sent", "[indeed] sent"])
        self.assertIn("Indeed: not logged in", str(failed))

    @override_settings(HUNTER_PARALLEL_SITES=1)
    def test_one_lane_runs_sites_on_the_calling_thread(self):
        _, threads, lines, failed = self.lanes({})
        self.assertEqual(set(threads.values()), {threading.current_thread().name})
        self.assertEqual(lines, ["sent", "sent"])
        self.assertIsNone(failed)

    @override_settings(HUNTER_MAX_APPLIES_PER_DAY=2)
    def test_sends_stop_when_another_lane_fills_the_daily_cap(self):
        first, second = self.vacancy("91"), self.vacancy("92")
        adapter = FakeAdapter(hh.parse_status({"resumes": {"1": {"hash": "hash"}}}))
        summary = RunSummary()
        with patch("apps.hunter.service.sent_last_day", side_effect=[0, 0, 2]):
            service.apply_ready(None, adapter, 10, [self.link], lambda line: None, summary)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(
            sorted([first.status, second.status]), [Vacancy.Status.APPLIED, Vacancy.Status.READY]
        )
        self.assertTrue(summary.daily_cap_reached)

    def test_a_stop_request_ends_sends_after_the_current_one(self):
        self.vacancy("93")
        adapter = FakeAdapter(hh.parse_status({"resumes": {"1": {"hash": "hash"}}}))
        service.STOPPING.set()
        try:
            service.apply_ready(None, adapter, 10, [self.link], lambda line: None, RunSummary())
        finally:
            service.STOPPING.clear()
        self.assertEqual(Vacancy.objects.get(external_id="93").status, Vacancy.Status.READY)


class TryLaterTests(LinkedCvCase):
    def run_refused(self):
        status = hh.parse_status({"resumes": {"1": {"hash": "hash"}}})
        adapter = FakeAdapter(status, (False, "Site said: Failed to save (server: 502 /x)"))
        adapter.TRY_LATER = ("Site said: Failed to save",)
        original = adapter.apply

        def apply(*args, **kwargs):
            kwargs["on_submit"]()
            return original(*args, **kwargs)

        adapter.apply = apply
        lines = []
        summary = RunSummary()
        service.apply_ready(None, adapter, 10, [self.link], lines.append, summary)
        return summary, lines

    def test_a_refused_send_goes_back_in_the_queue_and_the_next_job_is_tried(self):
        first, second = self.vacancy("95"), self.vacancy("96")
        Vacancy.objects.filter(pk=first.pk).update(match_score=99)
        summary, lines = self.run_refused()
        first.refresh_from_db()
        second.refresh_from_db()
        for row in (first, second):
            self.assertEqual(row.status, Vacancy.Status.READY)
            self.assertIsNone(row.submitted_at)
            self.assertIn("refused this job 1 time;", row.note)
        self.assertEqual(summary.review, [])
        self.assertEqual(sum(line.startswith("  LATER") for line in lines), 2)

    def test_a_job_refused_three_times_is_held(self):
        row = self.vacancy("97")
        for _ in range(3):
            summary, _ = self.run_refused()
        row.refresh_from_db()
        self.assertEqual(row.status, Vacancy.Status.NEEDS_REVIEW)
        self.assertIsNone(row.submitted_at)
        self.assertIn("refused this job 3 times", row.note)
        self.assertEqual([item.pk for item in summary.review], [row.pk])

    def run_stuck(self, submit=False, limit=10):
        adapter = FakeAdapter(
            self.status_ok(), (False, "Navigator stuck: The page did not change.")
        )
        if submit:
            original = adapter.apply

            def apply(*args, **kwargs):
                kwargs["on_submit"]()
                return original(*args, **kwargs)

            adapter.apply = apply
        summary = RunSummary()
        with patch("apps.hunter.service.evidence.capture"):
            service.apply_ready(None, adapter, limit, [self.link], lambda line: None, summary)
        return adapter, summary

    def status_ok(self):
        return hh.parse_status({"resumes": {"1": {"hash": "hash"}}})

    def test_a_stuck_job_goes_back_in_the_queue_and_is_held_the_third_time(self):
        row = self.vacancy("98")
        for count in (1, 2):
            _, summary = self.run_stuck()
            row.refresh_from_db()
            self.assertEqual(row.status, Vacancy.Status.READY)
            self.assertIn(f"got stuck on this job {count} time", row.note)
            self.assertEqual(summary.review, [])
        _, summary = self.run_stuck()
        row.refresh_from_db()
        self.assertEqual(row.status, Vacancy.Status.NEEDS_REVIEW)
        self.assertIn("got stuck on this job 3 times", row.note)
        self.assertEqual(review.kind_of(row), review.STUCK)
        self.assertEqual([item.pk for item in summary.review], [row.pk])

    def test_a_stuck_job_that_pressed_submit_is_held_at_once(self):
        row = self.vacancy("99")
        self.run_stuck(submit=True)
        row.refresh_from_db()
        self.assertEqual(row.status, Vacancy.Status.NEEDS_REVIEW)
        self.assertIsNotNone(row.submitted_at)
        self.assertNotIn("got stuck on this job", row.note)

    def test_a_retried_job_waits_behind_fresh_ones(self):
        retried, fresh = self.vacancy("100"), self.vacancy("101")
        Vacancy.objects.filter(pk=retried.pk).update(
            match_score=99, note="The agent got stuck on this job 1 time; nothing was submitted."
        )
        adapter = FakeAdapter(self.status_ok())
        service.apply_ready(None, adapter, 1, [self.link], lambda line: None, RunSummary())
        self.assertEqual(adapter.applied, [fresh.url])

    def test_skipped_duplicates_do_not_use_up_send_slots(self):
        Vacancy.objects.create(
            source="hh",
            external_id="102",
            url="https://astana.hh.kz/vacancy/102",
            title="Go Engineer",
            employer="Acme",
            status=Vacancy.Status.APPLIED,
            applied_at=timezone.now(),
        )
        twin, other = self.vacancy("103"), self.vacancy("104")
        Vacancy.objects.filter(pk=twin.pk).update(
            title="Go Engineer", employer="Acme", match_score=99
        )
        adapter = FakeAdapter(self.status_ok())
        service.apply_ready(None, adapter, 1, [self.link], lambda line: None, RunSummary())
        twin.refresh_from_db()
        self.assertEqual(twin.status, Vacancy.Status.SKIPPED)
        self.assertEqual(adapter.applied, [other.url])

    def test_the_server_answer_names_the_last_non_get_responses(self):
        def response(method, status, url, body):
            item = MagicMock(status=status, url=url)
            item.request.method = method
            item.text.return_value = body
            return item

        answers = [
            response("GET", 200, "https://dsml.kz/a.js", "code"),
            response("POST", 429, "https://dsml.kz/jobs/x", "Too   many\nrequests"),
        ]
        self.assertEqual(dsml.server_answer(answers), " (server: 429 /jobs/x Too many requests)")
        self.assertEqual(dsml.server_answer(answers[:1]), "")


ASHBY_JOB = "https://jobs.ashbyhq.com/acme/5bf4629b-d2ee-4129-980f-e31b96185c9c"


class AtsSourceTests(SimpleTestCase):
    def setUp(self):
        ats.CACHE.clear()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        override = override_settings(
            DATA_DIR=Path(folder.name), TAVILY_API_KEY="key", HUNTER_ATS_SEARCH_HOURS=24
        )
        override.enable()
        self.addCleanup(override.disable)

    def test_job_links_are_reduced_to_one_canonical_posting(self):
        cases = {
            "http://jobs.ashbyhq.com/acme/5BF4629B-d2ee-4129-980f-e31b96185c9c/application": (
                ASHBY_JOB
            ),
            "https://boards.greenhouse.io/inflect/jobs/4717912006?gh_src=x": (
                "https://job-boards.greenhouse.io/inflect/jobs/4717912006"
            ),
            "https://jobs.lever.co/qonto/1fb7a10a-9377-47d4-99f6-e826880c3a6b/apply": (
                "https://jobs.lever.co/qonto/1fb7a10a-9377-47d4-99f6-e826880c3a6b"
            ),
        }
        for link, canonical in cases.items():
            self.assertEqual(ats.job_url(*ats.parse_job(link)), canonical, link)
        self.assertIsNone(ats.parse_job("https://jobs.ashbyhq.com/acme"))
        self.assertIs(adapter_for(ASHBY_JOB), ats)
        self.assertEqual(ats.apply_url(ASHBY_JOB), f"{ASHBY_JOB}/application")

    def test_newer_boards_reduce_job_links_to_one_canonical_posting(self):
        rippling = "9cd647df-0857-4768-954e-9d71468c311b"
        cases = {
            "https://apply.workable.com/huggingface/j/81b46579fe/apply/": (
                ("workable", "huggingface", "81B46579FE"),
                "https://apply.workable.com/huggingface/j/81B46579FE/apply/",
            ),
            "https://somnio.recruitee.com/o/backend-developer/c/new": (
                ("recruitee", "somnio", "backend-developer"),
                "https://somnio.recruitee.com/o/backend-developer/c/new",
            ),
            "https://acme.jobs.personio.com/job/2730632?language=de": (
                ("personio", "acme", "2730632"),
                "https://acme.jobs.personio.de/job/2730632/apply?language=en",
            ),
            "https://flyio.bamboohr.com/careers/35?source=x": (
                ("bamboohr", "flyio", "35"),
                "https://flyio.bamboohr.com/careers/35",
            ),
            "https://jobs.smartrecruiters.com/Canva/6000000001468836-senior-backend-engineer": (
                ("smartrecruiters", "Canva", "6000000001468836"),
                "https://jobs.smartrecruiters.com/Canva/6000000001468836",
            ),
            f"https://ats.rippling.com/en-CA/pythian/jobs/{rippling}": (
                ("rippling", "pythian", rippling),
                f"https://ats.rippling.com/pythian/jobs/{rippling}/apply",
            ),
        }
        for link, (job, apply) in cases.items():
            self.assertEqual(ats.parse_job(link), job, link)
            self.assertEqual(ats.parse_job(ats.job_url(*job)), job, link)
            self.assertEqual(ats.apply_url(link), apply, link)
            self.assertIs(adapter_for(link), ats)
        self.assertIsNone(ats.parse_job("https://www.bamboohr.com/careers/12"))
        self.assertIsNone(ats.parse_job("https://somnio.recruitee.com/"))
        self.assertEqual(ats.board_of("https://recruitee.com/?q=Go"), "recruitee")

    def test_company_scoped_ids_name_the_company(self):
        self.assertEqual(ats.external_id("bamboohr", "flyio", "35"), "bamboohr:flyio/35")
        self.assertEqual(ats.external_id("rippling", "pythian", "x"), "rippling:x")
        self.assertEqual(ats.external_id("ashby", "acme", "x"), "ashby:x")

    def test_newer_boards_list_remote_jobs_once_per_id(self):
        listings = {
            "workable": [
                {"shortcode": "ab12", "title": "Go Engineer", "telecommuting": True},
                {"shortcode": "cd34", "title": "Designer", "telecommuting": False},
            ],
            "recruitee": [
                {"slug": "go-engineer", "title": "Go Engineer", "remote": True},
                {"slug": "old", "title": "Old", "remote": True, "status": "closed"},
            ],
            "bamboohr": [
                {"id": "35", "jobOpeningName": "Go Engineer", "locationType": "1"},
                {"id": "36", "jobOpeningName": "Office", "locationType": "0", "isRemote": None},
            ],
            "smartrecruiters": [
                {"id": "6", "name": "Go Engineer", "location": {"remote": True}, "company": {}},
            ],
            "rippling": [
                {"id": "U", "name": "Go Engineer", "locations": [{"workplaceType": "ON_SITE"}]},
                {"id": "U", "name": "Go Engineer", "locations": [{"workplaceType": "REMOTE"}]},
            ],
        }
        for board, listing in listings.items():
            with patch("apps.hunter.sources.ats.board_listing", return_value=listing):
                jobs = ats.board_jobs(board, "acme")
            self.assertEqual(jobs[0]["title"], "Go Engineer", board)
            self.assertTrue(jobs[0]["remote"] or board == "rippling", board)
        with patch("apps.hunter.sources.ats.board_listing", return_value=listings["recruitee"]):
            self.assertEqual(
                [job["id"] for job in ats.board_jobs("recruitee", "x")], ["go-engineer"]
            )
        with patch("apps.hunter.sources.ats.board_listing", return_value=listings["rippling"]):
            self.assertEqual(
                [job["remote"] for job in ats.board_jobs("rippling", "x")], [False, True]
            )
        with patch("apps.hunter.sources.ats.board_listing", return_value=listings["workable"]):
            self.assertEqual(
                [(job["id"], job["remote"]) for job in ats.board_jobs("workable", "x")],
                [("AB12", True), ("CD34", False)],
            )

    def test_personio_reads_its_xml_feed_and_finds_remote_offices(self):
        feed = ats.ElementTree.fromstring(
            "<workzag-jobs><position><id>7</id><name>Go Engineer</name><office>Berlin</office>"
            "<additionalOffices><office>Germany (Remote)</office></additionalOffices>"
            "<jobDescriptions><jobDescription><name>Tasks</name><value><![CDATA[<p>Build</p>]]>"
            "</value></jobDescription></jobDescriptions></position></workzag-jobs>"
        )
        [job] = ats.personio_positions(feed)
        self.assertEqual((job["id"], job["name"]), ("7", "Go Engineer"))
        self.assertTrue(ats.remote_of("personio", job))
        with patch("apps.hunter.sources.ats.board_listing", return_value=[job]):
            found = ats.posting("https://acme.jobs.personio.de/job/7")
        self.assertIn("Build", found["text"])
        self.assertTrue(found["remote"])
        with patch("apps.hunter.sources.ats.fetch", return_value=b"<html"):
            self.assertRaises(ValueError, ats.get_xml, "https://acme.jobs.personio.de/xml")

    def test_newer_board_search_titles_name_the_employer(self):
        cases = [
            ("workable", "Go Engineer - EMEA Remote - Hugging Face", "huggingface"),
            ("recruitee", "Somnio Software - Go Engineer", "somnio"),
            ("personio", "Go Engineer | Jobs at 1KOMMA5°", "x"),
            ("smartrecruiters", "Canva Go Engineer | SmartRecruiters", "canva"),
            ("rippling", "Go Engineer | Pythian", "pythian"),
        ]
        employers = [ats.hit_names(*case)[1] for case in cases]
        titles = {ats.hit_names(*case)[0] for case in cases}
        self.assertEqual(
            employers, ["Hugging Face", "Somnio Software", "1KOMMA5°", "Canva", "Pythian"]
        )
        self.assertEqual(titles, {"Go Engineer", "Go Engineer - EMEA Remote"})

    def test_a_source_url_expands_to_one_search_per_title(self):
        urls = ats.expand_source("https://jobs.lever.co/?q=Backend+Engineer&q=Go+Developer", [])
        self.assertEqual(
            [ats.search_terms(url) for url in urls],
            [("lever", "Backend Engineer", "Remote"), ("lever", "Go Developer", "Remote")],
        )

    def test_a_remote_search_also_asks_for_worldwide_roles(self):
        with patch("apps.hunter.sources.ats.get_json", return_value={"results": []}) as get:
            ats.search("ashby", "Backend Engineer", "Remote")
            ats.search("ashby", "Backend Engineer", "Berlin")
        queries = [call.args[1]["query"] for call in get.call_args_list]
        self.assertEqual(
            queries,
            ['"Backend Engineer" (Remote OR Worldwide OR Anywhere)', '"Backend Engineer" Berlin'],
        )

    def test_titles_match_across_hyphens_and_spacing(self):
        self.assertTrue(ats.title_matches("Full-Stack Engineer", "Senior Fullstack Engineer"))
        self.assertTrue(ats.title_matches("Full-Stack Engineer", "Full Stack Software Engineer"))
        self.assertFalse(ats.title_matches("Full-Stack Engineer", "Frontend Engineer"))

    def test_search_titles_name_the_employer(self):
        self.assertEqual(
            ats.hit_names("ashby", "Backend Engineer @ Fathom", "fathom.video"),
            ("Backend Engineer", "Fathom"),
        )
        self.assertEqual(
            ats.hit_names("lever", "Qonto - Go Backend Engineer - remote", "qonto"),
            ("Go Backend Engineer - remote", "Qonto"),
        )
        self.assertEqual(
            ats.hit_names("greenhouse", "Job Application for Backend Engineer at Inflect", "x"),
            ("Backend Engineer", "Inflect"),
        )

    def crawl(self, hits):
        listing = [
            {"id": "5bf4629b-d2ee-4129-980f-e31b96185c9c", "title": "Backend Engineer"},
            {
                "id": "11111111-2222-3333-4444-555555555555",
                "title": "Senior Backend Engineer",
                "workplaceType": "Remote",
            },
            {
                "id": "66666666-2222-3333-4444-555555555555",
                "title": "Backend Engineer, Berlin",
                "workplaceType": "OnSite",
            },
            {
                "id": "77777777-2222-3333-4444-555555555555",
                "title": "Designer",
                "workplaceType": "Remote",
            },
        ]
        with (
            patch("apps.hunter.sources.ats.search", return_value=hits) as search,
            patch("apps.hunter.sources.ats.board_listing", return_value=listing),
        ):
            found = ats.crawl(None, "https://jobs.ashbyhq.com/?q=Backend+Engineer", 1)
        return found, search

    def test_crawl_dedupes_hits_and_adds_matching_remote_jobs_from_the_same_board(self):
        hits = [
            {"url": ASHBY_JOB, "title": "Backend Engineer @ Acme"},
            {"url": f"{ASHBY_JOB}/application", "title": "Backend Engineer @ Acme"},
            {"url": "https://jobs.lever.co/x/1fb7a10a-9377-47d4-99f6-e826880c3a6b", "title": ""},
        ]
        found, search = self.crawl(hits)
        search.assert_called_once_with("ashby", "Backend Engineer", "Remote")
        self.assertEqual(
            sorted(item.external_id for item in found),
            [
                "ashby:11111111-2222-3333-4444-555555555555",
                "ashby:5bf4629b-d2ee-4129-980f-e31b96185c9c",
            ],
        )
        self.assertEqual({item.employer for item in found}, {"Acme"})
        again, search = self.crawl(hits)
        search.assert_not_called()
        self.assertEqual(
            [item.external_id for item in again], ["ashby:11111111-2222-3333-4444-555555555555"]
        )

    def test_a_closed_posting_is_impossible_and_a_network_error_is_retried(self):
        with patch("apps.hunter.sources.ats.board_listing", return_value=[]):
            status = ats.response_status(None, ASHBY_JOB)
        self.assertTrue(status.impossible)
        ats.CACHE.clear()
        with patch("apps.hunter.sources.ats.board_listing", side_effect=OSError("down")):
            self.assertIsNone(ats.response_status(None, ASHBY_JOB))
            self.assertEqual(ats.read_vacancy(None, ASHBY_JOB).text, "")

    def test_a_failed_search_is_logged_and_the_run_goes_on(self):
        lines = []
        with patch("apps.hunter.sources.ats.search", side_effect=OSError("429")):
            found = service.discover(
                None, ats, "https://jobs.ashbyhq.com/?q=Backend+Engineer", 1, lines.append, 5
            )
        self.assertEqual(found, [])
        self.assertIn("search failed: 429", lines[0])


class EmployerBoardTests(LinkedCvCase):
    def test_a_captcha_holds_only_that_job_and_the_next_one_is_sent(self):
        status = hh.parse_status({"resumes": {"1": {"hash": "hash"}}})
        adapter = FakeAdapter(status)
        adapter.EMPLOYER_BOARDS = True
        first, second = self.vacancy("98"), self.vacancy("99")
        Vacancy.objects.filter(pk=first.pk).update(match_score=99)
        original = adapter.apply
        calls = []

        def apply(*args, **kwargs):
            calls.append(args[1])
            if len(calls) == 1:
                raise CaptchaError("captcha")
            return original(*args, **kwargs)

        adapter.apply = apply
        summary = RunSummary()
        service.apply_ready(None, adapter, 10, [self.link], lambda line: None, summary)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, Vacancy.Status.NEEDS_REVIEW)
        self.assertIn("captcha", first.note)
        self.assertEqual(second.status, Vacancy.Status.APPLIED)
        self.assertEqual(len(calls), 2)

    def test_a_failed_lookup_skips_only_that_job(self):
        status = hh.parse_status({"resumes": {"1": {"hash": "hash"}}})
        adapter = FakeAdapter(status)
        adapter.EMPLOYER_BOARDS = True
        first, second = self.vacancy("98"), self.vacancy("99")
        Vacancy.objects.filter(pk=first.pk).update(match_score=99)
        answers = [None, status]
        adapter.response_status = lambda page, url: answers.pop(0)
        service.apply_ready(None, adapter, 10, [self.link], lambda line: None, RunSummary())
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, Vacancy.Status.READY)
        self.assertEqual(second.status, Vacancy.Status.APPLIED)

    def test_repeated_failed_lookups_stop_the_lane(self):
        adapter = FakeAdapter(None)
        adapter.EMPLOYER_BOARDS = True
        rows = [self.vacancy(str(90 + index)) for index in range(service.BOARD_MISSES + 1)]
        lookups = []
        adapter.response_status = lambda page, url: lookups.append(url)
        service.apply_ready(None, adapter, 10, [self.link], lambda line: None, RunSummary())
        self.assertEqual(len(lookups), service.BOARD_MISSES)
        self.assertTrue(
            all(Vacancy.objects.get(pk=row.pk).status == Vacancy.Status.READY for row in rows)
        )

    def navigate(self, confirmation, external_id):
        adapter = FakeAdapter(None)
        adapter.EMPLOYER_BOARDS = True
        adapter.open_for_apply = lambda page, url: None
        adapter.navigator_goal = lambda *args: "goal"
        result = navigator.Result("done", "submitted")
        result.submitted = True
        result.trace = []
        status = hh.parse_status({})
        with (
            patch("apps.hunter.service.Navigator") as built,
            patch("apps.hunter.service.evidence.capture"),
            patch("apps.hunter.service.confirm_external", return_value=confirmation),
        ):
            built.return_value.run.return_value = result
            outcome = service.navigate(
                MagicMock(), adapter, self.vacancy(external_id), status, "", "", print, False, None
            )
        self.assertEqual(
            built.call_args.kwargs["max_steps"], settings.HUNTER_NAVIGATOR_EXTERNAL_STEPS
        )
        return outcome

    def test_evidence_keys_stay_valid_for_board_ids(self):
        row = SimpleNamespace(source="ats", external_id="greenhouse:4717912006")
        self.assertEqual(evidence.key_for(row), "ats-greenhouse-4717912006")
        self.assertIsNotNone(evidence.folder(evidence.key_for(row)))

    def test_the_confirmation_page_decides_whether_it_was_sent(self):
        self.assertEqual(self.navigate("Applied (thanks)", "90"), (True, "Applied (thanks)"))
        applied, note = self.navigate("", "91")
        self.assertFalse(applied)
        self.assertIn("did not confirm", note)


def raw_email(sender, subject, body, message_id, html=False):
    kind = "html" if html else "plain"
    return (
        f"From: {sender}\r\nSubject: {subject}\r\nDate: Wed, 14 Oct 2026 10:00:00 +0000\r\n"
        f"Message-ID: <{message_id}>\r\nContent-Type: text/{kind}; charset=utf-8\r\n\r\n{body}"
    ).encode()


FAKE_IMAPS = []


class FakeImap:
    def __init__(self, host, timeout=None):
        self.host = host
        self.messages = {}
        self.calls = []
        self.selected = None
        FAKE_IMAPS.append(self)

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if password != "secret":
            raise mail.imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"ok"]

    def list(self):
        return "OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
        ]

    def select(self, folder, readonly=False):
        self.selected = (folder, readonly)
        return "OK", [b"3"]

    def response(self, code):
        return code, [b"77"]

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "SEARCH":
            return "OK", [" ".join(str(uid) for uid in sorted(self.messages)).encode()]
        uids = [int(uid) for uid in args[0].split(",")]
        data = []
        for uid in uids:
            data.append((f"{uid} (UID {uid} BODY[]<0> {{10}}".encode(), self.messages[uid]))
            data.append(b")")
        return "OK", data

    def logout(self):
        self.calls.append(("logout",))


class MailSortingTests(LinkedCvCase):
    def setUp(self):
        super().setUp()
        FAKE_IMAPS.clear()
        self.lines = []
        self.settings_override = override_settings(
            HUNTER_MAIL_ACCOUNTS="me@gmail.com:5:sec ret,work@gmail.com:all:secret",
            MIMO_API_KEY="key",
            HUNTER_NOTIFY_DESKTOP=False,
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()

    def imap(self, messages):
        def connect(host, timeout=None):
            fake = FakeImap(host, timeout)
            fake.messages = dict(messages)
            return fake

        return connect

    def test_accounts_parse_window_and_strip_app_password_spaces(self):
        with override_settings(
            HUNTER_MAIL_ACCOUNTS="a@gmail.com:5:abcd efgh, b@gmail.com:all:xyz,bad,c@x:-2:p"
        ):
            parsed = mail.accounts()
        self.assertEqual(
            parsed,
            [
                mail.Account("a@gmail.com", "abcdefgh", 5),
                mail.Account("b@gmail.com", "xyz", None),
            ],
        )

    def test_reads_all_mail_read_only_with_peek_and_window(self):
        sorted_rows = {
            9: {"kind": "interview", "employer": "Fathom", "summary": "Pick a time."},
        }
        connect = self.imap({9: raw_email("hr@fathom.video", "Interview", "Hi", "m9@x")})
        with patch.object(mail, "classify", return_value=sorted_rows):
            saved = mail.sync_account(mail.accounts()[0], self.lines.append, 10, connect=connect)
        fake = FAKE_IMAPS[0]
        self.assertEqual(fake.selected, ('"[Gmail]/All Mail"', True))
        search = next(call for call in fake.calls if call[0] == "SEARCH")
        self.assertIn("newer_than:5d", search[2])
        self.assertIn("-in:sent", search[2])
        fetch = next(call for call in fake.calls if call[0] == "FETCH")
        self.assertIn("BODY.PEEK[]", fetch[2])
        self.assertEqual([message.uid for message in saved], [9])
        self.assertEqual(saved[0].uidvalidity, 77)
        self.assertEqual(saved[0].message_id, "<m9@x>")
        self.assertIn(("logout",), fake.calls)

    def test_all_window_has_no_date_filter_and_known_uids_are_skipped(self):
        MailMessage.objects.create(account="work@gmail.com", uidvalidity=77, uid=1, kind="other")
        messages = {
            1: raw_email("a@b.c", "Old", "x", "m1@x"),
            2: raw_email("a@b.c", "New", "x", "m2@x"),
        }
        seen = {}

        def classify(emails):
            seen.update(emails)
            return {uid: {"kind": "newsletter", "employer": "", "summary": ""} for uid in emails}

        with patch.object(mail, "classify", side_effect=classify):
            mail.sync_account(mail.accounts()[1], self.lines.append, 0, connect=self.imap(messages))
        search = next(call for call in FAKE_IMAPS[0].calls if call[0] == "SEARCH")
        self.assertNotIn("newer_than", search[2])
        self.assertEqual(list(seen), [2])
        self.assertEqual(MailMessage.objects.filter(account="work@gmail.com").count(), 2)

    def test_limit_takes_newest_first(self):
        messages = {uid: raw_email("a@b.c", f"S{uid}", "x", f"m{uid}@x") for uid in range(1, 6)}
        with patch.object(
            mail,
            "classify",
            side_effect=lambda emails: {
                uid: {"kind": "other", "employer": "", "summary": ""} for uid in emails
            },
        ):
            saved = mail.sync_account(
                mail.accounts()[1], self.lines.append, 2, connect=self.imap(messages)
            )
        self.assertEqual(sorted(message.uid for message in saved), [4, 5])

    def test_model_failure_stores_nothing_so_the_email_is_retried(self):
        connect = self.imap({3: raw_email("a@b.c", "S", "x", "m3@x")})
        with patch.object(mail, "classify", side_effect=ValueError("bad json")):
            saved = mail.sync_account(mail.accounts()[1], self.lines.append, 0, connect=connect)
        self.assertEqual(saved, [])
        self.assertFalse(MailMessage.objects.exists())
        self.assertTrue(any("sorting failed" in line for line in self.lines))

    def test_login_failure_is_logged_without_the_password(self):
        with (
            override_settings(HUNTER_MAIL_ACCOUNTS="me@gmail.com:5:wrong pass"),
            patch.object(mail.imaplib, "IMAP4_SSL", self.imap({})),
        ):
            saved = mail.sync(self.lines.append)
        self.assertEqual(saved, [])
        self.assertTrue(any("AUTHENTICATIONFAILED" in line for line in self.lines))
        self.assertFalse(any("wrong" in line or "pass" in line for line in self.lines))

    def test_classify_keeps_only_known_ids_and_kinds(self):
        content = json.dumps(
            {
                "emails": [
                    {"id": "4", "kind": "Interview", "employer": " Acme ", "summary": "Call"},
                    {"id": "5", "kind": "spam", "employer": "", "summary": ""},
                    {"id": "99", "kind": "offer"},
                ]
            }
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
        client = MagicMock()
        client.chat.completions.create.return_value = response
        emails = {
            uid: {"sender": "", "subject": "", "received_at": None, "text": ""} for uid in (4, 5)
        }
        with patch.object(mail, "OpenAI", return_value=client):
            rows = mail.classify(emails)
        self.assertEqual(
            rows[4], {"kind": "interview", "employer": "Acme", "summary": "Call", "position": ""}
        )
        self.assertEqual(rows[5]["kind"], "other")
        self.assertNotIn(99, rows)

    def test_html_body_is_reduced_to_text(self):
        parsed = mail.parse(
            raw_email(
                "a@b.c",
                "S",
                "<html><style>p{}</style><p>Hello&nbsp;there</p></html>",
                "m@x",
                html=True,
            )
        )
        self.assertEqual(parsed["text"], "Hello there")

    def sent(self, external_id, employer, title, days_ago=1, status=Vacancy.Status.APPLIED):
        vacancy = self.vacancy(external_id, status=status)
        moment = timezone.now() - timedelta(days=days_ago)
        Vacancy.objects.filter(pk=vacancy.pk).update(
            employer=employer,
            title=title,
            applied_at=moment if status == Vacancy.Status.APPLIED else None,
            submitted_at=moment,
        )
        vacancy.refresh_from_db()
        return vacancy

    def test_links_email_to_the_job_by_company_and_title(self):
        self.sent("1", "Acme Inc.", "Data Engineer", days_ago=3)
        backend = self.sent("2", "ACME", "Backend Engineer", days_ago=2)
        self.sent("3", "Other", "Backend Engineer")
        pool = mail.candidates()
        found = mail.match_vacancy(
            "Acme", "Your Backend Engineer application", timezone.now(), pool
        )
        self.assertEqual(found, backend)
        self.assertIsNone(mail.match_vacancy("Ac", "x", timezone.now(), pool))
        self.assertIsNone(
            mail.match_vacancy("Acme", "x", timezone.now() - timedelta(days=30), pool)
        )

    def test_board_email_links_by_a_full_unique_title(self):
        python = self.sent("4", "Kopylova", "Python Backend Engineer Senior")
        self.sent("5", "Bnovo", "Backend Developer")
        pool = mail.candidates()
        found = mail.match_vacancy(
            "",
            "Вам написали по вакансии Python Backend Engineer Senior",
            timezone.now(),
            pool,
            '"hh.kz" <noreply@hh.kz>',
        )
        self.assertEqual(found, python)
        self.assertIsNone(
            mail.match_vacancy(
                "", "Senior Backend Developer", timezone.now(), pool, "noreply@hh.kz"
            )
        )
        self.assertIsNone(
            mail.match_vacancy(
                "Syngenta", "Python Backend Engineer Senior", timezone.now(), pool, "x@syngenta.com"
            )
        )
        self.sent("6", "Научсофт", "Senior Go Developer")
        self.assertIsNone(
            mail.match_vacancy(
                "Acme",
                "Вам написали по вакансии",
                timezone.now(),
                mail.candidates(),
                "noreply@hh.kz",
                "Senior Backend Developer/Ведущий разработчик (Go)",
            )
        )
        self.assertIsNone(
            mail.match_vacancy(
                "",
                "Новое сообщение",
                timezone.now(),
                mail.candidates(),
                "noreply@hh.kz",
                "Senior Backend Developer/Ведущий разработчик (Go)",
            )
        )

    def test_title_match_needs_exactly_one_job(self):
        self.sent("4", "One", "Python Backend Engineer")
        self.sent("5", "Two", "Python Backend Engineer")
        pool = mail.candidates()
        self.assertIsNone(
            mail.match_vacancy("", "Python Backend Engineer role", timezone.now(), pool)
        )

    def test_relink_links_old_unlinked_email_and_reads_titles(self):
        python = self.sent("4", "Kopylova", "Python Backend Engineer Senior", days_ago=5)
        message = MailMessage.objects.create(
            account="me@gmail.com",
            uidvalidity=1,
            uid=1,
            kind="recruiter",
            sender='"hh.kz" <noreply@hh.kz>',
            subject="Новое сообщение от работодателя",
            summary="An employer wrote about your application.",
            received_at=timezone.now() - timedelta(days=1),
        )
        with patch.object(
            mail, "extract_positions", return_value={message.pk: "Python Backend Engineer Senior"}
        ):
            linked = mail.relink(self.lines.append, classify_positions=True)
        message.refresh_from_db()
        self.assertEqual(linked, 1)
        self.assertEqual(message.vacancy, python)
        self.assertEqual(message.position, "Python Backend Engineer Senior")

    def test_reply_confirms_an_unconfirmed_send(self):
        held = self.sent("7", "Fathom", "Backend Engineer", status=Vacancy.Status.NEEDS_REVIEW)
        Vacancy.objects.filter(pk=held.pk).update(
            note="Submitted, but no confirmation; check before resending."
        )
        connect = self.imap({4: raw_email("no-reply@ashbyhq.com", "Thanks", "x", "m4@x")})
        rows = {4: {"kind": "confirmation", "employer": "Fathom", "summary": "Received."}}
        with (
            patch.object(mail, "classify", return_value=rows),
            patch.object(mail.timezone, "now", return_value=timezone.now()),
        ):
            Vacancy.objects.filter(pk=held.pk).update(
                submitted_at=datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
            )
            saved = mail.sync_account(mail.accounts()[1], self.lines.append, 0, connect=connect)
        held.refresh_from_db()
        self.assertEqual(saved[0].vacancy, held)
        self.assertEqual(held.status, Vacancy.Status.APPLIED)
        self.assertIn("confirmation email", held.note)

    def test_marketing_email_is_not_linked(self):
        self.sent("8", "Fathom", "Backend Engineer")
        connect = self.imap({5: raw_email("news@fathom.video", "News", "x", "m5@x")})
        rows = {5: {"kind": "newsletter", "employer": "Fathom", "summary": ""}}
        with patch.object(mail, "classify", return_value=rows):
            saved = mail.sync_account(mail.accounts()[1], self.lines.append, 0, connect=connect)
        self.assertIsNone(saved[0].vacancy)

    def test_desktop_lists_shown_kinds_and_dismiss_hides_them(self):
        shown = MailMessage.objects.create(
            account="work@gmail.com",
            uidvalidity=1,
            uid=1,
            kind="interview",
            message_id="<abc@x>",
            subject="Interview",
            received_at=timezone.now(),
        )
        MailMessage.objects.create(
            account="work@gmail.com",
            uidvalidity=1,
            uid=3,
            kind="interview",
            received_at=timezone.now() - timedelta(days=90),
        )
        MailMessage.objects.create(
            account="work@gmail.com", uidvalidity=1, uid=2, kind="newsletter"
        )
        listing = agent_desk.mail_listing()
        self.assertEqual([row["id"] for row in listing["rows"]], [shown.pk])
        self.assertEqual(listing["sorted"], 3)
        self.assertIn("rfc822msgid%3Aabc%40x", listing["rows"][0]["gmail_url"])
        self.assertEqual(mail.dismiss(shown.pk), "")
        self.assertEqual(agent_desk.mail_listing()["rows"], [])

    def test_desktop_keeps_an_older_interview_behind_many_confirmations(self):
        now = timezone.now()
        interview = MailMessage.objects.create(
            account="work@gmail.com",
            uidvalidity=1,
            uid=1,
            kind="interview",
            received_at=now - timedelta(days=2),
        )
        MailMessage.objects.bulk_create(
            MailMessage(
                account="me@gmail.com",
                uidvalidity=1,
                uid=10 + index,
                kind="confirmation",
                received_at=now - timedelta(minutes=index),
            )
            for index in range(agent_desk.MAIL_ROWS + 5)
        )
        listing = agent_desk.mail_listing()
        self.assertIn(interview.pk, [row["id"] for row in listing["rows"]])
        self.assertEqual(
            listing["counts"]["me@gmail.com"]["confirmation"], agent_desk.MAIL_ROWS + 5
        )
        self.assertEqual(listing["counts"]["work@gmail.com"], {"interview": 1})
        self.assertEqual(len(listing["rows"]), agent_desk.MAIL_ROWS + 1)

    def test_desktop_shows_the_job_an_email_is_about(self):
        vacancy = self.sent("9", "Tenth Revolution Group", "Software Engineer")
        Vacancy.objects.filter(pk=vacancy.pk).update(
            match_reason=(
                "Fits. Flagship CV: a.pdf (from b.pdf), reviewer fit 46. Added for this job: "
                "Node.js, BigQuery. Cannot be written in: Ruby."
            ),
            text="The posting.",
        )
        MailMessage.objects.create(
            account="work@gmail.com",
            uidvalidity=1,
            uid=1,
            kind="interview",
            position="Software Engineer",
            received_at=timezone.now(),
            vacancy=vacancy,
        )
        row = agent_desk.mail_listing()["rows"][0]
        self.assertEqual(row["vacancy_id"], vacancy.pk)
        self.assertEqual(row["job_site"], "hh.kz")
        self.assertEqual(row["position"], "Software Engineer")
        self.assertTrue(row["job_sent_at"])
        job = agent_desk.job_payload(vacancy.pk)
        self.assertEqual(job["added"], "Node.js, BigQuery")
        self.assertEqual(job["text"], "The posting.")
        self.assertTrue(job["cv_name"])

    def test_desktop_flags_and_counts_ai_interviews(self):
        now = timezone.now()
        ai = MailMessage.objects.create(
            account="work@gmail.com",
            uidvalidity=1,
            uid=1,
            kind="interview",
            subject="Next step: Complete your 20-minute AI Interview",
            received_at=now,
        )
        human = MailMessage.objects.create(
            account="work@gmail.com",
            uidvalidity=1,
            uid=2,
            kind="interview",
            subject="Interview with the hiring manager",
            summary="A call with the team lead about the training platform.",
            received_at=now,
        )
        listing = agent_desk.mail_listing()
        flags = {row["id"]: row["ai_interview"] for row in listing["rows"]}
        self.assertEqual(flags, {ai.pk: True, human.pk: False})
        self.assertEqual(listing["counts"]["work@gmail.com"], {"interview": 2})
        self.assertEqual(listing["ai_counts"], {"work@gmail.com": {"interview": 1}})

    def test_urgent_recent_email_raises_one_desktop_notice(self):
        recent = MailMessage(kind="interview", employer="Acme", received_at=timezone.now())
        old = MailMessage(
            kind="offer", employer="Old", received_at=timezone.now() - timedelta(days=30)
        )
        alert = MailMessage(kind="job_alert", received_at=timezone.now())
        with patch.object(notify, "send_desktop") as send:
            mail.notify_urgent([recent, old, alert])
        title, body = send.call_args.args
        self.assertEqual(title, "1 email needs you")
        self.assertIn("Acme", body)
        self.assertNotIn("Old", body)

    def test_broken_email_and_missing_answer_are_stored_as_other_not_retried(self):
        messages = {
            1: raw_email("a@b.c", "Good", "x", "m1@x"),
            2: b"\xff\xfe broken",
        }
        with (
            patch.object(mail, "parse", side_effect=[ValueError("bad"), mail.parse(messages[1])]),
            patch.object(
                mail,
                "classify",
                return_value={1: {"kind": "interview", "employer": "", "summary": ""}},
            ),
        ):
            saved = mail.sync_account(
                mail.accounts()[1], self.lines.append, 0, connect=self.imap(messages)
            )
        kinds = {message.uid: message.kind for message in saved}
        self.assertEqual(kinds, {1: "interview", 2: "other"})

    def test_missing_uidvalidity_is_a_mail_error(self):
        def connect(host, timeout=None):
            fake = FakeImap(host, timeout)
            fake.response = lambda code: (code, [None])
            return fake

        with patch.object(mail.imaplib, "IMAP4_SSL", connect):
            saved = mail.sync(self.lines.append, only="work@gmail.com")
        self.assertEqual(saved, [])
        self.assertTrue(any("no UIDVALIDITY" in line for line in self.lines))


class MailImportTests(LinkedCvCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.data = override_settings(
            DATA_DIR=Path(self.directory.name),
            MIMO_API_KEY="key",
            HUNTER_MAIL_ACCOUNTS="work@gmail.com:all:secret",
        )
        self.data.enable()
        self.lines = []

    def tearDown(self):
        self.data.disable()
        self.directory.cleanup()

    def mbox(self, messages, name="All mail.mbox"):
        path = Path(self.directory.name) / name
        box = mail.mailbox.mbox(path)
        for message in messages:
            box.add(message)
        box.flush()
        box.close()
        return path

    def labelled(self, message_id, labels):
        raw = raw_email("hr@acme.com", f"Subject {message_id}", "Body", message_id)
        return f"X-Gmail-Labels: {labels}\r\n".encode() + raw

    def sort_all(self, emails):
        return {uid: {"kind": "rejection", "employer": "", "summary": "No."} for uid in emails}

    def test_imports_received_mail_once_and_leaves_out_sent_and_spam(self):
        path = self.mbox(
            [
                self.labelled("a@x", "Inbox,Opened"),
                self.labelled("b@x", "Sent"),
                self.labelled("c@x", "Spam"),
                self.labelled("d@x", "Archived"),
                "X-Gmail-Labels: Отправленные\r\n".encode()
                + raw_email("Me <Work@gmail.com>", "Re", "Body", "e@x"),
            ]
        )
        with patch.object(mail, "classify", side_effect=self.sort_all) as classify:
            saved = mail.import_mbox(path, "work@gmail.com", self.lines.append)
            again = mail.import_mbox(path, "work@gmail.com", self.lines.append)
        self.assertEqual(sorted(m.message_id for m in saved), ["<a@x>", "<d@x>"])
        self.assertEqual(again, [])
        self.assertEqual(classify.call_count, 1)
        self.assertTrue(all(m.uidvalidity == mail.IMPORTED for m in saved))

    def test_reads_the_mbox_inside_a_takeout_zip(self):
        path = self.mbox([self.labelled("z@x", "Inbox")])
        archive = Path(self.directory.name) / "takeout.zip"
        with mail.zipfile.ZipFile(archive, "w") as handle:
            handle.write(path, "Takeout/Mail/All mail Including Spam and Trash.mbox")
        path.unlink()
        with patch.object(mail, "classify", side_effect=self.sort_all):
            saved = mail.import_mbox(archive, "work@gmail.com", self.lines.append)
        self.assertEqual([m.message_id for m in saved], ["<z@x>"])

    def test_model_failure_stops_and_a_rerun_continues(self):
        path = self.mbox([self.labelled("a@x", "Inbox")])
        with (
            patch.object(mail, "classify", side_effect=ValueError("down")),
            patch.object(mail.time, "sleep"),
        ):
            saved = mail.import_mbox(path, "work@gmail.com", self.lines.append)
        self.assertEqual(saved, [])
        self.assertTrue(any("run it again" in line for line in self.lines))
        with patch.object(mail, "classify", side_effect=self.sort_all):
            saved = mail.import_mbox(path, "work@gmail.com", self.lines.append)
        self.assertEqual(len(saved), 1)

    def test_imap_adopts_an_imported_email_instead_of_sorting_it_again(self):
        path = self.mbox([self.labelled("a@x", "Inbox")])
        with patch.object(mail, "classify", side_effect=self.sort_all):
            mail.import_mbox(path, "work@gmail.com", self.lines.append)

        def connect(host, timeout=None):
            fake = FakeImap(host, timeout)
            fake.messages = {
                5: raw_email("hr@acme.com", "Subject a@x", "Body", "a@x"),
                6: raw_email("hr@acme.com", "New", "Body", "n@x"),
            }
            return fake

        with patch.object(mail, "classify", side_effect=self.sort_all) as classify:
            saved = mail.sync_account(mail.accounts()[0], self.lines.append, 0, connect=connect)
        self.assertEqual([m.uid for m in saved], [6])
        self.assertEqual(list(classify.call_args.args[0]), [6])
        adopted = MailMessage.objects.get(message_id="<a@x>")
        self.assertEqual((adopted.uidvalidity, adopted.uid), (77, 5))
        self.assertEqual(MailMessage.objects.count(), 2)


class MailReplyKindTests(SimpleTestCase):
    def test_a_security_code_email_does_not_prove_a_send(self):
        self.assertNotIn("action_needed", mail.REPLY_KINDS)
        self.assertIn("confirmation", mail.REPLY_KINDS)


class CvReviewerTests(SimpleTestCase):
    DRAFT = "Backend engineer with 9 years. Built Go and Java services on PostgreSQL."

    def test_contradictions_found_in_the_draft_and_missing_requirements_fail(self):
        outcome = cv_reviewer.verdict(
            {
                "contradictions": [
                    {"quote": "engineer with  9 years", "why": "dates show 4"},
                    {"quote": "Kubernetes operator", "why": "not in the draft"},
                ],
                "must_haves": [
                    {"requirement": "Go", "status": "covered"},
                    {"requirement": "Kafka", "status": "missing"},
                    {"requirement": "React", "status": "partial"},
                    {"requirement": "10 years", "status": "fixed_fact"},
                    {"requirement": "Testing", "status": "excellent"},
                ],
                "red_flags": [
                    {"text": "Same metric twice", "severity": "huge"},
                    {"text": "Summary copies the posting", "severity": "high"},
                ],
                "fit_score": "71",
            },
            self.DRAFT,
        )
        self.assertFalse(outcome["passed"])
        self.assertEqual(
            [c["quote"] for c in outcome["contradictions"]], ["engineer with  9 years"]
        )
        self.assertEqual(outcome["missing"], ["Kafka"])
        self.assertEqual(outcome["partial"], ["React", "Testing"])
        self.assertEqual(outcome["gaps"], ["10 years"])
        self.assertEqual(outcome["red_flags"][0]["severity"], "medium")
        self.assertEqual(outcome["fit_score"], 71)
        self.assertEqual(len(outcome["problems"]), 2)
        revision = cv_reviewer.revision(outcome)
        self.assertIn("Add these requirements", revision)
        self.assertIn("Kafka", revision)
        self.assertIn("React", revision)
        self.assertIn("Summary copies the posting", revision)
        self.assertNotIn("Same metric twice", revision)

    def test_a_missing_excluded_language_is_a_gap_not_a_failure(self):
        outcome = cv_reviewer.verdict(
            {"must_haves": [{"requirement": "Strong Ruby on Rails", "status": "missing"}]},
            self.DRAFT,
            ["Ruby", "Rust"],
        )
        self.assertTrue(outcome["passed"])
        self.assertEqual(outcome["gaps"], ["Strong Ruby on Rails"])

    def test_partial_and_fixed_facts_alone_do_not_fail_the_draft(self):
        outcome = cv_reviewer.verdict(
            {
                "contradictions": [{"quote": "", "why": "empty"}],
                "must_haves": [
                    {"requirement": "Rust", "status": "partial"},
                    {"requirement": "US citizen", "status": "fixed_fact"},
                ],
            },
            self.DRAFT,
        )
        self.assertTrue(outcome["passed"])
        self.assertEqual(outcome["gaps"], ["US citizen"])


@override_settings(HUNTER_EXCLUDED_SKILLS=["C", "C++", "Rust"])
class FlagshipCvTests(LinkedCvCase):
    def flagship(self, employer="GitLab Inc.", external_id="60"):
        vacancy = self.vacancy(external_id)
        Vacancy.objects.filter(pk=vacancy.pk).update(employer=employer, text="Go, PostgreSQL")
        vacancy.refresh_from_db()
        return vacancy

    def drafts(self, count):
        return [
            Cv.objects.create(
                file=f"cvs/d{n}.pdf", original_filename=f"Draft {n}.pdf", raw_text="x"
            )
            for n in range(count)
        ]

    def cv_service(self, drafts, calls, added=()):
        def generate_from(source_id, instructions, **kwargs):
            calls.append(instructions)
            index = len(calls) - 1
            return drafts[index], list(added[index]) if index < len(added) else [], []

        return SimpleNamespace(
            generate_from=generate_from, delete=lambda cv_id: Cv.objects.filter(pk=cv_id).delete()
        )

    def outcome(self, passed, partial=(), fit=80):
        return {
            "contradictions": [],
            "must_haves": [],
            "red_flags": [],
            "fit_score": fit,
            "missing": [] if passed else ["Go"],
            "partial": list(partial),
            "gaps": ["10 years"],
            "problems": [] if passed else ["Go is missing"],
            "passed": passed,
        }

    def run_flagship(self, vacancy, drafts, calls, reviews, added=()):
        with (
            patch(
                "apps.hunter.service.CvsContainer.cv_service",
                return_value=self.cv_service(drafts, calls, added),
            ),
            patch("apps.hunter.service.cv_reviewer.review", side_effect=reviews) as reviewer,
        ):
            result = service.flagship_cv(vacancy, lambda line: None)
        vacancy.refresh_from_db()
        return result, reviewer

    @override_settings(MIMO_API_KEY="key")
    def test_only_flagship_employers_on_upload_sites_qualify(self):
        upload = SimpleNamespace(USES_RESUME_LINKS=False)
        self.assertTrue(service.is_flagship(upload, self.flagship()))
        self.assertFalse(
            service.is_flagship(
                SimpleNamespace(USES_RESUME_LINKS=True), self.flagship(external_id="61")
            )
        )
        self.assertFalse(service.is_flagship(upload, self.flagship("GitLabs Clone Co", "62")))
        marked = self.flagship(external_id="63")
        marked.match_reason = f"{service.FLAGSHIP_MARK} Draft.pdf"
        self.assertFalse(service.is_flagship(upload, marked))

    @override_settings(HUNTER_STACK="Languages: Python, Go, Java.")
    def test_a_failed_review_is_revised_and_added_skills_are_recorded(self):
        vacancy = self.flagship()
        drafts, calls = self.drafts(2), []
        reviews = [self.outcome(False), self.outcome(True)]
        result, _ = self.run_flagship(vacancy, drafts, calls, reviews, [[], ["Java", "React"]])
        self.assertTrue(result)
        self.assertEqual(vacancy.cv_id, drafts[1].id)
        self.assertFalse(Cv.objects.filter(pk=drafts[0].pk).exists())
        self.assertIn("matches the posting 100%", calls[0])
        self.assertIn("Languages: Python, Go, Java.", calls[0])
        self.assertIn("never add C, C++, Rust", calls[0])
        self.assertIn("Add these requirements to the skills", calls[1])
        self.assertIn("Added for this job: Java, React.", vacancy.match_reason)
        self.assertIn("Cannot be written in: 10 years.", vacancy.match_reason)

    def test_an_excluded_language_is_never_reviewed_or_sent(self):
        vacancy = self.flagship()
        drafts, calls = self.drafts(2), []
        result, reviewer = self.run_flagship(
            vacancy, drafts, calls, [self.outcome(True)], [["Rust", "Kafka"], ["Kafka"]]
        )
        self.assertTrue(result)
        self.assertEqual(reviewer.call_count, 1)
        self.assertEqual(vacancy.cv_id, drafts[1].id)
        self.assertIn("Do not list Rust.", calls[1])
        self.assertEqual(
            service.excluded_skills(["C#", "C++", "Objective-C", "Go/Rust"]),
            [
                "C++",
                "Go/Rust",
            ],
        )

    def test_partial_coverage_is_pushed_and_the_draft_with_fewest_partials_kept(self):
        vacancy = self.flagship()
        drafts, calls = self.drafts(3), []
        reviews = [
            self.outcome(True, ["React", "Kafka"]),
            self.outcome(True, ["React", "Kafka", "gRPC"]),
            self.outcome(True, ["React"], fit=60),
        ]
        result, _ = self.run_flagship(vacancy, drafts, calls, reviews)
        self.assertTrue(result)
        self.assertIn("Make these clear and early", calls[1])
        self.assertEqual(vacancy.cv_id, drafts[2].id)
        self.assertEqual(Cv.objects.filter(pk__in=[d.pk for d in drafts]).count(), 1)

    def test_a_headline_naming_the_employer_is_caught(self):
        self.assertTrue(
            service.names_employer("Jane Doe\nStaff Engineer at GitLab\nRemote", "GitLab Inc.")
        )
        self.assertFalse(
            service.names_employer(
                "Jane Doe\nStaff Engineer\nAstana\nBuilt GitLab CI", "GitLab Inc."
            )
        )

    def test_skip_titles_match_whole_phrases(self):
        manager = self.vacancy("70")
        engineer = self.vacancy("71")
        Vacancy.objects.filter(pk=manager.pk).update(title="Senior Project Manager (No-Code)")
        Vacancy.objects.filter(pk=engineer.pk).update(title="Product Engineer, Backend")
        manager.refresh_from_db()
        engineer.refresh_from_db()
        self.assertIn("not an engineering role", service.skip_reason(manager))
        self.assertEqual(service.skip_reason(engineer), "")

    def test_failed_drafts_hold_the_job_and_are_deleted(self):
        vacancy = self.flagship()
        drafts, calls = self.drafts(service.FLAGSHIP_DRAFTS), []
        with (
            patch(
                "apps.hunter.service.CvsContainer.cv_service",
                return_value=self.cv_service(drafts, calls),
            ),
            patch(
                "apps.hunter.service.cv_reviewer.review",
                side_effect=[self.outcome(False)] * service.FLAGSHIP_DRAFTS,
            ),
        ):
            self.assertFalse(service.flagship_cv(vacancy, lambda line: None))
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.status, Vacancy.Status.NEEDS_REVIEW)
        self.assertEqual(vacancy.cv_id, self.cv.id)
        self.assertIn("Go is missing", vacancy.note)
        self.assertEqual(review.kind_of(vacancy), review.CV)
        self.assertFalse(Cv.objects.filter(pk__in=[d.pk for d in drafts]).exists())

    def test_a_held_flagship_job_is_not_sent_and_skips_plain_tailoring(self):
        vacancy = self.flagship()
        adapter = FakeAdapter(hh.parse_status({"resumes": {"1": {"hash": "hash"}}}))
        adapter.USES_RESUME_LINKS = False

        def hold(row, log):
            service.finish(row, False, f"{review.CV_NOTE}: test")
            return False

        with (
            override_settings(MIMO_API_KEY="key"),
            patch("apps.hunter.service.flagship_cv", side_effect=hold),
            patch("apps.hunter.service.tailor_cv") as tailor,
            patch("apps.hunter.service.adapter_for", return_value=adapter),
        ):
            service.apply_ready(None, adapter, 10, [self.link], lambda line: None, RunSummary())
        vacancy.refresh_from_db()
        self.assertEqual(adapter.applied, [])
        tailor.assert_not_called()
        self.assertEqual(vacancy.status, Vacancy.Status.NEEDS_REVIEW)


class FakeGmail:
    def __init__(self, pages, messages):
        self.pages = pages
        self.messages = messages
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url.rsplit("/me/", 1)[1], dict(params or {})))
        path = url.rsplit("/me/", 1)[1]
        if path == "messages":
            body = self.pages[(params or {}).get("pageToken")]
        else:
            raw = self.messages[path.split("/", 1)[1]]
            body = {"raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)


class GmailApiTests(LinkedCvCase):
    def setUp(self):
        super().setUp()
        self.lines = []
        override = override_settings(
            HUNTER_MAIL_ACCOUNTS="me@gmail.com:5:app pass,work@gmail.com:5:oauth",
            MIMO_API_KEY="key",
            HUNTER_NOTIFY_DESKTOP=False,
        )
        override.enable()
        self.addCleanup(override.disable)

    def newsletter(self, emails):
        return {uid: {"kind": "newsletter", "employer": "", "summary": ""} for uid in emails}

    def test_uids_fit_a_signed_64_bit_column(self):
        self.assertEqual(mail.gmail_uid("ffffffffffffffff"), (1 << 63) - 1)
        self.assertEqual(mail.gmail_uid("19a2b3c4d5e6f708"), 0x19A2B3C4D5E6F708)

    def test_pages_are_followed_known_ids_skipped_and_takeout_rows_adopted(self):
        work = mail.accounts()[1]
        self.assertEqual(work.password, mail.OAUTH)
        MailMessage.objects.create(
            account="work@gmail.com",
            uidvalidity=mail.GMAIL_API,
            uid=mail.gmail_uid("a1"),
            kind="other",
        )
        MailMessage.objects.create(
            account="work@gmail.com",
            uidvalidity=mail.IMPORTED,
            uid=123,
            message_id="<m2@x>",
            kind="rejection",
        )
        session = FakeGmail(
            {
                None: {"messages": [{"id": "a1"}, {"id": "a2"}], "nextPageToken": "p2"},
                "p2": {"messages": [{"id": "a3"}]},
            },
            {
                "a2": raw_email("hr@acme.io", "Thanks", "x", "m2@x"),
                "a3": raw_email("news@x.io", "Weekly", "x", "m3@x"),
            },
        )
        seen = {}

        def classify(emails):
            seen.update(emails)
            return self.newsletter(emails)

        with patch.object(mail, "classify", side_effect=classify):
            saved = mail.sync_gmail(work, self.lines.append, 0, session=session)
        self.assertIn("newer_than:5d", session.calls[0][1]["q"])
        self.assertIn("-in:sent", session.calls[0][1]["q"])
        self.assertEqual(session.calls[1][1].get("pageToken"), "p2")
        self.assertIn(("messages/a2", {"format": "raw"}), session.calls)
        self.assertNotIn("messages/a1", [call[0] for call in session.calls])
        self.assertEqual(list(seen), [mail.gmail_uid("a3")])
        self.assertEqual([m.message_id for m in saved], ["<m3@x>"])
        adopted = MailMessage.objects.get(message_id="<m2@x>")
        self.assertEqual((adopted.uidvalidity, adopted.uid), (mail.GMAIL_API, 0xA2))
        self.assertEqual(adopted.kind, "rejection")

    def test_a_missing_or_dead_sign_in_is_logged_and_other_accounts_still_sync(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with (
            override_settings(DATA_DIR=Path(folder.name)),
            patch.object(mail, "sync_account", return_value=[]) as imap_sync,
        ):
            mail.sync(self.lines.append)
        imap_sync.assert_called_once()
        self.assertIn("run mail_login work@gmail.com again", self.lines[-1])


class MimoDeadlineTests(SimpleTestCase):
    def test_an_answer_that_never_finishes_is_given_up(self):
        release = threading.Event()
        client = MagicMock()
        client.chat.completions.create.side_effect = lambda **request: release.wait(5)
        with self.assertRaises(mimo.MimoTimeout):
            mimo.chat(client, deadline=0.1, model="m")
        release.set()
        client.close.assert_called_once()

    def test_a_prompt_answer_is_returned(self):
        client = MagicMock()
        client.chat.completions.create.return_value = "answer"
        self.assertEqual(mimo.chat(client, model="m"), "answer")
        client.chat.completions.create.assert_called_once_with(model="m")


class EmailCodeTests(LinkedCvCase):
    def setUp(self):
        super().setUp()
        override = override_settings(
            HUNTER_MAIL_ACCOUNTS="me@gmail.com:5:app pass,work@gmail.com:5:oauth",
            MIMO_API_KEY="k",
        )
        override.enable()
        self.addCleanup(override.disable)
        self.since = datetime(2026, 10, 14, 13, 15, 52, tzinfo=UTC)

    def session(self, messages):
        session = FakeGmail({None: {"messages": [{"id": key} for key in messages]}}, {})
        stamps = {key: value[0] for key, value in messages.items()}
        raws = {key: value[1] for key, value in messages.items()}

        def get(url, params=None, timeout=None):
            path = url.rsplit("/me/", 1)[1]
            session.calls.append((path, dict(params or {})))
            if path == "messages":
                body = session.pages[None]
            else:
                key = path.split("/", 1)[1]
                body = {
                    "raw": base64.urlsafe_b64encode(raws[key]).decode().rstrip("="),
                    "internalDate": str(int(stamps[key].timestamp() * 1000)),
                }
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)

        session.get = get
        return session

    def greenhouse(self, code, employer="Affirm"):
        return raw_email(
            "Greenhouse <no-reply@us.greenhouse-mail.io>",
            f"Security code for your application to {employer}",
            "Copy and paste this code into the security code field on your application: "
            f"{code} After you enter the code, resubmit your application.",
            f"{code}@greenhouse",
        )

    def read(self, messages, employer="Affirm", address="work@gmail.com"):
        session = self.session(messages)
        with patch.object(mail, "gmail_session", return_value=session):
            return mail.email_code(address, self.since, employer, wait_seconds=0), session

    def test_the_greenhouse_code_sent_after_the_click_is_read(self):
        later = self.since + timedelta(seconds=3)
        code, session = self.read({"m1": (later, self.greenhouse("aBCDeFG4"))})
        self.assertEqual(code, "aBCDeFG4")
        self.assertIn("after:", session.calls[0][1]["q"])

    def test_an_all_letter_greenhouse_code_is_read(self):
        later = self.since + timedelta(seconds=3)
        code, _ = self.read({"m1": (later, self.greenhouse("URpqhTvf"))})
        self.assertEqual(code, "URpqhTvf")

    def test_a_code_from_before_the_click_is_never_used(self):
        earlier = self.since - timedelta(minutes=5)
        code, _ = self.read({"m1": (earlier, self.greenhouse("OLDcode1"))})
        self.assertEqual(code, "")

    def test_a_generic_code_needs_the_employer_in_the_sender_or_subject(self):
        later = self.since + timedelta(seconds=5)
        body = "Your verification code is: 482913"
        stranger = raw_email("no-reply@bank.example", "Sign-in code", body, "b@x")
        employer = raw_email("talent@kunai.example", "Kunai application", body, "k@x")
        self.assertEqual(self.read({"m1": (later, stranger)}, employer="Kunai")[0], "")
        self.assertEqual(self.read({"m1": (later, employer)}, employer="Kunai")[0], "482913")

    def test_only_a_gmail_api_inbox_can_be_read(self):
        self.assertIsNone(mail.code_account("me@gmail.com"))
        self.assertIsNotNone(mail.code_account("Work@Gmail.com"))
        self.assertEqual(self.read({}, address="me@gmail.com")[0], "")

    def test_the_code_goes_only_into_a_code_field(self):
        code_field = {"ref": "1", "tag": "input", "type": "text", "label": "Security code*"}
        name_field = {"ref": "2", "tag": "input", "type": "text", "label": "First name"}
        box = {"ref": "3", "tag": "input", "type": "checkbox", "label": "Code of conduct"}
        decision = {"action": "email_code"}
        vet = navigator.vet
        self.assertEqual(vet(decision, code_field, {"x.io"}, False, reads_code=True), "")
        self.assertIn("inbox", vet(decision, code_field, {"x.io"}, False))
        self.assertIn("code", vet(decision, name_field, {"x.io"}, False, reads_code=True))
        self.assertIn("text field", vet(decision, box, {"x.io"}, False, reads_code=True))
        zip_field = {"ref": "4", "tag": "input", "type": "text", "label": "Zip code"}
        self.assertIn("code", vet(decision, zip_field, {"x.io"}, False, reads_code=True))
        bare = {
            "ref": "5",
            "tag": "input",
            "type": "text",
            "label": "",
            "group": "Enter the security code we emailed you",
        }
        self.assertEqual(vet(decision, bare, {"x.io"}, False, reads_code=True), "")
        phone = {
            "ref": "6",
            "tag": "input",
            "type": "tel",
            "label": "Phone",
            "group": "Phone number, country code",
        }
        self.assertIn("code", vet(decision, phone, {"x.io"}, False, reads_code=True))

    def test_the_navigator_types_the_code_without_tracing_it(self):
        elements = [
            {
                "ref": "1",
                "tag": "button",
                "type": "submit",
                "text": "Submit application",
                "label": "",
                "group": "",
                "submit": True,
                "in_form": True,
            },
            {
                "ref": "2",
                "tag": "input",
                "type": "text",
                "text": "",
                "label": "Security code",
                "group": "",
                "required": True,
            },
        ]
        decisions = [
            {"action": "click", "ref": "1", "final_submit": True},
            {"action": "email_code", "ref": "2", "value": "guess"},
        ]
        page = MagicMock()
        page.url = "https://job-boards.greenhouse.io/affirm/jobs/1"
        page.context.pages = [page]
        page.evaluate.side_effect = lambda script, *args: (
            [dict(e) for e in elements] if script == navigator.OUTLINE_JS else ""
        )
        reader = MagicMock(return_value="aBCDeFG4")
        with (
            patch.object(
                navigator.Navigator,
                "decide",
                side_effect=lambda shown: (
                    decisions.pop(0) if decisions else {"action": "stuck", "thought": "end"}
                ),
            ),
            patch.object(navigator.Navigator, "type_into") as typed,
        ):
            nav = navigator.Navigator(
                page,
                goal="apply",
                cv_text="",
                job_text="",
                log=lambda line: None,
                code_reader=reader,
            )
            nav.max_steps = 5
            nav.loop()
        typed.assert_called_once()
        self.assertEqual(typed.call_args.args[2], "aBCDeFG4")
        self.assertGreaterEqual(reader.call_args.args[0], nav.started_at)
        self.assertEqual(reader.call_args.args[0], nav.submit_clicked_at)
        self.assertNotIn("aBCDeFG4", json.dumps(nav.trace))
        self.assertEqual(nav.trace[1]["result"], "ok: typed the code from the candidate's email")

    def test_a_code_hold_is_its_own_kind_and_retries_without_confirming(self):
        vacancy = Vacancy.objects.create(
            source="ats",
            external_id="greenhouse:1",
            url="https://job-boards.greenhouse.io/affirm/jobs/1",
            title="Backend",
            cv=self.cv,
            status=Vacancy.Status.NEEDS_REVIEW,
            submitted_at=timezone.now(),
            note="Navigator stuck: The form requires an 8-character email verification code.",
        )
        self.assertEqual(review.kind_of(vacancy), review.EMAIL_CODE)
        self.assertEqual(review.resolve(vacancy.pk, review.RETRY), "")
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.status, Vacancy.Status.READY)

    def test_the_code_naming_this_employer_wins_over_a_newer_one(self):
        later = self.since + timedelta(seconds=3)
        newer = self.since + timedelta(seconds=20)
        messages = {
            "m2": (newer, self.greenhouse("OTHERco1", employer="Kunai")),
            "m1": (later, self.greenhouse("aBCDeFG4")),
        }
        self.assertEqual(self.read(messages)[0], "aBCDeFG4")
        self.assertEqual(self.read(messages, employer="Unknown Co")[0], "OTHERco1")
