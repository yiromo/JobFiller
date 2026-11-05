import json
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import anthropic
from django.conf import settings
from openai import OpenAI, OpenAIError

from agent import mimo

MIMO = "mimo"
CLAUDE = "claude"
PROVIDERS = (MIMO, CLAUDE)

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"

TASKS = {
    "score": (HAIKU, "medium"),
    "select": (HAIKU, "low"),
    "mail": (HAIKU, "low"),
    "position": (HAIKU, "low"),
    "options": (HAIKU, "low"),
    "eeo": (HAIKU, "low"),
    "queries": (HAIKU, "low"),
    "navigate": (HAIKU, "medium"),
    "lesson": (HAIKU, "low"),
    "fields": (SONNET, "medium"),
    "answer": (SONNET, "medium"),
    "letter": (SONNET, "medium"),
    "analysis": (SONNET, "medium"),
    "cv": (OPUS, "high"),
    "review": (OPUS, "high"),
}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
LONG_TASKS = {"cv", "review"}
MAX_TOKENS = 16000
LONG_MAX_TOKENS = 64000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
JSON_RULE = (
    "\n\nReply with the JSON object only: no markdown code fence and no text before or after it."
)
FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
DATA_URL_RE = re.compile(r"^data:(?P<media>[\w/+.-]+);base64,(?P<data>.+)$", re.DOTALL)


class LlmError(Exception):
    pass


ERRORS = (OpenAIError, anthropic.AnthropicError, LlmError)


def pairs(entries) -> dict[str, str]:
    found = {}
    for entry in entries or ():
        key, _, value = str(entry).partition("=")
        if key.strip() and value.strip():
            found[key.strip().lower()] = value.strip()
    return found


def provider(task: str) -> str:
    chosen = pairs(settings.LLM_PROVIDER_BY_TASK).get(task) or settings.LLM_PROVIDER
    chosen = str(chosen).strip().lower()
    return chosen if chosen in PROVIDERS else MIMO


def key_name(task: str) -> str:
    return "ANTHROPIC_API_KEY" if provider(task) == CLAUDE else "MIMO_API_KEY"


def ready(task: str) -> bool:
    if provider(task) == CLAUDE:
        return bool(settings.ANTHROPIC_API_KEY)
    return bool(settings.MIMO_API_KEY)


def claude_choice(task: str) -> tuple[str, str]:
    model, effort = TASKS.get(task, (SONNET, "medium"))
    model = pairs(settings.CLAUDE_MODEL_BY_TASK).get(task) or model
    wanted = pairs(settings.CLAUDE_EFFORT_BY_TASK).get(task, "").lower()
    return model, wanted if wanted in EFFORTS else effort


def complete(
    task: str,
    system: str,
    user: str,
    *,
    image: str = "",
    json_mode: bool = False,
    timeout: float = 60,
    deadline: float = mimo.DEADLINE_SECONDS,
) -> str:
    if provider(task) == CLAUDE:
        text = claude(task, system, user, image, json_mode, timeout, deadline)
    else:
        text = mimo_text(system, user, image, json_mode, timeout, deadline)
    return json_text(text) if json_mode else text.strip()


def mimo_text(
    system: str, user: str, image: str, json_mode: bool, timeout: float, deadline: float
) -> str:
    client = OpenAI(api_key=settings.MIMO_API_KEY, base_url=settings.MIMO_BASE_URL)
    content = (
        [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": image}}]
        if image
        else user
    )
    request = {
        "model": settings.MIMO_VISION_MODEL if image else settings.MIMO_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        "timeout": timeout,
    }
    if json_mode:
        request["response_format"] = {"type": "json_object"}
    response = mimo.chat(client, deadline=deadline, **request)
    return response.choices[0].message.content or ""


def image_block(image: str) -> dict:
    match = DATA_URL_RE.match(image.strip())
    if not match:
        raise LlmError("The screenshot is not a base64 data URL.")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": match["media"], "data": match["data"]},
    }


def claude(
    task: str,
    system: str,
    user: str,
    image: str,
    json_mode: bool,
    timeout: float,
    deadline: float,
) -> str:
    model, effort = claude_choice(task)
    content = ([image_block(image)] if image else []) + [{"type": "text", "text": user}]
    request = {
        "model": model,
        "max_tokens": LONG_MAX_TOKENS if task in LONG_TASKS else MAX_TOKENS,
        "system": system + (JSON_RULE if json_mode else ""),
        "messages": [{"role": "user", "content": content}],
        "output_config": {"effort": effort},
    }
    beta = model.startswith(("claude-opus", "claude-sonnet", "claude-fable"))
    if beta:
        request.update(betas=[FALLBACK_BETA], fallbacks="default")
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=1, timeout=timeout)
    try:
        message = within(
            deadline, client, model, lambda: send(client, request, beta, task in LONG_TASKS)
        )
    finally:
        client.close()
    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None) or "unspecified"
        raise LlmError(f"{model} declined the request (refusal category: {category}).")
    if message.stop_reason == "max_tokens":
        raise LlmError(f"{model} ran out of output tokens before finishing the answer.")
    return "".join(block.text for block in message.content if block.type == "text")


def send(client, request: dict, beta: bool, streamed: bool):
    api = client.beta.messages if beta else client.messages
    if not streamed:
        return api.create(**request)
    with api.stream(**request) as stream:
        return stream.get_final_message()


def within(deadline: float, client, model: str, call):
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(call)
    try:
        return future.result(timeout=deadline)
    except FutureTimeout as error:
        client.close()
        raise LlmError(f"{model} sent no complete answer within {deadline:.0f} s.") from error
    finally:
        pool.shutdown(wait=False)


def json_text(text: str) -> str:
    stripped = FENCE_RE.sub("", (text or "").strip())
    try:
        json.loads(stripped)
    except ValueError:
        pass
    else:
        return stripped
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    return stripped
