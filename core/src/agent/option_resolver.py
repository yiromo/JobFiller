import json
import logging

from agent import llm
from agent.llm_mapper import validate_override

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are matching an already-decided answer to the real options of a \
dropdown/combobox whose choices weren't visible on the page when that answer was first guessed.
You are given, for each field: its label, the intended answer ("wanted"), and the real \
"options" available on the page. Rules:
- If one option means the same thing as "wanted", respond "select" and copy that option \
verbatim — never invent or reword an option.
- If "wanted" does not actually answer what "label" asks (e.g. a name, URL, or other text \
unrelated to the question), or no option is a reasonable match, respond "skip". Never force a \
mismatched option.
Respond with a JSON object: {"fields": [{"ref": <ref>, "value": <string>, \
"action": "select"|"skip", "confidence": <0-1 number>}, ...]} — one entry per field given, in \
the same order, using the exact "ref" values given."""


def resolve_options(fields: list[dict]) -> list[dict]:
    if not llm.ready("options") or not fields:
        return [_skip(f["ref"]) for f in fields]

    try:
        overrides = {o["ref"]: o for o in _call_llm(fields)}
    except Exception:
        logger.exception("LLM option resolution call failed; leaving fields skipped")
        return [_skip(f["ref"]) for f in fields]

    results = []
    for f in fields:
        if f["ref"] not in overrides:
            results.append(_skip(f["ref"]))
            continue
        result = validate_override(overrides[f["ref"]], f)
        results.append(result if result["action"] == "select" else _skip(f["ref"]))
    return results


def _skip(ref: str) -> dict:
    return {"ref": ref, "value": "", "action": "skip", "confidence": 0.0}


def _call_llm(fields: list[dict]) -> list[dict]:
    user_content = json.dumps(
        {
            "fields": [
                {
                    "ref": f["ref"],
                    "label": f.get("label", ""),
                    "wanted": f.get("wanted", ""),
                    "options": f.get("options", []),
                }
                for f in fields
            ]
        }
    )
    parsed = json.loads(
        llm.complete("options", _SYSTEM_PROMPT, user_content, json_mode=True, timeout=45)
    )
    fields_out = parsed.get("fields", [])
    logger.warning("LLM raw option resolution: %s", fields_out)
    return fields_out
