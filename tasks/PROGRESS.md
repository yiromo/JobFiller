# Progress log

Roughly newest first, one entry per feature/fix commit, added when it lands. Entries keep the root
cause and the constraint that made the fix non-obvious — the stuff a future agent needs to not
repeat a mistake. Everything else (what was curled, what lint said, which build number) is in git.

- **`isVisible` dropped every field inside a fixed-position form** — a SmartRecruiters
  `oneclick-ui` page scanned to exactly one field: a `file` input labelled "Upload profile image".
  One field is the tell, and so is its type — file inputs are the only kind exempted from
  `isVisible` (they are routinely styled hidden behind a custom Attach button), so a scan that
  returns nothing but a file input means `isVisible` rejected all the rest. The cause was
  `el.offsetParent !== null`: `offsetParent` is null for anything inside a `position: fixed`
  subtree, which is how that apply UI renders its whole form, so every text input on the page
  failed. The check now accepts a non-zero bounding box as an alternative to `offsetParent`, which
  is strictly more permissive — nothing that passed before can fail now — and `isHoneypot` is still
  what keeps traps out, not this. Pre-existing, not a regression from the modal-scoping change in
  the entry below; that change was confirmed innocent because the field it did find sits in the
  real form, next to its "Fields marked with * are required." heading.
  Same run confirmed the scan nonce works in a browser: after a page reload three Fill clicks in a
  row reported `smu3b0zzl-jf-0: not-found` instead of writing into whatever element had inherited
  that id. Failing safe is right but silent, so a fill where every failure is `not-found` now says
  the page re-rendered and to click Re-scan.

- **Scan scope, ref staleness, and a placeholder masquerading as a section heading** — a LinkedIn
  Easy Apply run typed the candidate's name into LinkedIn's own job-search box. Four separate
  causes, found from the persisted `Application.form_snapshot`, which is the artifact to reach for
  first when a fill goes wrong — it is what core actually saw.
  `scanPage` ran `document.querySelectorAll("input, select, textarea")` over the whole document, so
  with a modal open it also collected the page behind it: of three fields found, two were LinkedIn
  chrome (the "Describe the job you want" box and the global search combobox in an iframe). It now
  scopes to the open modal, tried as `[aria-modal="true"]`, then `dialog[open]`, then
  `[role="dialog"]`, taking the outermost of each tier and only accepting a tier whose containers
  actually hold a control — a cookie banner marked `role="dialog"` therefore falls through to the
  document instead of reducing a Greenhouse page to zero fields. The bare `[role="dialog"]` tier
  additionally needs two controls before it wins, because a chat or messaging widget is one lone
  textarea marked `role="dialog"` and would otherwise capture the scan on an ordinary careers page
  that has no modal at all; `aria-modal` and `dialog[open]` are explicit enough to accept a single
  control, which is what the LinkedIn case needs. Visibility here uses
  `getBoundingClientRect`, not the existing `isVisible`: modals are `position: fixed`, whose
  `offsetParent` is null, so `isVisible` rejects every one of them.
  `data-jf-ref` now carries a per-scan nonce. The refs on that page were React 19 `useId` values
  (`«r27»`, `«r28»`) and on another were react-select's `react-select-N-input`; both are assigned in
  mount order and **recycled onto different nodes** across renders, so a ref from an earlier scan
  did not fail to resolve, it resolved to a live element that was a different question. The
  documented "refs don't survive a re-render, re-scan" hazard assumed the failure mode was
  `not-found`; with mount-order ids it is a silent write to the wrong field, which is worse. The
  nonce makes a stale plan match nothing.
  `resolveSection` was returning the widget's own placeholder as the question: on react-select the
  placeholder is a `div` that is a previous sibling of the input's wrapper and contains no form
  control, so it passed every existing guard, and four dropdowns came back with sections like
  "Select all that interest you" and "Select stages you've worked at" instead of the headings above
  them. The new guard rejects a sibling whose bounding box overlaps the field's own — a heading sits
  above a control, an in-widget placeholder or adornment is painted over it. This is deliberately
  geometric rather than class-based; walking by class name is the mistake that is already documented
  two bullets down.
  `POST /resolve-options/` 400d and lost a whole batch because `options` was `[""]` — the page's
  listbox had a blank row and the serializer's `CharField` rejects it. `allow_blank=True` now, the
  extension drops blank options and skips a field left with none, and a non-2xx response logs its
  body: `core returned 400` on its own hid `options: This field may not be blank`.
  Two smaller things from the same runs. A composite textarea — one box whose label is ten questions
  ("Full Name: Total Years of Experience: ... Expected Salary Per Year:") — was being answered with
  just the name, because `_map_field` matched "full name" in the haystack. `is_composite_question`
  (textarea, label of 80+ chars with 3+ colons) now skips it and also fails `_is_llm_eligible`, so
  neither mapper guesses at salary or visa status; the extension already attaches a "Generate with
  AI" button to open-ended textareas, which is the right way to answer it. And the fill log now
  prints the plan it actually applied, ref by ref — a report where the log's `wanted=` disagreed
  with the persisted `field_mapping` could not be resolved without it.
  `findOptions`' document-wide `[role="option"]` fallback was left alone on purpose: many combobox
  libraries portal their listbox to `document.body`, so scoping it would break real ATSs, and once
  the page's own search box is no longer scanned there is nothing to trigger the leak.

- **Employment titles are overridable, but only by an explicit directive** — the verbatim guard on
  `role` did its job and then became the complaint: a CV headlined "Full-Stack Engineer" listed five
  `Backend Developer` jobs, which is correct but not what the candidate wanted. Titles are now
  overridable via a `Title <employer> as <role>` line in the instructions, parsed by
  `_title_overrides` and matched to an experience by containment after `_comparable`
  (`dreams` matches `Dreams Group`), with a blanket `all roles` form. The mechanism has to be a
  dedicated parsed directive, not "the title string appears somewhere in the instructions": the same
  instructions already say `Change the headline to "Full-Stack Engineer"`, so a substring test would
  be satisfied by the headline line and silently reinstate the exact bug the guard was built for.
  There is a regression test for that direction — the original instruction text, unchanged, must
  still be blocked. `_role_allowed` strips the override from the model's role and requires the
  remainder to be empty or itself in the source, which lets
  `Full-Stack Engineer (Part-time Contract)` through while still blocking a `Senior` the model
  added on its own. Only `role` takes this path; `company` and `period` stay unconditionally
  blocked, so an overridden experience is still transitively grounded in the source. Every applied
  override is reported as a warning naming the employer, as is a directive matching no employer.
  `_lost_qualifiers` warns when the source attaches a parenthetical to a title
  (`Backend Developer (Part-time)`) and the output drops it — a real run did exactly that, turning
  two part-time contracts into apparent full-time roles, which is a second misrepresentation nobody
  asked for; putting the qualifier inside the directive is the fix and the warning is what surfaces
  it. Also learned from the same runs, and worth knowing before trusting the skills diff:
  `_added_skills` appends the model's own `added_skills` claim on top of the Python diff, so a
  flagged skill is not proof the diff caught it — `Next.js` showed up flagged only because the model
  self-reported it, and the substring check still cannot catch it (the source contains "behind a
  Next.js frontend"). The one-page trim also proved it has teeth in the wrong direction: with 3
  bullets across 5 jobs it dropped the very project the instructions asked to highlight, so project
  order in the instructions now matters — the trim always cuts from the end.

- **Generated CVs stopped inventing employment history** — two real runs (Golang Backend,
  Full-Stack) each dropped a job, reordered the employment history, lost the header's
  `UTC+5 / Worldwide Remote / B2B / EOR` line, and one rewrote every historical title to the
  targeted one. Root cause: the port of yiromo.com's `npm run cv` kept the LaTeX template verbatim
  but replaced the whole data layer with model output. In `portfolio/src/data/cv.ts` the role,
  period, header detail parts, ordering and project links are hand-authored data that
  `generate-cv.mjs` renders with a bare `.map()` — no sort, no filter, all five jobs always — and
  page fit is enforced *after* compile by a `pdfinfo` check that fails the build and tells the
  human to trim `CV_PROJECT_IDS`. `cv_writer.py` had made every one of those a model decision and
  dropped both guards, replacing them with two prompt lines that combine into silent truncation:
  "reorder ... so the most relevant work comes first" plus "at most 4 experiences" over a 5-job CV
  deletes whichever job scores least relevant. It was never a length problem — both bad PDFs were
  one page and the source fits 5 jobs plus 2 projects. The Golang run lost the tail (Cleverest);
  the Full-Stack run lost Turing from the middle, leaving a visible Jan 2024 - Apr 2025 gap.
  Fixes, all in Python rather than prompting, same principle as `added_skills`:
  `_ungrounded_facts` requires `role`/`company`/`period` to be whitespace-collapsed, accent-folded,
  casefolded verbatim substrings of the source `raw_text` and raises `CvGenerationError` naming the
  field, employer and offending value — blocking, not a warning, because the added-skills surface
  demonstrably already fired on `Stripe` and `TypeScript` in the bad runs and the human shipped
  past it. `_in_source_order` sorts experiences by where their period (then company) appears in the
  source text: it reproduces the human's own hand-ordering exactly and has no date-format failure
  mode, which a month-parsing sort would. The 4-experience cap is gone and `render_pdf` re-added
  the lost page gate — it reads the count from pdflatex's own `Output written on ... (N pages`
  line rather than taking a poppler dependency the Docker image doesn't have, drops one project per
  retry like the original tells the human to, reports each drop as a warning, and raises if it is
  still over with no projects left. Removing the experience cap makes overflow likelier, so the
  per-experience bullet cap dropped from 4 to 3. `location` (schema-narrowed to "city, country",
  which is why the rest of the header line could not survive) became `location_details`, a list
  validated part-by-part and joined with `$\cdot$` like the original. `_unsourced_prose` extends
  the fabrication diff past the skills dict into summary/impact/bullets/project prose, flagging
  capitalized tokens that are not sentence-initial and not in the source — that is what catches
  `Stripe` replacing the source's `BCC 3-D Secure`, which lived in a bullet where the skills diff
  could never see it. It skips `title` deliberately, or every generation warns on its own
  repositioned headline. Two prompt rules also changed: a technology named only as something to
  "prioritize" or "lead with" is explicitly *not* permission to add it (the user's own instructions
  listed WebSockets and Next.js/TypeScript under "prioritize", and the old rule read that as
  consent), and a technology the source mentions only as something the work sat *behind* may not be
  listed. That second one is prompt-only with no Python backstop: `_added_skills` is a substring
  check, so `Next.js` passes silently because "behind a Next.js frontend" is in the source text and
  it cannot tell "I built X" from "my backend sat behind X". Rerunning both original instruction
  texts now yields five jobs in source order, real titles under repositioned headlines, the header
  line intact, one page each, no Stripe and no TypeScript; the warnings channel surfaced `SaaS`
  and `Go-based` as unsourced wording and the Full-Stack run's four added skills.

- **Label resolution: generic accessible names rejected, `section` added to the contract** — on
  Rippling's ATS a scan produced 9 of 16 fields with a label of `""`, `"Search"`, `"Select..."` or
  `"textbox"`: its component library sets a generic `aria-label` on every control, randomizes
  `name` to a nonce (`D_p4hxxjUY`), numbers `id` as `field-NN`, and renders the real question as a
  sibling `div` rather than a `<label for>`. `field_haystack` was therefore semantically empty for
  those fields, which lost the obvious things (résumé and cover-letter dropzones both matched no
  keyword and were skipped, so nothing ever attached; the three real technical questions were
  skipped) and one non-obvious one: **the EEO/attestation/logistics hard skips are substring
  checks over that haystack, so they silently stopped applying** — the salary question was
  answered by the CV-grounded pass, and the one scannable EEOC select escaped `eeo_pending` (it
  resolved to `skip` by luck, not by rule). `resolveLabel` now rejects a set of known generic
  names (returning `""`, which is safer than a label that looks real) and prefers
  `aria-labelledby` over `aria-label`, per the accessible-name spec — the old order had
  `aria-label` winning, which is exactly backwards for this case. New `resolveSection` finds the
  question by DOM proximity and travels as its own `section` key rather than being folded into
  `label`, because a dropzone's `<label>` ("Drop or select (.doc / .docx / .pdf)") is a *correct*
  accessible name that no blacklist should discard — and because `section` is the same mechanism
  a radio/scale group will need when the scanner is widened (BACKLOG 8/11). Two knock-ons the
  section text forced: a phone widget's country picker shares its heading with the number input,
  so `field_mapper` skips a dropdown-like phone match — and, since `augment_skipped_fields` treats
  every `skip` as a candidate, it also has to fail `_is_llm_eligible` or the model types the phone
  number into the country picker (observed, not theorized). `pronoun` joined `EEO_KEYWORDS`: it's
  self-identification, so it belongs to the Settings-grounded `eeo_mapper`, never to a CV guess.
  Verified by replaying the stored snapshot of the bad scan with `section` filled in, through the
  real `/scan/` endpoint: résumé and cover letter now `upload`, salary `skip`, pronouns and the
  EEOC select `skip` via the EEO path, the country picker `skip`, Location fills a city instead of
  the applicant's name, the three technical questions get grounded prose, and the five
  already-correct fields are unchanged. The extension half is unverified — no browser here; it
  passes `web-ext lint` and the walk was reviewed, nothing more.

  Two follow-ups the first attempt still got wrong, both found by reading the live form's
  `outerHTML` rather than reasoning about it — **the uploads still didn't attach**:
  - **`resolveSection` stopped at a screen-reader-only sibling.** Rippling puts
    `<div data-testid="screen-reader-only">Total 0 file selected</div>` immediately before the
    file input's `<label>`, so the walk returned that instead of climbing to the "Résumé" heading
    one level up. It's clipped, not `display:none`, so it's still in the layout and `innerText`
    happily returns its text. Siblings now have to be `aria-hidden="false"` and paint a box
    bigger than 1×1 — a rendered-size test, not a class-name test, so it isn't Rippling-specific.
  - **`Résumé` doesn't contain `resume`.** `_RESUME_KEYWORDS` is a substring check and the field's
    heading carries acute accents, so the résumé dropzone matched nothing even once the section
    resolved. `field_haystack` now NFKD-folds and strips combining marks before lowercasing.
    Deliberately narrower than the separator-normalizing rewrite that was tried and reverted for
    breaking `"email"` vs `"e-mail"`: folding touches diacritics only, never separators, and can
    only ever make more things match.

  Same pass also confirmed, from that markup, that the 4 remaining EEOC pickers, both yes/no
  radio groups and both 1–5 scales are `div[role=radio]`/`div[role=combobox]` with their real
  `<input>` at `display:none` or absent entirely — still unscanned, still BACKLOG 8/11. Two
  measurements from that markup worth keeping for when the scanner does widen: a `div[role=radio]`
  reaches its group question at ancestor depth 3–4, but the hidden `input[type=radio]` two levels
  further in sits at 6 — pick the div, not the input. And a heading is not always reachable at
  all: the phone country picker's own "Phone number" heading is **11** ancestors up, past two
  `data-testid="field"` wrappers, which is deeper than any cap that doesn't also reach page-level
  containers. So depth is 8 and the real protection is structural, not numeric — a dropdown-like
  field with no label, no section and no options is unguessable by definition and is now refused
  by `_is_llm_eligible` outright, which is what actually stops a blind combobox from being
  answered (the phone guard needs `"phone"` in the haystack and wouldn't have had it).

- **Fill dismissed the LinkedIn Easy Apply dialog instead of filling it** — three ways
  `applyFillPlan` could close a native modal, none visible on a non-modal ATS page. (1)
  `sizedTarget` walks up to 5 ancestors for a clickable box and reached the `<dialog>` itself,
  whose synthetic click a light-dismiss handler reads as a click outside the form; the walk now
  stops at `dialog`/`form`/`[role="dialog"]`/any node over half the viewport, and `clickOption`
  refuses those nodes too. (2) `closeWidget`'s Escape and the commit path's Enter bubbled to the
  page's document-level dismiss/submit handlers; inside an open dialog they now carry a one-shot
  listener on that dialog that stops propagation for that exact event, so the combobox still sees
  the key and the page doesn't. (3) `selectValue` starts with `closeWidget(document.activeElement)`
  — `<body>` when nothing is focused, i.e. outside the dialog and unstoppable from inside it — so
  those two keys are now dropped entirely in that case. Scoping is conditional on an open dialog;
  Greenhouse/Ashby comboboxes that listen at the document still work. Confirmed live.

- **Download button per CV in Manage CVs** — fetches `/api/v1/cvs/<id>/file/` and saves the blob
  through a temporary object URL rather than linking at the endpoint, because that view returns
  `Content-Disposition: inline` (a plain link opens the PDF in a tab and loses the stored
  filename). The URL is revoked a minute later; revoking in the same tick races the browser's read.

- **CV generation works in Docker** — it shipped working only under a host `runserver` while `core`
  actually runs from `docker compose`. The image installs `texlive-latex-base`,
  `-latex-recommended`, `-latex-extra`, `-fonts-recommended`, `lmodern` (272 MB), plus
  `fontawesome5` straight from CTAN's 1.7 MB zip into `TEXMFLOCAL` — Debian ships it only inside
  `texlive-fonts-extra` (~1 GB for five icons). Copy the *whole* `tex/` dir from that zip, not just
  `*.sty`: the package loads `fontawesome5-mapping.def` at runtime, so a `.sty`-only install
  succeeds and then fails at compile time. Needs `mktexlsr` + `updmap-sys --enable
  Map=fontawesome5.map` to embed the Type1 fonts. The download is deliberately non-fatal and the
  template guards with `\IfFileExists{fontawesome5.sty}` (no-op `\fa...` macros, `\@ifstar` to
  swallow `\faMapMarker*`), so a CTAN outage costs icons, not the image. ~250 MB → 895 MB.

- **Generate a new CV from an existing one** — `POST /api/v1/cvs/<id>/generate/`
  (`{instructions, position_text, filename}`) rewrites a stored CV for a target position and saves
  the PDF as a new row, selectable like any upload. `agent/cv_writer.py`: one MiMo call
  (`json_object`, 120s) to structured JSON, then a `pdflatex` render whose template is ported from
  yiromo.com's `npm run cv` (`portfolio/scripts/generate-cv.mjs`), so the output looks like the
  hand-maintained CV. `CvService.generate_from` wraps the bytes in a `ContentFile` and reuses
  `upload()`, so extraction and `extract_profile` run exactly as for a hand-uploaded file — no new
  model, no migration. Grounding: employers/titles/dates/degrees/numbers copied verbatim, bullets
  rewritten freely, a technology added only if it's in the instructions or posting text. **Added
  technologies are detected in Python** by diffing rendered skills against the source CV's text,
  not taken from the model's own report — a real run added "Docker" and reported only "Temporal".
  A trailing version number doesn't count as an addition ("Django" → "Django 5" stays quiet), but
  the check deliberately doesn't collapse on a shared first word or "Apache Kafka" would be waved
  through on a CV that says "Apache Spark". Contact fields never pass through the model, so no
  phone digit can drift. Output is NFKC-folded to Latin-1 before escaping — the template's fonts
  have no Cyrillic glyphs and pdflatex would die on a place name. Missing `pdflatex` → 503 with
  install instructions; failed compile → 502 with the last 30 log lines; never a 500.

- **Panel slides instead of snapping** — `[hidden]` stays the single source of truth for panel
  state, but its rules now use `visibility: hidden` + `pointer-events: none` instead of
  `display: none`, transitioning `visibility` with a delay equal to the slide so the element stays
  painted for the animation and goes non-interactive immediately. Honours
  `prefers-reduced-motion`.

- **Panel was unclickable on LinkedIn Easy Apply** — not a z-index problem: LinkedIn opens that
  form with native `<dialog>.showModal()`, and a modal dialog sits in the browser's **top layer**,
  which paints above every z-index, with everything outside its subtree inert. No styling can fix
  that; the host has to be inside the dialog. `panel.js` reparents `#job-filler-panel-host` into
  the topmost open modal dialog and back to `<body>` on close, driven by an
  `attributeFilter: ["open"]` subtree observer (`showModal()` only works on a connected element, so
  the attribute flip always fires) plus a narrow `childList` observer on the dialog's parent for
  the case where it's removed while still open. Both funnel into one rAF-debounced sync; the
  reparent's own mutation converges. Guarded by `CSS.supports("selector(:modal)")`. Open risk: if
  LinkedIn ever puts a `transform` on that dialog it becomes the containing block for our
  `position: fixed` host and the panel would render inside the card — the fix then is the popover
  API, not abandoning the reparent.

- **A scan's three AI passes run in parallel** — `augment_skipped_fields`, cover-letter generation
  and EEO resolution were three serial MiMo round trips; they're independent, each rewriting only
  entries carrying its own placeholder action (`skip`, `cover_letter_*`, `eeo_pending`).
  `_run_resolution_passes` forks them into a `ThreadPoolExecutor` and merges by `ref`, taking from
  each pass only the refs it owns, so a pass that strays outside its slice can't leak. Safe off the
  request thread because no pass touches an ORM object. This was the answer to "would FastAPI be
  faster": the latency was three serial LLM waits, not framework overhead.

- **UI rewritten black-and-white and scaled up** — charcoal `#161616` ground, black surfaces, white
  text and borders (10% alpha dividers, 30% interactive edges), Arial. Scan/Analyze buttons keep an
  outlined idle state because they double as progress bars and a solid fill would hide the growing
  bar. The log `<pre>` keeps an explicit monospace stack rather than `inherit`, which would now
  resolve to Arial and lose column alignment. `font-family`/`size`/`weight`/`style`/`color` joined
  the inline `!important` pins on the shadow host, same reason as the text-rendering ones below.

- **Panel text collapsed on pages with aggressive typography** — `:host { all: initial }` is
  outranked by any page rule targeting the host element, so a site's near-zero `line-height` was
  inherited by the log `<pre>` and stacked every line on one baseline. Inherited text properties
  (`line-height`, `letter-spacing`, `word-spacing`, `text-transform`, `text-indent`, `white-space`,
  `direction`) are now pinned inline with `!important` on the host, like `position`/`z-index`.

- **Fills are a try-verify-escalate cascade** — every action type tries several techniques in order
  and verifies after each. Text: native setter + key-event sandwich → `execCommand("insertText")` →
  direct assignment, checked against `el.value`, plus `contentEditable`. Checkbox/radio: skip if
  already right → native `.click()` → synthetic pointers → `checked` setter. Combobox: open tactics
  (click → click sized ancestor → ArrowDown → Alt+ArrowDown → Space → type 4 chars) then commit
  tactics (pointer sequence → `.click()` → Enter → type full text + Enter), with a virtualized-list
  scroll pass. Commit counts only if the option list disappears *and* the control's text contains
  the choice; otherwise it reports `selection-not-confirmed` rather than a silent success. The
  cascade checks `aria-expanded` between tactics — many widgets open on a bubbled mousedown, and
  the next tactic's click would toggle the menu shut again. Matching is tiered: exact → normalized
  → prefix with a word boundary → substring for 4+ chars; the word boundary is what lets "No" match
  "No, I don't have a disability" without matching "Norway+47". The `via=` log tag names the
  winning pair.

- **Combobox lookup ignores listboxes that were already on the page** — a live run had every
  combobox on a Greenhouse board reporting the same option list (a phone country-code picker's),
  because that widget keeps its `[role="option"]` nodes in the DOM permanently and fields with an
  empty `aria-controls` fall through to the document-wide sweep. `findOptions` now requires options
  to be rendered (`getClientRects().length > 0`) and, with no `aria-controls`/`aria-owns` to trust,
  prefers ones that appeared after the field was opened (snapshot taken before interaction).

- **Combobox wrong-widget bug, plus a fill-time option round trip** — `findToggleControl`/
  `findOptions` located a field's toggle via `el.closest('[class*="control" i]')`, which on a real
  ATS walked past the field's own wrapper to a shared page-level container, so every combobox
  opened and read one unrelated field's menu. Fixed by dropping the heuristic: open by clicking the
  exact `data-jf-ref`-stamped element, which is guaranteed correctly scoped. A no-match now also
  clears the typed text and closes the widget (clearing alone re-triggers filter-as-you-type).
  On top of that, `POST /api/v1/applications/resolve-options/`: when a combobox opens and matches
  none of core's guesses, the extension sends `{ref, wanted, options}` (the real option text, known
  only at fill time) and `agent/option_resolver.py` makes one batched MiMo call, snapped to the
  given options by `llm_mapper.validate_override`. It is EEO-safe purely because it never sees CV
  or page text — it only reconciles an already-decided value against real wording. Resolved entries
  persist into `field_mapping` and are spliced into the in-memory plan so a second Fill doesn't
  repeat the trip.

- **Combobox failures log wanted vs. seen** — `selectValue` returns `{status, wanted, seen, via}`
  instead of a bare string, so a failed fill says whether core's guess or the widget's real options
  were wrong, without a devtools trip. Root cause it surfaced: a custom combobox's options don't
  exist in the DOM at scan time, so core can only guess free text — a mapping-input gap, not a DOM
  bug (the round trip above is the actual fix).

- **`applyFillPlan` robustness pass** — `setValue` also sets the `value` *attribute* after the
  native setter, since some ATS validation reads the DOM attribute; `isDropdownLike`/`findOptions`
  check `el.closest('[role="combobox"], [aria-haspopup="listbox"]')` because WAI-ARIA 1.1 allows
  those roles on a wrapper rather than the input; the `check` action calls `el.click()` when the
  state differs instead of assigning `.checked`, because React listens for a native click on
  checkboxes and direct assignment trips the same value-tracker trap as `.value`.

- **Manage CVs tab opens zoomed out** — `browser.tabs.setZoom(tab.id, 0.3)` after `tabs.create`;
  `0.3` is the API minimum and needs no permission.

- **Dedicated Logs tab, plus a CV-required gate** — the shared log moved into its own third tab
  (with Copy and Download .txt), and `log()` gained an optional `mirrorId` so scan/fill lines also
  render in a small mirror on the Scanner tab. The Scan button starts disabled until a CV is
  selected, with a guard in `runScan` for the Re-scan link (a text link can't be disabled-styled).

- **Extension versioning, structured logging, and the scan disconnect it found** — Firefox rejects
  `version_name` in the manifest (Chrome-only), hence `src/version.js` holding one `JF_BUILD`
  constant loaded into all three JS contexts without a bundler; bump it on every extension change
  so a bug report pins to a build. `panel.js` timestamps every line and logs `SEND`/`RECV` for
  every message; `background.js` mirrors to its own console. The bug this found: "Receiving end
  does not exist" on scans *with a CV*, and only those — a CV-attached scan runs the batched MiMo
  pass (26s for 25 fields), and Firefox can evict a non-persistent MV3 background script after ~30s
  idle **including while a `fetch()`-backed `onMessage` promise is pending**. Fixed with
  `startKeepalive()`: a 20s `setInterval` hitting `browser.storage.session.get` (any extension-API
  call resets the idle timer), wrapped once around every handler via `respond()`. The first
  theory — `executeScript` rejecting on an unreachable iframe — was wrong; the structured log
  disproved it by showing the same frames succeed in 107ms with no CV.

- **Panel reorganized into tabs with one big action button each** — Scanner/Filler and Analyze,
  persisted as `activeTab` in the existing `saveScanState` round trip. `#jf-scan-btn` does both
  steps via a `data-mode` toggle rather than two elements needing separate state sync; a "Re-scan"
  link stays available because refs die on any SPA re-render. Analyze can be re-run (it used to
  render its result card once, forever). Progress fill is a shared `runProgress(btn, tau)` — analyze
  gets `tau` 18 vs scan's, since it runs 30–90s over four external calls. A `.jf-busy` class exempts
  an actively-running button from the `:disabled { opacity: 0.4 }` rule.

- **Scan button fills as a live progress bar** — a hard-stop `linear-gradient` driven by
  `--jf-progress`, eased to approach but never reach 92%, so a real finish always visibly jumps to
  100% — scan has no incremental server-side progress to report. The button also disables itself
  for the click, which it alone didn't do before (a second click raced two `/scan/` calls).

- **In-page panel replaces the toolbar popup** — a browser popup is destroyed on every close,
  including a tab switch, wiping UI state. `panel.js` now injects on `<all_urls>` and mounts a
  closed shadow DOM host with a corner tab (right edge, vertically centred, clear of ATS Submit
  buttons); a content-script node survives tab switches for free. `background.js` owns everything
  a content script can't do: all `fetch` to core and every `scripting.executeScript`.
  Non-obvious pieces, all found the hard way: MV3 requires `web_accessible_resources` for a content
  script to fetch its own extension files, so the panel CSS is inlined as a string instead (that
  flag would also expose it to every page); the host's `position`/`z-index` are inline styles with
  `!important`, not a `:host {}` rule, which a page stylesheet can outrank since the host lives in
  the light DOM; and `storage.session` is unavailable in content scripts in Firefox, so state goes
  through `background.js`. `<all_urls>` moved from `optional_permissions` to required
  `host_permissions` (the tab must appear everywhere), which changes the install consent prompt;
  `activeTab` was dropped. `popup.*` deleted, `action` key removed from the manifest.

- **"Analyze Application" — CV fit, company insight and market stats grounded in live search** —
  `POST /api/v1/applications/analyze/`. MiMo has no internet and would fabricate "current" company
  facts, so `agent/analyzer.py` adds a real search step via Tavily (`TAVILY_API_KEY`, optional,
  same empty-key-disables pattern): one MiMo call extracts company/role/queries, two Tavily
  searches run (company `general`, market `news` + `time_range: month` so figures are fresh), then
  a second MiMo call synthesizes — fit grounded only in CV/posting text, insights and stats only in
  the snippets, each carrying its source URL, empty array rather than an invented fact. Unset keys
  return 503 rather than degrading to hallucinated stats; grounding is the whole point here. The
  report renders via `textContent`, never `innerHTML` — it relays third-party web content — and
  source links are `http(s)` only with `rel="noopener noreferrer"`. Gunicorn's `--timeout` went
  60 → 180 for this feature's four sequential calls.

- **Manual "Generate Cover Letter" button, and About-section context** — `POST /api/v1/
  applications/generate-cover-letter/` reloads the persisted `Application` by id (cv and
  form_snapshot come from the stored row, so the button doesn't resend what the scan captured),
  re-identifies cover-letter refs via `field_mapper.is_cover_letter_field`, regenerates and
  persists back into `field_mapping`. Zero matching refs still returns 200 with `entries: []` so
  the button works for copy-paste on a page with no such field. `scanPage`'s `extractAboutText`
  reads the posting's About blurb from the *untruncated* body text (page_text is cut at 15000
  chars and an About section can sit past that) and requires the next line to read like prose
  (≥60 chars) so a bare nav link isn't mistaken for the section; it's taken from the lowest-frameId
  frame that has one, not the frame with the most fields, since the blurb usually sits in the
  wrapper page even when the form is in an iframe.

- **Analyze shows a live elapsed counter** — a real run took ~7 minutes behind a static
  "Analyzing..." message. Ticks real seconds rather than a guessed range.

- **Per-field "Generate with AI" button on open-ended textareas** — `attachGenerateButtons` is
  injected per frame after a scan, and each button proxies to `POST /api/v1/applications/
  generate-answer/` through `background.js`. A field only gets a button once
  (`el.dataset.jfAiAttached`), but the click handler reads `window.__jfScanContext` rather than the
  closure's original args, so re-scanning with a different CV updates already-attached buttons too
  — without that, switching CVs would silently keep answering from the old one. This is the only
  injected function that calls `browser.runtime.sendMessage` from a persistent listener rather than
  returning a value; if a button ever does nothing, check the *page* console for
  `browser is not defined` first.

- **Delete a stored CV** — `DELETE /api/v1/cvs/{id}/`, 204/404. The file is removed from disk
  (`FieldFile.delete(save=False)`) before the row. `Application.cv` is `SET_NULL`, so past
  applications keep their `field_mapping` with `cv` nulled. A stale `cv_id` from an already-open
  panel degrades safely: the scan path falls back to `None`, and `buildFileMap` skips the missing
  CV, surfacing as a per-ref `no-file-data`.

- **`isHoneypot` skipped Ashby's real resume input** — a live Ashby "Resume" field is a
  `type="file"` input with `tabindex="-1"`, visually clipped behind a styled dropzone; Ashby takes
  it out of tab order on purpose, it isn't a trap. `type="file"` is now exempt from the `tabIndex`
  half of the check only — an `aria-hidden="true"` file input is still treated as a honeypot.

- **`findToggleControl` could click "Clear selections" and wipe a pre-filled combobox** —
  react-select renders `button[aria-label="Clear selections"]` *before* `[aria-label="Toggle
  flyout"]`, and the old `querySelector('button, [role="button"], svg')` returns document order.
  Clicking Clear empties a correct pre-filled value and opens no menu. Candidates whose closest
  button ancestor has an `aria-label` matching `/clear/i` are now skipped — checked on the
  *ancestor*, since the icon `svg` inside has no label of its own but its bubbled click still
  fires the button's handler. A widget with an unlabeled clear control is still exposed; that needs
  another real markup sample.

- **Cover-letter fields were skipped when unlabeled** — root cause of "the résumé attaches but the
  cover letter never does": `_COVER_LETTER_KEYWORDS` required the literal phrase "cover letter"
  with a space, while `_RESUME_KEYWORDS` matched single words. Real ATS file inputs often have no
  usable label, so the haystack falls back to `name`/`id` — `cover_letter`, `coverLetter`,
  `cover-letter`, none containing a space. Widened that one keyword list. Deliberately *not* a
  general separator-normalizing rewrite of `field_haystack`: that was tried and reverted because it
  broke `"email"` against `"e-mail"`.

- **EEO answers routed through a dedicated AI pass** — the old client-side fill needed the
  Settings answer to literally substring-match a field's real option text ("i do not have any"
  never matched "No, I do not have a disability"), so most EEO selects stayed skipped. The boundary
  moved from "core never sees EEO fields" to "AI never invents an EEO answer": `field_mapper` marks
  them `eeo_pending`, and `agent/eeo_mapper.py` resolves that with one MiMo call whose prompt gets
  *only* the EEO fields and the user's own `{match, answer}` rows — no CV text, no posting text, so
  there's nothing else to invent from. It may normalize wording or pick the closest option, but
  every value traces to something the user typed; no matching row, an empty row or a failed call
  all resolve to `skip`. `applyEeoSettings` remains as a client-side verbatim fallback. Resolved
  values persist in `field_mapping` like any other answer. Radio-rendered EEO questions are still
  unhandled (BACKLOG item 8).

- **Checkbox-list questions were never checked** — a single-choice question rendered as five
  independent checkboxes: the LLM prompt documented only `type`/`select`, so MiMo answered `select`
  with the option label, `validate_override` let it through (no `options` to check against), and
  the fill typed text into a checkbox. Added a `check` action, which must be `check`+`"true"` or
  `skip` — never `check`+`"false"`, since the fill treats any non-empty string as checked. Same
  pass confirmed two known gaps rather than guessing: bare `"type"` echoes are model flakiness
  (already handled by the echo strip), and Yes/No *button* widgets with no underlying form control
  are invisible to `scanPage` (BACKLOG item 11).

- **Click the dropdown's real toggle instead of guessing at click targets** — every custom combobox
  on a react-select form failed while native `<select>`s on the same page worked. The widget has a
  dedicated toggle button and no `aria-controls` at all, so "click el / el.parentElement" opened
  nothing, and the document-wide option search then matched a *previous* field's leftover menu —
  producing a false "options found" that failed to match. That's why an earlier "the menu never
  opens" diagnosis was wrong: the real problem was matching against the wrong menu. `no-options` is
  now logged as `dropdown-never-opened` instead of silently succeeding.

- **Scan hidden file inputs** — file inputs are routinely `display:none` behind a custom button,
  which doesn't stop `el.files = ...` + `change` from working, so `type === "file"` bypasses the
  visibility check (honeypot/disabled checks still apply).

- **Cover letter generator (.docx)** — any field matching "cover letter" gets a real generated
  letter. `agent/cover_letter.py` makes one dedicated MiMo call per scan, separate from
  `llm_mapper`'s batch (a 250–400 word letter needs its own prompt, not the "concise 50–150 word"
  one), and renders `.docx` via `python-docx`. `field_mapper` marks matching fields
  `cover_letter_type`/`cover_letter_upload` *before* the resume/profile checks, so the general LLM
  pass never touches them (it only acts on `skip`). A file field carries the docx inline as base64
  in a `file` key on the mapping, with no stored CV row behind it. An unconfigured or failed call
  falls back to `skip` for both — never partially fill, never crash the scan.

- **Bare `"type"`/`"select"` slipped past the echo strip** — the regex only stripped a leading
  `"type "` when something followed; a value that was the bare word got typed verbatim into real
  form fields. `validate_override` now also skips when what remains is empty or exactly
  `type`/`select`.

- **Scan and fill forms in a cross-origin iframe** — a Newton/gnewton career page returned "0
  fields" because the form lives in an iframe on another domain and `scanPage` only queried the top
  document. Firefox returns partial results for inaccessible frames instead of rejecting the whole
  `executeScript` call (Chrome rejects; irrelevant here). Scans now run with `allFrames: true` and
  merge every frame's fields, prefixing each `ref` with its `frameId` (`refFrameMap`) since a
  `data-jf-ref` only resolves inside the frame that stamped it; Fill groups the plan back by frame.
  Posting text comes from whichever frame contributed the most fields, not always frame 0.

- **Strip MiMo's action-keyword echo, and hard-filter logistics questions** — a real fill produced
  the literal text "type Backend Developer" in a job-title field; not reproducible in isolation, so
  it's stochastic prompt echo. Stripped defensively in `validate_override` rather than by
  re-prompting. Same pass: the model answered "Are you legally authorized to work in the US?" with
  "No" at confidence 1.0 and zero CV basis, so work-authorization phrasings joined
  `_LOGISTICS_KEYWORDS` (travel, relocation, salary, notice period, visa, start date), which are
  filtered out of the LLM call entirely. A prompt cannot be trusted to self-police this category —
  the same lesson as the EEO and attestation hard-skips.

- **Fill dropdowns by structure, not by upstream classification** — EEO answers were landing as
  typed text inside dropdowns because `applyEeoSettings` decided `type` vs `select` from the scan
  snapshot's `role`, which some ATS widgets don't set. The live element is now checked at fill time
  (`isDropdownLike`), since different ATSs mark dropdowns up differently and an upstream guess can
  be wrong. `selectValue` also falls back to clearing the input and opening the widget unfiltered
  when typing filters the list to zero.

- **Heuristic field-mapping agent** — `agent/field_mapper.py` matches a field's label/name/id/
  placeholder against known categories (email, names, phone, resume upload) using the CV's
  extracted profile, passed as `cv_id` on the scan. Hard rules, not confidence thresholds:
  EEO/demographic fields are always skipped regardless of available data, and unrecognized fields
  are skipped rather than guessed.

- **MiMo LLM pass + custom combobox filling** — whatever the heuristic skipped (minus EEO,
  attestations and logistics) goes to `mimo-v2.5` in one batched call per scan, grounded in the CV
  text and page text. A no-op when `MIMO_API_KEY` is empty or the call fails — never crashes a
  scan. Native `<select>` answers are validated server-side against the field's real `options` so
  the model can't invent one. The scan also sends `role`/`aria-haspopup`/`aria-controls` and the
  page text so the model can tell a custom combobox from a text input.

- **EEO/demographic settings (user-declared)** — Manage CVs > Settings stores `{match, answer}`
  rows in `browser.storage.local`. This does not relax core's EEO rule; it adds a place for the
  user's own explicit statement. Fixed a latent bug found here: native `<select>` filling assumed
  the chosen option *text* equals its `value` attribute, silently no-opping whenever they differ
  (`<option value="US">United States</option>`); it now matches by visible text.

- **CVs: upload + extraction** — `POST /api/v1/cvs/`, `GET /api/v1/cvs/`, `GET /api/v1/cvs/{id}/
  file/`. Raw text via `pypdf`/`python-docx`, profile via regex (`agent/profile.py`): email, phone,
  name from the first non-empty line with a filename fallback, plus LinkedIn and Git URLs — those
  were added later, after LinkedIn/GitHub fields were always skipped for lack of data rather than
  for lack of a rule.

- **Browser extension skeleton** — Manifest V3 for Firefox. The scanner stamps every candidate
  input/select/textarea with `data-jf-ref`, resolves labels (`label[for]`, closest `<label>`,
  `aria-label`/`aria-labelledby`) and skips honeypots and hidden fields. Fill sets values via the
  native property setter + `input`/`change`, which is what React-controlled inputs need.
  `data_collection_permissions` is declared honestly (`personallyIdentifyingInfo`,
  `websiteContent` — sent only to the local `core` API).

- **Applications: scan endpoint, then the real thing** — `POST /api/v1/applications/scan/` started
  as a deliberately dumb stub to prove the scan → DOM-fill wiring before the mapper landed.
  `Application` has a nullable `cv` FK recording which CV a scan used.

- **Core backend skeleton** — Django 5 + DRF, uv-managed, SQLite, `GET /health/`. Repo scaffold:
  monorepo layout, README, CLAUDE.md, `tasks/`.

- **Upload closed the popup, and a scan was lost on every close** — clicking a hidden file input
  from inside a panel popup opens a native picker that steals focus and closes the popup, 100%
  reproducible under Flatpak Zen because the picker is brokered by `xdg-desktop-portal`. Upload
  moved to its own persistent extension page opened with `tabs.create` (no extra permission
  needed). Scan state moved into `storage.session`, keyed per tab and checked against the tab's
  current URL before restoring.

- **Extension appeared to load but rendered nothing (Flatpak)** — the Flatpak sandbox only grants
  access to the file the picker pointed at (`manifest.json`), so every sibling file resolves empty
  with no error anywhere. Fix: `flatpak override --user --filesystem=/path/to/job-filler
  app.zen_browser.zen`, then fully quit Zen and load the add-on again — a plain Reload doesn't
  re-apply the grant. An earlier CSS "fix" for the same symptom was a wrong diagnosis; noted so it
  isn't repeated.

- **Fresh-clone quick start was broken** — `SECRET_KEY` has no default and `DATA_DIR` was never
  created (SQLite doesn't create parent directories). README says to `cp .env.example .env`;
  settings.py creates `DATA_DIR` on startup.

- **Resume upload would have attached garbage** — `executeScript` args must be JSON-serializable,
  so the raw `ArrayBuffer` wouldn't survive the trip. Base64 across the boundary, decoded back to
  bytes in the injected function.

- **`core/.dockerignore` wasn't excluding `src/data/`** — bare patterns (`db.sqlite3`, `media`)
  don't match a nested path, so a locally-migrated dev DB got baked into the image and a brand-new
  named volume looked already-migrated (Docker seeds an empty volume from the image's directory
  content).
