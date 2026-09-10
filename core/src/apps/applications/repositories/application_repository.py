from apps.applications.dto import ScanResultDTO
from apps.applications.models import Application

from .interfaces import IApplicationRepository


class ApplicationRepository(IApplicationRepository):
    def create(
        self,
        url: str,
        site: str,
        form_snapshot: list[dict],
        field_mapping: list[dict],
    ) -> ScanResultDTO:
        obj = Application.objects.create(
            url=url,
            site=site,
            form_snapshot=form_snapshot,
            field_mapping=field_mapping,
        )
        return self._to_dto(obj)

    @staticmethod
    def _to_dto(obj: Application) -> ScanResultDTO:
        return ScanResultDTO(
            id=obj.id,
            url=obj.url,
            site=obj.site,
            field_mapping=obj.field_mapping,
            created_at=obj.created_at,
        )
