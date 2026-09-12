import io
import logging

import docx
from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You write professional cover letters using ONLY facts grounded in the \
candidate's CV, for the specific job posting given. Rules:
- 250-400 words, three or four paragraphs.
- Never invent employers, dates, numbers, or skills that are not in the CV.
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


def generate(cv_raw_text: str, page_text: str, applicant_name: str, about_text: str = "") -> str:
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
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        timeout=45,
    )
    return response.choices[0].message.content.strip()


def render_docx(text: str) -> bytes:
    document = docx.Document()
    for block in text.split("\n\n"):
        document.add_paragraph(block.strip())
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
