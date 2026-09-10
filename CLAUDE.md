# CLAUDE.md

Guidance for Claude Code (or any agent) working in this repo.

## What this repo is

`job-filler` — an agent that fills job applications from a user's CVs. Monorepo:

- `core/` — Django 5 + DRF API, uv-managed. CV storage/parsing, job-posting scan, and
  field-mapping (deciding what value goes in which form field). All AI/agent logic lives
  behind this API — the extension never calls an LLM directly.
- `extension/` — Firefox (Zen) WebExtension (Manifest V3). Manually triggered per page: user
  clicks "Scan" to read the form, then "Fill" to apply the plan `core` returns. No crawling,
  no auto-apply, no background activity.

The proactive/background app (auto-scroll job boards, apply across many sites unattended) is
explicitly **not** built yet — see `tasks/BACKLOG.md`. Do not start it without being asked.

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
```

Docker: `docker compose up --build` (from repo root) — runs `core` on `:8000` with a SQLite
volume.

Extension: no build step (plain WebExtension JS, no bundler). Load unpacked via
`about:debugging#/runtime/this-firefox` → "Load Temporary Add-on…" → `extension/manifest.json`.
`npx web-ext lint --source-dir extension` catches manifest errors before loading.

There is no automated test suite. "Verify" means: backend `manage.py check` + `ruff check` +
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
  (`agent/profile.py` builds the structured profile from a CV's raw text).
- `applications` — `POST /api/v1/applications/scan/`: takes a page's `form_snapshot`, returns
  a fill plan built by `agent/field_mapper.py`.

`agent/` (`core/src/agent/`) is a **plain module, not a Django app** — it has no models. It's
injected into `cvs`/`applications` services via their own containers. Don't turn it into a
layered app; there's nothing to layer.

Settings: SQLite (no multi-user, nothing Redis-dependent, no deploy target yet — revisit if
that changes), `python-decouple` for env vars, CORS open to `moz-extension://` origins for
local extension testing.

## Field-mapping contract (core ↔ extension)

This is the one thing both sides must agree on. Content script scans the page and stamps every
candidate field with a `data-jf-ref` attribute (existing `id` reused when present), then sends:

```json
{
  "url": "...",
  "form_snapshot": [
    {"ref": "...", "tag": "input", "type": "text", "name": "...", "id": "...",
     "label": "...", "placeholder": "...", "options": [...], "required": true}
  ]
}
```

Core returns:

```json
[{"ref": "...", "value": "...", "action": "type|select|check|upload|skip", "confidence": 0.0}]
```

`ref` is the only thing the extension uses to find the element again — never a CSS selector or
guessed XPath. Fields the content script identifies as honeypots (`aria-hidden="true"`,
`tabindex="-1"` traps) or demographic/EEO questions are never sent for auto-fill guessing.

## Non-obvious things (these will bite you)

- **React-controlled inputs** don't pick up `el.value = x`. Use the native property setter
  (`Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set`) then
  dispatch `input`/`change` events. See `extension/src/content.js`.
- **Custom comboboxes** (Greenhouse/Ashby's country/gender/location pickers) are not native
  `<select>` — they're a text input + a JS-rendered listbox. Setting a value doesn't select an
  option. The mapper skips these rather than faking a fill; see `tasks/BACKLOG.md` item 7.
- **EEO/demographic fields are never auto-filled**, even if the mapper could guess an answer —
  these are legally-sensitive voluntary disclosures. This is a hard rule in
  `agent/field_mapper.py`, not a confidence threshold.
- **Refs don't survive a full re-render.** If the SPA re-renders the form between Scan and
  Fill, the stamped `data-jf-ref` attributes are gone — the fix is re-scanning, not retrying.
- Only `core/.env` (git-ignored) holds secrets, e.g. `MIMO_API_KEY` once that's wired in. Never
  put a key in a commit, a chat message that becomes a commit, or `docker-compose.yml`.

## Conventions

- Comments: only where intent is genuinely non-obvious (see list above). No restating what the
  code does.
- Commit messages: single line, `<prefix>: <description>` (`feat:`, `fix:`, `chore:`), no body,
  no attribution trailers.
