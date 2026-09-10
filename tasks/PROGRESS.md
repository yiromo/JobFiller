# Progress log

Newest first. One entry per feature commit — added when the feature actually lands, not before.

## Done

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
