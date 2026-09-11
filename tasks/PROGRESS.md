# Progress log

Newest first. One entry per feature commit — added when the feature actually lands, not before.

## Done

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
