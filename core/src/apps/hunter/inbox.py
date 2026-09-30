import json
import os

from django.conf import settings

MAX_ROWS = 50


def inbox_dir():
    return settings.DATA_DIR / "hunter-inbox"


def eeo_path():
    return inbox_dir() / "eeo.json"


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


def write_eeo(rows) -> list[dict]:
    cleaned = clean_rows(rows)
    inbox_dir().mkdir(parents=True, exist_ok=True)
    temporary = eeo_path().with_suffix(".tmp")
    temporary.write_text(json.dumps(cleaned, ensure_ascii=False))
    os.replace(temporary, eeo_path())
    return cleaned


def read_eeo() -> list[dict]:
    try:
        return clean_rows(json.loads(eeo_path().read_text()))
    except (OSError, ValueError, TypeError):
        return []


def answered_eeo() -> list[dict]:
    return [row for row in read_eeo() if row["answer"]]
