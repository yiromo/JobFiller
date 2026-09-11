from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ScanRequestDTO:
    url: str
    form_snapshot: list[dict]
    cv_id: int | None = None
    page_text: str = ""
    eeo_answers: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ScanResultDTO:
    id: int
    url: str
    site: str
    field_mapping: list[dict]
    created_at: datetime
