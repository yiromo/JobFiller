from abc import ABC, abstractmethod

from apps.applications.dto import ScanResultDTO


class IApplicationRepository(ABC):
    @abstractmethod
    def create(
        self,
        url: str,
        site: str,
        form_snapshot: list[dict],
        field_mapping: list[dict],
        cv_id: int | None,
    ) -> ScanResultDTO: ...
