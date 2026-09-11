from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CvDTO:
    id: int
    original_filename: str
    full_name: str
    email: str
    phone: str
    linkedin_url: str
    git_url: str
    uploaded_at: datetime
    file_path: str
