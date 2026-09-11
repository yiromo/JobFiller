from urllib.parse import urlparse

from agent.field_mapper import build_fill_plan
from agent.llm_mapper import augment_skipped_fields
from agent.profile import Profile
from apps.applications.dto import ScanRequestDTO, ScanResultDTO
from apps.applications.repositories.interfaces import IApplicationRepository
from apps.cvs.dto import CvDTO
from apps.cvs.repositories.interfaces import ICvRepository


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

        site = urlparse(payload.url).netloc
        return self._repo.create(
            url=payload.url,
            site=site,
            form_snapshot=payload.form_snapshot,
            field_mapping=field_mapping,
            cv_id=resolved_cv_id,
        )

    @staticmethod
    def _profile_from_cv(cv: CvDTO) -> Profile:
        return Profile(
            full_name=cv.full_name,
            email=cv.email,
            phone=cv.phone,
            linkedin_url=cv.linkedin_url,
            git_url=cv.git_url,
        )
