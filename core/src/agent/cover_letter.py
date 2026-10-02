import io
import logging

import docx
from django.conf import settings
from openai import OpenAI

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
    client = OpenAI(api_key=settings.MIMO_API_KEY, base_url=settings.MIMO_BASE_URL)
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
    response = client.chat.completions.create(
        model=settings.MIMO_MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt(size, max_chars)
                + (
                    f"\nWrite the whole letter in {language}, including the greeting, "
                    'which replaces "Dear Hiring Team,".'
                    if language
                    else ""
                ),
            },
            {"role": "user", "content": user_content},
        ],
        timeout=45,
    )
    return response.choices[0].message.content.strip()


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
