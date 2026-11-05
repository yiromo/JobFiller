import io
import logging

import docx

from agent import llm, style

logger = logging.getLogger(__name__)

OFF = "off"
LENGTHS = {
    "very_short": "60-100 words, a single short paragraph.",
    "short": "120-180 words, two short paragraphs.",
    "medium": "250-400 words, three or four paragraphs.",
    "long": "400-550 words, four or five paragraphs.",
    "max": "600-800 words, five or six paragraphs.",
}
SIZES = (OFF, *LENGTHS)
DEFAULT_SIZE = "medium"

_SYSTEM_PROMPT = """You write professional cover letters using ONLY facts grounded in the \
candidate's CV, for the specific job posting given. Rules:
- {length}
- Never invent employers, dates, numbers, or skills that are not in the CV.
- Never state availability, start date, salary, work format (office/remote/hybrid), relocation, \
or schedule commitments unless the CV states them explicitly.
- Write in first person, as the candidate.
- Open with "Dear Hiring Team," unless the job posting names a specific person to address.
- Identify the company and role from the job posting text and reference them naturally.
- Close by signing off with the candidate's name.
- Never use a bracketed placeholder like [Company Name] or [Your Name] — write around it if \
the posting doesn't give you a fact, rather than leaving a blank to fill in.
- Never use an em dash (—) or double hyphen (--). Use a period, comma, or "and"/"but" instead.
- Write like a person, not an AI assistant: vary sentence length, avoid stock phrases like \
"I am excited to apply" or "I am confident that", and don't over-use rhetorical triples or \
overly polished transitions.
- Lead with proof, not enthusiasm: the first sentence after the greeting names the posting's \
main requirement and one concrete thing from the CV that meets it (the system, its scale, or \
a number that is in the CV). Every later sentence also carries a specific fact; drop any \
sentence that would fit any other company's letter.
- Never repeat the posting's keyword list back. Use its words only where a CV fact backs them.
Respond with the letter's plain text only — no subject line, no markdown, no commentary."""


def generate(
    cv_raw_text: str,
    page_text: str,
    applicant_name: str,
    about_text: str = "",
    language: str = "",
    size: str = DEFAULT_SIZE,
    max_chars: int = 0,
) -> str:
    about_block = (
        f'\n\nAbout the company/role (from the posting\'s "About" section):\n{about_text[:2000]}'
        if about_text
        else ""
    )
    user_content = (
        f"Candidate name: {applicant_name}\n\n"
        f"CV text:\n{cv_raw_text[:8000]}\n\n"
        f"Job posting text:\n{(page_text or '')[:8000]}"
        f"{about_block}"
    )
    system = system_prompt(size, max_chars) + (
        f"\nWrite the whole letter in {language}, including the greeting, "
        'which replaces "Dear Hiring Team,".'
        if language
        else ""
    )
    letter = llm.complete("letter", system, user_content, timeout=60)
    problems = style.tells(letter) + [
        f"the number {number} is not in the CV or the posting"
        for number in style.unsupported_numbers(letter, cv_raw_text, page_text, about_text)
    ]
    if not problems:
        return letter
    retry = (
        f"{user_content}\n\nYour previous draft:\n{letter}\n\n"
        f"Rewrite it to fix these problems: {'; '.join(problems)}."
    )
    return llm.complete("letter", system, retry, timeout=60)


def system_prompt(size: str, max_chars: int = 0) -> str:
    length = LENGTHS.get(size, LENGTHS[DEFAULT_SIZE])
    if max_chars:
        length += f" The whole letter must stay under {max_chars} characters."
    return _SYSTEM_PROMPT.replace("{length}", length)


def render_docx(text: str) -> bytes:
    document = docx.Document()
    for block in text.split("\n\n"):
        document.add_paragraph(block.strip())
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
