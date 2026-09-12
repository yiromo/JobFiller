from agent.profile import extract_profile
from apps.cvs.dto import CvDTO
from apps.cvs.repositories.interfaces import ICvRepository
from apps.cvs.text_extraction import extract_text


class CvService:
    def __init__(self, cv_repo: ICvRepository) -> None:
        self._repo = cv_repo

    def upload(self, file, original_filename: str) -> CvDTO:
        raw_text = extract_text(file, original_filename)
        file.seek(0)  # extraction consumes the stream; rewind before saving it
        profile = extract_profile(raw_text, original_filename)
        return self._repo.create(
            file=file,
            original_filename=original_filename,
            raw_text=raw_text,
            full_name=profile.full_name,
            email=profile.email,
            phone=profile.phone,
            linkedin_url=profile.linkedin_url,
            git_url=profile.git_url,
        )

    def list_cvs(self) -> list[CvDTO]:
        return self._repo.list_cvs()

    def get(self, cv_id: int) -> CvDTO | None:
        return self._repo.get(cv_id)

    def delete(self, cv_id: int) -> bool:
        return self._repo.delete(cv_id)
