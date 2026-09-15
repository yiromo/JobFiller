import json
import logging
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)


class CvGenerationError(RuntimeError):
    pass


class ToolchainMissing(CvGenerationError):
    pass


_SYSTEM_PROMPT = """You rewrite an existing CV into a new one targeted at a specific position, \
following the candidate's own instructions. You respond with a JSON object only.

Grounding rules, in order of priority:
- Employers, job titles, employment dates, locations, degrees, schools, GPA and every number \
(team sizes, percentages, user counts, revenue) are copied from the source CV. Never invent one, \
never inflate one, never shift a date. A job title is the candidate's real employment title, not \
the position being targeted: the headline may say anything, "role" may not.
- One exception, the only one: when the candidate's instructions contain a line of the form \
"Title <employer> as <role>", use that role verbatim for that employer, and keep any parenthetical \
qualifier the source CV attaches to it, e.g. "Title Dreams Group as Full-Stack Engineer" applied to \
a source role of "Backend Developer (Part-time)" gives "Full-Stack Engineer (Part-time)". Employer \
names and dates are never overridable this way, and without such a line a role is copied.
- Include every experience the source CV lists, in the order it lists them. Never drop one, never \
merge two, never reorder them. Repositioning happens in the headline, the summary and the wording \
of bullets, never in the employment history itself.
- You may rewrite the wording of any bullet freely: sharpen it, lead with impact, drop what is \
irrelevant to the target position, and reorder the bullets within one experience so the most \
relevant work comes first.
- Technologies: reorder and rename the candidate's existing stack to the current 2026 naming and \
put what the target position asks for first. You may ADD a technology only when the candidate's \
instructions explicitly ask for that technology to be added. A technology named only as something \
to prioritize, emphasize or lead with is NOT permission to add it -- prioritizing means reordering \
what is already there. Never add one from the target position text alone, and never from your own \
idea of what is modern.
- Never list a technology that the source CV mentions only as something the candidate's work sat \
behind, next to, or integrated with, rather than something the candidate built in.
- Every technology you added that was not already in the source CV must be listed in \
"added_skills", verbatim as you wrote it in the skills section. This list is shown to the \
candidate so they can confirm each one before sending the CV out.
- Latin script only. No em dash, no en dash, no double hyphen, no smart quotes, no emoji. Write \
like a person, not an AI assistant: vary sentence length, avoid stock phrases.
- Keep the whole CV to what fits on one page: at most 3 bullets per experience, at most 3 \
projects, at most 5 skill categories. Never drop an experience to save space -- cut bullets.

Respond with this JSON object:
{"title": <the professional title line under the name, targeted at the position>,
 "location_details": [<each part of the source CV's header location line, as written in the \
source CV -- city, timezone, work mode, contract type; [] if the source CV has no such line>],
 "summary": <3-4 sentence professional summary in first person without "I", targeted>,
 "impact": [<up to 4 short "<number> <what it was>" achievement fragments taken from the source \
CV, e.g. "40% faster checkout">],
 "skills": {<category name>: [<technology>, ...], ...},
 "experiences": [{"role": <as written in the source CV>, "company": <as written in \
the source CV>, "company_url": <url or "">, \
"period": <as written in the source CV>, "location": <as written or "">, \
"description": [<bullet>, ...]}, ...],
 "projects": [{"title": <name>, "subtitle": <one short line>, "description": <one sentence>, \
"link_label": <the link label from the source CV, "" if absent>, "link_url": <the matching url \
from the source CV, "" if absent>}, ...],
 "education": {"degree": <degree>, "school": <school>, "period": <as written>, "gpa": <as \
written or "">},
 "languages": [{"language": <name>, "level": <level>}, ...],
 "added_skills": [<technology not present in the source CV>, ...]}"""

_PUNCTUATION = {
    "\u2014": "-",
    "\u2013": "-",
    "\u2012": "-",
    "\u2212": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a0": " ",
    "\u2022": "-",
    "\u2192": "->",
}


def _sanitize(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    for source, replacement in _PUNCTUATION.items():
        text = text.replace(source, replacement)
    text = "".join(char for char in text if char == "\n" or 32 <= ord(char) < 256)
    return text.strip()


_WHITESPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[A-Za-z][\w.+#-]*")
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s")
_PAGE_COUNT_RE = re.compile(r"Output written on .*?\((\d+) pages?,")
_GROUNDED_FIELDS = ("role", "company", "period")
_TITLE_DIRECTIVE_RE = re.compile(r"(?im)^\s*title\s+(.+?)\s+as\s+(.+?)\s*$")
_QUALIFIER_RE = r"\(([^)]{2,40})\)\s*\|\s*"
_BLANKET_EMPLOYERS = (
    "all",
    "all roles",
    "every role",
    "all jobs",
    "every job",
    "all positions",
    "all titles",
)


def _comparable(value) -> str:
    return _WHITESPACE_RE.sub(" ", _sanitize(value)).casefold()


def _title_overrides(instructions: str) -> list[tuple[str, str]]:
    overrides = []
    for employer, role in _TITLE_DIRECTIVE_RE.findall(_sanitize(instructions)):
        pattern, title = _comparable(employer), _sanitize(role)
        if pattern and title:
            overrides.append((pattern, title))
    return overrides


def _override_matches(pattern: str, company: str) -> bool:
    return pattern in _BLANKET_EMPLOYERS or (bool(company) and pattern in company)


def _override_for(company, overrides: list[tuple[str, str]]) -> str:
    target = _comparable(company)
    for pattern, role in overrides:
        if pattern not in _BLANKET_EMPLOYERS and _override_matches(pattern, target):
            return role
    for pattern, role in overrides:
        if pattern in _BLANKET_EMPLOYERS:
            return role
    return ""


def _role_allowed(role: str, override: str, haystack: str) -> bool:
    if _comparable(role) in haystack:
        return True
    if not override:
        return False
    remainder = _comparable(role).replace(_comparable(override), " ")
    remainder = _WHITESPACE_RE.sub(" ", remainder).strip()
    return not remainder or remainder in haystack


def _lost_qualifiers(experiences: list[dict], haystack: str) -> list[tuple[str, str]]:
    lost = []
    for exp in experiences:
        company = _comparable(exp.get("company"))
        if not company:
            continue
        match = re.search(_QUALIFIER_RE + re.escape(company), haystack)
        if match and match.group(1) not in _comparable(exp.get("role")):
            lost.append((_sanitize(exp.get("company")), match.group(1)))
    return lost


def _ungrounded_facts(
    experiences: list[dict], haystack: str, overrides: list[tuple[str, str]]
) -> list[str]:
    facts = []
    for exp in experiences:
        employer = _sanitize(exp.get("company")) or "an unnamed employer"
        for field in _GROUNDED_FIELDS:
            value = _sanitize(exp.get(field))
            if not value:
                continue
            if field == "role":
                if not _role_allowed(value, _override_for(exp.get("company"), overrides), haystack):
                    facts.append(
                        f'role for {employer}: "{value}" is not in the source CV and no '
                        f'"Title {employer} as ..." line authorises it'
                    )
            elif _comparable(value) not in haystack:
                facts.append(f'{field} for {employer}: "{value}" is not in the source CV')
    return facts


def _in_source_order(experiences: list[dict], haystack: str) -> list[dict]:
    def position(exp: dict) -> tuple[bool, int]:
        for field in ("period", "company"):
            needle = _comparable(exp.get(field))
            at = haystack.find(needle) if needle else -1
            if at >= 0:
                return (False, at)
        return (True, 0)

    return sorted(experiences, key=position)


def _split_sourced(values: list, haystack: str) -> tuple[list[str], list[str]]:
    kept, dropped = [], []
    for value in values:
        text = _sanitize(value)
        if not text:
            continue
        (kept if _comparable(text) in haystack else dropped).append(text)
    return kept, dropped


def _unsourced_prose(data: dict, haystack: str) -> list[str]:
    passages = [data.get("summary") or ""]
    passages.extend(str(item) for item in data.get("impact") or [])
    for exp in data.get("experiences") or []:
        passages.extend(str(line) for line in exp.get("description") or [])
    for project in data.get("projects") or []:
        passages.extend(str(project.get(key) or "") for key in ("title", "subtitle", "description"))

    found: list[str] = []
    for passage in passages:
        for sentence in _SENTENCE_BREAK_RE.split(_sanitize(passage)):
            for token in list(_TOKEN_RE.finditer(sentence))[1:]:
                term = token.group(0).rstrip(".,;:")
                if term[:1].isupper() and term.casefold() not in haystack and term not in found:
                    found.append(term)
    return found


def _escape(value) -> str:
    text = _sanitize(value)
    text = text.replace("\\", "\\textbackslash{}")
    text = re.sub(r"([{}])", r"\\\1", text)
    text = re.sub(r"([%&#_$])", r"\\\1", text)
    text = text.replace("~", "\\textasciitilde{}")
    text = text.replace("^", "\\textasciicircum{}")
    return text


def _href(url: str, label: str) -> str:
    return f"\\hrefWithoutArrow{{{_sanitize(url)}}}{{{_escape(label)}}}"


def _strip_scheme(url: str) -> str:
    return re.sub(r"^https?://", "", _sanitize(url)).rstrip("/")


def _contact_line(contact: dict) -> str:
    parts = []
    if contact.get("email"):
        parts.append(
            f"\\faEnvelope[regular] {_href('mailto:' + contact['email'], contact['email'])}"
        )
    if contact.get("phone"):
        parts.append(f"\\faPhone{{}} {_escape(contact['phone'])}")
    if contact.get("linkedin_url"):
        url = _sanitize(contact["linkedin_url"])
        parts.append(f"\\faLinkedin{{}} {_href(url, _strip_scheme(url))}")
    if contact.get("git_url"):
        url = _sanitize(contact["git_url"])
        parts.append(f"\\faGithub{{}} {_href(url, _strip_scheme(url))}")
    return " \\textbar{} ".join(parts)


def _skills_block(skills: dict) -> str:
    rows = [
        f"\\textbf{{{_escape(category)}:}} {_escape(', '.join(str(item) for item in items))}"
        for category, items in skills.items()
        if items
    ]
    return " \\\\\n        ".join(rows)


def _experience_entries(experiences: list[dict]) -> str:
    blocks = []
    for exp in experiences:
        company = (
            _href(exp["company_url"], exp.get("company", ""))
            if exp.get("company_url")
            else _escape(exp.get("company", ""))
        )
        location = (
            f" -- {{\\footnotesize {_escape(exp['location'])}}}" if exp.get("location") else ""
        )
        bullets = "\n".join(
            f"            \\item \\small {_escape(line)}" for line in exp.get("description", [])
        )
        blocks.append(
            f"""    \\begin{{twocolentry}}{{{_escape(exp.get("period", ""))}}}
        \\textbf{{{_escape(exp.get("role", ""))}}} $|$ {company}{location}
    \\end{{twocolentry}}
    \\vspace{{0.02cm}}
    \\begin{{onecolentry}}
        \\begin{{highlights}}
{bullets}
        \\end{{highlights}}
    \\end{{onecolentry}}"""
        )
    return "\n\n    \\vspace{0.03cm}\n\n".join(blocks)


def _project_entries(projects: list[dict]) -> str:
    blocks = []
    for project in projects:
        link = (
            _href(project["link_url"], project.get("link_label") or project["link_url"])
            if project.get("link_url")
            else ""
        )
        subtitle = f" -- {_escape(project['subtitle'])}" if project.get("subtitle") else ""
        blocks.append(
            f"""    \\begin{{twocolentry}}{{{link}}}
        \\textbf{{{_escape(project.get("title", ""))}}}{subtitle}
    \\end{{twocolentry}}
    \\vspace{{0.02cm}}
    \\begin{{onecolentry}}
        \\begin{{highlights}}
            \\item \\small {_escape(project.get("description", ""))}
        \\end{{highlights}}
    \\end{{onecolentry}}"""
        )
    return "\n\n    \\vspace{0.03cm}\n\n".join(blocks)


def _education_section(education: dict, languages: list[dict]) -> str:
    if not education.get("degree") and not education.get("school"):
        return ""
    gpa = (
        f" \\textbar{{}} GPA: \\textbf{{{_escape(education['gpa'])}}}"
        if education.get("gpa")
        else ""
    )
    languages_line = ", ".join(
        f"{_escape(item.get('language', ''))} ({_escape(item.get('level', ''))})"
        for item in languages
        if item.get("language")
    )
    languages_block = (
        f"""    \\vspace{{0.04cm}}
    \\begin{{onecolentry}}
        \\small
        \\textbf{{Languages:}} {languages_line}
    \\end{{onecolentry}}"""
        if languages_line
        else ""
    )
    return f"""    \\section{{Education}}

    \\begin{{twocolentry}}{{{_escape(education.get("period", ""))}}}
        \\textbf{{{_escape(education.get("degree", ""))}}} \\\\ \
{_escape(education.get("school", ""))}{gpa}
    \\end{{twocolentry}}
{languages_block}"""


def _build_tex(data: dict, contact: dict) -> str:
    name = _escape(contact.get("full_name") or "")
    title = _escape(data.get("title") or "")
    details = [_sanitize(item) for item in data.get("location_details") or []]
    details = [item for item in details if item] or (
        [_sanitize(data["location"])] if data.get("location") else []
    )
    location_line = (
        " $\\cdot$ ".join(
            [f"\\faMapMarker* {_escape(details[0])}"] + [_escape(item) for item in details[1:]]
        )
        + "\\\\"
        if details
        else ""
    )
    impact = " \\textbar{} ".join(_escape(item) for item in data.get("impact", []) if item)
    impact_block = (
        f"\n\n        \\vspace{{3pt}}\n        \\textbf{{Selected Impact:}} {impact}"
        if impact
        else ""
    )
    skills = _skills_block(data.get("skills") or {})
    skills_section = (
        f"""    \\section{{Core Skills}}

    \\begin{{onecolentry}}
        \\small
        {skills}
    \\end{{onecolentry}}
"""
        if skills
        else ""
    )
    experiences = _experience_entries(data.get("experiences") or [])
    experience_section = (
        f"""    \\section{{Professional Experience}}

    \\vspace{{0.05cm}}
{experiences}
"""
        if experiences
        else ""
    )
    projects = _project_entries(data.get("projects") or [])
    projects_section = (
        f"""    \\section{{Selected Projects}}

    \\vspace{{0.05cm}}

{projects}
"""
        if projects
        else ""
    )
    education_section = _education_section(data.get("education") or {}, data.get("languages") or [])

    return rf"""\documentclass[11pt, letterpaper]{{article}}

\usepackage[
    ignoreheadfoot,
    top=0.6 cm,
    bottom=0.6 cm,
    left=1.6 cm,
    right=1.6 cm,
    footskip=0.4 cm,
]{{geometry}}
\usepackage{{titlesec}}
\usepackage{{tabularx}}
\usepackage{{array}}
\usepackage[dvipsnames]{{xcolor}}
\definecolor{{primaryColor}}{{RGB}}{{25, 25, 112}}
\definecolor{{accentColor}}{{RGB}}{{65, 105, 225}}
\usepackage{{enumitem}}
\usepackage{{amsmath}}
\usepackage[
    pdftitle={{{name} - {title}}},
    pdfauthor={{{name}}},
    colorlinks=true,
    urlcolor=accentColor
]{{hyperref}}
\usepackage[pscoord]{{eso-pic}}
\usepackage{{calc}}
\usepackage{{bookmark}}
\usepackage{{changepage}}
\usepackage{{paracol}}
\usepackage{{ifthen}}
\usepackage{{needspace}}
\usepackage{{iftex}}
\IfFileExists{{fontawesome5.sty}}{{\usepackage{{fontawesome5}}}}{{
    \newcommand{{\faEnvelope}}[1][]{{}}
    \newcommand{{\faPhone}}{{}}
    \newcommand{{\faLinkedin}}{{}}
    \newcommand{{\faGithub}}{{}}
    \makeatletter
    \newcommand{{\faMapMarker}}{{\@ifstar{{}}{{}}}}
    \makeatother
}}

\ifPDFTeX
    \input{{glyphtounicode}}
    \pdfgentounicode=1
    \usepackage[T1]{{fontenc}}
    \usepackage[utf8]{{inputenc}}
    \usepackage{{lmodern}}
\fi

\usepackage{{charter}}

\raggedright
\AtBeginEnvironment{{adjustwidth}}{{\partopsep0pt}}
\pagestyle{{empty}}
\setcounter{{secnumdepth}}{{0}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\topskip}}{{0pt}}
\setlength{{\columnsep}}{{0.15cm}}
\pagenumbering{{gobble}}

\titleformat{{\section}}{{\needspace{{2\baselineskip}}\bfseries\normalsize\color{{primaryColor}}}}{{}}{{0pt}}{{}}[\vspace{{0.3pt}}{{\color{{accentColor}}\titlerule[0.8pt]}}]
\titlespacing{{\section}}{{-1pt}}{{0.08 cm}}{{0.03 cm}}

\renewcommand\labelitemi{{$\vcenter{{\hbox{{\small$\bullet$}}}}$}}
\newenvironment{{highlights}}{{
    \begin{{itemize}}[
        topsep=0.03 cm,
        parsep=0.02 cm,
        partopsep=0pt,
        itemsep=0pt,
        leftmargin=0 cm + 9pt
    ]
}}{{
    \end{{itemize}}
}}

\newenvironment{{onecolentry}}{{
    \begin{{adjustwidth}}{{0 cm + 0.00001 cm}}{{0 cm + 0.00001 cm}}
}}{{
    \end{{adjustwidth}}
}}

\newenvironment{{twocolentry}}[2][]{{
    \onecolentry
    \def\secondColumn{{#2}}
    \setcolumnwidth{{\fill, 3.8 cm}}
    \begin{{paracol}}{{2}}
}}{{
    \switchcolumn \raggedleft \secondColumn
    \end{{paracol}}
    \endonecolentry
}}

\newenvironment{{header}}{{
    \setlength{{\topsep}}{{0pt}}\par\kern\topsep\centering\linespread{{1.1}}
}}{{
    \par\kern\topsep
}}

\let\hrefWithoutArrow\href

\begin{{document}}
    \begin{{header}}
        \fontsize{{22pt}}{{22pt}}\selectfont\color{{primaryColor}}\textbf{{{name}}}

        \vspace{{3pt}}
        {{\small\color{{accentColor}}\textbf{{{title}}}}}

        \vspace{{5pt}}
        \footnotesize\color{{black}}
        {location_line}
        {_contact_line(contact)}
    \end{{header}}

    \vspace{{2pt}}

    \section{{Summary}}

    \begin{{onecolentry}}
        \small
        {_escape(data.get("summary") or "")}{impact_block}
    \end{{onecolentry}}

{skills_section}
{experience_section}
{projects_section}
{education_section}

\end{{document}}
"""


def _is_new_skill(token: str, haystack: str) -> bool:
    stem = re.sub(r"\s*v?\d+(\.\d+)*$", "", token).strip().lower()
    return token.lower() not in haystack and (not stem or stem not in haystack)


def _added_skills(skills: dict, cv_raw_text: str, claimed: list[str]) -> list[str]:
    haystack = _sanitize(cv_raw_text).lower()
    added = []
    for items in skills.values():
        for item in items:
            token = _sanitize(item)
            if token and token not in added and _is_new_skill(token, haystack):
                added.append(token)
    for item in claimed:
        token = _sanitize(item)
        if token and token not in added:
            added.append(token)
    return added


def rewrite(cv_raw_text: str, instructions: str, position_text: str = "") -> dict:
    if not settings.MIMO_API_KEY:
        raise ToolchainMissing("MIMO_API_KEY is not set in core/.env, so no CV can be written.")
    client = OpenAI(api_key=settings.MIMO_API_KEY, base_url=settings.MIMO_BASE_URL)
    user_content = json.dumps(
        {
            "source_cv_text": (cv_raw_text or "")[:12000],
            "candidate_instructions": (instructions or "")[:4000],
            "target_position_text": (position_text or "")[:6000],
        }
    )
    try:
        response = client.chat.completions.create(
            model=settings.MIMO_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            timeout=120,
        )
        parsed = json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.exception("CV rewrite failed")
        raise CvGenerationError(f"The model could not rewrite the CV: {exc}") from exc

    skills = {
        str(category): [str(item) for item in items or []]
        for category, items in (parsed.get("skills") or {}).items()
    }
    haystack = _comparable(cv_raw_text)
    experiences = parsed.get("experiences") or []
    overrides = _title_overrides(instructions)
    ungrounded = _ungrounded_facts(experiences, haystack, overrides)
    if ungrounded:
        raise CvGenerationError(
            "The rewrite changed employment facts that must be copied from the source CV: "
            + "; ".join(ungrounded)
            + ". Generate again."
        )

    details, unsourced_details = _split_sourced(parsed.get("location_details") or [], haystack)
    data = {
        "title": str(parsed.get("title") or ""),
        "location_details": details,
        "summary": str(parsed.get("summary") or ""),
        "impact": [str(item) for item in parsed.get("impact") or []],
        "skills": skills,
        "experiences": _in_source_order(experiences, haystack),
        "projects": parsed.get("projects") or [],
        "education": parsed.get("education") or {},
        "languages": parsed.get("languages") or [],
    }
    warnings = [
        f"Employment title for {_sanitize(exp.get('company'))} changed to "
        f'"{_sanitize(exp.get("role"))}" on your instruction; the source CV says otherwise.'
        for exp in experiences
        if _sanitize(exp.get("role")) and _comparable(exp.get("role")) not in haystack
    ]
    warnings += [
        f'Dropped "({qualifier})" from the title for {employer}, which the source CV attaches to it.'
        for employer, qualifier in _lost_qualifiers(experiences, haystack)
    ]
    warnings += [
        f'"Title {pattern} as {role}" matched none of your employers.'
        for pattern, role in overrides
        if not any(
            _override_matches(pattern, _comparable(exp.get("company"))) for exp in experiences
        )
    ]
    warnings += [
        f'Left "{item}" out of the header line: it is not in the source CV.'
        for item in unsourced_details
    ]
    unsourced = _unsourced_prose(data, haystack)
    if unsourced:
        warnings.append(
            "Wording not found in the source CV, check each one before sending: "
            + ", ".join(unsourced)
        )
    data["added_skills"] = _added_skills(
        skills, cv_raw_text, [str(item) for item in parsed.get("added_skills") or []]
    )
    data["warnings"] = warnings
    return data


def render_pdf(data: dict, contact: dict) -> tuple[bytes, list[str]]:
    pdflatex = shutil.which("pdflatex")
    if not pdflatex:
        raise ToolchainMissing(
            "pdflatex is not installed on the machine running core, so the CV cannot be typeset. "
            "Install a TeX distribution (on Fedora: texlive-scheme-medium plus "
            "texlive-fontawesome5, texlive-charter and texlive-paracol)."
        )

    projects = list(data.get("projects") or [])
    dropped: list[str] = []
    while True:
        pdf_bytes, pages = _typeset({**data, "projects": projects}, contact, pdflatex)
        if pages <= 1 or not projects:
            break
        dropped.append(_sanitize(projects[-1].get("title")) or "an untitled project")
        projects = projects[:-1]
    if pages > 1:
        raise CvGenerationError(
            f"The rewritten CV is {pages} pages with no projects left to cut. Ask for fewer "
            "bullets or a shorter summary and generate again."
        )
    return pdf_bytes, [
        f'Dropped the project "{title}" to keep the CV on one page.' for title in dropped
    ]


def _typeset(data: dict, contact: dict, pdflatex: str) -> tuple[bytes, int]:
    tex = _build_tex(data, contact)
    with tempfile.TemporaryDirectory(prefix="jobfiller-cv-") as build_dir:
        tex_path = Path(build_dir) / "cv.tex"
        pdf_path = Path(build_dir) / "cv.pdf"
        tex_path.write_text(tex, encoding="utf-8")
        for _ in range(2):
            result = subprocess.run(
                [
                    pdflatex,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-output-directory",
                    build_dir,
                    str(tex_path),
                ],
                cwd=build_dir,
                capture_output=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                log_path = Path(build_dir) / "cv.log"
                log = (
                    log_path.read_text(encoding="utf-8", errors="replace")
                    if log_path.exists()
                    else result.stdout.decode("utf-8", "replace")
                )
                tail = "\n".join(log.splitlines()[-30:])
                logger.error("pdflatex failed:\n%s", tail)
                raise CvGenerationError(f"pdflatex could not typeset the CV:\n{tail}")
            match = _PAGE_COUNT_RE.search(result.stdout.decode("utf-8", "replace"))
        return pdf_path.read_bytes(), int(match.group(1)) if match else 0
