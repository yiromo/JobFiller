import json
import logging

from django.conf import settings
from openai import OpenAI

from agent.field_mapper import EEO_KEYWORDS, field_haystack

logger = logging.getLogger(__name__)

# Legal/consent attestations ("I agree to...", AI-use disclaimers, privacy
# policy acknowledgment) are the applicant's own click, not something to
# auto-answer even with high confidence — same hard-skip treatment as EEO.
_ATTESTATION_KEYWORDS = (
    "i agree",
    "i confirm",
    "i have read",
    "i understand",
    "i acknowledge",
    "consent",
    "privacy policy",
    "privacy notice",
    "terms of service",
    "terms and conditions",
)

# Logistics/preference questions a CV cannot answer — a model asked to guess
# will confidently guess anyway (observed live: "willing to travel?" -> "Yes",
# confidence 1.0). Pre-filtered out rather than trusted to the prompt's
# "skip if unknowable" instruction, same as EEO/attestations.
_LOGISTICS_KEYWORDS = (
    "willing and able",
    "willing to travel",
    "willing to relocate",
    "relocat",
    "salary",
    "compensation expectation",
    "notice period",
    "visa sponsorship",
    "require sponsorship",
    "available to start",
    "start date",
)

_SYSTEM_PROMPT = """You fill in job application form fields using ONLY facts grounded in the \
candidate's CV (and, for context, the job posting text). Rules:
- Never invent employers, dates, numbers, or skills that are not in the CV.
- Write answers in first person.
- If a field's tag is "select" or its role is "combobox": respond with "select" and, when a \
non-empty options list is given, copy one option verbatim; otherwise give a short canonical \
value (e.g. a country or degree name) for the extension to pick from the page's own list.
- For "input"/"textarea" fields, respond with "type" and a free-text answer, concise \
(roughly 50-150 words unless the question implies a single fact).
- If the CV does not support a confident, honest answer (unknown fact, or a personal/logistics \
question like salary, relocation, or availability with no CV basis), respond with "skip" — \
never guess.
Respond with a JSON object: {"fields": [{"ref": <ref>, "value": <string>, \
"action": "type"|"select"|"skip", "confidence": <0-1 number>}, ...]} — one entry per field \
given, in the same order, using the exact "ref" values given."""


def _is_llm_eligible(field: dict) -> bool:
    haystack = field_haystack(field)
    never_llm_keywords = EEO_KEYWORDS + _ATTESTATION_KEYWORDS + _LOGISTICS_KEYWORDS
    return not any(keyword in haystack for keyword in never_llm_keywords)


def augment_skipped_fields(
    form_snapshot: list[dict],
    field_mapping: list[dict],
    cv_raw_text: str,
    page_text: str,
) -> list[dict]:
    if not settings.MIMO_API_KEY:
        return field_mapping

    fields_by_ref = {field["ref"]: field for field in form_snapshot}
    candidates = [
        fields_by_ref[mapping["ref"]]
        for mapping in field_mapping
        if mapping["action"] == "skip"
        and mapping["ref"] in fields_by_ref
        and _is_llm_eligible(fields_by_ref[mapping["ref"]])
    ]
    if not candidates:
        return field_mapping

    try:
        overrides = {o["ref"]: o for o in _call_llm(candidates, cv_raw_text, page_text)}
    except Exception:
        # A flaky/misconfigured LLM call must degrade to the heuristic's plan,
        # never crash the scan.
        logger.exception("MiMo field-mapping call failed; leaving fields skipped")
        return field_mapping

    return [
        _validate_override(overrides[mapping["ref"]], fields_by_ref[mapping["ref"]])
        if mapping["ref"] in overrides
        else mapping
        for mapping in field_mapping
    ]


def _call_llm(candidates: list[dict], cv_raw_text: str, page_text: str) -> list[dict]:
    client = OpenAI(api_key=settings.MIMO_API_KEY, base_url=settings.MIMO_BASE_URL)
    user_content = json.dumps(
        {
            "cv_text": cv_raw_text[:8000],
            "job_posting_text": (page_text or "")[:8000],
            "fields": [
                {
                    "ref": field["ref"],
                    "label": field.get("label", ""),
                    "tag": field.get("tag", ""),
                    "type": field.get("type", ""),
                    "role": field.get("role", ""),
                    "options": field.get("options", []),
                    "required": field.get("required", False),
                }
                for field in candidates
            ],
        }
    )
    response = client.chat.completions.create(
        model=settings.MIMO_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        timeout=45,
    )
    parsed = json.loads(response.choices[0].message.content)
    return parsed.get("fields", [])


def _validate_override(override: dict, field: dict) -> dict:
    ref = field["ref"]
    action = override.get("action")
    value = str(override.get("value") or "")
    confidence = override.get("confidence", 0.5)

    if action not in ("type", "select") or not value:
        return {"ref": ref, "value": "", "action": "skip", "confidence": 0.0}

    # A native <select>'s options are a closed set — an invented option would
    # silently fail to apply in the page, so fall back to skip rather than
    # ship a value that can't actually be selected.
    options = field.get("options") or []
    if action == "select" and options:
        value_lower = value.strip().lower()
        matched = next((o for o in options if o.strip().lower() == value_lower), None)
        if matched is None:
            matched = next((o for o in options if value_lower in o.strip().lower()), None)
        if matched is None:
            return {"ref": ref, "value": "", "action": "skip", "confidence": 0.0}
        value = matched

    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.5

    return {"ref": ref, "value": value, "action": action, "confidence": confidence}
