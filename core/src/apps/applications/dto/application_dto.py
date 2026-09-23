from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ScanRequestDTO:
    url: str
    form_snapshot: list[dict]
    cv_id: int | None = None
    page_text: str = ""
    about_text: str = ""
    eeo_answers: list[dict] = field(default_factory=list)
    screenshot: str = ""


@dataclass(frozen=True)
class ScanResultDTO:
    id: int
    url: str
    site: str
    field_mapping: list[dict]
    created_at: datetime


@dataclass(frozen=True)
class ApplicationDTO:
    id: int
    url: str
    site: str
    cv_id: int | None
    form_snapshot: list[dict]
    field_mapping: list[dict]
    created_at: datetime
