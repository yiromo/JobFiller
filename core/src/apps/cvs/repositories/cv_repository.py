from apps.cvs.dto import CvDTO
from apps.cvs.models import Cv

from .interfaces import ICvRepository


class CvRepository(ICvRepository):
    def create(
        self,
        file,
        original_filename: str,
        raw_text: str,
        full_name: str,
        email: str,
        phone: str,
    ) -> CvDTO:
        obj = Cv.objects.create(
            file=file,
            original_filename=original_filename,
            raw_text=raw_text,
            full_name=full_name,
            email=email,
            phone=phone,
        )
        return self._to_dto(obj)

    def list_cvs(self) -> list[CvDTO]:
        return [self._to_dto(obj) for obj in Cv.objects.all()]

    def get(self, cv_id: int) -> CvDTO | None:
        obj = Cv.objects.filter(id=cv_id).first()
        return self._to_dto(obj) if obj else None

    @staticmethod
    def _to_dto(obj: Cv) -> CvDTO:
        return CvDTO(
            id=obj.id,
            original_filename=obj.original_filename,
            full_name=obj.full_name,
            email=obj.email,
            phone=obj.phone,
            uploaded_at=obj.uploaded_at,
            file_path=obj.file.path,
        )
