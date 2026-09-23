# job-filler

An agent that fills job applications from your own CVs. You can open a posting, click Scan, check
what it plans to write, and click Fill. An optional Telegram service also finds and applies to
matching jobs from a private channel.

- `core/` — Django 5 + DRF API. CV storage and parsing, the job-posting scan, and every AI call.
  The extension never talks to a model directly.
- `extension/` — Firefox (Zen) WebExtension, Manifest V3. Reads the form on the page you're on,
  sends it to `core`, applies the plan that comes back.

`CLAUDE.md` has the architecture and the traps; `tasks/PROGRESS.md` is what's built and why,
`tasks/BACKLOG.md` what's next.

## Quick start

Backend, straight from the host:

```bash
cd core
cp .env.example .env   # edit SECRET_KEY before any real use
uv sync
cd src && uv run python manage.py migrate
uv run python manage.py runserver 0.0.0.0:8000
```

Or via Docker (still needs `core/.env` — same `cp` step, from `core/`):

```bash
docker compose up --build
```

`core/.env` is the only place secrets live. `MIMO_API_KEY` empty is a supported state: the LLM
passes no-op and you get the heuristic plan. `TAVILY_API_KEY` empty disables Analyze.

Extension, with `core` on `localhost:8000`:

1. `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on…** → `extension/manifest.json`.
2. A small tab appears on the right edge of every page — that's the panel. Open it and click
   **Manage CVs** to upload a CV, fill in the EEO answers you want used, and generate tailored CVs.
3. On a job posting (a `job-boards.greenhouse.io` listing is a good first test), open the panel,
   pick a CV and click **Scan & Fill** — the same button reads **Fill application** once the scan
   comes back, so filling is a second, deliberate click.
4. Read the Logs tab for what was skipped and why, and check the form yourself before submitting.
   The manual Scan & Fill flow does not submit the form.

There's no toolbar icon and no per-site permission prompt: the panel is a content script and
`<all_urls>` is a required host permission, so installing asks for "Access your data for all
websites" once.

Greenhouse, Ashby and LinkedIn Easy Apply have all been driven by hand; `tasks/PROGRESS.md` marks
what's confirmed live versus only reviewed.

On LinkedIn, select a CV in the panel and click **Fill Easy Apply steps**. The extension opens
Easy Apply if needed, fills each page, and presses Continue/Review until the final review page.
It leaves **Submit application** for you to review and click. If a required answer is missing or
LinkedIn rejects a step, it stops with the dialog open. This flow has been checked against a
multi-page Firefox fixture; it still needs a live LinkedIn run after reloading the extension.

### Generating a tailored CV

Manage CVs → **Generate a tailored CV** rewrites a stored CV for a position you paste in and saves
the result as a new PDF you can pick when filling. It typesets with `pdflatex`, so that one feature
needs TeX on whatever runs `core`. The Docker image installs it. From the host, on Fedora:

```bash
sudo dnf install texlive-scheme-medium texlive-fontawesome5 texlive-charter texlive-paracol
```

Without TeX that endpoint returns a 503 naming what to install; nothing else is affected.

### Zen/Firefox installed via Flatpak (common on Linux)

The add-on will load with no error and then do nothing — no corner tab, and a blank Manage CVs
tab. The Flatpak sandbox only grants access to the one file the "Load Temporary Add-on…" picker
pointed at (`manifest.json`); every sibling file resolves empty. Fix:

```bash
flatpak override --user --filesystem=/absolute/path/to/job-filler app.zen_browser.zen
```

Then fully quit and relaunch Zen and load the add-on again — Reload alone won't pick up the grant.

## What it fills, and what it refuses to

Field mapping runs a heuristic pass first: contact fields (name, email, phone, LinkedIn, GitHub)
and the résumé upload come free from regex against your CV. Whatever it skips goes to MiMo in one
batched call, grounded in your CV text and the scanned posting, including custom JS comboboxes
(Greenhouse/Ashby-style pickers that aren't real `<select>`s — the extension opens the widget at
fill time and picks from the real options, with a second round trip to core when core's blind guess
matches nothing).

Never answered, regardless of confidence:

- **Legal attestations** ("I agree…", privacy and terms consent). Your click to make, not ours.
- **Logistics a CV can't answer** — travel, relocation, salary, notice period, visa, start date.
  These are filtered out of the model call entirely rather than left to the prompt.
- **EEO/demographic questions**, which are never guessed from a CV or posting. Type your own answer
  once in Manage CVs → Settings and a dedicated pass picks or words the value per field, grounded
  strictly in what you typed — no CV text, no posting text in that prompt. A blank row stays
  skipped.

Also there: a **cover letter** generated per scan from your CV and the posting (text for a paste
field, a `.docx` for an upload field), a per-field **Generate with AI** button on open-ended
textareas, and **Analyze Application** — a fit score plus company and job-market notes, each
grounded in live Tavily search results and carrying its source URL, because a model with no
internet would simply invent them.

Generated CVs list back every technology that wasn't already in your source CV, so you can confirm
each one is true before sending it anywhere.

## Telegram opportunity agent

The proactive service reads the private **Digital nomads. Work from anywhere** channel from a
Telegram account that has already joined it. Get an API ID and hash at
[my.telegram.org](https://my.telegram.org), set `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in
`core/.env`, and log in locally (enter the phone, code, and any 2FA password in the terminal):

```bash
cd core/src
uv run python manage.py migrate
uv run python manage.py telegram_login
uv run python manage.py sync_telegram_jobs
```

Do not paste Telegram secrets or login codes into chat. The account session is stored in
`core/src/data/telegram.session`; keep this file private and back it up with the data directory.
The running installation uses Docker: `core` serves the API on localhost, and `telegram-sync`
checks for new posts every six hours. Both share the `core_data` volume. For a fresh Docker setup,
run `docker compose run --rm --no-deps telegram-sync uv run --no-sync python manage.py telegram_login`
once, then `docker compose up -d --build`. The Docker volume's CV database and Telegram session are
separate from the host `core/src/data`; upload CVs to the running Docker API or migrate them first.

The service follows each post's Telegraph category links to individual job descriptions and final
application links. MiMo first selects promising job titles, then compares their descriptions with
uploaded CVs in one batch. Set `MIMO_API_KEY` to enable this matching. The default `MIMO_MODEL` and
`MIMO_VISION_MODEL` are `mimo-v2.6-flash`. The extension sends a screenshot with scanned form fields
so the vision model can read visual labels; unsupported controls still need DOM support to be filled.
Matches above `OPPORTUNITY_MIN_SCORE` (default 75) enter a queue. While Firefox/Zen
and the extension are running, it polls this queue every 30 minutes, opens one job at a time,
scans and fills its form with the selected CV, and submits only when required fields are answered,
filling succeeds, and a single final submit button is found. It marks the job **applied** only
after detecting a confirmation; otherwise it leaves the tab open and marks it **needs review**.
For LinkedIn Easy Apply links, the queue worker uses the same multi-page flow and submits after
the final review page only if every step succeeds.
Reload the Firefox/Zen extension after updating it. See Manage CVs → Telegram opportunities,
`GET /api/v1/opportunities/`, or Django admin for the queue
and reasons. Posts without an individual application link stay available for review.
