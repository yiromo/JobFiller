import random
from dataclasses import dataclass, field

CONTRACT = (
    "SITE",
    "NAME",
    "LOGIN_URL",
    "USES_RESUME_LINKS",
    "SCRIPTED_APPLY",
    "WANTS_LETTER",
    "RECHECK_BATCH",
    "NAVIGABLE",
    "handles",
    "origin",
    "expand_source",
    "is_logged_in",
    "check_captcha",
    "crawl",
    "read_vacancy",
    "response_status",
    "apply",
    "open_for_apply",
    "navigator_goal",
    "pause",
)


class CaptchaError(RuntimeError):
    pass


@dataclass
class Listing:
    external_id: str
    url: str
    title: str
    employer: str
    external_apply: bool = False


@dataclass
class VacancyPage:
    title: str
    employer: str
    text: str
    has_respond_button: bool
    external_apply: bool = False


@dataclass
class ResponseStatus:
    already_applied: bool
    impossible: bool
    letter_required: bool
    has_test: bool
    letter_max_length: int
    resume_hashes: set[str] = field(default_factory=set)
    relocation_warning: bool = False
    remote: bool = False
    external_apply: bool = False

    @property
    def needs_relocation(self) -> bool:
        return self.relocation_warning and not self.remote


def pause(page, low: float = 0.8, high: float = 2.2) -> None:
    page.wait_for_timeout(int(random.uniform(low, high) * 1000))


def external_goal(job: str, button: str, letter: str) -> str:
    lines = [
        f"Apply to {job} on the employer's own website.",
        f"Press '{button}'. It opens the employer's careers page, usually in a new tab.",
        (
            "On the employer's page open the application form (e.g. 'Apply' or 'Apply for this "
            "job'), fill every field from the CV, candidate_contact and candidate_facts, and use "
            "the upload action wherever it asks for a résumé or CV file."
        ),
        (
            "If the site asks you to sign in, log in or create an account before applying, reply "
            "stuck: the agent never signs in or registers on employer sites."
        ),
        (
            "Submit the form. The application is sent only when the page confirms it (e.g. "
            "'Thank you for applying' or 'Application received')."
        ),
    ]
    if letter:
        lines.append(f"If there is a cover letter field, paste this letter:\n{letter}")
    return "\n".join(lines)
