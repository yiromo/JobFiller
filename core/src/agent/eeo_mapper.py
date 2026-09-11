import json
import logging

from django.conf import settings
from openai import OpenAI

from agent.llm_mapper import validate_override

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are matching a job applicant's own previously-stated answers to \
EEO/demographic form fields (gender, race, ethnicity, veteran status, disability status, etc.).
You are given the applicant's own answer rows ("match": a topic keyword, "answer": what they \
told you in their own words) and a list of form fields. Rules:
- Use ONLY the given rows. Never invent, infer, or guess an answer that is not a direct \
restatement of a row's "answer" text.
- For each field, decide whether any row is about the same topic as the field's label (a \
"hispanic"/"latino" row answers a Hispanic-or-Latino ethnicity question, not a general race \
question, and vice versa — treat them as distinct topics).
- If a matching row exists: for a field with a non-empty "options" list, respond with "select" \
and copy one option verbatim (choose the option that best represents the row's stated answer — \
e.g. a "no" answer to a disability question should select a "No, I do not have a disability" \
style option, not a decline-to-answer option, unless the row's answer itself says the applicant \
prefers not to disclose). For a field with no options list, respond with "type" and a short, \
direct restatement of the row's answer (normalize wording, e.g. "im asian" -> "Asian"), not the \
row's raw text verbatim.
- If no row is about the same topic as a field, or the row's answer doesn't clearly resolve the \
field's question, respond with "skip" — never guess.
Respond with a JSON object: {"fields": [{"ref": <ref>, "value": <string>, \
"action": "type"|"select"|"skip", "confidence": <0-1 number>}, ...]} — one entry per field \
given, in the same order, using the exact "ref" values given."""


def resolve_eeo_fields(fields: list[dict], eeo_answers: list[dict]) -> list[dict]:
    if not settings.MIMO_API_KEY or not fields or not eeo_answers:
        return [_skip(field["ref"]) for field in fields]

    try:
        overrides = {o["ref"]: o for o in _call_llm(fields, eeo_answers)}
    except Exception:
        logger.exception("MiMo EEO mapping call failed; leaving fields skipped")
        return [_skip(field["ref"]) for field in fields]

    return [
        validate_override(overrides[field["ref"]], field)
        if field["ref"] in overrides
        else _skip(field["ref"])
        for field in fields
    ]


def _skip(ref: str) -> dict:
    return {"ref": ref, "value": "", "action": "skip", "confidence": 0.0}


def _call_llm(fields: list[dict], eeo_answers: list[dict]) -> list[dict]:
    client = OpenAI(api_key=settings.MIMO_API_KEY, base_url=settings.MIMO_BASE_URL)
    user_content = json.dumps(
        {
            "answers": [
                {"match": row.get("match", ""), "answer": row.get("answer", "")}
                for row in eeo_answers
                if row.get("match") and row.get("answer")
            ],
            "fields": [
                {
                    "ref": field["ref"],
                    "label": field.get("label", ""),
                    "tag": field.get("tag", ""),
                    "type": field.get("type", ""),
                    "role": field.get("role", ""),
                    "options": field.get("options", []),
                }
                for field in fields
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
    fields_out = parsed.get("fields", [])
    logger.warning("MiMo raw EEO mapping: %s", fields_out)
    return fields_out
