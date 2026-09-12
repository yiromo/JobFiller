import json
import logging
import urllib.request

from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"

_EXTRACT_SYSTEM_PROMPT = """You read a job posting (and optional About section) and extract \
structured facts to drive two web searches. Respond with a JSON object: {"company": <the \
hiring company's name, "" if not stated>, "role": <the job title>, "posting_age": <how long \
ago the posting was made if stated, e.g. "posted 3 days ago", else "">, "company_query": <a \
short web search query to find current info about this company's culture, size, and hiring \
signals>, "market_query": <a short web search query to find current labor-market demand and \
hiring statistics for this specific role>}. Base every field only on the text given; never \
invent a company or role that isn't there."""

_SYNTHESIS_SYSTEM_PROMPT = """You assess how likely a hiring team is to actually read and \
seriously consider a specific candidate's CV for a specific job posting, using the candidate's \
CV, the job posting, and web search results gathered about the company and the job market. \
Rules:
- fit_score is an integer 0-100: how well the CV's actual experience matches what the posting \
asks for. Base it only on the CV and posting text, never on the search results.
- fit_summary explains the score in 3-5 sentences of plain prose, in second person ("you"), \
pointing at specific overlaps and gaps between the CV and the posting.
- company_insights: an array of up to 4 objects {"point": <one fact about the company relevant \
to how this application will be received>, "url": <the exact source url from the given company \
search results>, "published_date": <the source's published_date, or "" if none given>}. Every \
point must be grounded in the given company_search_results content; never state a fact not \
present in them. Empty array if nothing useful was found.
- market_stats: same shape, grounded only in market_search_results — hiring demand, posting \
volume, competition level, or application-rate figures for this role. Never invent a number; \
if a result gives no number, describe the qualitative trend it states instead. Empty array if \
nothing useful was found.
- apply_timing: one or two sentences recommending when to apply (which days/times see less \
competition, or how days-since-posting affects odds), grounded in market_search_results if they \
cover it, otherwise stated plainly as general hiring-cycle knowledge rather than as if sourced.
- suggestions: an array of 2-4 additional concrete ideas to improve this specific application's \
chances, grounded in the actual CV/posting gap you found, not generic career advice.
- Never use an em dash (—) or double hyphen (--) anywhere. Write like a person, not an AI \
assistant: vary sentence length, avoid stock phrases and rhetorical triples.
Respond with a JSON object: {"fit_score": <int>, "fit_summary": <string>, \
"company_insights": [...], "market_stats": [...], "apply_timing": <string>, \
"suggestions": [...]}."""


def _tavily_search(
    query: str, *, topic: str = "general", time_range: str = "month", max_results: int = 5
) -> list[dict]:
    body = json.dumps(
        {"query": query, "max_results": max_results, "topic": topic, "time_range": time_range}
    ).encode()
    request = urllib.request.Request(
        _TAVILY_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {settings.TAVILY_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read())
    return [
        {
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "content": (item.get("content") or "")[:1200],
            "published_date": item.get("published_date", ""),
        }
        for item in payload.get("results", [])
    ]


def _extract_queries(page_text: str, about_text: str) -> dict:
    client = OpenAI(api_key=settings.MIMO_API_KEY, base_url=settings.MIMO_BASE_URL)
    user_content = json.dumps(
        {"job_posting_text": (page_text or "")[:6000], "about_text": (about_text or "")[:2000]}
    )
    response = client.chat.completions.create(
        model=settings.MIMO_MODEL,
        messages=[
            {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        timeout=45,
    )
    return json.loads(response.choices[0].message.content)


def _synthesize(
    cv_raw_text: str,
    page_text: str,
    about_text: str,
    applicant_name: str,
    extracted: dict,
    company_results: list[dict],
    market_results: list[dict],
) -> dict:
    client = OpenAI(api_key=settings.MIMO_API_KEY, base_url=settings.MIMO_BASE_URL)
    user_content = json.dumps(
        {
            "candidate_name": applicant_name,
            "cv_text": cv_raw_text[:8000],
            "job_posting_text": (page_text or "")[:6000],
            "about_text": (about_text or "")[:2000],
            "extracted": extracted,
            "company_search_results": company_results,
            "market_search_results": market_results,
        }
    )
    response = client.chat.completions.create(
        model=settings.MIMO_MODEL,
        messages=[
            {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        timeout=60,
    )
    parsed = json.loads(response.choices[0].message.content)
    logger.warning("MiMo raw analysis: %s", parsed)
    return {
        "fit_score": int(parsed.get("fit_score") or 0),
        "fit_summary": str(parsed.get("fit_summary") or ""),
        "company_insights": parsed.get("company_insights") or [],
        "market_stats": parsed.get("market_stats") or [],
        "apply_timing": str(parsed.get("apply_timing") or ""),
        "suggestions": parsed.get("suggestions") or [],
    }


def analyze(cv_raw_text: str, page_text: str, applicant_name: str, about_text: str = "") -> dict:
    extracted = _extract_queries(page_text, about_text)
    company_query = extracted.get("company_query") or (
        f"{extracted.get('company', '')} company culture hiring".strip()
    )
    market_query = extracted.get("market_query") or (
        f"{extracted.get('role', '')} job market demand application statistics".strip()
    )

    company_results = _tavily_search(company_query, topic="general", time_range="year")
    market_results = _tavily_search(market_query, topic="news", time_range="month")
    logger.warning(
        "Analyzer queries=%r company_hits=%d market_hits=%d",
        {"company_query": company_query, "market_query": market_query},
        len(company_results),
        len(market_results),
    )

    return _synthesize(
        cv_raw_text,
        page_text,
        about_text,
        applicant_name,
        extracted,
        company_results,
        market_results,
    )
