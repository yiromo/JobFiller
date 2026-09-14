# Progress log

Newest first. One entry per feature commit — added when the feature actually lands, not before.

## Done

- **Fill closed the LinkedIn Easy Apply dialog instead of filling it** — three ways `applyFillPlan`
  could dismiss a native modal, all now blocked, none of which show up on a non-modal ATS page so
  none were caught before. (1) `sizedTarget` walks up to 5 ancestors looking for a clickable box
  when the field's own element is too small; on a tight LinkedIn field that walk reaches the
  `<dialog>` itself, and the `click-box` tactic then fires `pointerdown/mousedown/mouseup/click`
  on it — exactly what a light-dismiss handler reads as a click outside the form. The walk now
  stops at any `dialog`, `form`, `[role="dialog"]` or node covering over half the viewport and
  falls back to the field itself, and `clickOption` refuses those nodes outright as a second
  guard. Same lesson as the `[class*="control" i]` ancestor-walk bug already in CLAUDE.md. (2)
  `closeWidget`'s Escape bubbles to whatever the page listens on; inside a modal that is usually a
  document-level dismiss handler. Escape and Enter dispatched at an element inside an open dialog
  now carry a one-shot bubble listener on that dialog which stops propagation for that exact event
  object, so the combobox's own input/wrapper handlers still see the key and the page's dismiss
  and submit handlers never do. Enter matters as much as Escape here: it can advance the Easy
  Apply step, which loses more than closing it. (3) `selectValue` opens by calling
  `closeWidget(document.activeElement)`, and with nothing focused that is `<body>` — an Escape
  fired outside the dialog, unstoppable by any listener inside it, so those two keys are now
  dropped entirely when a dialog is open and the target sits outside it. The scoping is
  deliberately conditional on an open dialog: on Greenhouse/Ashby the keys still bubble normally,
  because plenty of comboboxes there listen at the document.
  Still open after this, from the same run: `«r23»` came back `not-found` and `«r1m»`
  (wanted "Sanzhar Amanzholov") `dropdown-never-opened` with every tactic tried, so LinkedIn's
  contact-info widgets are a shape the fill engine doesn't recognise yet. That needs the real
  markup, not a guess.

- **Download button per CV in Manage CVs** — generated CVs only existed inside core's media
  directory, so the obvious next thing after generating one (open it, check it, attach it
  somewhere by hand) meant digging through a Docker volume. Each row now has Download next to
  Delete. It fetches `/api/v1/cvs/<id>/file/` and saves the blob through a temporary object URL
  rather than linking straight at the endpoint, because that view returns `Content-Disposition:
  inline` — a plain link would open the PDF in a tab instead of saving it, and would lose the
  stored filename. The object URL is revoked a minute later, not immediately, since revoking it in
  the same tick can race the browser's own read of it.

- **CV generation now works in Docker** — it shipped working only under a host `runserver`, and
  `core` actually runs from `docker compose`, so the first real click returned the 503 telling the
  user to install TeX on a machine that wasn't running anything. The image now installs
  `texlive-latex-base`, `-latex-recommended`, `-latex-extra`, `-fonts-recommended` and `lmodern`
  (272 MB; every `.sty` the template uses except one). The exception is `fontawesome5`, which
  Debian ships only inside `texlive-fonts-extra` (~1 GB for a handful of contact icons), so it's
  installed straight from CTAN's 1.7 MB package zip into `TEXMFLOCAL` instead — `.sty`/`.def`/
  `.fd` into `tex/latex`, the Type1 `.pfb`s, `.tfm`s and `.enc`s into their font trees, then
  `mktexlsr` + `updmap-sys --enable Map=fontawesome5.map` so pdflatex can actually embed them.
  Copying only `*.sty` out of that zip is what the first attempt got wrong: the package loads
  `fontawesome5-mapping.def` at runtime, so it installed cleanly and then failed at compile time.
  That download is deliberately non-fatal — a CTAN outage must not break the whole backend image
  over icons — and the template pairs it with `\IfFileExists{fontawesome5.sty}`, falling back to
  no-op `\fa...` macros (including a `\@ifstar` swallow for `\faMapMarker*`) so the CV renders
  icon-less rather than not at all. Image goes from ~250 MB to 895 MB. Verified by rebuilding and
  curling the real containerised core: 201, one page, icons present, then the smoke-test row
  deleted again.

- **Generate a new CV from an existing one** — `POST /api/v1/cvs/<id>/generate/` takes
  `{instructions, position_text, filename}`, rewrites that CV for the target position and saves
  the result as a new PDF row, so it shows up in the panel's CV dropdown like any uploaded file.
  Two stages in `agent/cv_writer.py`: one MiMo call (`response_format=json_object`, 120s timeout)
  turning the source CV's raw text plus the user's instructions into a structured CV, then a
  `pdflatex` render. The LaTeX template is ported from yiromo.com's `npm run cv`
  (`portfolio/scripts/generate-cv.mjs`) — same preamble, `twocolentry`/`highlights`/`header`
  environments and charter+fontawesome5 look, so a generated CV is visually the same document as
  the hand-maintained one. `CvService.generate_from` wraps the PDF bytes in a `ContentFile` and
  hands it to the existing `upload()`, which means text extraction and `extract_profile` run on
  the generated file exactly as they do for a hand-uploaded one; no new model, no migration.
  Grounding: employers, titles, dates, locations, degrees and numbers are copied from the source
  CV, bullets may be rewritten and reordered freely, and a technology may only be added if it
  appears in the user's instructions or the posting text. **Every added technology is detected in
  Python** by diffing the rendered skills against the source CV's raw text, not trusted from the
  model's own report — a real run added "Docker" while reporting only "Temporal", which is
  exactly the failure that would get someone caught in an interview. The union of both lists is
  shown back in Manage CVs under "confirm each one is true before you send this CV". A trailing
  version number doesn't count as an addition (source "Django", output "Django 5" stays quiet),
  but only that — the check deliberately doesn't collapse on a shared first word, or "Apache
  Kafka" would be silently waved through on a CV that only says "Apache Spark".
  The contact block (name, email, phone, LinkedIn, GitHub) is taken from the source CV's stored
  fields and never passes through the model, so no digit of a phone number can drift. Model
  output is NFKC-normalised, smart punctuation is folded to ASCII and anything outside Latin-1 is
  dropped before LaTeX escaping, because the template's fonts have no glyphs for it and pdflatex
  would otherwise fail on a Cyrillic place name. A missing `pdflatex` returns 503 with install
  instructions and a failed compile returns 502 with the last 30 log lines, never a 500. Verified
  end to end against a running server: upload → generate → `GET /api/v1/cvs/` lists it → download
  → one page, correct content, 45s round trip.

- **Panel slides instead of snapping** — closing with × and opening from the corner tab were
  instant `display: none` flips. Both now animate: the panel slides out to the right and fades,
  the corner tab slides back in behind it (its own transform keeps the `-50%` vertical centring).
  Done purely in the shadow stylesheet with no change to the open/close JS — `[hidden]` stays the
  single source of truth for panel state (`saveScanState` still reads it), but the `[hidden]` rules
  now render the element with `visibility: hidden` + `pointer-events: none` instead of
  `display: none`, and transition `visibility` with a delay equal to the slide so the element stays
  painted for the duration and goes non-interactive the instant it's dismissed. Honours
  `prefers-reduced-motion`.

- **Panel was dead on LinkedIn Easy Apply** — the corner tab rendered but no click reached it once
  the Easy Apply dialog was open. Not a z-index problem: LinkedIn opens that form with native
  `<dialog>.showModal()`, confirmed live (`document.elementFromPoint` at the tab's coordinates
  returned the `DIALOG`, `document.querySelector(':modal')` non-null, while the host itself was
  connected, `position: fixed`, `z-index: 2147483647`, `pointer-events: auto`, not `inert`). A
  modal dialog sits in the browser's **top layer**, which paints above every z-index there is, and
  the HTML spec makes everything outside its subtree inert — so the panel was both covered and
  unclickable, and no styling on our side could have fixed it. The only escape is to be inside the
  dialog: `panel.js` now reparents `#job-filler-panel-host` into the topmost open modal dialog
  while one exists and back to `<body>` when it closes. Driven by two observers rather than a
  one-shot at mount (the modal opens long after the panel does): an `attributeFilter: ["open"]`
  subtree observer on `documentElement` catches `showModal()`/`close()` — `showModal()` can only
  be called on an already-connected element, so the `open` attribute flip always fires — plus a
  narrow `childList` observer on the current dialog's parent for the case where the dialog is
  ripped out of the DOM while still open, which mutates no attribute. Both funnel into one
  rAF-debounced sync, so LinkedIn's DOM churn costs one `querySelectorAll` per frame at worst, and
  the reparent's own mutation converges instead of looping. The shadow root, its listeners and all
  panel state survive the move (`appendChild` relocates the node; nothing is rebuilt). Guarded by
  `CSS.supports("selector(:modal)")` so an engine without `:modal` keeps the old body-anchored
  behaviour instead of throwing on every page. Known open question: if LinkedIn ever positions
  that dialog with a `transform`, the dialog becomes the containing block for our `position:
  fixed` host and the panel would render inside the card — the fix then is promoting the host to
  the top layer with the popover API, not abandoning the reparent.

- **A scan's three AI passes now run in parallel instead of back to back** — `scan()` fired
  `augment_skipped_fields`, then the cover-letter generation, then the EEO resolution, each a
  separate MiMo round trip of its own, so a page with all three cost the sum of three model calls
  while the extension sat on a progress bar. They were never actually dependent on each other:
  all three read the heuristic plan `build_fill_plan` returns and each one only rewrites entries
  carrying its own placeholder action (`skip`, `cover_letter_upload`/`cover_letter_type`,
  `eeo_pending`) — three disjoint slices. `_run_resolution_passes` now forks them into a
  `ThreadPoolExecutor` and merges the results by `ref`, taking from each pass only the refs it
  owns, so a pass that rewrites something outside its slice can't leak into the plan. A pass whose
  slice is empty isn't submitted at all, and with no active passes the heuristic plan is returned
  untouched. Wall-clock scan time drops from roughly the sum of the three calls to roughly the
  slowest one. Safe off the request thread because no pass touches an ORM object — they take plain
  dicts, a `CvDTO` and strings, and the only DB write (`_repo.create`) happens after the join.
  This was the answer to "would FastAPI be faster": the latency was three serial LLM waits, not
  framework overhead, so the fix is here and not a rewrite.

- **UI rewritten black-and-white and scaled up** — the green-on-near-black monospace terminal look
  is gone, replaced with the palette a real ATS board renders under (charcoal `#161616` ground,
  pure-black `#000000` surfaces for inputs/cards/logs, white text, white borders at 10% alpha for
  dividers and 30% for interactive edges, Arial/system-sans type). Everything that was `#4ade80`
  is now white: tab underline, primary-button edge, analysis fit score, corner brackets, the
  injected "Generate with AI" button in `background.js` (now a solid white/black pill). One
  deliberate divergence — a board's primary button is solid white, but the Scan/Analyze buttons
  double as progress bars, so their idle state is outlined and only the *done* state fills solid
  white, leaving the 18%-white growing fill readable in between. The log `<pre>` keeps an explicit
  monospace stack rather than `font-family: inherit`, which would now resolve to Arial and lose
  column alignment. Sizes up across the board: panel 340→440px wide, base 13→15px, big buttons
  14→16px, tabs 11→13px, cover-letter textarea 130→180px, corner tab 36×64→44×76px; the manage /
  settings page was the worst offender at a fixed `width: 560px` in a full browser tab and is now
  `max-width: 960px; width: 100%` with 15px base type and 12/16px control padding. `font-family`,
  `font-size`, `font-weight`, `font-style` and `color` joined the inline `!important` pins on the
  shadow host for the same reason the text-rendering properties did — `:host {}` loses to a page
  rule that targets the host element, and every control inside inherits its font from it.
  `JF_BUILD` bumped to `"02"`.

- **Panel text no longer collapses on pages with aggressive typography** — the log `<pre>` had no
  `line-height` of its own, so it inherited one from the host page: `:host { all: initial }` is
  outranked by any page rule that targets the host element itself, and a site setting a near-zero
  line-height made every log line render on the same baseline, stacked on top of each other. Fixed
  on both sides — the inherited text properties (`line-height`, `letter-spacing`, `word-spacing`,
  `text-transform`, `text-indent`, `white-space`, `direction`) are now pinned inline with
  `!important` on the host element, the same technique already used for `position`/`z-index`, and
  `.jf-log` sets its own `line-height`/`font-family` explicitly. `JF_BUILD` bumped to `"11"`.

- **Fills are now a try-verify-escalate cascade instead of one fixed path** — every action type
  tries several techniques in order and checks the result after each, rather than firing one
  sequence of events and assuming it worked. Text/textarea: native-setter + key-event sandwich →
  `execCommand("insertText")` → direct assignment, verified against `el.value` each time, plus
  `contentEditable` support (`setValue` no longer throws on a non-input element). Checkbox/radio:
  skip if already in the wanted state → native `.click()` → synthetic pointer sequence → native
  `checked` setter + input/change, verified against `el.checked`. Upload: `input`(composed) +
  `change` + jQuery `.trigger()` for older ATSs, verified via `el.files.length`. Native
  `<select>`: assignment → prototype setter if it didn't take. Custom combobox: open-tactics
  (click the element → click its nearest ≥10×10 ancestor → ArrowDown → Alt+ArrowDown → Space →
  type the first 4 characters), then commit-tactics (pointer sequence on the option → native
  `.click()` → Enter → type the full text + Enter), with a virtualized-list pass (scroll the
  option container by one page, up to 16 rounds, bail when `scrollTop` stops moving) when no
  visible option matches. Commit is confirmed by the option list disappearing *and* the control's
  rendered text containing the chosen option; an unconfirmed commit is now its own honest status
  (`selection-not-confirmed`) rather than a silent success. The `via=` tag in the log names the
  winning open+commit pair, so a live run says which technique worked per field.
  Two supporting fixes: option lookup can now scope to a widget's own instance (deriving the id
  stem from the element's own `id`/`aria-describedby`/`aria-activedescendant`, e.g.
  `react-select-gender-*`), which is
  exact per-field even when `aria-controls` is empty while the menu is closed; and the matcher is
  now tiered — exact → normalized (case, curly apostrophes, whitespace) → prefix with a
  word-boundary check → substring for targets of 4+ chars. The word-boundary tier is what lets a
  short answer like "No" correctly match "No, I don't have a disability" without also matching
  "Norway+47". The open cascade also checks `aria-expanded` between tactics: many widgets open on
  a mousedown that bubbles from the input to the control box, so once the widget reports itself
  open the cascade stops escalating and just waits longer — otherwise the next tactic's click on
  the box would toggle the menu back closed. A widget that says it is open but exposes no options
  now reports `options-unreachable` instead of the misleading `dropdown-never-opened`.
  `JF_BUILD` bumped to `"10"`. `node --check` + `web-ext lint` clean, not yet run
  live.

- **Combobox option lookup now ignores listboxes that were already on the page** — a live run
  showed every combobox on a Greenhouse board reporting the *same* option list (a phone
  country-code picker's), because that widget keeps its `[role="option"]` nodes in the DOM at all
  times and the failing fields (`input[role="combobox"]` with an **empty** `aria-controls`) always
  fall through to `findOptions`' document-wide sweep. `findOptions` now filters to options that
  are actually rendered (`getClientRects().length > 0`) and, when there's no `aria-controls`/
  `aria-owns` scope to trust, prefers those that appeared *after* the field was opened
  (`optionSnapshot()` taken before any interaction). This also explains an earlier run's inflated
  fill count: the unbounded substring match was quietly clicking country entries into unrelated
  fields ("No" matching "Monaco+377"), which the 4-char bound in build `"08"` turned into honest
  failures. `selectValue` also now escalates through the ways a person would open the widget —
  click, then `ArrowDown` (the WAI-ARIA combobox open key), then typing — each labelled in the
  log's `via=` tag, with the per-attempt wait cut to 1.2s so three attempts cost less than the
  old two. Round-trip failures are no longer indistinguishable from "core said skip": the log now
  reads `Could not resolve N dropdown(s) via core: <reason>` when the request itself failed.
  `JF_BUILD` bumped to `"09"`. `node --check` + `web-ext lint` clean, not yet re-run live.

- **Combobox fills: fixed a wrong-widget bug, and added a core round trip for genuinely
  unmatched options** — a live test surfaced two real bugs the earlier instrumentation made
  visible instead of silent: (1) `findToggleControl`/`findOptions` in `background.js` located a
  field's open-toggle and its option list via `el.closest('[class*="control" i]')`; on one real
  ATS this walked past the field's own wrapper to a shared page-level container, so every
  combobox on the page ended up opening and reading a single unrelated field's menu (a country
  phone-code list). Fixed by dropping that heuristic entirely: `selectValue` now opens a
  combobox by clicking the exact element `data-jf-ref` was stamped on (guaranteed correctly
  scoped, since it's the real control), and `findOptions` falls back to a document-wide
  `[role="option"]` query — safe only because a combobox is always closed again before the next
  one opens (see next point), so at most one menu's options ever exist in the DOM at a time. (2)
  A "no match" no longer leaves core's guessed text sitting in the field — `selectValue` clears
  it and now also closes the widget (`Escape` + blur), since clearing alone re-triggers some
  widgets' filter-as-you-type reopening; `selectValue` also checks for a stale still-open menu
  before opening its own, closing it first if found. (3) `bestMatch`'s substring fallback tier is
  now bounded to targets of 4+ characters, so a short value like "US" can no longer
  substring-match an unrelated option like "Australia".
  On top of that fix, a **`resolve-options` round trip** now runs when a combobox opens but
  matches none of core's guessed options: `applyFillPlan` returns those as `unresolved`
  (`{ref, wanted, options}`, options being the field's real, only-visible-at-fill-time text),
  `handleFill` POSTs them to a new `POST /api/v1/applications/resolve-options/` endpoint, then
  re-runs a small `applyFillPlan` pass to click whatever option core picks. Core's side
  (`agent/option_resolver.py`) makes one batched MiMo call (same shape as `eeo_mapper.py`: system
  prompt + JSON payload + `response_format` + 45s timeout, degrades to all-`skip` with no
  `MIMO_API_KEY` or on any exception — confirmed by calling it directly with the key unset) given
  only each field's `label`, `wanted` guess, and real `options` — no CV text, no page text — and
  reuses `llm_mapper.validate_override` to snap the result to the closed option set or force
  `skip`. Resolved entries persist into `Application.field_mapping` (`ApplicationService.
  resolve_options`) and are returned to `panel.js`, which splices them into `lastFieldMapping` the
  same way cover-letter regeneration already does, so a second Fill click doesn't repeat the
  round trip. Curl-tested directly against the running core container on the real failing
  application row: a `wanted="Male"` guess against real page options resolved to `"Male"`, and a
  clearly mismatched guess (a GitHub URL against a Yes/No question) correctly resolved to `skip`
  instead of a forced wrong click. `JF_BUILD` bumped to `"08"`. `node --check` + `web-ext lint`
  clean on the extension, `ruff check` + `manage.py check` clean on core; the DOM-side fix and
  round trip are not yet re-tested live end-to-end in a browser.

- **`no-matching-option`/`dropdown-never-opened` log lines now show wanted vs. seen** —
  `selectValue` in `background.js` used to return a bare outcome string, so a failed combobox
  fill only ever logged a generic tag with no way to tell, from the log alone, whether core's
  guessed value was wrong or the widget's real option list was. It now returns
  `{status, wanted, seen, via}` (`seen` bounded to the first 10 options, each truncated to 40
  chars; `via` notes whether the option list came from clicking a toggle or from typing into the
  field first), and `outcomeResult` folds that into the reason string, e.g. `no-matching-option
  wanted="Not a veteran" saw="I am not a protected veteran" | "I identify as one or more
  classifications of protected veteran" via=toggle`. Root cause of a live failure this surfaced:
  on a custom (non-native-`<select>`) combobox, the scan-time DOM snapshot has no way to see the
  widget's options (they don't exist in the DOM until it's opened), so core's field/EEO mapping
  has no option list to match against and returns its best free-text guess — which then fails to
  match the widget's real, differently-worded option labels at fill time. That's a mapping-input
  gap, not a DOM-interaction bug, and isn't fixed here — this change only makes the failure mode
  visible in the panel's own log instead of requiring a devtools trip. `JF_BUILD` bumped to
  `"07"`. `node --check` + `web-ext lint` clean, not yet re-run against a live page.

- **`applyFillPlan` fill-robustness pass** — four small fixes in `background.js`, all in
  `applyFillPlan`/`isDropdownLike`/`findOptions`: (1) `setValue` now also does
  `el.setAttribute("value", v)` on `INPUT` after the native property setter, since some
  ATS-side validation/CSS reads the DOM attribute rather than the live property, which the
  setter alone doesn't touch; (2) `isDropdownLike` and `findOptions` now also check
  `el.closest('[role="combobox"], [aria-haspopup="listbox"]')`, not just the focused element's
  own attributes — the WAI-ARIA 1.1 combobox pattern allows those roles (and
  `aria-controls`/`aria-owns`) to live on a wrapper around the input instead of on the input
  itself, which the old own-attribute-only check missed; (3) the `"check"` action no longer sets
  `el.checked` directly — it now compares against the wanted state and calls `el.click()` when
  they differ, because React's `ChangeEventPlugin` listens for a native `click` on
  checkboxes/radios (not `change`), and assigning `.checked` directly trips the same
  value-tracker trap `.value` does on text inputs. `JF_BUILD` bumped to `"06"`. `node --check` +
  `web-ext lint` clean, not yet exercised against a real dropdown/checkbox in a live browser.

- **Manage CVs tab opens zoomed to 30%** — `openManage`'s handler in `background.js` now calls
  `browser.tabs.setZoom(tab.id, 0.3)` right after `browser.tabs.create` for `manage.html`; `0.3` is
  the minimum value the Tabs API's `setZoom` accepts (range `0.3`–`5`), and needs no manifest
  permission. `JF_BUILD` bumped to `"05"`.

- **Dedicated Logs tab, Scan & Fill mirrors its own response, and a CV-required gate** — the
  shared `#jf-log` element used to sit below both tab panels at all times, competing for vertical
  space with the Scanner/Filler and Analyze content. Added a third tab (`jf-tab-logs` /
  `jf-panel-logs`) holding the relocated log element (now `jf-log jf-log-full`, `max-height: 420px`
  instead of `200px` since it has the whole panel to itself) plus a `Copy logs` button
  (`navigator.clipboard.writeText`, no extra manifest permission needed since it runs from a user
  click in a content script) and a `Download .txt` button (`Blob` + `URL.createObjectURL` + a
  temporary `<a download>` click, revoked immediately after). `setActiveTab`/`getActiveTab` were
  generalized from a scan/analyze boolean toggle to loop over `["scan", "analyze", "logs"]`, and
  all three tab buttons go through one `switchTab(tab, sourceId)` helper that logs the click and
  persists `activeTab` via the existing `saveScanState`. A separate "View logs" link on the
  Scanner/Filler and Analyze tabs was tried and then dropped — the tab alone is enough to reach the
  Logs tab. Instead, `log()` grew an optional second `mirrorId` argument: `runScan`/`runFill` now
  call `log(line, "jf-scan-log")` for every line in `result.logLines` (and for their catch-block
  errors), writing to both the full `#jf-log` and a small `<pre id="jf-scan-log" class="jf-log
  jf-log-mini" hidden>` sitting right in the Scanner/Filler tab, so the outcome of clicking Scan &
  Fill (or Re-scan, or Fill) is visible without leaving that tab — it starts and resets `hidden`
  between scans so an empty bordered box doesn't show before the first scan or after a page-reload
  restore (this mirror isn't persisted; only the full log survives a reload). Also added the
  validation this surfaced a need for: `#jf-scan-btn` now starts `disabled` and is re-enabled only
  once a CV is selected (`jf-cv-select`'s `change` handler, `loadCvs()`'s `.then()` in `mount()`,
  and `restoreScanState` when a prior scan is restored, all keep it in sync with the current
  selection); a guard at the top of `runScan` also blocks Re-scan without a CV, since a `.jf-link-btn`
  can't be `disabled`-styled the same way and the user asked for no scan to be possible without one
  chosen. `JF_BUILD` bumped to `"04"`. `node --check` and `web-ext lint` clean (0 errors, same 2
  pre-existing warnings); not yet clicked through in a real browser.

- **Extension versioning + structured logging, and a real scan bug this surfaced** — after the
  tab redesign below, a live scan on a real Ashby page failed with "Could not establish
  connection. Receiving end does not exist." even after reloading the add-on and the page, with
  no way to tell whether the content script, the background script, or something inside core was
  at fault. Added transparency infrastructure so this class of report is diagnosable without
  guessing: `manifest.json` keeps `version` as strict semver (`0.3.0` — Firefox's manifest
  validator rejects a hyphenated version string). First tried a `version_name` field for the
  human-facing `X.Y.Z-NN` display string — Firefox rejected it outright ("An unexpected property
  was found in the WebExtension manifest", `version_name` is Chrome-only, unlike Chrome/Safari
  which accept it silently) — replaced with a new `src/version.js` (just `const JF_BUILD = "01"`)
  loaded as an extra script alongside both `background.js` (in `background.scripts`) and
  `panel.js` (in `content_scripts[0].js`), plus a `<script>` tag in `manage.html` before
  `manage.js`, so the one build-number constant is shared across all three JS contexts without a
  bundler. Bump `JF_BUILD` on every further extension change so a bug report can be pinned to an
  exact build. `panel.js` (header, next to the JOBFILLER logo), `background.js` (its console
  prefix), and `manage.js`/`manage.html` (next to the "Manage CVs" heading) all compute
  `` `${browser.runtime.getManifest().version}-${JF_BUILD}` `` and show/log it as `v0.3.0-01`.
  `panel.js`'s `log()` now timestamps every line (`[HH:MM:SS.mmm] ...`) and a new `logEvent(action,
  details)` helper formats structured `key=value` entries; every button click, the CV-select
  change, and every `send()` call (now logging `SEND`/`RECV`/`RECV_ERROR` with the message type
  and `ok` status) writes a line, so the log panel reads as a chronological trace of exactly what
  was clicked and what the background script answered — not just the final per-field fill results
  it showed before. Fixed a bug this introduced before it shipped: `restoreScanState` used to
  unconditionally overwrite `#jf-log` with the persisted `logText`, which would have silently
  discarded the fresh `BOOT`/`whoami`/`getState` lines logged earlier in the same `mount()` call —
  changed to prepend the restored history instead of replacing. `background.js` mirrors this with
  a `logBg(action, details)` writing to `console.info` (visible via `about:debugging` → *This
  Firefox* → JobFiller → **Inspect** → its own Console, not the page console or the panel) logging
  a `BACKGROUND_LOADED` line at script load and `RECEIVE`/`RESPOND` for every message; a new
  `reportError(type, err)` also `console.error`s the real error object (not just `String(err)`,
  which throws away the stack) in every message-handler `.catch`.
  First guess at the cause — `handleScan`'s `browser.scripting.executeScript({ target: { tabId,
  allFrames: true }, func: scanPage })` rejecting on an unreachable third-party iframe — turned
  out wrong: the structured log from a real failing run showed the *same tab, same frames, no page
  reload* succeed in 107ms with no CV selected and then fail 6 seconds later, 31.67s after the
  retry click, with a CV selected. Frame structure hadn't changed; only `cv_id` had. (Kept the
  allFrames→top-frame fallback anyway since it's harmless and a real gap, but it isn't this bug.)
  Real cause, confirmed by curling core directly with a realistic payload: a scan with a CV
  attached runs `agent/llm_mapper.py`'s batched MiMo pass over every open-ended/skipped field,
  which took 26.4s for 25 fields against the real running container — squarely in the range that
  killed the connection at 31.67s live. Firefox can unload a non-persistent MV3 background script
  after ~30s idle, including (on some Firefox versions) while a `fetch()`-backed `onMessage`
  promise is still pending, which severs the content script's connection mid-response with exactly
  this error text. Added `startKeepalive()` in `background.js`: a `setInterval` polling
  `browser.storage.session.get(...)` (a trivial extension-API call, which resets Firefox's idle
  timer) every 20s for the duration of every message handler, wrapped once around all of them via
  the shared `respond()` helper rather than in each `handleX` function individually. Also fixed
  the scan button's progress bar/label in `panel.js`, tuned when scan was assumed sub-second: `tau`
  raised from 1.2 to 12 and the button label now ticks elapsed seconds ("Scanning... 23s") past 2s,
  matching Analyze's treatment, since a CV-attached scan legitimately takes 20-30+ seconds and the
  bar was sitting frozen at 92% the whole time. Not yet confirmed against a real failing page —
  needs the user to retry Scan & Fill with a CV selected and report back: whether it now succeeds,
  and if not, whether the background console (`about:debugging` → *This Firefox* → JobFiller →
  Inspect → Console) shows a second `BACKGROUND_LOADED` line (background actually restarted mid-
  request, confirming the eviction theory) or a `reportError` line (a different failure entirely).
  `node --check` and `web-ext lint` clean (same 2 pre-existing manifest warnings, 0 errors) on all
  touched files (`version.js`, `panel.js`, `background.js`, `manage.js`).

- **Panel reorganized into two tabs, each with one big action button** — the flat stack of
  small side-by-side buttons (Scan / Fill / Generate cover letter / Analyze) is now two tabs,
  "Scanner/Filler" and "Analyze application", switched via a `role="tablist"` pair persisted as
  `activeTab` in the existing `saveScanState`/`restoreScanState` round trip (same `scan:<tabId>`
  session-storage entry everything else already rides on) so the active tab survives a popup
  reopen/tab switch like the rest of the scan state. CV select + Manage button and the status
  line/log stay shared above/below the tabs — Analyze still depends on the `applicationId` a scan
  produces, so splitting that state per-tab would have been wrong.
  Scanner/Filler: `#jf-scan-btn` is now one big full-width button that does both steps —
  `data-mode` toggles `"scan"`/`"fill"` and one click handler dispatches on it, replacing the old
  separate `#jf-fill-btn` (disabled dead-string bug: `finishProgress`/etc. reused the same button
  reference across both modes rather than two elements needing separate sync). On scan success the
  button relabels to "Fill application" and a small "Re-scan" text link appears next to it (refs
  die on any SPA re-render per this file's own notes above, so re-scan has to stay one click away
  even after a fill); clicking Fill again after a successful fill is left legitimate (re-filling a
  partially-completed form is a real use case), not reset back to scan mode automatically.
  "Generate cover letter" is now a second big full-width button directly under it instead of its
  own row.
  Analyze application: same big-button treatment, and a genuine functional gap in the old design
  is now closed — after one Analyze run there was no way to run it again without a page reload
  (`renderAnalysis` just unhid a static result card forever). Now the button hides once a report
  renders and a small "Analyze again" link takes over, both wired to the same `runAnalyze` function.
  Added a "Scan the page in Scanner/Filler first" hint under the button, visible whenever
  `lastApplicationId` is null, since a silently-disabled button on its own tab (no sibling button to
  compare against for context, unlike before) was confusing.
  Progress-fill mechanics: extracted the existing scan-button gradient/ticker into a shared
  `runProgress(btn, tau)`/`finishProgress`/`resetProgress` used by both buttons — analyze runs
  30–90s (four sequential external calls) versus scan's single round trip, so it gets a much larger
  `tau` (18 vs 1.2) instead of visually saturating in ~4s and sitting frozen at 92% for the rest of
  the wait; the elapsed-seconds counter the previous commit added to the status line now lives in
  the analyze button's own label ("Analyzing... 23s") since the button is the focal element now.
  Also fixed two contrast/specificity bugs the redesign would otherwise have shipped with, both
  caught by review before commit: (1) the done-state fill was originally the same solid `#4ade80`
  as the button's own hover/primary text color, which made the "Fill application" label vanish on
  hover at the exact moment it's about to be clicked — added an explicit `:hover` override. (2) the
  in-progress gradient was rendering at the existing `.jf-btn:disabled { opacity: 0.4 }` dimming the
  whole 30–90s analyze wait; added a `.jf-busy` class (set/cleared by `runProgress`/`stop()`) that
  exempts only an actively-running button from that opacity rule, not a disabled-because-no-scan-yet
  one. Separately caught and fixed a bug from an even earlier pass in this same edit: the old
  `.jf-btn { flex: 1 }` (meant for the now-deleted side-by-side button rows, `.jf-actions`, which no
  longer has any element using it) was declared *after* the new `.jf-big-btn { flex: none; width:
  100% }` in the stylesheet, so at equal specificity it silently won and every big button would
  have stretched to fill the tab panel's remaining vertical space — removed `flex: 1` from `.jf-btn`
  and the dead `.jf-actions` selector instead of fighting it with specificity or reordering.
  `node --check`/`web-ext lint` clean (same 2 pre-existing manifest warnings, 0 errors). **Not
  driven in a real browser** — the tab switch, the two-step button's mode toggle, the progress fill
  timing/opacity, and the restore-on-reload path (in particular: does `restoreScanState` correctly
  put the button in fill-mode-with-the-done-look, not just fill-mode-with-no-visual-state) are
  reviewed but unverified live.

- **"Scan this page" button fills as a live progress bar** — the button's own background is a
  hard-stop `linear-gradient` driven by a `--jf-progress` CSS custom property, ticked every 100ms
  on an easing curve (`92 * (1 - e^(-t/1.2))`) that approaches but never reaches 92% on its own —
  scan has no incremental server-side progress to report (one round trip), so a real finish always
  visibly jumps the rest of the way to 100% instead of the bar ever looking done before the result
  is back. On success the button gets a `.jf-scan-done` class (solid `#4ade80` background, black
  text, per the user's exact spec) that persists until the next scan resets it. Also disabled the
  Scan button itself for the duration of the click (it wasn't before — Fill/Generate/Analyze
  already disable themselves mid-click, Scan was the one exception), since a second click mid-scan
  would have raced two `/scan/` calls and orphaned the first progress ticker.

- **In-page panel replaces the toolbar popup** — a browser popup (`action.default_popup`) is
  destroyed and recreated every time it closes, including on a tab switch, which wiped all UI
  state even though the underlying data was already saved. Fix: `extension/src/content/panel.js`
  now injects on every page (`content_scripts`, `<all_urls>`) and mounts a closed shadow DOM host
  with a small corner tab (right edge, vertically centered — clear of ATS "Submit" buttons that
  commonly sit bottom-right) and a slide-out panel, styled dark/sharp/monospace to match the
  user's `yiromo.com` portfolio aesthetic (JetBrains Mono, `#4ade80` accent, corner-bracket frame
  motif) rather than reusing Simplify Copilot's literal light/blue look — only its layout
  (corner tab, docked panel, sectioned results) was the reference. A content-script-injected DOM
  node survives a tab switch for free (it's hidden, not destroyed); `browser.storage.session`
  (keyed `scan:<tabId>`) still covers the one case that does reset it, a full page
  reload/navigation. `extension/src/background.js` is new and owns everything a content script
  can't do itself: all `fetch` calls to core and every `scripting.executeScript` injection
  (`scanPage`, `applyFillPlan`, moved verbatim) — `panel.js` only talks to it via
  `browser.runtime.sendMessage`/`onMessage`. `popup.html`/`popup.js`/`popup.css` are deleted;
  `manifest.json` drops the `action` key entirely (no more toolbar icon — the corner tab is the
  only entry point) and adds `background`/`content_scripts`. **Permission change, not silent:**
  `<all_urls>` moves from `optional_permissions` (opt-in per site via Manage CVs > Page access,
  now removed) to a required `host_permissions` entry, since the corner tab must appear
  automatically on every page — this changes the install/update consent prompt to "Access your
  data for all websites." `activeTab` is no longer needed and was dropped (the old popup relied on
  its transient per-click grant; the content script has no such gate to begin with, and
  `<all_urls>` already covers everything `scripting`/`tabs` need). `manage.html`/`manage.css`
  restyled to match (same dark tokens); its "Grant page access" flow was removed since access is
  now always granted. Not yet built: a "hide the corner tab on this site" affordance — flagged as
  a likely follow-up now that the tab appears everywhere, including sites that aren't job
  applications, rather than built speculatively ahead of anyone hitting that friction.
  **Fixed after first real-world test:** the panel never rendered on any page — `panel.js`
  loaded its CSS via `fetch(browser.runtime.getURL("src/content/panel.css"))`, but Manifest V3
  requires a content script's own fetches of extension files to be declared in
  `web_accessible_resources`, which wasn't set, so the fetch silently failed and `mount()` (which
  builds the whole panel) never ran. Fixed by inlining the CSS as a string constant in `panel.js`
  instead of granting `web_accessible_resources` — that flag would also expose the file to every
  page's own scripts, which isn't needed here. `panel.css` is deleted; the CSS now lives in
  `panel.js`. **Also fixed:** the panel docked flush to the viewport edges (full height, no gap,
  no shadow), so on sites with a dark fixed header its background just fused with the page's own
  — insetting the panel 16px from every edge and adding a real box-shadow makes it read as a
  floating card regardless of what's behind it. **Also fixed, found by extracting the user's own
  installed Simplify Copilot `.xpi` and reading its content script:** the host element's
  `position`/`z-index` were set via a `:host {}` rule inside the shadow stylesheet, which has
  fairly low CSS specificity and can lose to a page's own stylesheet (this is almost certainly
  why it kept visually merging into Fastly's header even after the inset/shadow fix — the host
  itself, unlike its shadow-encapsulated children, lives in the light DOM and is fully subject to
  page CSS). Simplify sets these as plain inline styles on the host via JS instead, which beats
  page stylesheets regardless of specificity; matched that, with `!important` for extra safety,
  and moved the host from `document.documentElement` to `document.body` to match. **Also fixed:**
  `saveScanState`/`restoreScanState` in `panel.js` called `browser.storage.session.set`/`.get`
  directly, which crashed (`TypeError: can't access property "set", browser.storage.session is
  undefined`) — content scripts don't get `storage.session` in Firefox by default, only
  privileged extension contexts (confirmed Simplify's own content script avoids calling it at
  all, for the same reason). Moved the reads/writes into `background.js` (new `saveState`/
  `getState` message cases, keyed the same `scan:<tabId>` way); `panel.js` now only ever talks to
  it via `send()`. Per an explicit ask to adopt Simplify's fill technique where it's actually
  better, compared its value-setting function too: same native-setter core `applyFillPlan`
  already used, but wrapped in a fuller event sandwich
  (`focus`/`keydown`/`keypress`/[setter]/`textInput`/`input`/`keyup`/`change` vs. just
  `input`/`change`) to also reach autocomplete/masked-input widgets that key off keyboard events
  rather than a value change. Adopted that into `background.js`'s `setValue`; deliberately did
  not adopt Simplify's `.click()` call in the same function — this codebase's comboboxes already
  have a dedicated toggle-click flow (`findToggleControl`/`selectValue`), so an extra click on
  the plain-text path looked like added risk with no matching benefit. Not yet re-verified live:
  the crash happened during scan-state save, right after a successful scan but before Fill was
  reached, so this is the first real test of Fill (and the new event sequence) in the new
  in-page-panel architecture.

- **"Analyze Application" button — CV fit, company insight, and job-market stats grounded in
  live web search** — new `POST /api/v1/applications/analyze/`
  (`{application_id, page_text, about_text}` -> `{fit_score, fit_summary, company_insights,
  market_stats, apply_timing, suggestions}`). MiMo alone has no internet access and would
  fabricate "current" company facts and statistics, which defeats the point of an analysis meant
  to reflect real, current conditions — so `agent/analyzer.py` adds a real search step via the
  Tavily API (`TAVILY_API_KEY`, new optional `.env` setting, same empty-key-disables pattern as
  `MIMO_API_KEY`): one MiMo call extracts `{company, role, company_query, market_query}` from the
  job posting text, two Tavily searches run (`topic: "general"` for the company, `topic: "news"`
  + `time_range: "month"` for market/demand stats so figures are actually fresh), then a second
  MiMo call synthesizes the final report — grounded strictly in the given CV/posting text for
  `fit_score`/`fit_summary`, and strictly in the Tavily snippets for `company_insights`/
  `market_stats` (each point required to carry the source `url`/`published_date` it came from;
  empty array rather than an invented fact if search found nothing useful). Reuses the CV-prose
  house style from `cover_letter.py` (no em dash, no AI-assistant stock phrasing) since this is
  also free-form generated text. `ApplicationService.analyze_application` mirrors
  `regenerate_cover_letter`'s error shape: 404 unknown application, 400 no CV on the record, 503
  if either `MIMO_API_KEY` or the new `SearchNotConfiguredError` (`TAVILY_API_KEY`) is unset —
  never silently degrades to hallucinated stats, since grounding is the entire point of this
  feature. No new persistence (ephemeral per click, like cover-letter regeneration's returned
  text). Extension: new "Analyze Application" button (gated on `lastApplicationId`, same as
  Generate Cover Letter) renders the report into a new `#analysis-result` block built via DOM
  APIs (`textContent`, not `innerHTML`) since `company_insights`/`market_stats` ultimately
  originate from third-party web search results relayed through the LLM — untrusted content —
  and source links are restricted to `http(s)` with `rel="noopener noreferrer"`. Wired into the
  existing `saveScanState`/`restoreScanState` round trip alongside the cover-letter preview so
  the report survives a popup close. `analyze()` logs the extracted search queries and Tavily hit
  counts, and `_synthesize` logs MiMo's raw parsed response (same `logger.warning` pattern as
  `llm_mapper`/`eeo_mapper`) so a "why is this section empty" report is diagnosable from
  `docker logs` rather than guessed at; `_synthesize` also normalizes every field with `.get(...,
  default)` before returning, since `response_format=json_object` guarantees valid JSON but not
  that MiMo's keys match the prompt (this codebase has documented prompt-drift flakiness
  elsewhere) — a missing key degrades to an empty/zero field instead of a 500. Gunicorn's
  `--timeout` raised from 60 to 180 in `core/Dockerfile`: this feature's worst case is four
  sequential MiMo/Tavily calls (45+20+20+60s), which the old 60s timeout would have had gunicorn
  kill mid-request. Verified live end to end against the real `Application` #35
  (CircleCI/Greenhouse, `cv_id=3`) with a realistic job-posting text: a fit score with concrete
  CV-gap reasoning, company insights and market stats each citing a real source URL (one run's
  empty `company_insights` turned out to be normal search/synthesis variance, not a bug — a
  second identical curl after adding the logging returned 2 grounded company facts and 2 dated
  market stats, confirmed via `docker logs`), an apply-timing note based on the posting's stated
  age, and CV-specific suggestions; separately verified 404 (nonexistent application), 400
  (`#26`, no CV on record), and confirmed the Tavily request/response shape by hand
  (`Authorization: Bearer`, `results[].{url, title, content, published_date}`) before writing the
  client, rather than guessing the API from memory. `ruff check` clean on all new/edited files
  (pre-existing formatting drift in 5 unrelated files, untouched), `manage.py check` clean,
  `web-ext lint` clean (same pre-existing manifest warnings), `node --check` clean on `popup.js`.
  Not yet driven in a real browser.

- **Manual "Generate Cover Letter" button + About-section context** — scan-time generation
  (`ApplicationService._resolve_cover_letter`) only ever ran once per scan and only for fields the
  keyword match caught; there was no way to re-roll a letter or get one at all on a page with no
  detected cover-letter field. Added `POST /api/v1/applications/generate-cover-letter/`
  (`{application_id, page_text, about_text}` -> `{text, entries}`): `ApplicationService
  .regenerate_cover_letter` loads the persisted `Application` by id (not a fresh CV/page_text pair
  from the request — cv_id and form_snapshot come from the stored row, so the button doesn't need
  to re-send everything scan already captured), re-identifies cover-letter refs from the stored
  `form_snapshot` via a new `agent.field_mapper.is_cover_letter_field` (extracted from the same
  check `_map_field` already used, so both stay in sync on what counts), regenerates, and persists
  the updated entries back into `field_mapping` (`ApplicationRepository.get`/
  `update_field_mapping`, new `ApplicationDTO`) — so a later Fill uses the new text. A
  no-CV-on-record application returns 400 and an unset `MIMO_API_KEY` returns 503 (mirrors the
  scan path's degrade-not-crash guard, but a manual click needs an explicit answer instead of a
  silent skip). Zero matching refs still returns 200 with `entries: []` so the button also works
  for copy-paste on a page with no recognized cover-letter field at all.
  Extension: `popup.html`/`.js` add a "Generate Cover Letter" button and a readonly preview
  `<textarea>`; clicking it calls the new endpoint with the page text/about text captured at scan
  time (does not re-run `scanPage`, which would re-stamp `data-jf-ref` and duplicate the
  frame-selection logic for no gain) and splices the returned `entries` into `lastFieldMapping` by
  ref. The popup document is destroyed on every outside click (existing `storage.session` comment
  in `popup.js`), so `lastApplicationId`/`lastPageText`/`lastAboutText`/the preview text are wired
  into the existing `saveScanState`/`restoreScanState` round trip alongside `lastFieldMapping` —
  without this the button would silently go stale (disabled, unrecoverable short of a full
  re-scan) the moment the user clicked anything on the page, which is the common case. Gating is
  now purely "a scan produced an `Application` id" rather than "a CV was selected at scan time" —
  the actual CV check happens server-side against the persisted record, and `cvSelect`'s value
  isn't itself persisted across popup reopens, so gating on it at restore time would have been
  wrong anyway.
  Also: `scanPage`'s `extractAboutText` pulls the posting's own "About the company/role" blurb
  from the *untruncated* body text (page_text's LLM-context field is cut at 15000 chars and an
  About section can sit past that) and sends it separately as `about_text` on both the scan and
  generate-cover-letter requests; `agent/cover_letter.generate()` gives it its own labeled block
  in the prompt rather than folding it into the generic job-posting text. The heuristic requires
  the candidate "About" line's next non-empty line to read like real prose (>=60 chars) before
  accepting it, specifically so a bare nav link ("About" in the header, followed immediately by
  another short nav item) doesn't get picked up as the section. `about_text` is taken from the
  lowest-frameId frame that has one (not tied to `bestFrame`, which is chosen by field count) since
  the About blurb is typically in the top frame even when the actual form is in an embedded ATS
  iframe. Verified end-to-end against the running container with real persisted data: `curl`'d the
  new endpoint for `Application` #32 (a real KoBold/Greenhouse posting, `cv_id=3`) with a synthetic
  about_text and got back a letter that referenced the about text's specifics, an `entries` list
  with the correct `upload`+`.docx` shape for the page's `cover_letter` file field, and confirmed
  the write landed in `Application.field_mapping` in the DB; separately verified the 400 (no CV on
  the application, using #26) and 404 (nonexistent application id) paths, and the empty-`entries`
  copy-paste path (#29, no cover-letter field on that page). `ruff check` + `manage.py check`
  clean, `web-ext lint` clean (same pre-existing manifest warnings), `node --check` clean on the
  extension JS. Not yet driven in a real browser — the popup button click, the preview textarea,
  and the storage-session persistence round trip are reviewed but unverified in an actual
  Firefox/Zen popup.

- **"Analyzing..." status shows a live elapsed-time counter instead of a static message** — a
  real analyze run took ~7 minutes (4 sequential external calls: MiMo query-extraction, 2 Tavily
  searches, MiMo synthesis), and the panel just sat on a static "Analyzing application..." the
  whole time with no sign it was still working. Tried a hardcoded "usually 1-3 min" estimate
  first; the user asked for a live one instead. `panel.js`'s analyze click handler now starts a
  1s `setInterval` ticking real elapsed seconds into the status text and shows the actual total
  on completion — an honest number instead of a guessed range copy.

- **Per-field "Generate with AI" button on open-ended textareas** — inspected Simplify Copilot's
  real implementation (`contentScriptMain.js`, `CustomQuestionAI` component) at the user's
  request: theirs opens a modal ("Application Question AI") with a `browser.runtime.sendMessage
  ({method:"requestGPTValue", question, ...})` call to their background script, then either
  writes the result into the field or offers "Copy Answer to Clipboard". Built a simpler direct
  version instead of copying the modal: a small inline "Generate with AI" button, styled in this
  project's own dark/`#4ade80` aesthetic rather than Simplify's UI, appended right after every
  scanned `<textarea>` that has a usable label/placeholder — clicking it fills that one field
  directly, no intermediate dialog. Backend: `agent/question_answer.generate(cv_raw_text,
  question, page_text)` (new, one MiMo call, same "ground strictly in CV text, honest if nothing
  relevant" house style as `cover_letter.py`), `ApplicationService.generate_question_answer`
  mirrors `regenerate_cover_letter`/`analyze_application`'s 404/400/503 error shape exactly, new
  `POST /api/v1/applications/generate-answer/`. Extension: `background.js` gets a new injected
  page-context function `attachGenerateButtons` (called once per frame right after a scan's core
  response returns, so it has a real `application_id` to attach), and a `generateAnswer` message
  case that proxies to the new endpoint — same architecture as every other privileged call in
  this file. A field only gets a button once (`el.dataset.jfAiAttached`, survives across re-scans
  in the same page load); `window.__jfScanContext` (not the closure's original
  `applicationId`/`pageText` args) is what the click handler actually reads, so a re-scan with a
  different CV/application updates *already-attached* buttons too, not just newly-seen ones —
  caught before shipping: without this, switching CVs and re-scanning would silently keep
  generating answers grounded in the old CV. Deliberately not gated on whether core already
  filled the field — a cover-letter textarea gets the button too, and clicking it overwrites the
  generated letter with a short 2-5 sentence answer instead; that's user-initiated, not a bug, but
  worth knowing before reporting it as one. No hide/disable toggle (Simplify has one) — flagged in
  `tasks/BACKLOG.md` item 12 rather than built speculatively. Verified live end to end against the
  real running container (rebuilt via `docker compose up --build`): scanned a synthetic form with
  the exact "If you require sponsorship now or in the future..." question from the reference
  screenshot using the real test CV, got back a real grounded answer referencing the CV's actual
  location; separately confirmed 404 (unknown application) and 400 (application with no CV on
  record). `ruff check`/`manage.py check`/`web-ext lint` clean. **Not verified**: the actual
  button click inside a real browser. This is the one genuinely new pattern in the codebase —
  every other `scripting.executeScript`-injected function (`scanPage`, `applyFillPlan`) is
  self-contained and returns a value; this one calls `browser.runtime.sendMessage` from inside an
  injected function's persistent click listener, which should work in Firefox's default
  "ISOLATED" execution world (same privilege level as a content script) but has not been observed
  running. If the button does nothing or logs "Failed" immediately on click, check the page's own
  console (not the extension's) for `browser is not defined` first — that pinpoints this exact
  assumption being wrong.

- **Delete a stored CV** — `DELETE /api/v1/cvs/{id}/` (new `CvDetailView`), 204 on success, 404 if
  already gone/unknown. `CvRepository.delete` removes the file from disk (`FieldFile.delete(save=
  False)`, confirmed via `find` inside the running container that the file is actually gone, not
  just orphaned) before deleting the row. `Application.cv` is `on_delete=SET_NULL`, so past
  applications keep their persisted `field_mapping` with `cv` nulled, not cascaded away. Manage
  CVs (`extension/src/manage/`) gets a "Delete" button per row (`confirm()` before calling it,
  `#cv-list li` switched to flex so the button doesn't overhang the row like a stray `float:
  right` would have — `.cv-name`/`.cv-filename` stay put, button pinned right via `margin-left:
  auto`) — a 404 response is treated the same as success (already gone) rather than surfaced as
  an error. Checked, not guessed, what happens when a scan/fill still references a since-deleted
  CV (the panel's `cvSelect` only refreshes on mount, so an already-open tab can still hold a
  stale id): `ApplicationService`'s scan path already resolves `cv_id` via `_cv_repo.get(...)`
  and falls back to `None` if not found (confirmed live: `cv_id: 9999` scans fine, degrades to
  no-CV/no-profile data, no `IntegrityError`) — pre-existing behavior, not new; and
  `background.js`'s `buildFileMap` already `continue`s past a CV missing from a fresh
  `fetchCvs()` call, which surfaces as the existing per-ref `no-file-data` failure in
  `applyFillPlan` rather than aborting the whole fill. Verified end to end against the real
  running container (rebuilt via `docker compose up --build` to pick up the new endpoint): real
  upload → 200 file download → 204 delete → gone from the list → 404 on file download → 404 on a
  second delete. `ruff check`/`manage.py check`/`web-ext lint` clean. The Manage UI itself (the
  button, the confirm dialog, the list refresh) is not yet driven in a real browser.

## Fixes

- **`isHoneypot` skipped Ashby's real resume file input, so it was never scanned at all** — got
  the real outerHTML of a live Ashby "Resume" field after the user reported nothing was uploaded:
  a `type="file"` input with `tabindex="-1"`, visually clipped (`clip: rect(0,0,0,0)`) behind a
  styled "Upload File" button/dropzone. `isHoneypot` treated any `tabIndex === -1` as a bot-catcher
  trap, same false-positive shape as the visibility check already carved an exception for on file
  inputs (`scanPage`'s existing `type !== "file"` guard on `isVisible`) — Ashby removes the real
  input from tab order on purpose since the styled button is the actual interactive element, not
  because it's a trap. Fixed by exempting `type="file"` from the `tabIndex` half of the check only
  (an `aria-hidden="true"` file input is still treated as a honeypot — that signal isn't
  file-input-specific). Verified two of the three links in the chain: a synthetic three-value
  logic test confirms the real Ashby input now passes, a plain honeypot text input with
  `tabindex="-1"` still gets caught, and an `aria-hidden="true"` file input still gets caught;
  separately curled `/scan/` with the real field's exact attributes and confirmed core maps it to
  `action: "upload"` with the CV's id. **Not verified**: whether Ashby's own file-drop handler
  actually accepts the programmatic `el.files = ...` + `change` event `applyFillPlan` sends — this
  is the first Ashby (react-dropzone-style) file input tested; every prior upload confirmation was
  Greenhouse. Needs a real Fill: no log line for this ref at all means the fix didn't take effect
  (reload the add-on); `no-file-data` means core/CV lookup failed; `ok` with no file actually
  showing in Ashby's dropzone UI means their handler didn't accept the synthetic event, which is a
  different, currently-unknown fix.

- **`findToggleControl` could click "Clear selections" instead of the dropdown toggle, wiping a
  pre-filled combobox** — got the real outerHTML of a live Greenhouse "My pronouns are:" widget
  (react-select-style, `role="combobox"` on the input, already showing a valid default of
  `(He, Him, His)`) after the user flagged that these dropdowns "need to choose, not just type."
  Its `.select__indicators` wrapper renders a `button[aria-label="Clear selections"]` *before*
  `button[aria-label="Toggle flyout"]` — `findToggleControl`'s old
  `control.querySelector('button, [role="button"], svg')` returns the first match in document
  order, which is Clear, not Toggle. Clicking Clear on a pre-filled field wipes its value; the
  code then waits 2s for a menu that never opens (Clear doesn't open one), falls through to the
  typing fallback, and usually recovers by typing+matching — but if `bestMatch` misses on that
  fallback, the field ends up **empty** instead of left at its original correct value, which is
  worse than doing nothing. Fixed by filtering candidates: for each clickable node, check its
  closest `button`/`[role="button"]` ancestor's `aria-label` (not the node's own — the icon `svg`
  inside the Clear button has no label of its own and would otherwise still pass, with its
  bubbled click still triggering the button's real handler) and skip anything matching `/clear/i`.
  Scoped to the one signal actually observed (`aria-label` text) rather than widening to a
  "prefer the last indicator" or "match toggle/open/dropdown" heuristic with no second markup
  sample to support it — a widget with an *unlabeled* clear control would still be exposed to
  this bug; needs another real sample to fix generally. React-select's ClearIndicator typically
  only renders once a value exists, so this most likely explains failures specifically on
  *pre-filled/defaulted* dropdown fields — plausible, not confirmed, as the likely cause of some
  of the still-unverified `no-matching-option` results logged in the KoBold combobox fix above.
  Not yet re-verified live — needs the user to re-test this field and report the per-ref log line
  (`ok` / `no-matching-option` / `dropdown-never-opened`) for `question_67944728`.

- **Cover-letter fields skipped when unlabeled, silently — root cause of "cover letter never
  attaches, résumé does"** — `_COVER_LETTER_KEYWORDS` only matched the literal phrase "cover
  letter" (a space required), while `_RESUME_KEYWORDS` matches single words with no such
  requirement — that asymmetry is exactly why résumé always worked and cover letter didn't. Real
  ATS file inputs routinely have no `<label for>`/`aria-label` (the visible "Cover Letter" text
  sits in an unassociated heading), so `field_haystack` falls back to `name`/`id`, which use
  `cover_letter`/`coverLetter`/`cover-letter` — none contain a literal space. Confirmed against
  real persisted data, not just synthesized: `Application` #27 (Databricks/Greenhouse,
  `gh_jid`-style embed) had `id: "cover_letter"`, `label: "Attach"` (a shared generic label) and
  a persisted `action: "skip"`; #32 (a separate Greenhouse posting) showed the same
  `0:cover_letter` ref skipped by both the heuristic and the LLM pass. Fixed by widening
  `_COVER_LETTER_KEYWORDS` to `("cover letter", "cover_letter", "cover-letter", "coverletter")`
  — deliberately *not* a general separator-normalizing rewrite of `field_haystack` (tried first,
  reverted: replacing `_`/`-` with spaces broke `_EMAIL_KEYWORDS`'s `"email"` against `"e-mail"`
  and would have broken `_LINKEDIN_KEYWORDS` against a hypothetical `"linked-in"` id — this fix
  is scoped to the one keyword list that needed it). Verified by patching the fix into the running
  `job-filler-core-1` container and replaying the exact #32 field through `build_fill_plan`: now
  resolves to `cover_letter_upload`. This also fully verifies "Scan hidden file inputs" further
  below — the previously-unverified Greenhouse case was this bug, not (only) a visibility gap.

## Done

- **EEO Settings answers routed through a dedicated AI pass instead of verbatim client-side
  matching** — the old `applyEeoSettings` client-side fill required the Settings answer text to
  literally substring-match a field's real option text (e.g. "i do not have any" never matched
  "No, I do not have a disability"), so real ATS EEO selects mostly stayed skipped. Changed the
  boundary from "core never sees EEO fields" to "AI never invents an EEO answer":
  `field_mapper.py` now marks EEO fields `eeo_pending` instead of `skip`;
  `ApplicationService._resolve_eeo` resolves that via new `agent/eeo_mapper.py`, one MiMo call
  whose prompt receives *only* the EEO fields and the user's `{match, answer}` rows (no CV text,
  no job posting text — nothing else to invent from), so it can normalize wording and disambiguate
  e.g. a "hispanic" row from a "race" row and pick the closest real `<select>` option. Extension
  now sends `eeoAnswers` as `eeo_answers` on the scan request; `applyEeoSettings` is kept as the
  client-side verbatim fallback for anything core still returns `skip` on. `_resolve_eeo` runs
  after the cover-letter step, not before `augment_skipped_fields`, so an `eeo_pending` field
  never becomes an `action: "skip"` candidate for the CV-grounded LLM pass. Reused
  `llm_mapper.validate_override` (renamed from `_validate_override`) for the new mapper instead
  of copying it, so the action-keyword-echo strip (`_ACTION_ECHO_RE`, from a prior live bug) isn't
  duplicated. Note: resolved EEO answers are now persisted in `Application.field_mapping` in
  SQLite like every other mapped field — they no longer stay entirely client-side. Verified via curl
  against the real MiMo API with a synthetic snapshot matching the actual Settings rows in use
  (gender/hispanic/race/veteran/disability): correct option picked for every native `<select>`,
  correct free-text normalization for a plain input, "hispanic: im asian" correctly resolved to
  "No" on a distinct ethnicity-question select rather than leaking into the race question, and
  all three negative cases confirmed skip (no relevant row, empty-answer row, no `eeo_answers` sent).
  `ruff check` + `manage.py check` clean, `web-ext lint` clean (same pre-existing warnings). Not
  yet re-verified against a real ATS page in a live browser. Known gap, unchanged: radio-rendered
  EEO questions still aren't handled by either path (`tasks/BACKLOG.md` item 8).

## Fixes

- **Checkbox-list questions (single choice rendered as separate `<input type="checkbox">`
  fields) silently never got checked** — a real Ashby form (Toggl) has a "which best describes
  your experience" question rendered as five independent checkbox inputs, each with the option
  text as its own label. `llm_mapper`'s system prompt only documented `"type"`/`"select"`
  actions, so MiMo had no correct action for a `type: "checkbox"` field and guessed `"select"`
  with the option's own label text as the value — `validate_override` let it through unvalidated
  (no `options` list to check against on a checkbox field), and `popup.js`'s fill routes a
  `"select"` action through `selectValue` regardless of element type, which types text into a
  checkbox input and looks for `[role="option"]` elements that don't exist there, so the checkbox
  was never actually checked. Confirmed by pulling the real `Application.form_snapshot` from
  SQLite for that scan and reproducing the exact bad response locally (`action: "select"`, value
  either the option's own label or the bare word `"select"`). Fixed by adding a `"check"` action
  to the prompt (checkbox fields must respond `check`+`"true"` or `skip`, never `check`+`"false"`
  — `popup.js`'s `el.checked = Boolean(item.value)` would treat any non-empty string, including
  `"false"`, as checked) and handling it in `validate_override` before the generic
  type/select path. Verified: re-ran the exact reproduction, `cb0` (the option the CV actually
  supports) now returns `check`/`true`, the other four correctly `skip`.
  Also investigated in the same pass, both against the real logged scan: (1) the same scan's four
  essay `<textarea>` fields all came back with the literal bare value `"type"` (already-correct
  behavior: `validate_override`'s existing bare-echo check turns this into `skip`) — reproduced
  the same batch of fields against the real CV twice outside the app and got full grounded
  answers both times, so this is genuine model flakiness on that one live call, not a code defect
  (matches the "stochastic prompt-echo" conclusion from the earlier single-field version of this
  same failure mode, now confirmed reproducible-but-intermittent rather than assumed). (2) the
  custom-combobox "Location" field (`role: combobox`, no scanned `options`) got a plausible
  CV-grounded value ("Astana, Kazakhstan") that then visibly sat in the input without being
  selected from the site's own dropdown — this is the documented `selectValue` typed-text
  fallback (`CLAUDE.md`), not a new bug; needs the popup's per-field log output
  (`ok`/`no-matching-option`/`dropdown-never-opened`) to tell which case it hit. (3) two Yes/No
  toggle questions on the same page never appeared in `form_snapshot` at all — not native
  radio/checkbox inputs, so invisible to `scanPage`'s scan, the same class of gap as
  `tasks/BACKLOG.md` item 8 (button/div-based widgets with no underlying form control); needs
  the real outerHTML before building a fix, not guessed at.

- **Click the dropdown's real toggle instead of guessing at click targets** — a real fill log
  showed every custom-combobox field on a react-select-based ATS (KoBold's Greenhouse-alternative
  form) failing with `no-matching-option`, while native `<select>` fields on the same page worked
  fine — not an EEO-specific bug, a mechanism bug affecting every non-native dropdown. Got the
  real markup this time (outerHTML of an open Gender field) instead of guessing a third
  heuristic: this widget has a dedicated toggle button (`aria-label="Toggle flyout"`, sibling of
  the input inside the `.select__control` wrapper) that opens the menu independent of focus, and
  no `aria-controls`/`aria-owns` on the input at all — meaning the old fallback's "click el/
  el.parentElement" never opened anything, and `findOptions`' document-wide fallback search could
  match stale `[role="option"]` elements left over from a previous field's widget, producing a
  false "options found" that then failed to match (`no-match`, not `no-options` — which is why
  the earlier single-screenshot diagnosis of "menu never opens" was wrong; the real problem was
  matching against the wrong menu). Fixed in `popup.js`: `findToggleControl` finds a button/
  `[role="button"]`/svg inside the nearest `[class*="control" i]` ancestor and `selectValue`
  clicks it *before* typing anything (typing-to-filter is now the fallback, not the first move);
  `findOptions` scopes to the menu sibling of that same control wrapper before ever falling back
  to a whole-document search. Also surfaced `no-options` (dropdown never opened at all) as a
  logged failure (`dropdown-never-opened`) instead of silently `ok: true`, so the next log can
  tell "never opened" apart from "opened, nothing matched" — worth keeping even after this is
  confirmed working. Not yet re-verified against the real page (inferred from static markup, not
  a live DOM interaction) — needs the user to re-test and send the log again. Separately: even
  with the menu correctly found, `bestMatch`'s exact/substring matching won't match a Settings
  answer like "i do not have any" against real option text like "No, I do not have a disability"
  — no fuzzy matching added for this (risk of silently picking the wrong option on a legally
  sensitive field is worse than leaving it skipped); the fix there is wording the Settings answer
  as a literal substring of the real option (e.g. "No, I do not").
- **Scan hidden file inputs** — a real Greenhouse "Cover Letter" upload widget ("Attach /
  Dropbox / Google Drive / Enter manually") never got the generated `.docx` because `scanPage`
  skipped it via the same `isVisible` check used for every field — file inputs are routinely
  styled `display:none` behind a custom button, which doesn't stop `el.files = ...` + a `change`
  event from working. `type === "file"` now bypasses the visibility check (honeypot/disabled
  checks still apply). Confirmed via real persisted data (`Application` #27/#32, see the
  cover-letter keyword fix above): the hidden file input was scanned and reached core fine — the
  remaining miss on that page was the keyword-matching bug, not this visibility gap.

- **Cover letter generator (.docx)** — any field matching "cover letter" (haystack: label/name/
  id/placeholder) now gets a real generated letter instead of being skipped or handed to the
  generic LLM pass. New `agent/cover_letter.py`: `generate()` makes one dedicated MiMo call per
  scan (separate from `llm_mapper`'s batch pass — a proper 250-400 word, three/four-paragraph
  letter needs its own prompt, not the general "concise 50-150 word" one), `render_docx()` builds
  the `.docx` via `python-docx` (already a dependency). `field_mapper.py` marks matching fields
  with placeholder actions (`cover_letter_type` for paste fields, `cover_letter_upload` for file
  fields) before the resume/profile checks run, so the general LLM pass never touches them (it
  only acts on `action: "skip"`). `ApplicationService._resolve_cover_letter` generates once and
  resolves both placeholders from the same text — a paste field becomes a plain `type` action, a
  file field becomes an `upload` action carrying the docx bytes inline as base64 in a new `file`
  field on the mapping item (no stored CV row behind it, unlike résumé upload) so the extension
  can attach it via the same `DataTransfer` path with no extra fetch. If MiMo is unconfigured or
  the generation call fails, both placeholders fall back to `skip` (never partially fill, never
  crash the scan — same guard pattern as `llm_mapper.augment_skipped_fields`). Verified via curl
  against a real CV: the file-upload field came back with a valid `.docx` (correct `PK` zip
  signature, ~37KB), the paste field came back with a 303-word, three-paragraph letter grounded
  in the actual CV/job-posting text, no bracketed placeholders. Not yet driven in a real browser.
  Note: the generated letter's text is persisted as part of the `Application` row's
  `field_mapping` in SQLite (not regenerated-and-discarded) — same as every other LLM answer.
- **Fix bare "type"/"select" value slipping past the echo-strip guard** — the earlier
  action-keyword-echo fix (`_ACTION_ECHO_RE`) only stripped a leading `"type "`/`"select "` when
  followed by real content; a value that was the bare word `"type"` with nothing after it (no
  `\s+` for the regex to match) passed through unchanged and got typed verbatim into several
  free-text fields on a real form ("How did you hear about this opportunity?", "please give
  date(s) and position(s)"). Fixed in `_validate_override`: after the regex strip, also skip if
  the remaining value is empty or exactly `"type"`/`"select"` case-insensitively. Verified via
  `_validate_override` directly: bare `"type"`/`"Type"`/`"select"` now skip, `"type Backend
  Developer"` still correctly reduces to `"Backend Developer"`, and real answers are untouched.
- **Scan/fill forms embedded in a cross-origin iframe** — a real Newton/gnewton career page
  ("View our Job Openings!") returned "Found 0 fields" because its actual form lives inside
  `<iframe id="gnewtonIframe">` on a different domain than the careers page, and `scanPage` only
  ever queried the top-level document. Confirmed via MDN before building (not guessed): Firefox's
  `activeTab` covers the top frame and same-origin frames only — a cross-origin iframe needs an
  explicit host permission — and `scripting.executeScript` with `allFrames: true` returns partial
  results for inaccessible frames in Firefox rather than rejecting the whole call (Chrome does
  reject; irrelevant here, this is Firefox-only). Added `optional_permissions: ["<all_urls>"]` to
  the manifest and a "Grant page access" button in Manage CVs (`browser.permissions.request`) —
  requested from the persistent tab, not the popup, since a native permission prompt steals focus
  and would close the panel popup the same way the file picker used to. `scanBtn` now injects with
  `allFrames: true`, merges every frame's `form_snapshot`, and prefixes each `ref` with its
  `frameId` (`popup.js`'s `refFrameMap`, persisted in `storage.session` alongside the scan) since a
  `data-jf-ref` value only resolves inside the frame it was stamped in; `fillBtn` groups the plan
  back by frame and runs `applyFillPlan` once per `frameIds: [n]` with the un-prefixed ref. The
  page-posting text sent to core now comes from whichever frame contributed the most fields, not
  always frame 0 — for an iframe-embedded ATS the posting text lives in that iframe too, not the
  wrapping page. `web-ext lint`: 0 errors (3 warnings — the 2 pre-existing plus a new
  Android-incompatibility notice for `permissions.request`, irrelevant to this desktop-only
  extension). Not yet re-verified against the real gnewton page (no live browser here) — still
  needs the user to grant access and re-scan. Known-not-fixed on that same page, seen in the
  screenshot but out of scope for this pass: its resume upload is a "Choose a File / Google
  Drive / Dropbox" widget, and the actual `<input type=file>` behind it is almost certainly
  `display:none` — `scanPage`'s `isVisible` check would skip it, so resume upload likely still
  won't work there without seeing that input's real markup.
- **Strip MiMo action-keyword echo from typed values** — a real fill showed a job-title field
  filled with the literal text "type Backend Developer" instead of "Backend Developer". Couldn't
  reproduce with isolated `_call_llm` test calls, consistent with a stochastic prompt-echo (the
  system prompt's "respond with "type" and a free-text answer" wording invites the model to
  occasionally fold the action word into the value string). Fixed defensively in
  `llm_mapper._validate_override`: strips a leading `type`/`select` echo from the value via regex
  before use, same "validate the model's output, don't trust prompt compliance" pattern as the
  existing select-option and travel-guess guards. Also added `logger.warning` of the raw MiMo
  response in `_call_llm` (WARNING, not INFO — this project has no custom `LOGGING` config, so
  only WARNING+ reaches `docker logs`) to make the next "field came out wrong" report diagnosable
  without guessing blind again. Same pass: `_LOGISTICS_KEYWORDS` gained "authorized/authorised to
  work", "work authorization/authorisation", "eligible to work" — a batch test surfaced the LLM
  confidently answering "Are you legally authorized to work in the US?" with "No" at confidence
  1.0 with zero CV basis, the same travel-guess failure mode on a field that's also a legal
  attestation. Verified: re-ran `_validate_override` with a synthetic echoed value (strips
  correctly) and confirmed `work_auth`-style fields are now excluded from the LLM call entirely.
- **Fill dropdowns by structure, not by upstream classification** — live testing on a real
  Greenhouse form showed EEO Settings answers landing as typed text inside a dropdown instead of
  a selected option, tripping the site's "please choose an option" JS validation. Root cause:
  `applyEeoSettings` decided `type` vs `select` from the scan snapshot's `role` attribute, which
  is `"combobox"` on some ATS widgets but not others (Workday-style ones use `aria-haspopup`,
  `aria-autocomplete="list"`, or bare `aria-controls` instead). Fixed in `popup.js`'s
  `applyFillPlan`: any `"type"` target is now checked against the live DOM
  (`isDropdownLike` — native `<select>`, `role="combobox"/"listbox"`, `aria-haspopup`,
  `aria-autocomplete="list"`, or `aria-controls`/`aria-owns`) and, if dropdown-like, routed
  through the same type-then-click-option path as `"select"`. `selectValue` also gained a
  fallback: if typing the value filters a react-select-style list down to zero options (or never
  opens one), it clears the input and opens the widget by focus + click instead, then matches
  against the unfiltered list — falling back to the typed text only if no option list appears at
  all either way. Not yet re-verified against the real form (no markup was available this pass,
  only the reported symptom) — still needs a live retest. Known-uncovered pattern, documented
  rather than guessed at: a dropdown built from a `<div>`/`<button>` trigger with no
  `input`/`select`/`textarea` in it at all (Ashby/Workday sometimes do this) is invisible to
  `scanPage`'s querySelector and has no fill path yet.
- **Heuristic field-mapping agent** — `core/src/agent/field_mapper.py` replaces the stub in
  `ApplicationService`. Matches a scanned field's label/name/id/placeholder against known
  categories (email, first/last/full name, phone, resume upload) using the CV's extracted
  profile, passed via a new `cv_id` on the scan request. `Application` now has a nullable `cv`
  FK recording which CV a scan used. Hard rules, not confidence thresholds: EEO/demographic
  fields (gender, ethnicity, veteran, disability) are always skipped regardless of profile data;
  unrecognized fields (job-specific questions, custom comboboxes we can't structurally detect
  yet) are skipped, never guessed. The extension's popup now lists/uploads CVs, sends the
  selected `cv_id` on scan, and — for `action: "upload"` — fetches the CV's file bytes from
  `GET /api/v1/cvs/{id}/file/` and attaches it to the file input via `DataTransfer` in the page.
  `web-ext lint` still clean. End-to-end verified: uploaded the real test CV, scanned the real
  Greenhouse fixture with that `cv_id`, and got back exactly the expected plan — correct
  name/email/phone, resume flagged for upload, and every EEO field plus every job-specific
  question (GitLab username, interview name preference, LinkedIn profile, location) correctly
  skipped rather than guessed.
- **CVs: upload + extraction** — `POST /api/v1/cvs/` (multipart `file`), `GET /api/v1/cvs/`,
  `GET /api/v1/cvs/{id}/file/`. Extracts raw text (`pypdf` for PDF, `python-docx` for `.docx`)
  and a profile (`core/src/agent/profile.py`: regex email/phone, name from the first non-empty
  line with a filename fallback). Verified against the real test CV
  (`CV_Sanzhar_Amanzholov.pdf`) — checked the actual extracted text *before* writing the name
  heuristic (first line is `"Sanzhar Amanzholov"`, so no filename fallback needed here), and
  confirmed by curl: uploaded it, got back the correct name/email/phone, then downloaded the
  stored file via `/file/` and diffed it byte-for-byte against the source PDF (identical — the
  text-extraction stream doesn't corrupt what gets saved).
- **Browser extension skeleton** — Manifest V3 for Firefox (`extension/manifest.json`), popup UI
  (`extension/src/popup/`). "Scan this page" injects a field-scanner into the active tab via
  `scripting.executeScript` (no persistent content script — only runs on a user click), which
  stamps every candidate input/select/textarea with `data-jf-ref`, resolves its label
  (`label[for]`, closest `<label>`, `aria-label`/`aria-labelledby`), and skips honeypot
  (`aria-hidden`/`tabindex="-1"`) and hidden fields. Posts the result to
  `/api/v1/applications/scan/`. "Fill application" injects a fill executor that sets values via
  the native property setter + dispatches `input`/`change` (required for React-controlled
  inputs) and reports per-field success/failure back to the popup log.
  `npx web-ext lint --source-dir extension` passes clean (0 errors/warnings/notices) — this
  included adding `data_collection_permissions` to the manifest, declared honestly
  (`personallyIdentifyingInfo`, `websiteContent` — sent only to the local `core` API, never to a
  third party). **Not driven in an actual browser** — no browser automation tool was available
  in this session; see the root README for manual test steps.
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

- **MiMo LLM pass + custom combobox filling** — `agent/llm_mapper.py` sends whatever the
  heuristic mapper skipped (minus EEO, legal attestations, and unanswerable-from-a-CV logistics
  questions — travel/relocation/salary/notice/visa/start-date, all hard pre-filtered, never sent
  to the model) to `mimo-v2.5` in one batched call per scan, grounded in the CV's raw text and
  the scanned page's text. A no-op (returns the heuristic plan unchanged) when `MIMO_API_KEY` is
  empty or the call fails — never crashes a scan. Native `<select>` answers are validated
  server-side against the field's real `options` list (exact, then substring match, else skip)
  so the model can't invent an option that doesn't exist. `popup.js`'s scan step now also sends
  `role`/`aria-haspopup`/`aria-controls` per field and the page's visible text, so the model can
  tell a custom JS combobox from a plain text input and has job-description context for
  open-ended questions. `applyFillPlan` is now `async` and fills sequentially (not
  `Promise.all`): a "select" on a non-native-`<select>` element types the value, polls (2s) for
  `[role="option"]` inside `aria-controls` (or the whole document), and clicks the best
  case-insensitive match — this is the actual mechanical fix for Greenhouse/Ashby-style
  comboboxes (School/Degree/Discipline, Country, etc.) that were previously always skipped.
  Verified: `ruff check` + `manage.py check` clean; live-called the real MiMo API (key confirmed
  live via `/v1/models`, `response_format: json_object` confirmed to return clean JSON); curled
  `/api/v1/applications/scan/` with a form snapshot built from the actual Canonical/Greenhouse
  fields in the user's screenshots (essay question, "willing to travel" select, country select,
  AI-use attestation select, gender select, a combobox-flagged school field) — essay answer
  correctly grounded in the real test CV's actual work history, country/school correctly
  answered from CV facts, gender/attestation correctly hard-skipped, and — after a live bug was
  caught and fixed (see below) — "willing to travel" correctly hard-skipped instead of the model
  confidently guessing "Yes". Combobox click-and-poll mechanics can only be confirmed in a real
  browser, not curl — not yet done.

- **EEO/demographic settings (user-declared, client-side only)** — a new Settings section on
  the Manage CVs page (`extension/src/manage/`) lets the user type their own answers to
  EEO/demographic questions (gender, race, veteran, disability status, etc.) once, as
  `{match, answer}` rows stored in `browser.storage.local`. This does **not** relax core's hard
  EEO skip rule — `field_mapper.py`/`llm_mapper.py` are untouched, core never sees these answers.
  `popup.js`'s `applyEeoSettings` applies them after core's plan comes back: for a field core
  left skipped, if the field's label/name/id/placeholder contains a row's `match` text, its
  `answer` is filled verbatim (matched against the field's real `<select>` options first,
  falling back to a plain "type" for text inputs and combobox role elements). An empty answer,
  or no matching row, leaves the field skipped exactly as before — the default is still "don't
  guess," this only adds a place for the user's own explicit statement. Also fixed a latent bug
  found while building this: `applyFillPlan`'s native-`<select>` handling did `el.value = value`
  assuming the mapper's chosen option *text* equals the option's `value` attribute — false
  whenever they differ (e.g. `<option value="US">United States</option>`), silently no-opping
  the fill. Now matches by visible text (reusing the same `bestMatch` combobox logic) and sets
  the real option's `.value`. Not yet driven in a real browser — `web-ext lint` clean.

## Fixes

- **MiMo confidently guessed "Yes" to an unanswerable question** — live-tested "are you willing
  to travel 2-4x/year?" (a preference question, not a CV fact) and the model answered "Yes" at
  confidence 1.0, ignoring the system prompt's explicit "skip if unknowable" instruction. A
  prompt cannot be trusted to self-police this category. Fixed by hard pre-filtering
  travel/relocation/salary/notice-period/visa/start-date questions out of the LLM call entirely
  (`agent/llm_mapper.py`'s `_LOGISTICS_KEYWORDS`), same mechanism as the EEO/attestation
  hard-skips — verified by re-running the same scan and confirming the field now comes back
  `action: "skip"`.
- **LinkedIn/GitHub/GitLab fields were always skipped even when answerable** — `profile.py`
  never extracted those URLs from CV text, so `field_mapper.py` had no data to offer even for
  a plain text field it could otherwise fill. Added regex extraction (`linkedin_url`, `git_url`)
  alongside the existing email/phone/name extraction, threaded through the `Cv` model → DTO →
  repository → service → serializer the same way those fields are. Verified against the real
  test CV: uploaded it, confirmed the API response includes both URLs, then scanned a synthetic
  form with "LinkedIn Profile"/"Github/Gitlab Account"/"Website" fields — the first two filled
  correctly, "Website" and a gender select still correctly skipped (no CV-derivable answer /
  EEO rule). Most other unfilled fields reported by the user (custom Greenhouse comboboxes,
  free-text essay questions) are the known gaps in `tasks/BACKLOG.md` items 1 and 7, not bugs.

- **Upload CV closed the popup, and a scan was lost on every popup close** — two separate
  bugs, same root cause of "the popup is a fragile, disposable document." (1) Clicking a hidden
  file input's `.click()` from inside a panel popup opens a native file picker, which steals
  focus and closes the popup before a selection can complete — a longstanding Firefox
  limitation, made 100% reproducible here because Flatpak Firefox/Zen brokers that picker
  through a separate `xdg-desktop-portal` process. Fixed by moving CV upload/listing to its own
  persistent extension page (`extension/src/manage/`), opened via `browser.tabs.create` from a
  "Manage CVs" button — `tabs.create` to the extension's own page needs no extra permission.
  (2) The popup document (and all its JS state, including the last scan's `field_mapping`) is
  destroyed and recreated every time it closes — a scan and a subsequent Fill had to happen in
  one uninterrupted popup session. Fixed with `storage.session` (new `storage` permission),
  keyed per-tab and checked against the tab's current URL before restoring, so reopening the
  popup on the same page brings back the last scan instead of starting over.

- **Popup appeared blank in the browser** — root cause was a Flatpak sandbox, not CSS. Zen on
  Linux is commonly installed via Flatpak, which only grants filesystem access to whatever the
  file-picker portal was pointed at. "Load Temporary Add-on…" reads `manifest.json` through that
  portal, so the extension shows as loaded with no error, but every sibling file (`popup.html`,
  `popup.js`, `popup.css`) is outside the sandbox and resolves to an empty document — confirmed
  via the Inspector showing a bodyless `<html><head></head><body></body></html>` for
  `popup.html` loaded directly as a tab. Fixed by granting the project directory:
  `flatpak override --user --filesystem=/path/to/job-filler app.zen_browser.zen`, then fully
  quitting Zen and re-loading the extension (a plain Reload doesn't re-apply the new grant). An
  earlier attempt made `popup.css` colors explicit instead of inherited — harmless, kept, but it
  was not the actual fix; noted here so the wrong diagnosis isn't repeated.
- **Fresh-clone quick start was broken** — `SECRET_KEY` has no default (`manage.py migrate`
  crashes with no `.env`), and `DATA_DIR` (holding `db.sqlite3`) was never created — SQLite
  doesn't create parent directories. README now says to `cp .env.example .env`; settings.py
  creates `DATA_DIR` on startup. Verified by actually cloning the repo into a scratch directory
  and following the README's backend steps verbatim (not just re-running in the already-set-up
  working tree).
- **Extension resume upload would have attached garbage** — `scripting.executeScript` args must
  be JSON-serializable; the raw `ArrayBuffer` fetched for the CV file wouldn't have survived
  that trip intact. Now base64-encoded in the popup, decoded back to bytes in the injected fill
  function before building the `File`.
- **`core/.dockerignore` wasn't excluding `src/data/`** — its bare patterns (`db.sqlite3`,
  `media`) didn't match that nested path, so a locally-migrated dev database got baked into the
  Docker image, making a brand-new named volume look already-migrated ("No migrations to apply"
  on a supposedly clean container — Docker seeds a new empty volume from the image's existing
  directory content). Found by inspecting the built image's filesystem directly, not by trusting
  a 200 from `/health/`. Fixed with an explicit `src/data` entry and re-verified against a
  genuinely fresh volume (`docker volume rm` + `docker compose up`) — migrations applied this
  time.
