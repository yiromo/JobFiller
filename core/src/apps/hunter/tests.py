import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.cvs.models import Cv
from apps.hunter import evidence, inbox, navigator, notify, service, state
from apps.hunter.models import ResumeLink, Vacancy
from apps.hunter.service import RunSummary, letter_language
from apps.hunter.sources import (
    ADAPTERS,
    adapter_for,
    dsml,
    hh,
    indeed,
    linkedin,
    missing_contract,
)


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
