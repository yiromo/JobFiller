import json
import os

from django.conf import settings

from agent.cover_letter import DEFAULT_SIZE, SIZES

MAX_ROWS = 50
APPLY_SCOPES = ("relevant", "broad", "all")
DEFAULT_SCOPE = "broad"


def inbox_dir():
    return settings.DATA_DIR / "hunter-inbox"


def eeo_path():
    return inbox_dir() / "eeo.json"


def choice_path(name: str):
    return inbox_dir() / f"{name}.json"


def clean_rows(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise TypeError("answers must be a list")
    cleaned = []
    for row in rows[:MAX_ROWS]:
        if not isinstance(row, dict):
            raise TypeError("each answer must be an object")
        match = str(row.get("match") or "").strip()[:100]
        answer = str(row.get("answer") or "").strip()[:200]
        if match:
            cleaned.append({"match": match, "answer": answer})
    return cleaned


def write_atomic(path, value) -> None:
    inbox_dir().mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    os.replace(temporary, path)


def write_eeo(rows) -> list[dict]:
    cleaned = clean_rows(rows)
    write_atomic(eeo_path(), cleaned)
    return cleaned


def read_eeo() -> list[dict]:
    try:
        return clean_rows(json.loads(eeo_path().read_text()))
    except (OSError, ValueError, TypeError):
        return []


def answered_eeo() -> list[dict]:
    return [row for row in read_eeo() if row["answer"]]


def write_choice(name: str, value, choices: tuple) -> str:
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(choices)}")
    write_atomic(choice_path(name), {"value": value})
    return value


def read_choice(name: str, choices: tuple, default: str) -> str:
    try:
        value = json.loads(choice_path(name).read_text()).get("value")
    except (OSError, ValueError, AttributeError):
        return default
    return value if value in choices else default


def write_letter_size(size) -> str:
    return write_choice("letter", size, SIZES)


def read_letter_size() -> str:
    return read_choice("letter", SIZES, DEFAULT_SIZE)


def write_apply_scope(scope) -> str:
    return write_choice("scope", scope, APPLY_SCOPES)


def read_apply_scope() -> str:
    return read_choice("scope", APPLY_SCOPES, DEFAULT_SCOPE)


def min_score() -> int:
    scope = read_apply_scope()
    if scope == "all":
        return 0
    if scope == "broad":
        return min(settings.HUNTER_BROAD_MIN_SCORE, settings.HUNTER_MIN_SCORE)
    return settings.HUNTER_MIN_SCORE
