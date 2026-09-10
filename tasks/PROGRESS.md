# Progress log

Newest first. One entry per feature commit — added when the feature actually lands, not before.

## Done

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
