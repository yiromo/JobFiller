from abc import ABC, abstractmethod

from apps.applications.dto import ApplicationDTO, ScanResultDTO


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

    @abstractmethod
    def get(self, application_id: int) -> ApplicationDTO | None: ...

    @abstractmethod
    def update_field_mapping(self, application_id: int, field_mapping: list[dict]) -> None: ...
