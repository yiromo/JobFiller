# CLAUDE.md

Guidance for Claude Code (or any agent) working in this repo.

## Never write comments in code

No comments. Not in new code, not in edited code, not in generated config, not "just this one
line because the intent is subtle", not JSDoc/docstring blocks, not `# noqa`-style explanations
of a workaround. If something needs explaining, name it better or put it in `tasks/PROGRESS.md`.
Leave comments that already exist alone unless the code under them changes; if it does, delete
the comment rather than update it. This rule outranks any instinct to document a non-obvious
fix — that context belongs in the PROGRESS entry, not the source.

## What this repo is

`job-filler` — an agent that fills job applications from a user's CVs. Monorepo:

- `core/` — Django 5 + DRF API, uv-managed. CV storage/parsing, job-posting scan, and
  field-mapping (deciding what value goes in which form field). All AI/agent logic lives
  behind this API — the extension never calls an LLM directly.
- `extension/` — Firefox (Zen) WebExtension (Manifest V3). Manually triggered per page: user
  clicks "Scan" to read the form, then "Fill" to apply the plan `core` returns. The optional
  Telegram opportunity queue can also drive its scan/fill path and attempt a final submit.
- `desktop/` — GNOME app for the hunter (`job_agent.py`, GTK4 + libadwaita on the system
  `/usr/bin/python3`, since PyGObject is not in the uv venv). `install.sh` adds the launcher and
  icon under `~/.local/share`. It never imports Django or opens the DB: every read and write goes
  through `manage.py agent_desk list|resolve` (JSON on stdout) run with `uv` in `core/src`.

The Telegram channel workflow lives in `apps.opportunities`; see `tasks/BACKLOG.md` for remaining
multi-step ATS and Telegram bot-link coverage. It was explicitly requested by the user.

Progress and what's next live in `tasks/` — read `tasks/PROGRESS.md` before starting work, and
add an entry there (plus `tasks/BACKLOG.md` if scope shifts) when a feature lands, in the same
commit as the code.

## Commands

Backend (`cd core`):
```bash
uv sync
cd src && uv run python manage.py migrate
uv run python manage.py runserver 0.0.0.0:8000
uv run python manage.py check      # quick sanity check
uv run ruff check .                # lint (line length 100, py3.12)
uv run ruff format .
uv run python manage.py test                                   # all Django tests
uv run python manage.py test apps.opportunities.tests          # one module (or add .Class.test_name)
uv run python manage.py sync_telegram_jobs [--days N]          # ingest the Telegram channel
uv run python manage.py hunter_login hh|linkedin|indeed|dsml  # visible browser: log in once per site
uv run python manage.py agent_desk list|resolve ID applied|skipped|retry  # desktop app bridge
uv run python manage.py hh_resumes [--link CV_ID=HASH]         # list/link hh résumés
uv run python manage.py hunt [--apply] [--headed] [--loop MIN] # hh.kz agent (dry run by default)
uv run python manage.py hunt --vacancy ID [--rehearse]         # send one row (or rehearse: never submits)
```

Docker: `docker compose up --build` (from repo root) — runs `core` on `:8000` with a SQLite
volume.

Extension: no build step (plain WebExtension JS, no bundler). Load unpacked via
`about:debugging#/runtime/this-firefox` → "Load Temporary Add-on…" → `extension/manifest.json`.
`npx web-ext lint --source-dir extension` catches manifest errors before loading.

Browser regression checks run in headless Firefox (`extension/tests/select-fill.cjs`,
`auto-apply.cjs`, `linkedin-easy-apply.cjs`); see `extension/tests/README.md` for setup and run
commands. They test DOM filling, not the installed extension's full
Scan/Fill workflow. Other verification: backend `manage.py check` + `ruff check` +
curl the endpoint with a real request; extension `web-ext lint` + manual load-and-click in
Zen/Firefox (an agent without a real browser cannot claim the extension "works" — only that it
lints clean and the DOM-fill logic was reviewed).

## Backend architecture (`core/src/apps/<app>/`)

Layered, same shape for every app, wired with `dependency-injector` (`container.py` per app):

```
models → dto → repositories (interface + impl) → services → api/v1 (serializers, views, urls)
```

Don't put DB queries or business logic in views — mirror an existing app. Apps:

- `core` — `/health/`
- `cvs` — CV upload/list/file-download. Regex-based email/phone extraction lives here for now
  (`agent/profile.py` builds the structured profile from a CV's raw text). Also
  `POST /api/v1/cvs/<id>/generate/`: rewrites that CV for a target position via
  `agent/cv_writer.py` (one MiMo call to structured JSON, then a `pdflatex` render ported from
  yiromo.com's `npm run cv`) and saves the PDF back through `CvService.upload`, so a generated CV
  is an ordinary `Cv` row and is immediately selectable for filling.
- `applications` — `POST /api/v1/applications/scan/`: takes a page's `form_snapshot`, returns
  a fill plan built by `agent/field_mapper.py` (heuristic pass) then `agent/llm_mapper.py`
  (MiMo pass over whatever the heuristic skipped, only if `MIMO_API_KEY` is set). Any field whose
  haystack matches "cover letter" is generated by `agent/cover_letter.py` (one MiMo call per
  scan, not the general LLM pass) — a paste-style field gets the letter as plain text (`action:
  "type"`), a file-upload field gets it rendered to `.docx` and attached inline via the field
  mapping's `file` object, same as the résumé upload but without a stored CV row behind it.
  Sibling endpoints: `generate-cover-letter/`, `generate-answer/` (`agent/question_answer.py`,
  the per-textarea "Generate with AI" button), `analyze/` (`agent/analyzer.py`, job fit analysis
  with Tavily web search; needs `TAVILY_API_KEY`) and `resolve-options/` (below).
- `opportunities` — Telegram job-channel queue under `/api/v1/opportunities/`. Flat module layout
  (`service.py`, `telegram.py`, `telegraph.py`, `models.py`), not the layered shape above; fed by
  the `telegram_login` and `sync_telegram_jobs` management commands. Needs `TELEGRAM_API_ID`/
  `TELEGRAM_API_HASH`; `OPPORTUNITY_MIN_SCORE` gates which jobs get queued.
- `hunter` — proactive hh.kz agent driven by Camoufox (Playwright Firefox), flat layout.
  `browser.py` owns the shared profile (`data/browser/<site>/`: Firefox profile, pinned
  `fingerprint.json`, `session.json` cookie snapshot); `sources/` holds one adapter per job site,
  picked by hostname from `JOB_SOURCE_URLS` (an hh homepage URL expands to per-résumé
  recommendation searches); `service.py` runs crawl → score → apply under a daily cap, and
  `notify.py` posts run summaries as GNOME notifications (`notify-send` with the
  `kz.jobfiller.Agent` desktop-entry hint, so a click opens the desktop app;
  `HUNTER_NOTIFY_DESKTOP`) and, only if `HUNTER_NOTIFY_TELEGRAM` is on, to Telegram Saved
  Messages. `review.kind_of` sorts held rows by what the user must do (captcha, unconfirmed send,
  question only they can answer, account wall, stuck, other) from code-written notes and the
  trace's last `refused:` result before falling back to the navigator's own wording. A hold the
  agent pressed Submit on is only requeued when the user says it was not sent. It is fully
  separate from `opportunities` on purpose: the extension polls `/opportunities/next/` and would
  claim hh rows. `state.py` makes `hunt --loop` publish `data/hunter/status.json`, and
  `GET /api/v1/hunter/` serves only that file (plus `up`), never the DB: the Docker `core` the
  extension calls has its own volume database, and compose bind-mounts just that directory
  read-only. The Manage page section and panel "hh agent" tab stay hidden unless `up`. Keep the
  endpoint read-only. `navigator.py` is the general fallback: each step sends MiMo a screenshot
  plus a numbered outline of the page's controls and executes one JSON action. Its safety rules
  live in `vet` (code, not prompt): captcha stops the run, consent/attestation and EEO answers are
  refused, off-site links are refused, and a rehearsal stops at the final submit (`data-qa`/
  `type=submit`/model flag). Attestation is judged on a control's own text, plus the surrounding question only for a short-labelled checkbox, radio or option, so a "Submit" button under an "I certify" footer goes through. Each field (keyed by tag, label and group, never `ref`) gets one try if optional and three if required (`required`, `*` or "required" in its label); a used-up or refused field is removed from the outline the model sees. `SiteLesson` notes are rewritten after each run and fed into the
  next; they must never carry send/stop rules. `evidence.py` keeps page HTML, a screenshot and
  the step trace per vacancy under `data/hunter/pages/`, served by `evidence/<id>/<file>`.
  Adapters (`sources/hh.py`, `linkedin.py`, `indeed.py`, `dsml.py`) implement `sources/base.CONTRACT`; each
  site has its own browser profile and `hunter_login SITE`. LinkedIn and Indeed have no scripted
  apply, always go through the navigator, and default to `HUNTER_NAVIGATOR_<SITE>=rehearse`.
  LinkedIn serves a client-rendered variant without `data-view-name` after the first navigation
  in a tab, and Playwright locators miss its cards there: query through `page.evaluate`. Never
  open Indeed `/viewjob` or `/rc/clk` (Cloudflare "Security Check"); a vacancy URL is the search
  URL plus `vjk=<jk>`, which shows the job in the side panel. Only visible `a[data-jk]` cards
  count: Indeed plants an invisible trap link. The captcha guard must stay visibility-based:
  both sites carry invisible reCAPTCHA Enterprise frames that are not a challenge.
  `sources/dsml.py` (dsml.kz) is scripted: it fills the "Apply without profile" guest form
  (name, email, CV file, LinkedIn from the CV, cover note ≤1200, phone/city contact note, no
  Telegram) from the `applicant` dict `apply_one` passes to every adapter's `apply`. The site has
  `/ru` and `/kk` routes, so it selects by `guest-apply-*` id prefixes and `#apply` hrefs, never by
  button text. The list is paginated as `/jobs/page/N` (no "Load more"); `crawl` walks at least
  `MIN_PAGES` and stops at the first page with no Quick Apply card, since older pages have none. A guest send never shows up as "applied" on reload, so `apply` itself decides
  success from the form's live message or the form being replaced. `browser.fingerprint_for`
  only pins presets whose WebGL pair Camoufox has data for; others crash the launch.
  The navigator's consent and EEO rules differ from the extension's scan path by the user's
  explicit choice (2026-10-01): it may tick privacy-notice and personal-data-processing
  acknowledgments (`privacy_acknowledgment`), never certifications, terms or other attestations;
  and it answers a demographic question only when the chosen option matches the user's own saved
  answer (`eeo_problem`). Those answers come from the extension's Settings through
  `PUT /api/v1/hunter/eeo/`, which writes `data/hunter-inbox/eeo.json`. The Manage agent tab's
  cover-letter size goes the same way (`PUT /api/v1/hunter/letter/` → `letter.json`). The
  `hunter-inbox` directory is the one writable path into the hunter, bind-mounted read-write into
  the Docker `core`. Keep everything else read-only. The agent tab's apply scope (`PUT /api/v1/hunter/scope/` →
  `scope.json`: `relevant` = `HUNTER_MIN_SCORE`, `broad` = `HUNTER_BROAD_MIN_SCORE`, `all` = 0) is
  a threshold only: the scoring prompt never changes with it, so stored scores stay comparable and
  `apply_scope_threshold` re-sorts unsent rows both ways each run. A row ready only because of the
  scope gets a CV tailored by `cv_writer` on upload sites; one that adds skills or changes a title
  is deleted and the original CV is used. Letter sizes (`off`, `very_short` … `max`)
  live in `agent/cover_letter.LENGTHS`; the panel's slider is `coverLetterSize` in
  `storage.local`, read by `background.js` for every scan, so Telegram auto-apply follows it too.

`agent/` (`core/src/agent/`) is a **plain module, not a Django app** — it has no models. Its
functions are called directly from `applications`/`cvs` services (not DI-injected — there's
nothing stateful to inject). Don't turn it into a layered app; there's nothing to layer.

Settings: SQLite (no multi-user, nothing Redis-dependent, no deploy target yet — revisit if
that changes), `python-decouple` for env vars, CORS open to `moz-extension://` origins for
local extension testing.

## Field-mapping contract (core ↔ extension)

This is the one thing both sides must agree on. Content script scans the page and stamps every
candidate field with a `data-jf-ref` attribute (existing `id` reused when present), then sends:

```json
{
  "url": "...",
  "page_text": "...",
  "form_snapshot": [
    {"ref": "...", "tag": "input", "type": "text", "name": "...", "id": "...",
     "label": "...", "section": "...", "placeholder": "...", "options": [...], "required": true,
     "role": "combobox", "aria_haspopup": "listbox", "aria_controls": "...listbox-id..."}
  ],
  "eeo_answers": [{"match": "gender", "answer": "male"}]
}
```

`label` is the field's accessible name and `section` is the nearest heading/question text
rendered beside it — see the "accessible name is often junk" bullet below for why both are
needed. Both feed `field_haystack`, so every keyword rule (EEO, attestation, logistics, resume,
cover letter) sees them, and both are sent to every LLM pass. `page_text` (job posting text,
truncated) and `role`/`aria_haspopup`/`aria_controls` exist only to give the LLM pass context and
to tell a custom combobox apart from a plain text input — the heuristic pass ignores them. Core
returns:

```json
[{"ref": "...", "value": "...", "action": "type|select|check|upload|skip", "confidence": 0.0,
  "file": {"filename": "...", "mime_type": "...", "base64": "..."}}]
```

`file` is present only on a generated cover letter's `upload` action — the extension attaches
those bytes directly instead of fetching a stored CV by `value` (which is empty in that case).

`ref` is the only thing the extension uses to find the element again — never a CSS selector or
guessed XPath. Fields the content script identifies as honeypots (`aria-hidden="true"`,
`tabindex="-1"` traps) or legal attestations ("I agree...", privacy/terms consent) are never sent
for auto-fill guessing, by either mapper. Demographic/EEO questions are never guessed from a CV
or job posting either, but they are routed through a dedicated AI pass grounded strictly in the
user's own `eeo_answers` rows — see the "EEO/demographic" bullets below.

### Combobox option resolution (fill-time round trip)

A custom combobox's real options don't exist in the DOM until it's opened, so `form_snapshot`'s
`options` is `[]` for these at scan time and both mappers can only guess a value blind. When
`background.js`'s `applyFillPlan` opens the widget at fill time and that guess matches none of
the real options, it's collected as `{ref, wanted, options}` (the real option text, now known)
and `handleFill` POSTs the batch to `POST /api/v1/applications/resolve-options/`:

```json
{"application_id": 1, "fields": [{"ref": "...", "wanted": "...", "options": ["...", "..."]}]}
```

Core (`agent/option_resolver.py`, one MiMo call for the whole batch, same shape as
`eeo_mapper.py`) returns one entry per field, snapped to the given `options` (or `skip`) by
`llm_mapper.validate_override`:

```json
{"fields": [{"ref": "...", "value": "...", "action": "select|skip", "confidence": 0.0}]}
```

Resolved entries persist into `Application.field_mapping` and are also returned to `panel.js`,
which splices them into the in-memory plan so a second Fill click doesn't repeat the round trip.

## Non-obvious things (these will bite you)

- **A field's accessible name is often junk, and every keyword rule depends on it.** An ATS built
  on a component library (Rippling is the known case) hands each control a generic
  `aria-label` — `Select...`, `Search`, `textbox`, literally `combobox` — randomizes `name` to a
  nonce, and renders the real question as a plain sibling `div`, not a `<label for>`. That
  leaves `field_haystack` semantically empty, and an empty haystack doesn't just lose a fill:
  `EEO_KEYWORDS`, `_ATTESTATION_KEYWORDS` and `_LOGISTICS_KEYWORDS` are substring checks over it,
  so **the hard skips silently stop applying** and a question they exist to block reaches the
  CV-grounded pass. Hence `resolveLabel` rejects a known set of generic names outright (returning
  `""` is safer than a label that looks real), prefers `aria-labelledby` over `aria-label` per the
  accessible-name spec, and `resolveSection` supplies the heading by DOM proximity. `section`
  never replaces `label`; a file dropzone's `<label>` legitimately reads "Drop or select
  (.doc / .docx / .pdf)", which is a correct accessible name and useless for deciding that the
  field is the résumé — the section heading above it is what says "Resume".
- **`resolveSection` must not walk by class name or stop at the first control.** It reads text
  only from a sibling containing no form control (so it can never pick up a neighbouring field's
  label or value), steps *over* control-bearing siblings rather than giving up — a phone widget's
  country picker sits between the number input and their shared "Phone number" heading — and caps
  the walk at 8 ancestors, a `<form>`, and 200 characters. Loosen any of those and it finds a
  page-level container, the same failure mode `findToggleControl` had. It also skips
  screen-reader-only siblings: those are clipped, not `display:none`, so they still paint a box
  and still yield `innerText` — a "Total 0 file selected" node sits directly above Rippling's
  résumé dropzone and was winning over the "Résumé" heading one level further up. Some headings
  are simply out of reach (that phone country picker's own heading is 11 ancestors up, past two
  nested field wrappers); the answer is the structural guard in the next bullet, not a bigger cap.
- **Skipping a field in the heuristic does not keep the LLM away from it.**
  `augment_skipped_fields` treats every `skip` as an unanswered candidate, so a heuristic skip is
  a suggestion, not a decision. A phone country picker proved this: `field_mapper` skipped it for
  want of a country, and the LLM pass — seeing a combobox under a "Phone number" heading — typed
  the phone number into it. Anything the heuristic skips *on purpose* must also fail
  `_is_llm_eligible`, which is why `PHONE_KEYWORDS` is public alongside `EEO_KEYWORDS`. A keyword
  guard only holds where a keyword actually reaches the haystack, though, so the general rule is
  structural: a dropdown-like field with no label, no section and no options is unguessable and
  `_is_llm_eligible` refuses it regardless of keywords.
- **`field_haystack` folds accents, and that is the only normalizing it does.** A résumé dropzone
  labelled "Résumé" matches none of `_RESUME_KEYWORDS`, since those are plain substring checks —
  hence the NFKD fold. Do not extend this into separator normalizing (treating `-`/`_`/spaces
  alike): that was tried, and it broke `"email"` against `"e-mail"`.
- **UI lives in a content script, not a toolbar popup.** `extension/src/content/panel.js` injects
  on every page (`<all_urls>`, a required permission) and mounts a closed shadow DOM host with a
  corner tab + slide-out panel — this replaced the old `action.default_popup`
  (`popup.html`/`popup.js`) because a browser popup is destroyed on every close, including a tab
  switch, wiping its UI state. A content-script-injected DOM node persists across tab switches for
  free (it's just hidden, not destroyed); `browser.storage.session` (keyed `scan:<tabId>`) still
  covers the one case that does reset it — a full page reload/navigation. `extension/src/
  background.js` owns everything that needs privileged APIs unavailable to content scripts: all
  `fetch` calls to core, and every `scripting.executeScript` injection (`scanPage`,
  `applyFillPlan`) — `panel.js` talks to it via `browser.runtime.sendMessage`/`onMessage`, never
  calls core or `scripting.*` directly.
- **React-controlled inputs** don't pick up `el.value = x`. Use the native property setter
  (`Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set`) then
  dispatch `input`/`change` events. See `applyFillPlan` in `extension/src/background.js`.
- **Custom comboboxes** (Greenhouse/Ashby's country/gender/location pickers) are not native
  `<select>` — a text input plus a JS-rendered listbox. `applyFillPlan` in `background.js` decides
  this from the live element at fill time (`isDropdownLike` — role, `aria-haspopup`,
  `aria-autocomplete`, or `aria-controls`/`aria-owns`), not from the action core/Settings
  assigned, since different ATSs mark up dropdowns differently and an upstream guess can be
  wrong. `selectValue` opens the widget and searches when its options do not match, including
  an expanded but empty menu, then clears the search and scans the unfiltered/virtualized list.
  ARIA option scopes resolve inside the field's own shadow root first; unscoped fallback excludes
  options that were already visible before this widget opened. A selected option or chip confirms
  a multi-select without requiring its menu to close. Input-only autocomplete values must survive
  blur after a commit event or an option click that closes the menu; typed text alone is not success.
  Fills are sequential (`async`, not parallel) because opening one combobox can close another.
- **ATS forms embedded in a cross-origin iframe** (Newton/gnewton career pages are the known
  case) are invisible to a same-frame-only scan — `background.js`'s scan handler injects
  `scanPage` with `target: { tabId, allFrames: true }` and merges every frame's fields, prefixing
  each `ref` with its `frameId` (`refFrameMap`, built in `background.js` and handed back to
  `panel.js` to store, maps the prefixed ref back to `{frameId, localRef}` for Fill, since a ref
  only resolves inside the frame it was scanned from). Firefox returns partial results for frames
  the extension lacks permission for instead of failing the whole call; this now always has
  access since `<all_urls>` is a required host permission (no more per-site opt-in flow).
- **Legal attestations are never auto-filled by core**, even if a mapper could guess an answer —
  that's the applicant's own click to make. Hard rule in `agent/llm_mapper.py`
  (`_ATTESTATION_KEYWORDS`), not a confidence threshold — never relax this via prompting alone.
- **EEO/demographic fields are never guessed from a CV or job posting** — `agent/field_mapper.py`
  (`EEO_KEYWORDS`) marks them `eeo_pending` instead of running the normal heuristic/LLM passes,
  and `ApplicationService._resolve_eeo` resolves that placeholder via `agent/eeo_mapper.py`: one
  dedicated MiMo call whose prompt receives *only* the EEO fields and the user's own
  `{match, answer}` Settings rows (typed in Manage CVs > Settings, sent as `eeo_answers` on the
  scan request) — no CV text, no job posting text, so the model has nothing else to invent an
  answer from. It may normalize wording or pick the closest matching option (e.g. "im asian" for
  a "hispanic" row correctly resolves a separate ethnicity question to "No", distinct from a
  "race" row), but every value still traces back to something the user explicitly typed; a field
  with no matching row, an empty row, or an unconfigured/failed MiMo call resolves to `skip`
  (`agent/eeo_mapper.py`'s `resolve_eeo_fields` degrades to all-skip in every one of those cases,
  same never-crash-the-scan pattern as `llm_mapper`/`cover_letter`). `background.js`'s
  `applyEeoSettings` still runs afterward as a client-side verbatim fallback for anything core
  still returned `skip` on. An `eeo_pending` field must stay out of `augment_skipped_fields`'s
  `action == "skip"` candidate filter so it's never sent to the CV-grounded LLM pass at all —
  that holds because every pass reads the same heuristic plan (see the parallel-passes bullet
  below), where an EEO field's action is `eeo_pending` and never `skip`.
  Resolved EEO values are persisted in `Application.field_mapping` in SQLite like every other
  answer (same as the cover-letter text) — they no longer stay entirely client-side. Radio-button-
  rendered EEO questions aren't handled by either path yet
  (not seen on any test site so far); don't build that blind — confirm the actual markup on a
  real ATS first.
- **A scan's three AI passes run in parallel threads, not in sequence.**
  `ApplicationService._run_resolution_passes` forks `augment_skipped_fields`, `_resolve_cover_letter`
  and `_resolve_eeo` off the same `build_fill_plan` output in a `ThreadPoolExecutor` and merges
  their results by `ref`. This is only correct because each pass owns a disjoint slice of the plan,
  identified by the heuristic action it replaces — `skip`, `cover_letter_upload`/`cover_letter_type`,
  and `eeo_pending` respectively — and a pass's edits outside its own slice are discarded by the
  merge. Adding a pass, or making one rewrite an action it doesn't own, breaks that: keep the
  owned-action set in `scan()` exactly matched to what the pass actually changes. The passes touch
  no ORM object (they take plain dicts, a `CvDTO` and strings; the only DB write is `_repo.create`
  after the join), which is what makes running them off the request thread safe.

- **hh.kz: decide from the popup JSON, confirm from negotiations, never solve captchas.**
  `GET /applicant/vacancy_response/popup?vacancyId=` returns résumés, letter requirement,
  questionnaire flag and prior responses, so discovery never opens the response modal.
  `alreadyApplied` there stays false after a successful send while another résumé could still be
  used — a sent response is `negotiations.topicList`/`usedResumeIds`. A headless submit can get a
  403 plus captcha, and captcha solving must not be automated: the user declined to have it
  automated and it is the site's own bot check. What the agent does instead (`captcha.py`): it
  asks on the desktop (`notify.ask_desktop`, a critical notification with an "Open browser"
  button, `HUNTER_CAPTCHA_WAIT_MINUTES`); on a click it closes the virtual browser and
  `assisted_apply` reopens the same profile visibly on the user's display, resends that row with
  `headed=True` (the hh adapter waits for the captcha element to go away, nothing more) and keeps
  sending while the user is there. Unanswered, the row goes back to `ready` (nothing was sent)
  and the site waits on a ladder, `HUNTER_CAPTCHA_BACKOFF_MINUTES` (5, 30, 60, 180, 480): each
  ignored captcha climbs a rung, a clean send resets it and remembers the rung that worked as
  the next starting point (forgotten one rung per later clean send). `retry_paused` waits for
  rungs due within 35 minutes at the end of a run (logging every 5 minutes so the heartbeat
  stays fresh) and retries with `crawl=False`; longer rungs are picked up by later cycles.
  Manual headed sends (`only`) ignore the wait and stay held if they fail. Only adapters with
  `HEADED_CAPTCHA` get the ask. `SEND_GAP`/`MAX_SENDS_PER_RUN` pace each site.
- **Refs don't survive a full re-render.** If the SPA re-renders the form between Scan and
  Fill, the stamped `data-jf-ref` attributes are gone — the fix is re-scanning, not retrying.
- **`agent/option_resolver.py`'s EEO-safety is entirely because it never sees CV or page text** —
  it can resolve a `gender`/`veteran_status`/etc. field same as any other, since it's only
  reconciling an already-decided value (sourced upstream from the user's own CV/Settings answers)
  against the page's real option wording, never inventing one. Adding page text "for context" —
  e.g. to help it resolve an ambiguous label — would silently break that guarantee for EEO fields
  routed through it; if that's ever needed, EEO refs must be excluded from this endpoint's input,
  not just trusted to behave.
- **A combobox's real options don't exist in the DOM until it's opened** — `form_snapshot`'s
  `options` is `[]` for these at scan time, so both mappers guess blind. `background.js`'s
  `applyFillPlan` finds the actual options at fill time and, on a mismatch, opens the round trip
  described above instead of leaving a wrong guess typed in. Also: never locate a field's own
  toggle/menu by walking up to the nearest ancestor matching a loose class-name pattern (e.g.
  `[class*="control" i]`) — on a real ATS this walked past the field's own wrapper to a shared
  page-level container, so every combobox on the page ended up clicking and reading one single
  unrelated field's menu. Click the exact `data-jf-ref`-stamped element itself instead; it's
  guaranteed correctly scoped.
- **A generated CV's "added skills" list is computed in Python, not taken from the model.**
  `cv_writer.rewrite` asks the model to report every technology it added, and then re-derives the
  list by diffing the rendered skills against the source CV's raw text — because the model does
  miss some (an observed run added "Docker" and reported only "Temporal"). The union is what the
  UI shows. That list is the entire safety story for the "apply a modern 2026 stack" feature, so
  never replace it with the model's own `added_skills`.
- Only `core/.env` (git-ignored) holds secrets — `MIMO_API_KEY` included. Never put a key in a
  commit or `docker-compose.yml`. An empty `MIMO_API_KEY` is a valid, supported state:
  `llm_mapper.augment_skipped_fields` no-ops and the heuristic-only plan is returned as-is.

## Conventions

- Comments: do not write comments in code. Do not add them for new/edited code, and do not
  restate what the code does.
- Commit messages: single line, `<prefix>: <description>` (`feat:`, `fix:`, `chore:`), no body,
  no attribution trailers.
