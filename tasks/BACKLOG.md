# Backlog

Roughly in order. Not started unless noted in `PROGRESS.md`.

1. ~~**MiMo LLM integration**~~ — done, see `tasks/PROGRESS.md`. Remaining under this heading:
   - Confirm the exact `image_url` payload shape against the real API before using vision
     (docs didn't show an example at plan time) — needed for backlog item 6.
   - A user-answers profile (salary expectations, relocation, visa sponsorship, notice period)
     so `llm_mapper`'s logistics hard-skips can eventually be answered instead of always skipped.
2. **CV structuring** — parse CV raw text into structured JSON (skills, experience, education)
   via MiMo, instead of just regex email/phone.
3. **Multi-CV "best fit" matching** — score uploaded CVs against a scanned job posting, auto-pick
   instead of requiring manual selection in the popup.
4. **Fit rate** — quick % match score for a job posting vs. the chosen/best CV.
5. **CV generator/adjuster** — tailor a CV's summary/bullets to a specific job posting. Output
   structured JSON + markdown; no PDF rendering (out of scope — see yiromo.com's pdflatex
   pipeline if that's wanted later).
6. **Vision fallback** — when the heuristic/LLM mapper has low confidence on a field, send a
   screenshot (`tabs.captureVisibleTab`, `activeTab` permission) alongside the HTML for that
   one field. This is the one part of the pipeline that's a real LangGraph graph (confidence
   branch + retry); everything before it is a plain pipeline.
7. ~~**Custom combobox filling**~~ — done, see `tasks/PROGRESS.md` (type + poll for
   `[role="option"]` + click best match, in `popup.js`'s `applyFillPlan`).
8. **Application submit tracking** — record scan → fill → submitted status once there's a
   reason to (nothing writes a status today, so no `status` field exists yet either).
9. **Proactive/workflow app** — explicitly out of scope until the extension is proven on all 5
   test sites. Background crawling/auto-scroll/multi-site queueing lives here, not before.
