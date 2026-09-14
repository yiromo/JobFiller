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
never inflate one, never shift a date.
- You may rewrite the wording of any bullet freely: sharpen it, lead with impact, drop what is \
irrelevant to the target position, and reorder bullets and sections so the most relevant work \
comes first.
- Technologies: reorder and rename the candidate's existing stack to the current 2026 naming and \
put what the target position asks for first. You may ADD a technology only if it appears in the \
candidate's instructions or in the target position text. Never add a technology from your own \
idea of what is modern.
- Every technology you added that was not already in the source CV must be listed in \
"added_skills", verbatim as you wrote it in the skills section. This list is shown to the \
candidate so they can confirm each one before sending the CV out.
- Latin script only. No em dash, no en dash, no double hyphen, no smart quotes, no emoji. Write \
like a person, not an AI assistant: vary sentence length, avoid stock phrases.
- Keep the whole CV to what fits on one page: at most 4 experiences, at most 4 bullets each, at \
most 3 projects, at most 5 skill categories.

Respond with this JSON object:
{"title": <the professional title line under the name, targeted at the position>,
 "location": <city, country from the source CV, "" if absent>,
 "summary": <3-4 sentence professional summary in first person without "I", targeted>,
 "impact": [<up to 4 short "<number> <what it was>" achievement fragments taken from the source \
CV, e.g. "40% faster checkout">],
 "skills": {<category name>: [<technology>, ...], ...},
 "experiences": [{"role": <title>, "company": <name>, "company_url": <url or "">, \
"period": <as written in the source CV>, "location": <as written or "">, \
"description": [<bullet>, ...]}, ...],
 "projects": [{"title": <name>, "subtitle": <one short line>, "description": <one sentence>, \
"link_label": <label or "">, "link_url": <url or "">}, ...],
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
    location = data.get("location") or ""
    location_line = f"\\faMapMarker* {_escape(location)}\\\\" if location else ""
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
    return {
        "title": str(parsed.get("title") or ""),
        "location": str(parsed.get("location") or ""),
        "summary": str(parsed.get("summary") or ""),
        "impact": [str(item) for item in parsed.get("impact") or []],
        "skills": skills,
        "experiences": parsed.get("experiences") or [],
        "projects": parsed.get("projects") or [],
        "education": parsed.get("education") or {},
        "languages": parsed.get("languages") or [],
        "added_skills": _added_skills(
            skills, cv_raw_text, [str(item) for item in parsed.get("added_skills") or []]
        ),
    }


def render_pdf(data: dict, contact: dict) -> bytes:
    pdflatex = shutil.which("pdflatex")
    if not pdflatex:
        raise ToolchainMissing(
            "pdflatex is not installed on the machine running core, so the CV cannot be typeset. "
            "Install a TeX distribution (on Fedora: texlive-scheme-medium plus "
            "texlive-fontawesome5, texlive-charter and texlive-paracol)."
        )

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
        return pdf_path.read_bytes()
