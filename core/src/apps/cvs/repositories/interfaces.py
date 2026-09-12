from abc import ABC, abstractmethod

from apps.cvs.dto import CvDTO


class ICvRepository(ABC):
    @abstractmethod
    def create(
        self,
        file,
        original_filename: str,
        raw_text: str,
        full_name: str,
        email: str,
        phone: str,
        linkedin_url: str,
        git_url: str,
    ) -> CvDTO: ...

    @abstractmethod
    def list_cvs(self) -> list[CvDTO]: ...

    @abstractmethod
    def get(self, cv_id: int) -> CvDTO | None: ...

    @abstractmethod
    def delete(self, cv_id: int) -> bool: ...
