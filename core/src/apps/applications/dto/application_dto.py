from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ScanRequestDTO:
    url: str
    form_snapshot: list[dict]
    cv_id: int | None = None


@dataclass(frozen=True)
class ScanResultDTO:
    id: int
    url: str
    site: str
    field_mapping: list[dict]
    created_at: datetime
