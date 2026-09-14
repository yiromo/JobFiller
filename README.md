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

Generating a tailored CV (Manage CVs → "Generate a tailored CV") typesets the result with
`pdflatex`, so that one feature needs a TeX distribution on whatever runs `core`. The Docker image
installs one, so `docker compose up --build` needs nothing extra. Running `core` straight from the
host needs it installed there — on Fedora: `sudo dnf install texlive-scheme-medium
texlive-fontawesome5 texlive-charter texlive-paracol`. Everything else works without TeX, and the
generate endpoint returns a 503 saying what to install rather than failing silently.

Extension (Firefox / Zen), with `core` running on `localhost:8000`:
1. Go to `about:debugging#/runtime/this-firefox`.
2. "Load Temporary Add-on…" → select `extension/manifest.json`.
3. Click the extension icon → "Manage CVs" to upload one or more CVs (each stays listed for
   reuse). If the form you're applying on loads inside an embedded iframe from another domain
   (Newton/gnewton career pages are the known case), click "Grant page access" there too — a
   plain scan can't see into a cross-origin iframe otherwise. Then open a job posting (e.g. a
   `job-boards.greenhouse.io` listing), click the extension icon, pick a CV from the dropdown,
   click "Scan this page", then "Fill application".
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

`core`'s field-mapping runs in two passes: a heuristic (keyword/regex) matcher fills contact
fields (name/email/phone/LinkedIn/GitHub) and the resume upload for free; whatever it skips is
then sent to MiMo (`mimo-v2.5`, only if `MIMO_API_KEY` is set in `core/.env`) grounded in the
CV text and the scanned page, including custom JS comboboxes (Greenhouse/Ashby-style — the
extension types + picks from the rendered option list). Never auto-answered by core, regardless of
confidence: legal attestations ("I agree...") and logistics questions a CV can't answer (travel,
relocation, salary, visa, start date). EEO/demographic questions are never guessed from a CV or
job posting either, but Manage CVs > Settings lets you type your own answer to each one once, and
a dedicated AI pass then picks/words the actual value per field — grounded strictly in what you
typed, never invented — with a client-side verbatim fallback for anything it still leaves
skipped; leave a row blank to keep that question skipped. Any "cover letter" field is generated
fresh per scan (grounded in your CV and the job
posting) — a paste field gets the text, a file-upload field gets a generated `.docx`. See
`tasks/PROGRESS.md` for what's actually built and `tasks/BACKLOG.md` for what's next (CV
structuring, fit rate, multi-CV best-fit matching). No proactive/background app yet (out of
scope for now).
