# Progress log

Newest first. One entry per feature commit — added when the feature actually lands, not before.

## Done

- **"Analyze Application" button — CV fit, company insight, and job-market stats grounded in
  live web search** — new `POST /api/v1/applications/analyze/`
  (`{application_id, page_text, about_text}` -> `{fit_score, fit_summary, company_insights,
  market_stats, apply_timing, suggestions}`). MiMo alone has no internet access and would
  fabricate "current" company facts and statistics, which defeats the point of an analysis meant
  to reflect real, current conditions — so `agent/analyzer.py` adds a real search step via the
  Tavily API (`TAVILY_API_KEY`, new optional `.env` setting, same empty-key-disables pattern as
  `MIMO_API_KEY`): one MiMo call extracts `{company, role, company_query, market_query}` from the
  job posting text, two Tavily searches run (`topic: "general"` for the company, `topic: "news"`
  + `time_range: "month"` for market/demand stats so figures are actually fresh), then a second
  MiMo call synthesizes the final report — grounded strictly in the given CV/posting text for
  `fit_score`/`fit_summary`, and strictly in the Tavily snippets for `company_insights`/
  `market_stats` (each point required to carry the source `url`/`published_date` it came from;
  empty array rather than an invented fact if search found nothing useful). Reuses the CV-prose
  house style from `cover_letter.py` (no em dash, no AI-assistant stock phrasing) since this is
  also free-form generated text. `ApplicationService.analyze_application` mirrors
  `regenerate_cover_letter`'s error shape: 404 unknown application, 400 no CV on the record, 503
  if either `MIMO_API_KEY` or the new `SearchNotConfiguredError` (`TAVILY_API_KEY`) is unset —
  never silently degrades to hallucinated stats, since grounding is the entire point of this
  feature. No new persistence (ephemeral per click, like cover-letter regeneration's returned
  text). Extension: new "Analyze Application" button (gated on `lastApplicationId`, same as
  Generate Cover Letter) renders the report into a new `#analysis-result` block built via DOM
  APIs (`textContent`, not `innerHTML`) since `company_insights`/`market_stats` ultimately
  originate from third-party web search results relayed through the LLM — untrusted content —
  and source links are restricted to `http(s)` with `rel="noopener noreferrer"`. Wired into the
  existing `saveScanState`/`restoreScanState` round trip alongside the cover-letter preview so
  the report survives a popup close. `analyze()` logs the extracted search queries and Tavily hit
  counts, and `_synthesize` logs MiMo's raw parsed response (same `logger.warning` pattern as
  `llm_mapper`/`eeo_mapper`) so a "why is this section empty" report is diagnosable from
  `docker logs` rather than guessed at; `_synthesize` also normalizes every field with `.get(...,
  default)` before returning, since `response_format=json_object` guarantees valid JSON but not
  that MiMo's keys match the prompt (this codebase has documented prompt-drift flakiness
  elsewhere) — a missing key degrades to an empty/zero field instead of a 500. Gunicorn's
  `--timeout` raised from 60 to 180 in `core/Dockerfile`: this feature's worst case is four
  sequential MiMo/Tavily calls (45+20+20+60s), which the old 60s timeout would have had gunicorn
  kill mid-request. Verified live end to end against the real `Application` #35
  (CircleCI/Greenhouse, `cv_id=3`) with a realistic job-posting text: a fit score with concrete
  CV-gap reasoning, company insights and market stats each citing a real source URL (one run's
  empty `company_insights` turned out to be normal search/synthesis variance, not a bug — a
  second identical curl after adding the logging returned 2 grounded company facts and 2 dated
  market stats, confirmed via `docker logs`), an apply-timing note based on the posting's stated
  age, and CV-specific suggestions; separately verified 404 (nonexistent application), 400
  (`#26`, no CV on record), and confirmed the Tavily request/response shape by hand
  (`Authorization: Bearer`, `results[].{url, title, content, published_date}`) before writing the
  client, rather than guessing the API from memory. `ruff check` clean on all new/edited files
  (pre-existing formatting drift in 5 unrelated files, untouched), `manage.py check` clean,
  `web-ext lint` clean (same pre-existing manifest warnings), `node --check` clean on `popup.js`.
  Not yet driven in a real browser.

- **Manual "Generate Cover Letter" button + About-section context** — scan-time generation
  (`ApplicationService._resolve_cover_letter`) only ever ran once per scan and only for fields the
  keyword match caught; there was no way to re-roll a letter or get one at all on a page with no
  detected cover-letter field. Added `POST /api/v1/applications/generate-cover-letter/`
  (`{application_id, page_text, about_text}` -> `{text, entries}`): `ApplicationService
  .regenerate_cover_letter` loads the persisted `Application` by id (not a fresh CV/page_text pair
  from the request — cv_id and form_snapshot come from the stored row, so the button doesn't need
  to re-send everything scan already captured), re-identifies cover-letter refs from the stored
  `form_snapshot` via a new `agent.field_mapper.is_cover_letter_field` (extracted from the same
  check `_map_field` already used, so both stay in sync on what counts), regenerates, and persists
  the updated entries back into `field_mapping` (`ApplicationRepository.get`/
  `update_field_mapping`, new `ApplicationDTO`) — so a later Fill uses the new text. A
  no-CV-on-record application returns 400 and an unset `MIMO_API_KEY` returns 503 (mirrors the
  scan path's degrade-not-crash guard, but a manual click needs an explicit answer instead of a
  silent skip). Zero matching refs still returns 200 with `entries: []` so the button also works
  for copy-paste on a page with no recognized cover-letter field at all.
  Extension: `popup.html`/`.js` add a "Generate Cover Letter" button and a readonly preview
  `<textarea>`; clicking it calls the new endpoint with the page text/about text captured at scan
  time (does not re-run `scanPage`, which would re-stamp `data-jf-ref` and duplicate the
  frame-selection logic for no gain) and splices the returned `entries` into `lastFieldMapping` by
  ref. The popup document is destroyed on every outside click (existing `storage.session` comment
  in `popup.js`), so `lastApplicationId`/`lastPageText`/`lastAboutText`/the preview text are wired
  into the existing `saveScanState`/`restoreScanState` round trip alongside `lastFieldMapping` —
  without this the button would silently go stale (disabled, unrecoverable short of a full
  re-scan) the moment the user clicked anything on the page, which is the common case. Gating is
  now purely "a scan produced an `Application` id" rather than "a CV was selected at scan time" —
  the actual CV check happens server-side against the persisted record, and `cvSelect`'s value
  isn't itself persisted across popup reopens, so gating on it at restore time would have been
  wrong anyway.
  Also: `scanPage`'s `extractAboutText` pulls the posting's own "About the company/role" blurb
  from the *untruncated* body text (page_text's LLM-context field is cut at 15000 chars and an
  About section can sit past that) and sends it separately as `about_text` on both the scan and
  generate-cover-letter requests; `agent/cover_letter.generate()` gives it its own labeled block
  in the prompt rather than folding it into the generic job-posting text. The heuristic requires
  the candidate "About" line's next non-empty line to read like real prose (>=60 chars) before
  accepting it, specifically so a bare nav link ("About" in the header, followed immediately by
  another short nav item) doesn't get picked up as the section. `about_text` is taken from the
  lowest-frameId frame that has one (not tied to `bestFrame`, which is chosen by field count) since
  the About blurb is typically in the top frame even when the actual form is in an embedded ATS
  iframe. Verified end-to-end against the running container with real persisted data: `curl`'d the
  new endpoint for `Application` #32 (a real KoBold/Greenhouse posting, `cv_id=3`) with a synthetic
  about_text and got back a letter that referenced the about text's specifics, an `entries` list
  with the correct `upload`+`.docx` shape for the page's `cover_letter` file field, and confirmed
  the write landed in `Application.field_mapping` in the DB; separately verified the 400 (no CV on
  the application, using #26) and 404 (nonexistent application id) paths, and the empty-`entries`
  copy-paste path (#29, no cover-letter field on that page). `ruff check` + `manage.py check`
  clean, `web-ext lint` clean (same pre-existing manifest warnings), `node --check` clean on the
  extension JS. Not yet driven in a real browser — the popup button click, the preview textarea,
  and the storage-session persistence round trip are reviewed but unverified in an actual
  Firefox/Zen popup.

## Fixes

- **Cover-letter fields skipped when unlabeled, silently — root cause of "cover letter never
  attaches, résumé does"** — `_COVER_LETTER_KEYWORDS` only matched the literal phrase "cover
  letter" (a space required), while `_RESUME_KEYWORDS` matches single words with no such
  requirement — that asymmetry is exactly why résumé always worked and cover letter didn't. Real
  ATS file inputs routinely have no `<label for>`/`aria-label` (the visible "Cover Letter" text
  sits in an unassociated heading), so `field_haystack` falls back to `name`/`id`, which use
  `cover_letter`/`coverLetter`/`cover-letter` — none contain a literal space. Confirmed against
  real persisted data, not just synthesized: `Application` #27 (Databricks/Greenhouse,
  `gh_jid`-style embed) had `id: "cover_letter"`, `label: "Attach"` (a shared generic label) and
  a persisted `action: "skip"`; #32 (a separate Greenhouse posting) showed the same
  `0:cover_letter` ref skipped by both the heuristic and the LLM pass. Fixed by widening
  `_COVER_LETTER_KEYWORDS` to `("cover letter", "cover_letter", "cover-letter", "coverletter")`
  — deliberately *not* a general separator-normalizing rewrite of `field_haystack` (tried first,
  reverted: replacing `_`/`-` with spaces broke `_EMAIL_KEYWORDS`'s `"email"` against `"e-mail"`
  and would have broken `_LINKEDIN_KEYWORDS` against a hypothetical `"linked-in"` id — this fix
  is scoped to the one keyword list that needed it). Verified by patching the fix into the running
  `job-filler-core-1` container and replaying the exact #32 field through `build_fill_plan`: now
  resolves to `cover_letter_upload`. This also fully verifies "Scan hidden file inputs" further
  below — the previously-unverified Greenhouse case was this bug, not (only) a visibility gap.

## Done

- **EEO Settings answers routed through a dedicated AI pass instead of verbatim client-side
  matching** — the old `applyEeoSettings` client-side fill required the Settings answer text to
  literally substring-match a field's real option text (e.g. "i do not have any" never matched
  "No, I do not have a disability"), so real ATS EEO selects mostly stayed skipped. Changed the
  boundary from "core never sees EEO fields" to "AI never invents an EEO answer":
  `field_mapper.py` now marks EEO fields `eeo_pending` instead of `skip`;
  `ApplicationService._resolve_eeo` resolves that via new `agent/eeo_mapper.py`, one MiMo call
  whose prompt receives *only* the EEO fields and the user's `{match, answer}` rows (no CV text,
  no job posting text — nothing else to invent from), so it can normalize wording and disambiguate
  e.g. a "hispanic" row from a "race" row and pick the closest real `<select>` option. Extension
  now sends `eeoAnswers` as `eeo_answers` on the scan request; `applyEeoSettings` is kept as the
  client-side verbatim fallback for anything core still returns `skip` on. `_resolve_eeo` runs
  after the cover-letter step, not before `augment_skipped_fields`, so an `eeo_pending` field
  never becomes an `action: "skip"` candidate for the CV-grounded LLM pass. Reused
  `llm_mapper.validate_override` (renamed from `_validate_override`) for the new mapper instead
  of copying it, so the action-keyword-echo strip (`_ACTION_ECHO_RE`, from a prior live bug) isn't
  duplicated. Note: resolved EEO answers are now persisted in `Application.field_mapping` in
  SQLite like every other mapped field — they no longer stay entirely client-side. Verified via curl
  against the real MiMo API with a synthetic snapshot matching the actual Settings rows in use
  (gender/hispanic/race/veteran/disability): correct option picked for every native `<select>`,
  correct free-text normalization for a plain input, "hispanic: im asian" correctly resolved to
  "No" on a distinct ethnicity-question select rather than leaking into the race question, and
  all three negative cases confirmed skip (no relevant row, empty-answer row, no `eeo_answers` sent).
  `ruff check` + `manage.py check` clean, `web-ext lint` clean (same pre-existing warnings). Not
  yet re-verified against a real ATS page in a live browser. Known gap, unchanged: radio-rendered
  EEO questions still aren't handled by either path (`tasks/BACKLOG.md` item 8).

## Fixes

- **Checkbox-list questions (single choice rendered as separate `<input type="checkbox">`
  fields) silently never got checked** — a real Ashby form (Toggl) has a "which best describes
  your experience" question rendered as five independent checkbox inputs, each with the option
  text as its own label. `llm_mapper`'s system prompt only documented `"type"`/`"select"`
  actions, so MiMo had no correct action for a `type: "checkbox"` field and guessed `"select"`
  with the option's own label text as the value — `validate_override` let it through unvalidated
  (no `options` list to check against on a checkbox field), and `popup.js`'s fill routes a
  `"select"` action through `selectValue` regardless of element type, which types text into a
  checkbox input and looks for `[role="option"]` elements that don't exist there, so the checkbox
  was never actually checked. Confirmed by pulling the real `Application.form_snapshot` from
  SQLite for that scan and reproducing the exact bad response locally (`action: "select"`, value
  either the option's own label or the bare word `"select"`). Fixed by adding a `"check"` action
  to the prompt (checkbox fields must respond `check`+`"true"` or `skip`, never `check`+`"false"`
  — `popup.js`'s `el.checked = Boolean(item.value)` would treat any non-empty string, including
  `"false"`, as checked) and handling it in `validate_override` before the generic
  type/select path. Verified: re-ran the exact reproduction, `cb0` (the option the CV actually
  supports) now returns `check`/`true`, the other four correctly `skip`.
  Also investigated in the same pass, both against the real logged scan: (1) the same scan's four
  essay `<textarea>` fields all came back with the literal bare value `"type"` (already-correct
  behavior: `validate_override`'s existing bare-echo check turns this into `skip`) — reproduced
  the same batch of fields against the real CV twice outside the app and got full grounded
  answers both times, so this is genuine model flakiness on that one live call, not a code defect
  (matches the "stochastic prompt-echo" conclusion from the earlier single-field version of this
  same failure mode, now confirmed reproducible-but-intermittent rather than assumed). (2) the
  custom-combobox "Location" field (`role: combobox`, no scanned `options`) got a plausible
  CV-grounded value ("Astana, Kazakhstan") that then visibly sat in the input without being
  selected from the site's own dropdown — this is the documented `selectValue` typed-text
  fallback (`CLAUDE.md`), not a new bug; needs the popup's per-field log output
  (`ok`/`no-matching-option`/`dropdown-never-opened`) to tell which case it hit. (3) two Yes/No
  toggle questions on the same page never appeared in `form_snapshot` at all — not native
  radio/checkbox inputs, so invisible to `scanPage`'s scan, the same class of gap as
  `tasks/BACKLOG.md` item 8 (button/div-based widgets with no underlying form control); needs
  the real outerHTML before building a fix, not guessed at.

- **Click the dropdown's real toggle instead of guessing at click targets** — a real fill log
  showed every custom-combobox field on a react-select-based ATS (KoBold's Greenhouse-alternative
  form) failing with `no-matching-option`, while native `<select>` fields on the same page worked
  fine — not an EEO-specific bug, a mechanism bug affecting every non-native dropdown. Got the
  real markup this time (outerHTML of an open Gender field) instead of guessing a third
  heuristic: this widget has a dedicated toggle button (`aria-label="Toggle flyout"`, sibling of
  the input inside the `.select__control` wrapper) that opens the menu independent of focus, and
  no `aria-controls`/`aria-owns` on the input at all — meaning the old fallback's "click el/
  el.parentElement" never opened anything, and `findOptions`' document-wide fallback search could
  match stale `[role="option"]` elements left over from a previous field's widget, producing a
  false "options found" that then failed to match (`no-match`, not `no-options` — which is why
  the earlier single-screenshot diagnosis of "menu never opens" was wrong; the real problem was
  matching against the wrong menu). Fixed in `popup.js`: `findToggleControl` finds a button/
  `[role="button"]`/svg inside the nearest `[class*="control" i]` ancestor and `selectValue`
  clicks it *before* typing anything (typing-to-filter is now the fallback, not the first move);
  `findOptions` scopes to the menu sibling of that same control wrapper before ever falling back
  to a whole-document search. Also surfaced `no-options` (dropdown never opened at all) as a
  logged failure (`dropdown-never-opened`) instead of silently `ok: true`, so the next log can
  tell "never opened" apart from "opened, nothing matched" — worth keeping even after this is
  confirmed working. Not yet re-verified against the real page (inferred from static markup, not
  a live DOM interaction) — needs the user to re-test and send the log again. Separately: even
  with the menu correctly found, `bestMatch`'s exact/substring matching won't match a Settings
  answer like "i do not have any" against real option text like "No, I do not have a disability"
  — no fuzzy matching added for this (risk of silently picking the wrong option on a legally
  sensitive field is worse than leaving it skipped); the fix there is wording the Settings answer
  as a literal substring of the real option (e.g. "No, I do not").
- **Scan hidden file inputs** — a real Greenhouse "Cover Letter" upload widget ("Attach /
  Dropbox / Google Drive / Enter manually") never got the generated `.docx` because `scanPage`
  skipped it via the same `isVisible` check used for every field — file inputs are routinely
  styled `display:none` behind a custom button, which doesn't stop `el.files = ...` + a `change`
  event from working. `type === "file"` now bypasses the visibility check (honeypot/disabled
  checks still apply). Confirmed via real persisted data (`Application` #27/#32, see the
  cover-letter keyword fix above): the hidden file input was scanned and reached core fine — the
  remaining miss on that page was the keyword-matching bug, not this visibility gap.

- **Cover letter generator (.docx)** — any field matching "cover letter" (haystack: label/name/
  id/placeholder) now gets a real generated letter instead of being skipped or handed to the
  generic LLM pass. New `agent/cover_letter.py`: `generate()` makes one dedicated MiMo call per
  scan (separate from `llm_mapper`'s batch pass — a proper 250-400 word, three/four-paragraph
  letter needs its own prompt, not the general "concise 50-150 word" one), `render_docx()` builds
  the `.docx` via `python-docx` (already a dependency). `field_mapper.py` marks matching fields
  with placeholder actions (`cover_letter_type` for paste fields, `cover_letter_upload` for file
  fields) before the resume/profile checks run, so the general LLM pass never touches them (it
  only acts on `action: "skip"`). `ApplicationService._resolve_cover_letter` generates once and
  resolves both placeholders from the same text — a paste field becomes a plain `type` action, a
  file field becomes an `upload` action carrying the docx bytes inline as base64 in a new `file`
  field on the mapping item (no stored CV row behind it, unlike résumé upload) so the extension
  can attach it via the same `DataTransfer` path with no extra fetch. If MiMo is unconfigured or
  the generation call fails, both placeholders fall back to `skip` (never partially fill, never
  crash the scan — same guard pattern as `llm_mapper.augment_skipped_fields`). Verified via curl
  against a real CV: the file-upload field came back with a valid `.docx` (correct `PK` zip
  signature, ~37KB), the paste field came back with a 303-word, three-paragraph letter grounded
  in the actual CV/job-posting text, no bracketed placeholders. Not yet driven in a real browser.
  Note: the generated letter's text is persisted as part of the `Application` row's
  `field_mapping` in SQLite (not regenerated-and-discarded) — same as every other LLM answer.
- **Fix bare "type"/"select" value slipping past the echo-strip guard** — the earlier
  action-keyword-echo fix (`_ACTION_ECHO_RE`) only stripped a leading `"type "`/`"select "` when
  followed by real content; a value that was the bare word `"type"` with nothing after it (no
  `\s+` for the regex to match) passed through unchanged and got typed verbatim into several
  free-text fields on a real form ("How did you hear about this opportunity?", "please give
  date(s) and position(s)"). Fixed in `_validate_override`: after the regex strip, also skip if
  the remaining value is empty or exactly `"type"`/`"select"` case-insensitively. Verified via
  `_validate_override` directly: bare `"type"`/`"Type"`/`"select"` now skip, `"type Backend
  Developer"` still correctly reduces to `"Backend Developer"`, and real answers are untouched.
- **Scan/fill forms embedded in a cross-origin iframe** — a real Newton/gnewton career page
  ("View our Job Openings!") returned "Found 0 fields" because its actual form lives inside
  `<iframe id="gnewtonIframe">` on a different domain than the careers page, and `scanPage` only
  ever queried the top-level document. Confirmed via MDN before building (not guessed): Firefox's
  `activeTab` covers the top frame and same-origin frames only — a cross-origin iframe needs an
  explicit host permission — and `scripting.executeScript` with `allFrames: true` returns partial
  results for inaccessible frames in Firefox rather than rejecting the whole call (Chrome does
  reject; irrelevant here, this is Firefox-only). Added `optional_permissions: ["<all_urls>"]` to
  the manifest and a "Grant page access" button in Manage CVs (`browser.permissions.request`) —
  requested from the persistent tab, not the popup, since a native permission prompt steals focus
  and would close the panel popup the same way the file picker used to. `scanBtn` now injects with
  `allFrames: true`, merges every frame's `form_snapshot`, and prefixes each `ref` with its
  `frameId` (`popup.js`'s `refFrameMap`, persisted in `storage.session` alongside the scan) since a
  `data-jf-ref` value only resolves inside the frame it was stamped in; `fillBtn` groups the plan
  back by frame and runs `applyFillPlan` once per `frameIds: [n]` with the un-prefixed ref. The
  page-posting text sent to core now comes from whichever frame contributed the most fields, not
  always frame 0 — for an iframe-embedded ATS the posting text lives in that iframe too, not the
  wrapping page. `web-ext lint`: 0 errors (3 warnings — the 2 pre-existing plus a new
  Android-incompatibility notice for `permissions.request`, irrelevant to this desktop-only
  extension). Not yet re-verified against the real gnewton page (no live browser here) — still
  needs the user to grant access and re-scan. Known-not-fixed on that same page, seen in the
  screenshot but out of scope for this pass: its resume upload is a "Choose a File / Google
  Drive / Dropbox" widget, and the actual `<input type=file>` behind it is almost certainly
  `display:none` — `scanPage`'s `isVisible` check would skip it, so resume upload likely still
  won't work there without seeing that input's real markup.
- **Strip MiMo action-keyword echo from typed values** — a real fill showed a job-title field
  filled with the literal text "type Backend Developer" instead of "Backend Developer". Couldn't
  reproduce with isolated `_call_llm` test calls, consistent with a stochastic prompt-echo (the
  system prompt's "respond with "type" and a free-text answer" wording invites the model to
  occasionally fold the action word into the value string). Fixed defensively in
  `llm_mapper._validate_override`: strips a leading `type`/`select` echo from the value via regex
  before use, same "validate the model's output, don't trust prompt compliance" pattern as the
  existing select-option and travel-guess guards. Also added `logger.warning` of the raw MiMo
  response in `_call_llm` (WARNING, not INFO — this project has no custom `LOGGING` config, so
  only WARNING+ reaches `docker logs`) to make the next "field came out wrong" report diagnosable
  without guessing blind again. Same pass: `_LOGISTICS_KEYWORDS` gained "authorized/authorised to
  work", "work authorization/authorisation", "eligible to work" — a batch test surfaced the LLM
  confidently answering "Are you legally authorized to work in the US?" with "No" at confidence
  1.0 with zero CV basis, the same travel-guess failure mode on a field that's also a legal
  attestation. Verified: re-ran `_validate_override` with a synthetic echoed value (strips
  correctly) and confirmed `work_auth`-style fields are now excluded from the LLM call entirely.
- **Fill dropdowns by structure, not by upstream classification** — live testing on a real
  Greenhouse form showed EEO Settings answers landing as typed text inside a dropdown instead of
  a selected option, tripping the site's "please choose an option" JS validation. Root cause:
  `applyEeoSettings` decided `type` vs `select` from the scan snapshot's `role` attribute, which
  is `"combobox"` on some ATS widgets but not others (Workday-style ones use `aria-haspopup`,
  `aria-autocomplete="list"`, or bare `aria-controls` instead). Fixed in `popup.js`'s
  `applyFillPlan`: any `"type"` target is now checked against the live DOM
  (`isDropdownLike` — native `<select>`, `role="combobox"/"listbox"`, `aria-haspopup`,
  `aria-autocomplete="list"`, or `aria-controls`/`aria-owns`) and, if dropdown-like, routed
  through the same type-then-click-option path as `"select"`. `selectValue` also gained a
  fallback: if typing the value filters a react-select-style list down to zero options (or never
  opens one), it clears the input and opens the widget by focus + click instead, then matches
  against the unfiltered list — falling back to the typed text only if no option list appears at
  all either way. Not yet re-verified against the real form (no markup was available this pass,
  only the reported symptom) — still needs a live retest. Known-uncovered pattern, documented
  rather than guessed at: a dropdown built from a `<div>`/`<button>` trigger with no
  `input`/`select`/`textarea` in it at all (Ashby/Workday sometimes do this) is invisible to
  `scanPage`'s querySelector and has no fill path yet.
- **Heuristic field-mapping agent** — `core/src/agent/field_mapper.py` replaces the stub in
  `ApplicationService`. Matches a scanned field's label/name/id/placeholder against known
  categories (email, first/last/full name, phone, resume upload) using the CV's extracted
  profile, passed via a new `cv_id` on the scan request. `Application` now has a nullable `cv`
  FK recording which CV a scan used. Hard rules, not confidence thresholds: EEO/demographic
  fields (gender, ethnicity, veteran, disability) are always skipped regardless of profile data;
  unrecognized fields (job-specific questions, custom comboboxes we can't structurally detect
  yet) are skipped, never guessed. The extension's popup now lists/uploads CVs, sends the
  selected `cv_id` on scan, and — for `action: "upload"` — fetches the CV's file bytes from
  `GET /api/v1/cvs/{id}/file/` and attaches it to the file input via `DataTransfer` in the page.
  `web-ext lint` still clean. End-to-end verified: uploaded the real test CV, scanned the real
  Greenhouse fixture with that `cv_id`, and got back exactly the expected plan — correct
  name/email/phone, resume flagged for upload, and every EEO field plus every job-specific
  question (GitLab username, interview name preference, LinkedIn profile, location) correctly
  skipped rather than guessed.
- **CVs: upload + extraction** — `POST /api/v1/cvs/` (multipart `file`), `GET /api/v1/cvs/`,
  `GET /api/v1/cvs/{id}/file/`. Extracts raw text (`pypdf` for PDF, `python-docx` for `.docx`)
  and a profile (`core/src/agent/profile.py`: regex email/phone, name from the first non-empty
  line with a filename fallback). Verified against the real test CV
  (`CV_Sanzhar_Amanzholov.pdf`) — checked the actual extracted text *before* writing the name
  heuristic (first line is `"Sanzhar Amanzholov"`, so no filename fallback needed here), and
  confirmed by curl: uploaded it, got back the correct name/email/phone, then downloaded the
  stored file via `/file/` and diffed it byte-for-byte against the source PDF (identical — the
  text-extraction stream doesn't corrupt what gets saved).
- **Browser extension skeleton** — Manifest V3 for Firefox (`extension/manifest.json`), popup UI
  (`extension/src/popup/`). "Scan this page" injects a field-scanner into the active tab via
  `scripting.executeScript` (no persistent content script — only runs on a user click), which
  stamps every candidate input/select/textarea with `data-jf-ref`, resolves its label
  (`label[for]`, closest `<label>`, `aria-label`/`aria-labelledby`), and skips honeypot
  (`aria-hidden`/`tabindex="-1"`) and hidden fields. Posts the result to
  `/api/v1/applications/scan/`. "Fill application" injects a fill executor that sets values via
  the native property setter + dispatches `input`/`change` (required for React-controlled
  inputs) and reports per-field success/failure back to the popup log.
  `npx web-ext lint --source-dir extension` passes clean (0 errors/warnings/notices) — this
  included adding `data_collection_permissions` to the manifest, declared honestly
  (`personallyIdentifyingInfo`, `websiteContent` — sent only to the local `core` API, never to a
  third party). **Not driven in an actual browser** — no browser automation tool was available
  in this session; see the root README for manual test steps.
- **Applications: scan endpoint (stub fill plan)** — `POST /api/v1/applications/scan/` takes a
  `form_snapshot` and returns a fill plan; text/email/tel fields get a placeholder value,
  everything else is skipped. This is intentionally dumb — it exists to prove the scan → DOM-fill
  wiring works before the real mapper (heuristic, next) lands, per `tasks/BACKLOG.md`. Verified
  with a `form_snapshot` built from the real Greenhouse GitLab posting's server-rendered HTML
  (`job-boards.greenhouse.io/gitlab/jobs/8704363002`), including its EEO/demographic fields and
  excluding its honeypot input — `ruff check`, `manage.py check`, migration applied, curl-tested.
- **Core backend skeleton** — Django 5 + DRF, uv-managed, SQLite, `GET /health/`. Verified:
  `ruff check`, `manage.py check`, `manage.py migrate`, curl'd `/health/` via `runserver` and
  again via a built Docker image (`docker build` + `docker run` + curl against the container).
- **Repo scaffold** — monorepo layout, root README, CLAUDE.md, tasks/.

- **MiMo LLM pass + custom combobox filling** — `agent/llm_mapper.py` sends whatever the
  heuristic mapper skipped (minus EEO, legal attestations, and unanswerable-from-a-CV logistics
  questions — travel/relocation/salary/notice/visa/start-date, all hard pre-filtered, never sent
  to the model) to `mimo-v2.5` in one batched call per scan, grounded in the CV's raw text and
  the scanned page's text. A no-op (returns the heuristic plan unchanged) when `MIMO_API_KEY` is
  empty or the call fails — never crashes a scan. Native `<select>` answers are validated
  server-side against the field's real `options` list (exact, then substring match, else skip)
  so the model can't invent an option that doesn't exist. `popup.js`'s scan step now also sends
  `role`/`aria-haspopup`/`aria-controls` per field and the page's visible text, so the model can
  tell a custom JS combobox from a plain text input and has job-description context for
  open-ended questions. `applyFillPlan` is now `async` and fills sequentially (not
  `Promise.all`): a "select" on a non-native-`<select>` element types the value, polls (2s) for
  `[role="option"]` inside `aria-controls` (or the whole document), and clicks the best
  case-insensitive match — this is the actual mechanical fix for Greenhouse/Ashby-style
  comboboxes (School/Degree/Discipline, Country, etc.) that were previously always skipped.
  Verified: `ruff check` + `manage.py check` clean; live-called the real MiMo API (key confirmed
  live via `/v1/models`, `response_format: json_object` confirmed to return clean JSON); curled
  `/api/v1/applications/scan/` with a form snapshot built from the actual Canonical/Greenhouse
  fields in the user's screenshots (essay question, "willing to travel" select, country select,
  AI-use attestation select, gender select, a combobox-flagged school field) — essay answer
  correctly grounded in the real test CV's actual work history, country/school correctly
  answered from CV facts, gender/attestation correctly hard-skipped, and — after a live bug was
  caught and fixed (see below) — "willing to travel" correctly hard-skipped instead of the model
  confidently guessing "Yes". Combobox click-and-poll mechanics can only be confirmed in a real
  browser, not curl — not yet done.

- **EEO/demographic settings (user-declared, client-side only)** — a new Settings section on
  the Manage CVs page (`extension/src/manage/`) lets the user type their own answers to
  EEO/demographic questions (gender, race, veteran, disability status, etc.) once, as
  `{match, answer}` rows stored in `browser.storage.local`. This does **not** relax core's hard
  EEO skip rule — `field_mapper.py`/`llm_mapper.py` are untouched, core never sees these answers.
  `popup.js`'s `applyEeoSettings` applies them after core's plan comes back: for a field core
  left skipped, if the field's label/name/id/placeholder contains a row's `match` text, its
  `answer` is filled verbatim (matched against the field's real `<select>` options first,
  falling back to a plain "type" for text inputs and combobox role elements). An empty answer,
  or no matching row, leaves the field skipped exactly as before — the default is still "don't
  guess," this only adds a place for the user's own explicit statement. Also fixed a latent bug
  found while building this: `applyFillPlan`'s native-`<select>` handling did `el.value = value`
  assuming the mapper's chosen option *text* equals the option's `value` attribute — false
  whenever they differ (e.g. `<option value="US">United States</option>`), silently no-opping
  the fill. Now matches by visible text (reusing the same `bestMatch` combobox logic) and sets
  the real option's `.value`. Not yet driven in a real browser — `web-ext lint` clean.

## Fixes

- **MiMo confidently guessed "Yes" to an unanswerable question** — live-tested "are you willing
  to travel 2-4x/year?" (a preference question, not a CV fact) and the model answered "Yes" at
  confidence 1.0, ignoring the system prompt's explicit "skip if unknowable" instruction. A
  prompt cannot be trusted to self-police this category. Fixed by hard pre-filtering
  travel/relocation/salary/notice-period/visa/start-date questions out of the LLM call entirely
  (`agent/llm_mapper.py`'s `_LOGISTICS_KEYWORDS`), same mechanism as the EEO/attestation
  hard-skips — verified by re-running the same scan and confirming the field now comes back
  `action: "skip"`.
- **LinkedIn/GitHub/GitLab fields were always skipped even when answerable** — `profile.py`
  never extracted those URLs from CV text, so `field_mapper.py` had no data to offer even for
  a plain text field it could otherwise fill. Added regex extraction (`linkedin_url`, `git_url`)
  alongside the existing email/phone/name extraction, threaded through the `Cv` model → DTO →
  repository → service → serializer the same way those fields are. Verified against the real
  test CV: uploaded it, confirmed the API response includes both URLs, then scanned a synthetic
  form with "LinkedIn Profile"/"Github/Gitlab Account"/"Website" fields — the first two filled
  correctly, "Website" and a gender select still correctly skipped (no CV-derivable answer /
  EEO rule). Most other unfilled fields reported by the user (custom Greenhouse comboboxes,
  free-text essay questions) are the known gaps in `tasks/BACKLOG.md` items 1 and 7, not bugs.

- **Upload CV closed the popup, and a scan was lost on every popup close** — two separate
  bugs, same root cause of "the popup is a fragile, disposable document." (1) Clicking a hidden
  file input's `.click()` from inside a panel popup opens a native file picker, which steals
  focus and closes the popup before a selection can complete — a longstanding Firefox
  limitation, made 100% reproducible here because Flatpak Firefox/Zen brokers that picker
  through a separate `xdg-desktop-portal` process. Fixed by moving CV upload/listing to its own
  persistent extension page (`extension/src/manage/`), opened via `browser.tabs.create` from a
  "Manage CVs" button — `tabs.create` to the extension's own page needs no extra permission.
  (2) The popup document (and all its JS state, including the last scan's `field_mapping`) is
  destroyed and recreated every time it closes — a scan and a subsequent Fill had to happen in
  one uninterrupted popup session. Fixed with `storage.session` (new `storage` permission),
  keyed per-tab and checked against the tab's current URL before restoring, so reopening the
  popup on the same page brings back the last scan instead of starting over.

- **Popup appeared blank in the browser** — root cause was a Flatpak sandbox, not CSS. Zen on
  Linux is commonly installed via Flatpak, which only grants filesystem access to whatever the
  file-picker portal was pointed at. "Load Temporary Add-on…" reads `manifest.json` through that
  portal, so the extension shows as loaded with no error, but every sibling file (`popup.html`,
  `popup.js`, `popup.css`) is outside the sandbox and resolves to an empty document — confirmed
  via the Inspector showing a bodyless `<html><head></head><body></body></html>` for
  `popup.html` loaded directly as a tab. Fixed by granting the project directory:
  `flatpak override --user --filesystem=/path/to/job-filler app.zen_browser.zen`, then fully
  quitting Zen and re-loading the extension (a plain Reload doesn't re-apply the new grant). An
  earlier attempt made `popup.css` colors explicit instead of inherited — harmless, kept, but it
  was not the actual fix; noted here so the wrong diagnosis isn't repeated.
- **Fresh-clone quick start was broken** — `SECRET_KEY` has no default (`manage.py migrate`
  crashes with no `.env`), and `DATA_DIR` (holding `db.sqlite3`) was never created — SQLite
  doesn't create parent directories. README now says to `cp .env.example .env`; settings.py
  creates `DATA_DIR` on startup. Verified by actually cloning the repo into a scratch directory
  and following the README's backend steps verbatim (not just re-running in the already-set-up
  working tree).
- **Extension resume upload would have attached garbage** — `scripting.executeScript` args must
  be JSON-serializable; the raw `ArrayBuffer` fetched for the CV file wouldn't have survived
  that trip intact. Now base64-encoded in the popup, decoded back to bytes in the injected fill
  function before building the `File`.
- **`core/.dockerignore` wasn't excluding `src/data/`** — its bare patterns (`db.sqlite3`,
  `media`) didn't match that nested path, so a locally-migrated dev database got baked into the
  Docker image, making a brand-new named volume look already-migrated ("No migrations to apply"
  on a supposedly clean container — Docker seeds a new empty volume from the image's existing
  directory content). Found by inspecting the built image's filesystem directly, not by trusting
  a 200 from `/health/`. Fixed with an explicit `src/data` entry and re-verified against a
  genuinely fresh volume (`docker volume rm` + `docker compose up`) — migrations applied this
  time.
