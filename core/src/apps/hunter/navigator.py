import base64
import json
import random
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from django.conf import settings
from openai import OpenAI, OpenAIError
from playwright.sync_api import Error as PlaywrightError

from agent.field_mapper import EEO_KEYWORDS
from agent.llm_mapper import _ATTESTATION_KEYWORDS

from .models import SiteLesson

MODEL_ERRORS = (OpenAIError, ValueError, TypeError, AttributeError, KeyError)
CHOICE_TAGS = {"label", "option"}
CHOICE_TYPES = {"radio", "checkbox"}
CHOICE_ROLES = {"radio", "checkbox", "option", "switch"}
ATTESTATION_KEYWORDS = (
    *_ATTESTATION_KEYWORDS,
    "согласен",
    "согласна",
    "даю согласие",
    "подтверждаю",
)
ACCOUNT_KEYWORDS = (
    "sign in",
    "log in",
    "login",
    "войти",
    "create account",
    "create an account",
    "sign up",
    "register",
    "зарегистрироваться",
    "регистрация",
    "создать аккаунт",
)
ELIGIBILITY_KEYWORDS = (
    "authorized to work",
    "authorised to work",
    "work authorization",
    "legally",
    "sponsorship",
    "sponsor",
    "visa",
    "work permit",
    "right to work",
    "security clearance",
    "citizen",
    "разрешение на работу",
    "гражданство",
)
ACTIONS = {"click", "fill", "select", "check", "upload", "scroll", "wait", "done", "stuck"}
TARGETED = {"click", "fill", "select", "check", "upload"}
TYPED_LIMIT = 300
EXTERNAL_LESSON = "employer-sites"
CONFIRMED_RE = re.compile(
    r"thank(s| you)[^.\n]{0,60}(appl|interest|submi)|application (has been |was )?"
    r"(submitted|received|sent|complete)|we('ve| have) received your application|"
    r"successfully (submitted|applied)",
    re.IGNORECASE,
)
REHEARSED = "Rehearsal reached the final submit:"
SUBMIT_RE = re.compile(
    r"^(откликнуться|отправить( отклик| заявку)?|подать заявку|submit( application)?|"
    r"send( application| response)?|respond|apply( now)?)$",
    re.IGNORECASE,
)
CAPTCHA_JS = """
() => {
  const visible = el => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 30 && box.height > 30 && box.bottom > 0 && box.right > 0
      && box.top < innerHeight && box.left < innerWidth && style.visibility !== "hidden"
      && style.display !== "none" && style.opacity !== "0";
  };
  const badge = el => !!el.closest(".grecaptcha-badge");
  if (/captcha|\\/checkpoint\\/challenge/i.test(location.pathname)) return true;
  const frames = [...document.querySelectorAll("iframe")].filter(frame =>
    /captcha|recaptcha|hcaptcha|turnstile|challenges\\.cloudflare/i.test(frame.src || "")
    && visible(frame) && !badge(frame));
  if (frames.length) return true;
  return [...document.querySelectorAll('[data-qa*="captcha" i], [id*="captcha" i], [class*="captcha" i]')]
    .some(el => visible(el) && !badge(el) && !/grecaptcha-badge/.test(el.className));
}
"""
DEEP_JS = """
const deepAll = (selector, root = document) => {
  const found = [];
  const visit = node => {
    node.querySelectorAll(selector).forEach(el => found.push(el));
    node.querySelectorAll("*").forEach(el => el.shadowRoot && visit(el.shadowRoot));
  };
  visit(root);
  return found;
};
const hostUp = el => el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null);
const closestDeep = (el, selector) => {
  for (let node = el; node; node = hostUp(node)) if (node.matches && node.matches(selector)) return node;
  return null;
};
const shown = el => {
  const box = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  return box.width > 1 && box.height > 1 && style.visibility !== "hidden"
    && style.display !== "none" && style.opacity !== "0";
};
const DIALOG = "[role=dialog], [aria-modal=true], dialog[open]";
const openDialog = () => deepAll(DIALOG).filter(shown).pop() || null;
"""
OUTLINE_JS = (
    "(limit) => {"
    + DEEP_JS
    + """
  const selector = [
    "a[href]", "button", "input", "select", "textarea", "label", "[contenteditable=true]",
    "[role=button]", "[role=radio]", "[role=checkbox]", "[role=option]", "[role=combobox]",
    "[role=textbox]", "[role=switch]", "[role=tab]", "[role=menuitem]",
  ].join(",");
  const clean = text => (text || "").replace(/\\s+/g, " ").trim();
  const labelOf = el => {
    const root = el.getRootNode();
    const labelled = el.getAttribute("aria-labelledby");
    if (labelled) {
      const text = labelled.split(/\\s+/).map(id => (root.getElementById ? root.getElementById(id) : null) || document.getElementById(id))
        .filter(Boolean).map(node => node.innerText).join(" ");
      if (clean(text)) return clean(text);
    }
    if (el.labels && el.labels.length) return clean([...el.labels].map(l => l.innerText).join(" "));
    return clean(el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.title);
  };
  const groupOf = el => {
    let node = el.parentElement;
    for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
      if (node.querySelectorAll(selector).length > 1) {
        const text = clean(node.innerText);
        return text.length <= 400 ? text : text.slice(0, 400);
      }
    }
    return "";
  };
  deepAll("[data-jf-nav]").forEach(el => el.removeAttribute("data-jf-nav"));
  const dialog = openDialog();
  const inForm = el => !!closestDeep(el, "form, " + DIALOG);
  const candidates = deepAll(selector, dialog || document).filter(el => {
    if (el.type === "hidden") return false;
    if (el.type === "file") return true;
    if (shown(el)) return true;
    return ["radio", "checkbox"].includes(el.type) && el.labels && [...el.labels].some(shown);
  });
  const listed = new Set(candidates);
  const pruned = candidates.filter(el => !(el.tagName === "LABEL" && el.control && listed.has(el.control) && shown(el.control)));
  const stepper = /^(next|continue|review|submit|apply|send|done|далее|продолжить|отправить|откликнуться)/i;
  const inView = el => {
    const box = el.getBoundingClientRect();
    return box.bottom > 0 && box.top < innerHeight && box.right > 0 && box.left < innerWidth;
  };
  const rank = el => (stepper.test(clean(el.innerText || el.value || el.getAttribute("aria-label"))) ? 8 : 0)
    + (inView(el) ? 4 : 0) + (inForm(el) ? 2 : 0)
    + (["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName) ? 1 : 0);
  const ranked = pruned.map((el, order) => [rank(el), order, el])
    .sort((a, b) => b[0] - a[0] || a[1] - b[1]).slice(0, limit)
    .sort((a, b) => a[1] - b[1]).map(entry => entry[2]);
  return ranked.map((el, index) => {
    const ref = String(index + 1);
    el.setAttribute("data-jf-nav", ref);
    const tag = el.tagName.toLowerCase();
    const item = {
      ref, tag, type: el.type || "", role: el.getAttribute("role") || "",
      text: clean(el.innerText || el.value || "").slice(0, 160),
      label: labelOf(el).slice(0, 200),
      group: groupOf(el),
      required: !!(el.required || el.getAttribute("aria-required") === "true"),
      disabled: !!(el.disabled || el.getAttribute("aria-disabled") === "true"),
      submit: tag === "button" ? (el.type || "submit") === "submit" && !!el.form
        : el.type === "submit",
      in_form: inForm(el),
      in_dialog: !!dialog,
      qa: el.getAttribute("data-qa") || "",
    };
    if (["radio", "checkbox"].includes(el.type)) item.checked = el.checked;
    if (tag === "select") item.options = [...el.options].map(o => clean(o.text)).slice(0, 40);
    if (["input", "textarea"].includes(tag) && !["radio", "checkbox"].includes(el.type)) {
      item.value = (el.value || "").slice(0, 600);
      item.value_length = (el.value || "").length;
    }
    if (tag === "a") item.href = el.href;
    if (el.type === "file") item.accept = el.accept || "";
    return item;
  });
}"""
)
PAGE_TEXT_JS = (
    "() => {"
    + DEEP_JS
    + """
  const dialog = openDialog();
  return ((dialog ? dialog.innerText + "\\n----\\n" : "") + document.body.innerText);
}"""
)
SCROLL_JS = (
    "(ref) => {"
    + DEEP_JS
    + """
  const target = ref ? deepAll('[data-jf-nav="' + ref + '"]')[0] : null;
  if (target) {
    target.scrollIntoView({block: "center", behavior: "smooth"});
    return "scrolled to the element";
  }
  const root = openDialog();
  const boxes = (root ? [root, ...deepAll("*", root)] : [document.scrollingElement])
    .filter(el => el && el.scrollHeight > el.clientHeight + 20
      && ["auto", "scroll"].includes(getComputedStyle(el).overflowY) || el === document.scrollingElement);
  const box = boxes.sort((a, b) => b.clientHeight - a.clientHeight)[0] || document.scrollingElement;
  box.scrollBy({top: box.clientHeight * 0.8});
  return root ? "scrolled the dialog" : "scrolled the page";
}"""
)
SYSTEM_PROMPT = """You drive a web browser for a job seeker, one action per turn, to reach a goal.
You get the goal, the candidate's CV text, the job posting, notes learned on earlier visits to
this site, your recent steps, a screenshot and a numbered list of the page's interactive
elements. Reply with one JSON object:
{"thought": "<one sentence>",
 "action": "click|fill|select|check|upload|scroll|wait|done|stuck",
 "ref": "<element number for click/fill/select/check/upload>", "value": "<text for fill/select>",
 "final_submit": <true only if this click sends the application>}
To click a button that is visible in the screenshot but missing from the element list, send
"click" with no "ref" and the button's visible name in "value".
"upload" attaches the candidate's CV file: point it at the file input or the upload button;
the harness picks the file, so leave "value" empty.
Rules:
- Answer employer questions truthfully from the CV. Never invent employers, dates, degrees,
  numbers or skills the CV does not show. If the CV does not answer a question, give the most
  honest short answer (e.g. that you have no such experience) rather than a made-up one.
- Fill empty required contact fields (name, email, phone, city) from candidate_contact. If a
  required value is not in candidate_contact or the CV, reply "stuck" and name the missing value.
- candidate_facts is the candidate's own statement and outranks the CV for everything it
  covers, including years of experience. Work authorization, visa, sponsorship, relocation,
  notice period and salary questions are answered only from candidate_facts. If candidate_facts does not cover one, reply "stuck" and
  name the question; never guess eligibility.
- Searchable dropdowns: type a short part of the answer and pick the matching option. If none
  matches after one try, pick "Other" when offered; otherwise leave an optional field empty and
  move on, and reply "stuck" naming a required one. Never retry the same field more than twice.
- Skip optional fields the CV cannot answer; required fields are marked with * or "required".
- Salary questions: use candidate_facts or the CV's figure, otherwise write that it is negotiable.
- Match the language of the question (Russian question, Russian answer).
- Never tick a legal consent or attestation, never answer gender, ethnicity, disability,
  veteran or other demographic questions, and never try to solve a captcha: reply "stuck".
- Do not leave the site or open unrelated pages. Do not log out or change account settings.
- Never create an account, register, or type a password: reply "stuck" at any login or
  sign-up wall.
- Reply "done" only when the page shows the application was sent. Reply "stuck" with the
  reason in "thought" when you cannot make progress."""
LESSON_PROMPT = """You keep short working notes for a browser agent that applies to jobs on one
website. Rewrite the notes given the previous notes and the latest run's steps and outcome.
Keep what still holds, add what this run taught (which controls worked, page structure,
pitfalls, what a finished application looks like), drop anything contradicted. At most 10
bullets and 1200 characters. No personal data: no names, contacts, CV facts or answers.
Never write rules about whether to send or stop before sending: the harness decides that, and
a "rehearsed" outcome means it stopped the run on purpose, not that the site blocked it.
Reply with the notes only."""


class CaptchaSeen(RuntimeError):
    pass


@dataclass
class Result:
    status: str
    note: str
    submitted: bool = False
    trace: list = field(default_factory=list)


def first_line(error: BaseException) -> str:
    return (str(error).strip().splitlines() or [type(error).__name__])[0]


def host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else host


def matches(text: str, keywords) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def vet(
    decision: dict,
    element: dict | None,
    allowed_hosts: set[str],
    rehearse: bool,
    can_upload: bool = False,
    has_facts: bool = False,
    may_leave: bool = False,
) -> str:
    action = decision.get("action")
    if action not in ACTIONS:
        return f"unknown action {action!r}"
    if action not in TARGETED:
        return ""
    if element is None:
        return f"no element numbered {decision.get('ref')!r} on this page"
    if element.get("disabled"):
        return "that element is disabled"
    haystack = " ".join(str(element.get(key, "")) for key in ("text", "label", "group"))
    own = " ".join(str(element.get(key, "")) for key in ("text", "label"))
    choice = (
        element.get("tag") in CHOICE_TAGS
        or element.get("type") in CHOICE_TYPES
        or element.get("role") in CHOICE_ROLES
    )
    if matches(own, ATTESTATION_KEYWORDS) and action in {"click", "check"}:
        return "refused: legal consent and attestation boxes are the candidate's own click"
    if matches(haystack, EEO_KEYWORDS) and (action != "click" or choice):
        return "refused: demographic questions are never answered by the agent"
    if matches(haystack, ELIGIBILITY_KEYWORDS) and not has_facts and (action != "click" or choice):
        return "refused: work authorization and visa answers need HUNTER_FACTS"
    if element.get("type") == "password":
        return "refused: the agent never types passwords"
    if action == "click" and matches(own, ACCOUNT_KEYWORDS):
        return "refused: the agent never creates accounts"
    if action == "upload" and not can_upload:
        return "refused: no CV file to upload"
    href = element.get("href") or ""
    off_site = href.startswith("http") and host_of(href) not in allowed_hosts
    if action == "click" and off_site and not may_leave:
        return f"refused: {host_of(href)} is outside {', '.join(sorted(allowed_hosts))}"
    if rehearse and is_final_submit(decision, element):
        return "rehearsal"
    return ""


def is_final_submit(decision: dict, element: dict) -> bool:
    if decision.get("action") != "click":
        return False
    if decision.get("final_submit") is True:
        return True
    if "submit" in element.get("qa", "").lower() or element.get("submit"):
        return True
    return bool(element.get("in_form")) and bool(SUBMIT_RE.match(element.get("text", "").strip()))


class Navigator:
    def __init__(
        self,
        page,
        *,
        goal,
        cv_text,
        job_text,
        log,
        rehearse=False,
        on_submit=None,
        upload_path="",
        allowed_hosts=None,
        contact=None,
        facts="",
        external_hops=0,
    ):
        self.page = page
        self.goal = goal
        self.cv_text = cv_text
        self.job_text = job_text
        self.log = log
        self.rehearse = rehearse
        self.on_submit = on_submit
        self.client = OpenAI(api_key=settings.MIMO_API_KEY, base_url=settings.MIMO_BASE_URL)
        self.host = host_of(page.url)
        self.allowed_hosts = set(allowed_hosts or ()) | {self.host}
        self.upload_path = upload_path
        self.contact = {key: value for key, value in (contact or {}).items() if value}
        self.facts = facts
        self.opened = []
        self.external_hops = external_hops
        self.max_steps = (
            settings.HUNTER_NAVIGATOR_EXTERNAL_STEPS
            if external_hops
            else settings.HUNTER_NAVIGATOR_STEPS
        )
        self.external_hosts = []
        lesson_host = EXTERNAL_LESSON if external_hops else self.host
        self.lesson, _ = SiteLesson.objects.get_or_create(host=lesson_host)
        self.trace = []
        self.submitted = False

    def run(self) -> Result:
        try:
            result = self.loop()
        except CaptchaSeen:
            result = Result("captcha", "A captcha appeared; the agent never solves captchas.")
        except PlaywrightError as error:
            result = Result("stuck", f"Browser error: {first_line(error)}")
        except MODEL_ERRORS as error:
            result = Result("stuck", f"Model error: {type(error).__name__}: {first_line(error)}")
        result.submitted = self.submitted
        result.trace = self.trace
        self.learn(result)
        return result

    def close_opened(self) -> None:
        for tab in self.opened:
            if not tab.is_closed():
                tab.close()
        self.opened = []

    def loop(self) -> Result:
        repeats = 0
        previous = None
        stale = 0
        last_view = None
        for step in range(1, self.max_steps + 1):
            self.guard_captcha()
            elements = self.page.evaluate(OUTLINE_JS, 120)
            view = (self.page.url, json.dumps(elements, sort_keys=True))
            stale = stale + 1 if view == last_view else 0
            last_view = view
            if stale >= 6:
                return Result("stuck", "The page did not change for six steps.")
            decision = self.decide(elements)
            action = decision.get("action")
            element = next((e for e in elements if e["ref"] == str(decision.get("ref"))), None)
            if element is None and action == "click" and not decision.get("ref"):
                element = self.named_button(str(decision.get("value") or ""))
            entry = {
                "step": step,
                "url": self.page.url,
                "action": action,
                "ref": decision.get("ref"),
                "target": (element or {}).get("text") or (element or {}).get("label") or "",
                "value": str(decision.get("value") or "")[:300],
                "thought": str(decision.get("thought") or "")[:300],
                "final_submit": decision.get("final_submit") is True,
                "element": {k: (element or {}).get(k) for k in ("tag", "type", "qa", "submit")},
            }
            self.trace.append(entry)
            self.log(f"    nav {step}: {action} {entry['target'][:40]!r} {entry['thought'][:80]}")
            if action == "done":
                return Result("done", entry["thought"] or "The page reports the application sent.")
            if action == "stuck":
                return Result("stuck", entry["thought"] or "The agent could not make progress.")
            problem = vet(
                decision,
                element,
                self.allowed_hosts,
                self.rehearse,
                bool(self.upload_path),
                bool(self.facts),
                self.external_hops > 0,
            )
            if problem == "rehearsal":
                entry["result"] = "stopped before the final submit (rehearsal)"
                return Result("rehearsed", f"{REHEARSED} {entry['target']}")
            if problem:
                entry["result"] = problem
                continue
            signature = (action, entry["target"], entry["value"])
            repeats = repeats + 1 if signature == previous else 0
            previous = signature
            if repeats >= 2:
                return Result(
                    "stuck", f"Repeated the same step three times: {action} {entry['target']}"
                )
            if element and is_final_submit(decision, element) and not self.submitted:
                self.submitted = True
                if self.on_submit:
                    self.on_submit()
            tabs = len(self.page.context.pages)
            entry["result"] = self.act(decision, element)
            self.page.wait_for_timeout(int(random.uniform(0.9, 2.6) * 1000))
            entry["result"] += self.follow_new_tab(tabs)
            if host_of(self.page.url) not in self.allowed_hosts:
                if self.hop(self.page):
                    entry["result"] += f"; now on the employer's site {host_of(self.page.url)}"
                else:
                    self.page.go_back(wait_until="domcontentloaded")
                    entry["result"] += f"; left {self.host}, went back"
        return Result("stuck", f"No result after {self.max_steps} steps.")

    def named_button(self, name: str) -> dict | None:
        name = name.strip()
        if not name:
            return None
        return {
            "ref": "",
            "name": name[:80],
            "tag": "button",
            "type": "button",
            "text": name[:80],
            "label": "",
            "group": "",
            "in_form": True,
        }

    def follow_new_tab(self, before: int) -> str:
        pages = self.page.context.pages
        if len(pages) <= before:
            return ""
        tab = pages[-1]
        tab.wait_for_load_state("domcontentloaded", timeout=20000)
        host = host_of(tab.url)
        if host not in self.allowed_hosts and self.hop(tab):
            host = host_of(tab.url)
        if host not in self.allowed_hosts:
            tab.close()
            return f"; a new tab opened {host}, outside the allowed sites, and was closed"
        tab.bring_to_front()
        self.opened.append(tab)
        self.page = tab
        return f"; switched to the new tab on {host}"

    def hop(self, page) -> bool:
        if self.external_hops <= 0:
            return False
        try:
            page.wait_for_load_state("load", timeout=20000)
        except PlaywrightError:
            pass
        page.wait_for_timeout(2500)
        host = host_of(page.url)
        if host in self.allowed_hosts:
            return True
        self.external_hops -= 1
        self.allowed_hosts.add(host)
        self.external_hosts.append(host)
        return True

    def guard_captcha(self) -> None:
        if self.page.evaluate(CAPTCHA_JS):
            raise CaptchaSeen(self.page.url)

    def decide(self, elements: list[dict]) -> dict:
        screenshot = base64.b64encode(self.page.screenshot(type="jpeg", quality=55)).decode()
        context = {
            "goal": self.goal,
            "url": self.page.url,
            "notes_from_earlier_visits": self.lesson.text,
            "candidate_contact": self.contact,
            "candidate_facts": self.facts,
            "recent_steps": [
                {key: entry.get(key) for key in ("action", "target", "value", "result")}
                for entry in self.trace[-8:]
            ],
            "cv_text": self.cv_text[:7000],
            "job_posting": self.job_text[:4000],
            "page_text": self.page.evaluate(PAGE_TEXT_JS)[:6000],
            "elements": elements,
        }
        response = self.client.chat.completions.create(
            model=settings.MIMO_VISION_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": json.dumps(context, ensure_ascii=False)},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{screenshot}"},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
            timeout=90,
        )
        try:
            decision = json.loads(response.choices[0].message.content or "{}")
        except json.JSONDecodeError:
            decision = {}
        return decision if isinstance(decision, dict) else {}

    def act(self, decision: dict, element: dict) -> str:
        action = decision["action"]
        if action == "scroll":
            ref = element["ref"] if element else ""
            return self.page.evaluate(SCROLL_JS, ref)
        if action == "wait":
            self.page.wait_for_timeout(2500)
            return "waited"
        if element.get("name"):
            locator = self.page.get_by_role("button", name=element["name"]).first
        else:
            locator = self.page.locator(f'[data-jf-nav="{element["ref"]}"]').first
        value = str(decision.get("value") or "")
        try:
            if action == "click":
                locator.click(timeout=8000)
            elif action == "check":
                try:
                    locator.check(timeout=8000)
                except PlaywrightError:
                    locator.click(timeout=8000, force=True)
            elif action == "select":
                try:
                    locator.select_option(label=value, timeout=8000)
                except PlaywrightError:
                    locator.select_option(value=value, timeout=8000)
            elif action == "fill":
                self.type_into(locator, element, value)
            elif action == "upload":
                self.upload(locator, element)
        except PlaywrightError as error:
            return f"failed: {first_line(error)[:200]}"
        return "ok"

    def type_into(self, locator, element: dict, value: str) -> None:
        native = element.get("tag") in {"input", "textarea"}
        if native and len(value) > TYPED_LIMIT:
            locator.fill(value, timeout=8000)
            return
        locator.click(timeout=8000)
        self.page.keyboard.press("Control+A")
        self.page.keyboard.press("Delete")
        for chunk in re.findall(r"\S+\s*|\s+", value):
            self.page.keyboard.type(chunk, delay=random.randint(35, 110))
            if random.random() < 0.15:
                self.page.wait_for_timeout(random.randint(150, 600))

    def upload(self, locator, element: dict) -> None:
        if element.get("type") == "file":
            locator.set_input_files(self.upload_path, timeout=8000)
            return
        with self.page.expect_file_chooser(timeout=8000) as chooser:
            locator.click(timeout=8000)
        chooser.value.set_files(self.upload_path)

    def learn(self, result: Result) -> None:
        if result.status in {"done", "rehearsed"}:
            self.lesson.successes += 1
        elif result.status == "stuck":
            self.lesson.failures += 1
        steps = [
            {key: entry.get(key) for key in ("action", "target", "result", "thought")}
            for entry in self.trace
        ]
        try:
            response = self.client.chat.completions.create(
                model=settings.MIMO_MODEL,
                messages=[
                    {"role": "system", "content": LESSON_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "site": self.host,
                                "previous_notes": self.lesson.text,
                                "goal": self.goal.split("\n", 1)[0],
                                "steps": steps,
                                "outcome": f"{result.status}: {result.note}",
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                timeout=60,
            )
            text = (response.choices[0].message.content or "").strip()
            if text:
                self.lesson.text = text[:2000]
        except MODEL_ERRORS as error:
            self.log(f"    lesson update failed: {first_line(error)}")
        self.lesson.save()
