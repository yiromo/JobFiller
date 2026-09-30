import random
from dataclasses import dataclass, field

CONTRACT = (
    "SITE",
    "NAME",
    "LOGIN_URL",
    "USES_RESUME_LINKS",
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


@dataclass
class VacancyPage:
    title: str
    employer: str
    text: str
    has_respond_button: bool


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

    @property
    def needs_relocation(self) -> bool:
        return self.relocation_warning and not self.remote


def pause(page, low: float = 0.8, high: float = 2.2) -> None:
    page.wait_for_timeout(int(random.uniform(low, high) * 1000))
