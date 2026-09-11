from apps.applications.dto import ApplicationDTO, ScanResultDTO
from apps.applications.models import Application

from .interfaces import IApplicationRepository


class ApplicationRepository(IApplicationRepository):
    def create(
        self,
        url: str,
        site: str,
        form_snapshot: list[dict],
        field_mapping: list[dict],
        cv_id: int | None,
    ) -> ScanResultDTO:
        obj = Application.objects.create(
            url=url,
            site=site,
            cv_id=cv_id,
            form_snapshot=form_snapshot,
            field_mapping=field_mapping,
        )
        return self._to_dto(obj)

    def get(self, application_id: int) -> ApplicationDTO | None:
        obj = Application.objects.filter(id=application_id).first()
        return self._to_full_dto(obj) if obj else None

    def update_field_mapping(self, application_id: int, field_mapping: list[dict]) -> None:
        Application.objects.filter(id=application_id).update(field_mapping=field_mapping)

    @staticmethod
    def _to_dto(obj: Application) -> ScanResultDTO:
        return ScanResultDTO(
            id=obj.id,
            url=obj.url,
            site=obj.site,
            field_mapping=obj.field_mapping,
            created_at=obj.created_at,
        )

    @staticmethod
    def _to_full_dto(obj: Application) -> ApplicationDTO:
        return ApplicationDTO(
            id=obj.id,
            url=obj.url,
            site=obj.site,
            cv_id=obj.cv_id,
            form_snapshot=obj.form_snapshot,
            field_mapping=obj.field_mapping,
            created_at=obj.created_at,
        )
