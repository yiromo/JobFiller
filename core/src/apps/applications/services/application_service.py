from urllib.parse import urlparse

from agent.field_mapper import build_fill_plan
from agent.profile import Profile
from apps.applications.dto import ScanRequestDTO, ScanResultDTO
from apps.applications.repositories.interfaces import IApplicationRepository
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
        profile, resolved_cv_id = self._resolve_profile(payload.cv_id)
        field_mapping = build_fill_plan(payload.form_snapshot, profile, resolved_cv_id)
        site = urlparse(payload.url).netloc
        return self._repo.create(
            url=payload.url,
            site=site,
            form_snapshot=payload.form_snapshot,
            field_mapping=field_mapping,
            cv_id=resolved_cv_id,
        )

    def _resolve_profile(self, cv_id: int | None) -> tuple[Profile | None, int | None]:
        if cv_id is None:
            return None, None
        cv = self._cv_repo.get(cv_id)
        if cv is None:
            return None, None
        return Profile(full_name=cv.full_name, email=cv.email, phone=cv.phone), cv.id
