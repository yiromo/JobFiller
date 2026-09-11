# Progress log

Newest first. One entry per feature commit — added when the feature actually lands, not before.

## Fixes

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
  checks still apply). Not yet re-verified against the real Greenhouse page.

## Done

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
