import re

STOCK_PHRASES = (
    "i am excited",
    "i'm excited",
    "i am thrilled",
    "i'm thrilled",
    "i am writing to",
    "i am confident",
    "i'm confident",
    "passionate about",
    "proven track record",
    "fast-paced",
    "dynamic team",
    "leverage my",
    "leveraging my",
    "delve",
    "synergy",
    "align perfectly",
    "aligns perfectly",
    "perfect fit",
    "ideal candidate",
    "unique blend",
    "wealth of experience",
    "hit the ground running",
    "look forward to the opportunity",
    "would be a great addition",
    "keen interest",
    "deeply resonates",
    "resonates with me",
    "game-changer",
    "cutting-edge",
    "results-driven",
    "detail-oriented",
    "team player",
    "i hope this message finds you well",
    "i hope this finds you well",
)
DASH_RE = re.compile(r"—|--")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def tells(text: str, max_words: int = 0) -> list[str]:
    lowered = (text or "").lower()
    found = [f'stock phrase "{phrase}"' for phrase in STOCK_PHRASES if phrase in lowered]
    if DASH_RE.search(text or ""):
        found.append("an em dash or double hyphen")
    words = len((text or "").split())
    if max_words and words > max_words:
        found.append(f"{words} words, over the {max_words}-word limit")
    return found


def unsupported_numbers(text: str, *sources: str) -> list[str]:
    known = set()
    for source in sources:
        known.update(number.replace(",", ".") for number in NUMBER_RE.findall(source or ""))
    return [
        number
        for number in dict.fromkeys(NUMBER_RE.findall(text or ""))
        if number.replace(",", ".") not in known
    ]
