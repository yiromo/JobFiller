# job-filler

An AI agent that fills out job applications from your CVs. Monorepo with two pieces:

- `core/` — Django + DRF API: CV storage/parsing, job-application scan, and field-mapping (the "what goes in which box" logic). Everything AI-related lives behind this API.
- `extension/` — Firefox (Zen) WebExtension. Reads the application form on the page you're on, sends it to `core`, and fills in the answer it gets back. Manually triggered per page — it does not crawl or auto-apply anywhere.

See `CLAUDE.md` for architecture conventions and `tasks/` for what's built and what's next.

## Quick start

Backend:
```bash
cd core
cp .env.example .env   # generates nothing by itself — edit SECRET_KEY before real use
uv sync
cd src && uv run python manage.py migrate
uv run python manage.py runserver 0.0.0.0:8000
```

Or via Docker (also needs `core/.env` — same `cp` step, from `core/`):
```bash
docker compose up --build
```

Extension (Firefox / Zen), with `core` running on `localhost:8000`:
1. Go to `about:debugging#/runtime/this-firefox`.
2. "Load Temporary Add-on…" → select `extension/manifest.json`.
3. Click the extension icon → "Manage CVs" to upload one or more CVs (each stays listed for
   reuse). Then open a job posting (e.g. a `job-boards.greenhouse.io` listing), click the
   extension icon, pick a CV from the dropdown, click "Scan this page", then "Fill application".
4. Check the popup's log for skipped fields, and check the form itself before submitting
   anything — nothing here submits a form for you.

This has been lint-checked (`web-ext lint`) and its DOM-fill logic reviewed, but not yet driven
in a real browser session by whoever built it — try it on the sites in `tasks/PROGRESS.md` and
report what breaks.

**Zen/Firefox installed via Flatpak (common on Linux):** the extension will appear to load with
no errors but its popup will be completely blank. The Flatpak sandbox only grants filesystem
access to the one file the "Load Temporary Add-on…" picker points at (`manifest.json`) — every
sibling file (`popup.html`/`.js`/`.css`) is unreadable and resolves empty. Fix:
```bash
flatpak override --user --filesystem=/absolute/path/to/job-filler app.zen_browser.zen
```
then fully quit and relaunch Zen, and re-load the extension (Reload alone won't pick up the new
grant — remove it and "Load Temporary Add-on…" again).

## Status

`core`'s field-mapping is a heuristic (keyword/regex) matcher, not an LLM yet — it fills
contact fields (name/email/phone) and the resume upload from your CV, and skips anything it
can't answer confidently: job-specific questions, custom dropdown pickers, and — always,
regardless of confidence — EEO/demographic questions (gender, ethnicity, veteran, disability
status). See `tasks/PROGRESS.md` for what's actually built and `tasks/BACKLOG.md` for what's
next (MiMo integration for the fields the heuristic can't handle, CV structuring, fit rate,
multi-CV matching). No proactive/background app yet (out of scope for now).
