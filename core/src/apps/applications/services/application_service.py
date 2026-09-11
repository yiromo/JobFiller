import base64
import logging
from urllib.parse import urlparse

from django.conf import settings

from agent import cover_letter
from agent.field_mapper import build_fill_plan
from agent.llm_mapper import augment_skipped_fields
from agent.profile import Profile
from apps.applications.dto import ScanRequestDTO, ScanResultDTO
from apps.applications.repositories.interfaces import IApplicationRepository
from apps.cvs.dto import CvDTO
from apps.cvs.repositories.interfaces import ICvRepository

logger = logging.getLogger(__name__)

_COVER_LETTER_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ApplicationService:
    def __init__(
        self,
        application_repo: IApplicationRepository,
        cv_repo: ICvRepository,
    ) -> None:
        self._repo = application_repo
        self._cv_repo = cv_repo

    def scan(self, payload: ScanRequestDTO) -> ScanResultDTO:
        cv = self._cv_repo.get(payload.cv_id) if payload.cv_id is not None else None
        profile = self._profile_from_cv(cv) if cv else None
        resolved_cv_id = cv.id if cv else None

        field_mapping = build_fill_plan(payload.form_snapshot, profile, resolved_cv_id)
        if cv is not None:
            field_mapping = augment_skipped_fields(
                form_snapshot=payload.form_snapshot,
                field_mapping=field_mapping,
                cv_raw_text=cv.raw_text,
                page_text=payload.page_text,
            )
            field_mapping = self._resolve_cover_letter(field_mapping, cv, payload.page_text)

        site = urlparse(payload.url).netloc
        return self._repo.create(
            url=payload.url,
            site=site,
            form_snapshot=payload.form_snapshot,
            field_mapping=field_mapping,
            cv_id=resolved_cv_id,
        )

    @staticmethod
    def _resolve_cover_letter(
        field_mapping: list[dict], cv: CvDTO, page_text: str
    ) -> list[dict]:
        placeholders = {"cover_letter_upload", "cover_letter_type"}
        if not any(item["action"] in placeholders for item in field_mapping):
            return field_mapping

        text = None
        if settings.MIMO_API_KEY:
            try:
                text = cover_letter.generate(cv.raw_text, page_text, cv.full_name)
            except Exception:
                logger.exception("Cover letter generation failed; leaving fields skipped")

        resolved = []
        for item in field_mapping:
            if item["action"] == "cover_letter_type":
                if text:
                    resolved.append(
                        {"ref": item["ref"], "value": text, "action": "type", "confidence": 0.9}
                    )
                else:
                    resolved.append({**item, "value": "", "action": "skip", "confidence": 0.0})
            elif item["action"] == "cover_letter_upload":
                if text:
                    filename = f"Cover_Letter_{cv.full_name.replace(' ', '_') or 'Applicant'}.docx"
                    file_bytes = cover_letter.render_docx(text)
                    resolved.append(
                        {
                            "ref": item["ref"],
                            "value": "",
                            "action": "upload",
                            "confidence": 0.9,
                            "file": {
                                "filename": filename,
                                "mime_type": _COVER_LETTER_MIME,
                                "base64": base64.b64encode(file_bytes).decode("ascii"),
                            },
                        }
                    )
                else:
                    resolved.append({**item, "value": "", "action": "skip", "confidence": 0.0})
            else:
                resolved.append(item)
        return resolved

    @staticmethod
    def _profile_from_cv(cv: CvDTO) -> Profile:
        return Profile(
            full_name=cv.full_name,
            email=cv.email,
            phone=cv.phone,
            linkedin_url=cv.linkedin_url,
            git_url=cv.git_url,
        )
