import re

from django.conf import settings

TERMS = {
    "Python": r"\bpython\b",
    "Go": r"\bgolang\b|\bGo\b(?![- ]to\b)",
    "Java": r"\bjava\b(?!\s*script)",
    "Kotlin": r"\bkotlin\b",
    "Scala": r"\bscala\b",
    "Rust": r"\brust\b",
    "C++": r"c\+\+",
    "C#/.NET": r"c#|\.net\b",
    "Ruby": r"\bruby\b|\brails\b",
    "PHP": r"\bphp\b|\blaravel\b",
    "Node.js": r"\bnode\.?js\b",
    "TypeScript": r"\btypescript\b",
    "React": r"\bReact(\.?js)?\b",
    "Vue": r"\bvue(\.?js)?\b",
    "Angular": r"\bangular\b",
    "Elixir": r"\belixir\b",
    "Django": r"\bdjango\b",
    "FastAPI": r"\bfastapi\b",
    "Flask": r"\bflask\b",
    "Spring": r"\bSpring( Boot)?\b",
    "gRPC": r"\bgrpc\b",
    "GraphQL": r"\bgraphql\b",
    "Kafka": r"\bkafka\b",
    "RabbitMQ": r"\brabbitmq\b",
    "PostgreSQL": r"\bpostgres(ql)?\b",
    "MySQL": r"\bmysql\b",
    "MongoDB": r"\bmongo(db)?\b",
    "Redis": r"\bredis\b",
    "ClickHouse": r"\bclickhouse\b",
    "Elasticsearch": r"\belasticsearch\b|\bopensearch\b",
    "Snowflake": r"\bsnowflake\b",
    "Spark": r"\bSpark\b",
    "Airflow": r"\bairflow\b",
    "dbt": r"\bdbt\b",
    "Docker": r"\bdocker\b",
    "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "Terraform": r"\bterraform\b",
    "AWS": r"\baws\b|amazon web services",
    "GCP": r"\bgcp\b|google cloud",
    "Azure": r"\bazure\b",
    "Linux": r"\blinux\b",
    "CI/CD": r"\bci/cd\b|github actions|gitlab ci|\bjenkins\b",
    "LLMs": r"\bllms?\b|large language models?",
    "RAG": r"\brag\b|retrieval[- ]augmented",
    "PyTorch/TensorFlow": r"\bpytorch\b|\btensorflow\b",
    "Celery": r"\bcelery\b",
}
CASE_SENSITIVE = {"Go", "React", "Spring", "Spark"}
PATTERNS = {
    name: re.compile(pattern, 0 if name in CASE_SENSITIVE else re.IGNORECASE)
    for name, pattern in TERMS.items()
}
OPTIONAL_RE = re.compile(
    r"nice[- ]to[- ]have|bonus points|\bbonus\b|preferred qualifications|preferred skills|"
    r"good to have|would be a plus|is a plus|are a plus|желательно|будет плюсом|"
    r"будет преимуществом",
    re.IGNORECASE,
)
MIN_TERMS = 3


def required_part(text: str) -> str:
    found = OPTIONAL_RE.search(text or "")
    return (text or "")[: found.start()] if found else (text or "")


def terms_in(text: str) -> set[str]:
    return {name for name, pattern in PATTERNS.items() if pattern.search(text or "")}


def measure(posting_text: str, cv_text: str) -> tuple[int | None, list[str]]:
    needed = terms_in(required_part(posting_text))
    if len(needed) < MIN_TERMS:
        return None, []
    have = terms_in(f"{cv_text}\n{settings.HUNTER_STACK}")
    missing = sorted(needed - have)
    return round(100 * (len(needed) - len(missing)) / len(needed)), missing


def missing_note(missing: list[str]) -> str:
    return f" Required but not in the CV: {', '.join(missing)}." if missing else ""


def below(coverage: int | None) -> bool:
    return bool(
        settings.HUNTER_MIN_COVERAGE
        and coverage is not None
        and coverage < settings.HUNTER_MIN_COVERAGE
    )
