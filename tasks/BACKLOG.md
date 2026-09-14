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
5. ~~**CV generator/adjuster**~~ — done, see `tasks/PROGRESS.md`; it does render a PDF, via the
   pdflatex template ported from yiromo.com. Remaining under this heading:
   - `core`'s Docker image has no TeX, so `POST /api/v1/cvs/<id>/generate/` 503s there while
     working fine under a local `runserver`. Either add texlive to the image (~1GB) or accept it
     as a local-only feature — don't half-add packages and find out at request time.
   - Generate from the panel, using the page the user is already on as `position_text`
     (`lastPageText` is already in `panel.js`), instead of pasting the posting into Manage CVs.
   - The one-page fit is prompt-enforced (bullet/section caps), not measured. If a generated CV
     ever spills to two pages, the check belongs server-side after the render, with one retry at
     a tighter cap — `pdfinfo` isn't guaranteed present, so count pages from the PDF itself.
6. **Vision fallback** — when the heuristic/LLM mapper has low confidence on a field, send a
   screenshot (`tabs.captureVisibleTab`, `activeTab` permission) alongside the HTML for that
   one field. This is the one part of the pipeline that's a real LangGraph graph (confidence
   branch + retry); everything before it is a plain pipeline.
7. ~~**Custom combobox filling**~~ — done, see `tasks/PROGRESS.md` (type + poll for
   `[role="option"]` + click best match, in `popup.js`'s `applyFillPlan`).
8. **EEO settings: radio-group support** — `applyEeoSettings` (`popup.js`) only handles native
   `<select>`, plain text inputs, and combobox-role widgets. Some ATSs render EEO questions as
   `<input type="radio">` groups instead. Not built — none of the 5 test sites have shown this
   pattern yet, and it needs real markup to design against (grouping by `name`, matching the
   user's answer against each radio's own label, not the group's).
9. **Application submit tracking** — record scan → fill → submitted status once there's a
   reason to (nothing writes a status today, so no `status` field exists yet either).
10. **Proactive/workflow app** — explicitly out of scope until the extension is proven on all 5
   test sites. Background crawling/auto-scroll/multi-site queueing lives here, not before.
11. **Yes/No button-pair widgets** — a real ATS form (screenshot) has "Are you 18 or older?"
   etc. as two styled Yes/No buttons per question, not a native `<input type="radio">` group or
   `<select>` — `scanPage` only scans `input, select, textarea`, so these are currently invisible
   to the scanner and never filled. Not built — waiting on the outerHTML of one such widget to
   know whether it's a hidden radio input behind styled labels or plain buttons with no
   underlying form control at all; the fix differs for each and shouldn't be guessed blind.
12. **"Generate with AI" per-field button: hide/disable toggle** — the inline button (see
   `tasks/PROGRESS.md`) is attached to every scanned textarea on every page unconditionally, no
   opt-out. Simplify Copilot ships exactly this as a settings toggle. Not built now — no reason
   to believe it's intrusive yet, add it if a real site makes it feel that way.
