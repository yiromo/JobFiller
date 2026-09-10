from urllib.parse import urlparse

from apps.applications.dto import ScanRequestDTO, ScanResultDTO
from apps.applications.repositories.interfaces import IApplicationRepository

# Fields typed straight through; anything else is skipped. Replaced by
# apps/agent/field_mapper.py in a later commit — this only proves the
# scan -> fill-plan -> DOM wiring works end to end.
_TYPEABLE = {"text", "email", "tel"}


class ApplicationService:
    def __init__(self, application_repo: IApplicationRepository) -> None:
        self._repo = application_repo

    def scan(self, payload: ScanRequestDTO) -> ScanResultDTO:
        field_mapping = self._stub_fill_plan(payload.form_snapshot)
        site = urlparse(payload.url).netloc
        return self._repo.create(
            url=payload.url,
            site=site,
            form_snapshot=payload.form_snapshot,
            field_mapping=field_mapping,
        )

    @staticmethod
    def _stub_fill_plan(form_snapshot: list[dict]) -> list[dict]:
        plan = []
        for field in form_snapshot:
            if field.get("type") in _TYPEABLE:
                plan.append(
                    {
                        "ref": field["ref"],
                        "value": f"placeholder-{field['ref']}",
                        "action": "type",
                        "confidence": 0.0,
                    }
                )
            else:
                plan.append(
                    {"ref": field["ref"], "value": "", "action": "skip", "confidence": 0.0}
                )
        return plan
