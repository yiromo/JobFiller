from django.conf import settings
from openai import OpenAI

_SYSTEM_PROMPT = """You write a direct answer to a single open-ended job-application question, \
grounded strictly in the candidate's CV and the job posting text given. Rules:
- Answer only the question asked, in first person, as the candidate.
- 2-5 sentences: concise and concrete, citing specific CV experience relevant to the question.
- Never invent a fact, employer, date, or number that isn't in the CV text.
- If the CV gives nothing relevant to the question, answer honestly and briefly rather than \
padding with generic filler.
- Never use an em dash (—) or double hyphen (--). Use a period, comma, or "and"/"but" instead.
- Write like a person, not an AI assistant: vary sentence length, avoid stock phrases like \
"I am excited" or "I am confident", and don't over-use rhetorical triples.
Respond with the answer's plain text only — no preamble, no markdown, no restating the question."""


def generate(cv_raw_text: str, question: str, page_text: str) -> str:
    client = OpenAI(api_key=settings.MIMO_API_KEY, base_url=settings.MIMO_BASE_URL)
    user_content = (
        f"Question: {question}\n\n"
        f"CV text:\n{cv_raw_text[:8000]}\n\n"
        f"Job posting text:\n{(page_text or '')[:6000]}"
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
