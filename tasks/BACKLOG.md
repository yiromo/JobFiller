# Backlog

Roughly in order. Not started unless noted in `PROGRESS.md`.

1. **MiMo LLM integration** (`core/src/agent/`) — replace/augment the heuristic mapper with a
   real `mimo-v2.5` call for fields the heuristic can't classify (open-ended questions, custom
   comboboxes). Blocked on a rotated API key in `core/.env` (`MIMO_API_KEY`) —
   the key pasted earlier in chat must not be reused as-is.
   - Confirm the exact `image_url` payload shape against the real API before using vision
     (docs didn't show an example at plan time).
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
7. **Custom combobox filling** — Greenhouse/Ashby-style JS comboboxes (not native `<select>`)
   need click+type+keydown simulation, not a value-set. Currently these are always skipped.
8. **Application submit tracking** — record scan → fill → submitted status once there's a
   reason to (nothing writes a status today, so no `status` field exists yet either).
9. **Proactive/workflow app** — explicitly out of scope until the extension is proven on all 5
   test sites. Background crawling/auto-scroll/multi-site queueing lives here, not before.
