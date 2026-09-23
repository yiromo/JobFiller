import base64
import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from django.conf import settings

from agent import analyzer, cover_letter, question_answer
from agent.eeo_mapper import resolve_eeo_fields
from agent.field_mapper import build_fill_plan, is_cover_letter_field
from agent.llm_mapper import augment_skipped_fields
from agent.option_resolver import resolve_options
from agent.profile import Profile
from apps.applications.dto import ScanRequestDTO, ScanResultDTO
from apps.applications.repositories.interfaces import IApplicationRepository
from apps.cvs.dto import CvDTO
from apps.cvs.repositories.interfaces import ICvRepository

logger = logging.getLogger(__name__)

_COVER_LETTER_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ApplicationNotFoundError(Exception):
    pass


class NoCvOnApplicationError(Exception):
    pass


class MimoNotConfiguredError(Exception):
    pass


class SearchNotConfiguredError(Exception):
    pass


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

        base_plan = build_fill_plan(payload.form_snapshot, profile, resolved_cv_id)

        passes = [
            (
                {"eeo_pending"},
                lambda: self._resolve_eeo(base_plan, payload.form_snapshot, payload.eeo_answers),
            )
        ]
        if cv is not None:
            passes.append(
                (
                    {"skip"},
                    lambda: augment_skipped_fields(
                        form_snapshot=payload.form_snapshot,
                        field_mapping=base_plan,
                        cv_raw_text=cv.raw_text,
                        page_text=payload.page_text,
                        screenshot=payload.screenshot,
                    ),
                )
            )
            passes.append(
                (
                    {"cover_letter_upload", "cover_letter_type"},
                    lambda: self._resolve_cover_letter(
                        base_plan, cv, payload.page_text, payload.about_text
                    ),
                )
            )
        field_mapping = self._run_resolution_passes(base_plan, passes)

        site = urlparse(payload.url).netloc
        return self._repo.create(
            url=payload.url,
            site=site,
            form_snapshot=payload.form_snapshot,
            field_mapping=field_mapping,
            cv_id=resolved_cv_id,
        )

    @staticmethod
    def _run_resolution_passes(
        base_plan: list[dict], passes: list[tuple[set[str], object]]
    ) -> list[dict]:
        owned = [
            ({item["ref"] for item in base_plan if item["action"] in actions}, run)
            for actions, run in passes
        ]
        active = [(refs, run) for refs, run in owned if refs]
        if not active:
            return base_plan

        with ThreadPoolExecutor(max_workers=len(active)) as pool:
            futures = [(refs, pool.submit(run)) for refs, run in active]
            results = [(refs, future.result()) for refs, future in futures]

        overrides = {}
        for refs, resolved in results:
            for item in resolved:
                if item["ref"] in refs:
                    overrides[item["ref"]] = item
        return [overrides.get(item["ref"], item) for item in base_plan]

    @staticmethod
    def _resolve_eeo(
        field_mapping: list[dict], form_snapshot: list[dict], eeo_answers: list[dict]
    ) -> list[dict]:
        pending_refs = {item["ref"] for item in field_mapping if item["action"] == "eeo_pending"}
        if not pending_refs:
            return field_mapping

        fields_by_ref = {field["ref"]: field for field in form_snapshot}
        pending_fields = [fields_by_ref[ref] for ref in pending_refs if ref in fields_by_ref]
        resolved_by_ref = {r["ref"]: r for r in resolve_eeo_fields(pending_fields, eeo_answers)}

        return [
            resolved_by_ref.get(
                item["ref"], {"ref": item["ref"], "value": "", "action": "skip", "confidence": 0.0}
            )
            if item["action"] == "eeo_pending"
            else item
            for item in field_mapping
        ]

    @staticmethod
    def _resolve_cover_letter(
        field_mapping: list[dict], cv: CvDTO, page_text: str, about_text: str
    ) -> list[dict]:
        placeholders = {"cover_letter_upload", "cover_letter_type"}
        if not any(item["action"] in placeholders for item in field_mapping):
            return field_mapping

        text = None
        if settings.MIMO_API_KEY:
            try:
                text = cover_letter.generate(cv.raw_text, page_text, cv.full_name, about_text)
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
                    resolved.append(
                        {
                            "ref": item["ref"],
                            "value": "",
                            "action": "upload",
                            "confidence": 0.9,
                            "file": ApplicationService._cover_letter_file_payload(cv, text),
                        }
                    )
                else:
                    resolved.append({**item, "value": "", "action": "skip", "confidence": 0.0})
            else:
                resolved.append(item)
        return resolved

    def resolve_options(self, application_id: int, fields: list[dict]) -> list[dict]:
        record = self._repo.get(application_id)
        if record is None:
            raise ApplicationNotFoundError

        labels_by_ref = {
            f["ref"]: f.get("label") or f.get("section", "") for f in record.form_snapshot
        }
        enriched = [{**f, "label": labels_by_ref.get(f["ref"], "")} for f in fields]
        resolved = resolve_options(enriched)

        resolved_by_ref = {r["ref"]: r for r in resolved}
        field_mapping = [resolved_by_ref.get(item["ref"], item) for item in record.field_mapping]
        self._repo.update_field_mapping(application_id, field_mapping)

        return resolved

    def regenerate_cover_letter(self, application_id: int, page_text: str, about_text: str) -> dict:
        record = self._repo.get(application_id)
        if record is None:
            raise ApplicationNotFoundError

        cv = self._cv_repo.get(record.cv_id) if record.cv_id is not None else None
        if cv is None:
            raise NoCvOnApplicationError

        if not settings.MIMO_API_KEY:
            raise MimoNotConfiguredError

        text = cover_letter.generate(cv.raw_text, page_text, cv.full_name, about_text)

        entries = [
            self._cover_letter_entry(field, cv, text)
            for field in record.form_snapshot
            if is_cover_letter_field(field)
        ]
        entries_by_ref = {entry["ref"]: entry for entry in entries}
        field_mapping = [entries_by_ref.get(item["ref"], item) for item in record.field_mapping]
        self._repo.update_field_mapping(application_id, field_mapping)

        return {"text": text, "entries": entries}

    def analyze_application(self, application_id: int, page_text: str, about_text: str) -> dict:
        record = self._repo.get(application_id)
        if record is None:
            raise ApplicationNotFoundError

        cv = self._cv_repo.get(record.cv_id) if record.cv_id is not None else None
        if cv is None:
            raise NoCvOnApplicationError

        if not settings.MIMO_API_KEY:
            raise MimoNotConfiguredError
        if not settings.TAVILY_API_KEY:
            raise SearchNotConfiguredError

        return analyzer.analyze(cv.raw_text, page_text, cv.full_name, about_text)

    def generate_question_answer(self, application_id: int, question: str, page_text: str) -> dict:
        record = self._repo.get(application_id)
        if record is None:
            raise ApplicationNotFoundError

        cv = self._cv_repo.get(record.cv_id) if record.cv_id is not None else None
        if cv is None:
            raise NoCvOnApplicationError

        if not settings.MIMO_API_KEY:
            raise MimoNotConfiguredError

        text = question_answer.generate(cv.raw_text, question, page_text)
        return {"text": text}

    @staticmethod
    def _cover_letter_entry(field: dict, cv: CvDTO, text: str) -> dict:
        ref = field["ref"]
        if field.get("type") == "file":
            return {
                "ref": ref,
                "value": "",
                "action": "upload",
                "confidence": 0.9,
                "file": ApplicationService._cover_letter_file_payload(cv, text),
            }
        return {"ref": ref, "value": text, "action": "type", "confidence": 0.9}

    @staticmethod
    def _cover_letter_file_payload(cv: CvDTO, text: str) -> dict:
        filename = f"Cover_Letter_{cv.full_name.replace(' ', '_') or 'Applicant'}.docx"
        file_bytes = cover_letter.render_docx(text)
        return {
            "filename": filename,
            "mime_type": _COVER_LETTER_MIME,
            "base64": base64.b64encode(file_bytes).decode("ascii"),
        }

    @staticmethod
    def _profile_from_cv(cv: CvDTO) -> Profile:
        return Profile(
            full_name=cv.full_name,
            email=cv.email,
            phone=cv.phone,
            linkedin_url=cv.linkedin_url,
            git_url=cv.git_url,
        )
