# JobFiller

**Fill job applications from your own CV, without letting an AI make things up.**

JobFiller is a self-hosted Firefox extension and a small Django API. Open a job posting, click
**Scan**, check what it plans to write in each field, then click **Fill**. It handles the fiddly
parts: custom dropdowns, forms inside iframes, React-controlled inputs, résumé uploads, cover
letters, and multi-page LinkedIn Easy Apply.

### Why use it

- **Built on your own data.** Every answer comes from your CV, the job posting, or a Settings
  answer you typed. If it can't back up an answer, it skips the field and tells you why.
- **It won't click some things for you.** It never auto-fills legal attestations, EEO/demographic
  questions it has no typed answer for, or logistics a CV can't answer (salary, visa, notice
  period, relocation).
- **You check it before sending.** Scan and Fill are two separate clicks, and the manual flow
  never submits the form.
- **Works on real ATSs.** Tested by hand on Greenhouse, Ashby and LinkedIn Easy Apply.
- **Self-hosted.** Your CVs stay in a local SQLite database. The extension talks only to your own
  `core` instance, never to an AI model directly.
- **Extras:** tailored CV generation (rendered to PDF with LaTeX), per-scan cover letters, a job
  fit analysis backed by web search with sources, and an optional Telegram job-channel agent.

### How it's built

- `core/`: Django 5 + DRF API. CV storage and parsing, the job-posting scan, and every AI call.
  AI calls go through the OpenAI SDK to [Xiaomi MiMo](https://api.xiaomimimo.com) by default.
  You can set `MIMO_BASE_URL` to another OpenAI-compatible endpoint, but only MiMo has been
  tested. Without a key, it runs on heuristics alone.
- `extension/`: Firefox (Zen) WebExtension, Manifest V3. Reads the form on the current page,
  sends it to `core`, and applies the plan that comes back.

`CLAUDE.md` covers the architecture and the traps. `tasks/PROGRESS.md` lists what's built and why,
and `tasks/BACKLOG.md` lists what's next.

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

On LinkedIn, select a CV and click **Fill Easy Apply steps**, or use the regular Scan button followed
by **Fill & continue Easy Apply**. The extension opens Easy Apply if needed, fills each page, and
presses Continue/Review until the final review page. It leaves **Submit application** for you to
review and click. If the CV cannot support a required answer, it fills the other fields and pauses
with the dialog open. Enter your answer and click **Continue Easy Apply** to resume. This flow has
been checked against a multi-page Firefox fixture; it still needs a live LinkedIn run after
reloading the extension. If your CV omits a required contact number, enter the phone number and
country code in LinkedIn before continuing. LinkedIn has separate country-code and mobile-number
fields; if you store a full `+7…` answer in Settings, JobFiller removes the selected `+7` prefix
before filling the mobile-number box.

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

The proactive service reads a Telegram job channel (set `TELEGRAM_CHANNEL_TITLE`; the default is
**Digital nomads. Work from anywhere**) from a Telegram account that has already joined it. Get an API ID and hash at
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
