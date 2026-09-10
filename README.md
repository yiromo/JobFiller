# job-filler

An AI agent that fills out job applications from your CVs. Monorepo with two pieces:

- `core/` — Django + DRF API: CV storage/parsing, job-application scan, and field-mapping (the "what goes in which box" logic). Everything AI-related lives behind this API.
- `extension/` — Firefox (Zen) WebExtension. Reads the application form on the page you're on, sends it to `core`, and fills in the answer it gets back. Manually triggered per page — it does not crawl or auto-apply anywhere.

See `CLAUDE.md` for architecture conventions and `tasks/` for what's built and what's next.

## Quick start

Backend:
```bash
cd core
uv sync
cd src && uv run python manage.py migrate
uv run python manage.py runserver 0.0.0.0:8000
```

Or via Docker:
```bash
docker compose up --build
```

Extension (Firefox / Zen):
1. Go to `about:debugging#/runtime/this-firefox`.
2. "Load Temporary Add-on…" → select `extension/manifest.json`.
3. Open a job posting, click the extension icon, pick a CV, click "Scan", then "Fill".

## Status

Core AI field-mapping currently uses a heuristic matcher (regex/keyword based), not an LLM yet — see `tasks/BACKLOG.md` for the MiMo integration plan. No proactive/background app yet (out of scope for now).
