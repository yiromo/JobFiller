const CORE_URL = "http://localhost:8000";

const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const scanBtn = document.getElementById("scan-btn");
const fillBtn = document.getElementById("fill-btn");
const cvSelect = document.getElementById("cv-select");
const manageCvsBtn = document.getElementById("manage-cvs-btn");

let lastFieldMapping = null;
let refFrameMap = {};
let cvsCache = [];

function log(message) {
  logEl.textContent += `${message}\n`;
}

function setStatus(message) {
  statusEl.textContent = message;
}

// Runs inside the page, injected via scripting.executeScript — cannot
// reference anything from popup.js's scope.
function scanPage() {
  let refCounter = 0;

  function isVisible(el) {
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && el.offsetParent !== null;
  }

  // Honeypot traps (e.g. Greenhouse's bot-catcher inputs) are hidden from
  // real users but present in the DOM — never fill these.
  function isHoneypot(el) {
    return el.getAttribute("aria-hidden") === "true" || el.tabIndex === -1;
  }

  function resolveLabel(el) {
    if (el.id) {
      const byFor = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (byFor && byFor.textContent.trim()) return byFor.textContent.trim();
    }
    const closestLabel = el.closest("label");
    if (closestLabel && closestLabel.textContent.trim()) return closestLabel.textContent.trim();
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel) return ariaLabel;
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const text = labelledBy
        .split(" ")
        .map((id) => document.getElementById(id)?.textContent?.trim())
        .filter(Boolean)
        .join(" ");
      if (text) return text;
    }
    return "";
  }

  const fields = [];
  document.querySelectorAll("input, select, textarea").forEach((el) => {
    // File inputs are routinely styled hidden behind a custom "Attach"/"Choose
    // a File" button — the input itself still works via el.files + a change
    // event regardless of CSS visibility, so don't skip it for that reason.
    if (isHoneypot(el) || el.disabled) return;
    if (el.type !== "file" && !isVisible(el)) return;
    if (["hidden", "submit", "button", "image"].includes(el.type)) return;

    const ref = el.id || `jf-${refCounter++}`;
    el.setAttribute("data-jf-ref", ref);

    fields.push({
      ref,
      tag: el.tagName.toLowerCase(),
      type: el.type || "",
      name: el.name || "",
      id: el.id || "",
      label: resolveLabel(el),
      placeholder: el.placeholder || "",
      options: el.tagName === "SELECT" ? Array.from(el.options).map((o) => o.textContent.trim()) : [],
      required: el.required || el.getAttribute("aria-required") === "true",
      // role/aria-haspopup/aria-controls are what distinguish a custom JS
      // combobox (Greenhouse/Ashby style) from a plain text input — a native
      // <select> is already identified by `tag`.
      role: el.getAttribute("role") || "",
      aria_haspopup: el.getAttribute("aria-haspopup") || "",
      aria_controls: el.getAttribute("aria-controls") || "",
    });
  });

  // Truncated: only meant to give the LLM job-posting context for open-ended
  // questions, not to reproduce the page.
  return {
    url: window.location.href,
    form_snapshot: fields,
    page_text: document.body.innerText.slice(0, 15000),
  };
}

// Runs inside the page. `plan` is the field_mapping array core returned;
// `fileByRef` maps a ref to { base64, filename, mimeType } for
// any "upload" actions — fetched by popup.js beforehand, since content
// scripts can't reliably reach the core API without extra host permissions.
//
// Must be async: filling a custom combobox (Greenhouse/Ashby style) requires
// typing into it and waiting for its JS-rendered option list to appear.
// scripting.executeScript awaits a returned Promise and resolves to its
// settled value, so this works the same as the old synchronous version did.
async function applyFillPlan(plan, fileByRef) {
  const nativeInputSetter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value",
  ).set;
  const nativeTextareaSetter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    "value",
  ).set;

  // React (and most SPA frameworks) tracks value changes through its own
  // event system, not the DOM property — setting `el.value` directly is
  // invisible to it. Calling the native setter first, then dispatching the
  // events React listens for, makes the framework pick up the change.
  function setValue(el, value) {
    const setter = el.tagName === "TEXTAREA" ? nativeTextareaSetter : nativeInputSetter;
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function clickOption(optionEl) {
    for (const type of ["pointerdown", "mousedown", "mouseup", "click"]) {
      optionEl.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true }));
    }
  }

  // Without aria-controls/aria-owns (react-select-style widgets often set
  // neither), scope to the menu that's actually a sibling of this field's
  // control wrapper — searching the whole document risks matching stale
  // `[role="option"]` elements left open from a previous field.
  function findOptions(el) {
    const controlsId = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
    if (controlsId) {
      const container = document.getElementById(controlsId);
      if (container) return Array.from(container.querySelectorAll('[role="option"]'));
    }
    const control = el.closest('[class*="control" i]');
    if (control?.parentElement) {
      const found = Array.from(control.parentElement.querySelectorAll('[role="option"]'));
      if (found.length) return found;
    }
    return Array.from(document.querySelectorAll('[role="option"]'));
  }

  // react-select-style widgets render a dedicated toggle (an icon/button
  // sibling of the text input, inside the same control wrapper) that opens
  // the menu independent of focus — clicking the input itself doesn't
  // always do it.
  function findToggleControl(el) {
    const control = el.closest('[class*="control" i]');
    return control ? control.querySelector('button, [role="button"], svg') : null;
  }

  function bestMatch(options, value) {
    const target = value.trim().toLowerCase();
    return (
      options.find((o) => o.textContent.trim().toLowerCase() === target) ||
      options.find((o) => o.textContent.trim().toLowerCase().includes(target)) ||
      null
    );
  }

  async function waitFor(predicate, timeoutMs = 2000, intervalMs = 100) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const result = predicate();
      if (result) return result;
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    return null;
  }

  // Different ATSs mark up dropdowns differently (role="combobox", just
  // aria-haspopup, aria-autocomplete="list", or only aria-controls pointing
  // at a listbox) — checking the live element at fill time catches patterns
  // the scan-time classifier (core, EEO settings) may have guessed wrong on.
  function isDropdownLike(el) {
    if (el.tagName === "SELECT") return true;
    const role = (el.getAttribute("role") || "").toLowerCase();
    if (role === "combobox" || role === "listbox") return true;
    const haspopup = (el.getAttribute("aria-haspopup") || "").toLowerCase();
    if (haspopup === "listbox" || haspopup === "true") return true;
    if (el.getAttribute("aria-autocomplete") === "list") return true;
    if (el.getAttribute("aria-controls") || el.getAttribute("aria-owns")) return true;
    return false;
  }

  // A native <select>'s options are real DOM nodes with fixed values — no
  // typing or waiting needed. A custom combobox (role="combobox", not a real
  // <select>) has to be driven like a user would: type into it, wait for its
  // async-rendered option list, then click the matching option.
  //
  // Returns "selected" (an option was clicked), "no-match" (an option list
  // appeared but nothing matched the value), or "no-options" (no widget ever
  // opened — either isDropdownLike false-positived on a plain input, or the
  // widget needs a different trigger than typing/click; the typed value is
  // left in place either way, same as a plain "type" would have done).
  async function selectValue(el, value) {
    if (el.tagName === "SELECT") {
      // `value` is the option's visible text (what core/settings matched
      // against) — not necessarily its `value` attribute (e.g.
      // <option value="US">United States</option>), so `el.value = value`
      // silently no-ops whenever those differ. Match by text, set by the
      // real option's `.value`.
      const match = bestMatch(Array.from(el.options), value);
      if (!match) return "no-match";
      el.value = match.value;
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return "selected";
    }

    // Open first, before typing anything: a dedicated toggle (if one exists)
    // reveals the real unfiltered option list, which is both a more reliable
    // trigger than typing and avoids filtering a search-as-you-type list down
    // to zero matches on a short/loosely-worded value.
    el.focus();
    const toggle = findToggleControl(el);
    if (toggle) clickOption(toggle);

    let options = await waitFor(() => {
      const found = findOptions(el);
      return found.length > 0 ? found : null;
    });

    if (!options) {
      setValue(el, value);
      options = await waitFor(() => {
        const found = findOptions(el);
        return found.length > 0 ? found : null;
      });
      if (!options) {
        setValue(el, value);
        return "no-options";
      }
    }

    const match = bestMatch(options, value);
    if (!match) {
      setValue(el, value);
      return "no-match";
    }
    clickOption(match);
    return "selected";
  }

  function outcomeResult(ref, outcome) {
    if (outcome === "selected") return { ref, ok: true };
    if (outcome === "no-match") return { ref, ok: false, reason: "no-matching-option" };
    return { ref, ok: false, reason: "dropdown-never-opened" };
  }

  const results = [];
  // Sequential, not parallel: opening one combobox's option list can close
  // another's, so fills must happen one at a time.
  for (const item of plan) {
    const el = document.querySelector(`[data-jf-ref="${CSS.escape(item.ref)}"]`);
    if (!el) {
      results.push({ ref: item.ref, ok: false, reason: "not-found" });
      continue;
    }

    try {
      switch (item.action) {
        case "type":
          if (isDropdownLike(el)) {
            results.push(outcomeResult(item.ref, await selectValue(el, item.value)));
          } else {
            setValue(el, item.value);
            results.push({ ref: item.ref, ok: true });
          }
          break;
        case "select":
          results.push(outcomeResult(item.ref, await selectValue(el, item.value)));
          break;
        case "check":
          el.checked = Boolean(item.value);
          el.dispatchEvent(new Event("change", { bubbles: true }));
          results.push({ ref: item.ref, ok: true });
          break;
        case "upload": {
          const fileInfo = fileByRef[item.ref];
          if (!fileInfo) {
            results.push({ ref: item.ref, ok: false, reason: "no-file-data" });
            break;
          }
          // scripting.executeScript args must be JSON-serializable — an
          // ArrayBuffer wouldn't survive the trip, so the bytes travel as
          // base64 and get decoded back here.
          const binary = atob(fileInfo.base64);
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
          const file = new File([bytes], fileInfo.filename, { type: fileInfo.mimeType });
          const transfer = new DataTransfer();
          transfer.items.add(file);
          el.files = transfer.files;
          el.dispatchEvent(new Event("change", { bubbles: true }));
          results.push({ ref: item.ref, ok: true });
          break;
        }
        case "skip":
          results.push({ ref: item.ref, ok: true, reason: "skipped" });
          break;
        default:
          results.push({ ref: item.ref, ok: false, reason: `unsupported-action:${item.action}` });
      }
    } catch (err) {
      results.push({ ref: item.ref, ok: false, reason: String(err) });
    }
  }
  return results;
}

async function loadEeoSettings() {
  const stored = await browser.storage.local.get("eeoAnswers");
  return (stored.eeoAnswers || []).filter((row) => row.match && row.answer);
}

function bestOptionMatch(options, value) {
  const target = value.trim().toLowerCase();
  return (
    options.find((o) => o.trim().toLowerCase() === target) ||
    options.find((o) => o.trim().toLowerCase().includes(target)) ||
    null
  );
}

function applyEeoSettings(formSnapshot, fieldMapping, eeoSettings) {
  if (!eeoSettings.length) return fieldMapping;
  const fieldsByRef = Object.fromEntries(formSnapshot.map((f) => [f.ref, f]));
  let filled = 0;
  let unmatched = 0;

  const result = fieldMapping.map((mapping) => {
    if (mapping.action !== "skip") return mapping;
    const field = fieldsByRef[mapping.ref];
    if (!field) return mapping;

    const haystack = [field.label, field.name, field.id, field.placeholder]
      .join(" ")
      .toLowerCase();
    const setting = eeoSettings.find((row) => haystack.includes(row.match.toLowerCase()));
    if (!setting) return mapping;

    if (field.tag === "select" && field.options.length) {
      const match = bestOptionMatch(field.options, setting.answer);
      if (!match) {
        unmatched++;
        return mapping;
      }
      filled++;
      return { ref: mapping.ref, value: match, action: "select", confidence: 1 };
    }

    filled++;
    const action = field.role === "combobox" ? "select" : "type";
    return { ref: mapping.ref, value: setting.answer, action, confidence: 1 };
  });

  if (filled) log(`Filled ${filled} field(s) from your Settings answers.`);
  if (unmatched) {
    log(`${unmatched} Settings answer(s) matched a field but not any of its options — adjust`);
    log(`  the answer's wording in Manage CVs > Settings to match this site.`);
  }
  return result;
}

async function getActiveTab() {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  return tab;
}

// The popup document is destroyed and recreated every time it closes, so any
// in-memory state (lastFieldMapping) is normally lost between opens.
// storage.session keeps the last scan per tab, cleared on browser restart —
// it's tied to the page's live DOM refs, which don't survive that anyway.
function scanStorageKey(tabId) {
  return `scan:${tabId}`;
}

async function saveScanState(tabId, url) {
  await browser.storage.session.set({
    [scanStorageKey(tabId)]: {
      url,
      fieldMapping: lastFieldMapping,
      refFrameMap,
      logText: logEl.textContent,
    },
  });
}

async function restoreScanState() {
  const tab = await getActiveTab();
  if (!tab) return;
  const key = scanStorageKey(tab.id);
  const stored = await browser.storage.session.get(key);
  const entry = stored[key];
  if (!entry || entry.url !== tab.url) return;

  lastFieldMapping = entry.fieldMapping;
  refFrameMap = entry.refFrameMap || {};
  logEl.textContent = entry.logText || "";
  fillBtn.disabled = false;
  setStatus("Restored previous scan — review, then Fill.");
}

function arrayBufferToBase64(buffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function guessMimeType(filename) {
  if (filename.endsWith(".pdf")) return "application/pdf";
  if (filename.endsWith(".docx")) {
    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  }
  return "application/octet-stream";
}

async function loadCvs(selectId) {
  const response = await fetch(`${CORE_URL}/api/v1/cvs/`);
  if (!response.ok) throw new Error(`core returned ${response.status}`);
  cvsCache = await response.json();

  cvSelect.innerHTML = '<option value="">No CV selected</option>';
  for (const cv of cvsCache) {
    const option = document.createElement("option");
    option.value = String(cv.id);
    option.textContent = `${cv.full_name || cv.original_filename} — ${cv.original_filename}`;
    cvSelect.appendChild(option);
  }
  if (selectId) cvSelect.value = String(selectId);
}

// Fetches the file bytes for every "upload" action in the plan, keyed by ref,
// so applyFillPlan (running in the page) can attach them via DataTransfer.
async function buildFileMap(plan) {
  const fileByRef = {};
  for (const item of plan) {
    if (item.action !== "upload") continue;
    if (item.file) {
      fileByRef[item.ref] = {
        base64: item.file.base64,
        filename: item.file.filename,
        mimeType: item.file.mime_type,
      };
      continue;
    }
    const cv = cvsCache.find((c) => String(c.id) === item.value);
    if (!cv) continue;
    const response = await fetch(`${CORE_URL}/api/v1/cvs/${cv.id}/file/`);
    if (!response.ok) continue;
    fileByRef[item.ref] = {
      base64: arrayBufferToBase64(await response.arrayBuffer()),
      filename: cv.original_filename,
      mimeType: guessMimeType(cv.original_filename),
    };
  }
  return fileByRef;
}

// File pickers opened from a panel popup steal focus and close it before a
// selection completes (worse still under a Flatpak browser, where the
// picker is a separate portal process) — CV upload lives on its own
// extension tab instead, which doesn't close on focus loss.
manageCvsBtn.addEventListener("click", () => {
  browser.tabs.create({ url: browser.runtime.getURL("src/manage/manage.html") });
});

scanBtn.addEventListener("click", async () => {
  setStatus("Scanning...");
  fillBtn.disabled = true;
  lastFieldMapping = null;
  refFrameMap = {};

  try {
    const tab = await getActiveTab();
    // allFrames catches ATS forms embedded in a cross-origin iframe (e.g.
    // Newton/gnewton career pages) — Firefox returns partial results for
    // frames we lack permission for instead of rejecting the whole call, so
    // this is safe even before the user grants <all_urls> in Manage CVs.
    const injectionResults = await browser.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: scanPage,
    });

    const framesWithFields = injectionResults.filter(
      (r) => r.result && r.result.form_snapshot.length > 0,
    );
    const bestFrame = framesWithFields.reduce(
      (best, r) =>
        !best || r.result.form_snapshot.length > best.result.form_snapshot.length ? r : best,
      null,
    );

    const formSnapshot = [];
    for (const { frameId, result } of framesWithFields) {
      for (const field of result.form_snapshot) {
        const ref = `${frameId}:${field.ref}`;
        refFrameMap[ref] = { frameId, localRef: field.ref };
        formSnapshot.push({ ...field, ref });
      }
    }
    log(`Found ${formSnapshot.length} fields across ${framesWithFields.length} frame(s).`);

    if (formSnapshot.length === 0 && injectionResults.length <= 1) {
      const hasAllUrls = await browser.permissions.contains({ origins: ["<all_urls>"] });
      if (!hasAllUrls) {
        log("No embedded-frame access yet — if this form loads inside an iframe, grant");
        log("  access in Manage CVs > Page access, then scan again.");
      }
    }

    const cvId = cvSelect.value ? Number(cvSelect.value) : null;
    const eeoSettings = await loadEeoSettings();
    const response = await fetch(`${CORE_URL}/api/v1/applications/scan/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: tab.url,
        page_text: bestFrame ? bestFrame.result.page_text : "",
        form_snapshot: formSnapshot,
        cv_id: cvId,
        eeo_answers: eeoSettings,
      }),
    });
    if (!response.ok) throw new Error(`core returned ${response.status}`);

    const data = await response.json();
    lastFieldMapping = applyEeoSettings(formSnapshot, data.field_mapping, eeoSettings);
    const skipped = lastFieldMapping.filter((f) => f.action === "skip").length;
    log(`Fill plan ready: ${lastFieldMapping.length - skipped} to fill, ${skipped} skipped.`);
    setStatus("Scanned — review, then Fill.");
    fillBtn.disabled = false;
    await saveScanState(tab.id, tab.url);
  } catch (err) {
    setStatus("Scan failed.");
    log(String(err));
  }
});

fillBtn.addEventListener("click", async () => {
  if (!lastFieldMapping) return;
  setStatus("Filling...");

  try {
    const fileByRef = await buildFileMap(lastFieldMapping);
    const tab = await getActiveTab();

    // Each field's ref only resolves inside the frame it was scanned from —
    // group by frame and translate back to the un-prefixed ref that's
    // actually stamped on the element there.
    const itemsByFrame = new Map();
    for (const item of lastFieldMapping) {
      const info = refFrameMap[item.ref] || { frameId: 0, localRef: item.ref };
      if (!itemsByFrame.has(info.frameId)) itemsByFrame.set(info.frameId, []);
      itemsByFrame.get(info.frameId).push({ ...item, ref: info.localRef, globalRef: item.ref });
    }

    const allResults = [];
    for (const [frameId, items] of itemsByFrame) {
      const localFileByRef = {};
      for (const item of items) {
        if (fileByRef[item.globalRef]) localFileByRef[item.ref] = fileByRef[item.globalRef];
      }
      const plan = items.map(({ ref, value, action, confidence }) => ({
        ref,
        value,
        action,
        confidence,
      }));
      const [{ result }] = await browser.scripting.executeScript({
        target: { tabId: tab.id, frameIds: [frameId] },
        func: applyFillPlan,
        args: [plan, localFileByRef],
      });
      allResults.push(...result.map((r) => ({ ...r, frameId })));
    }

    const failed = allResults.filter((r) => !r.ok);
    log(`Filled ${allResults.length - failed.length}/${allResults.length}.`);
    failed.forEach((r) => log(`  frame ${r.frameId} / ${r.ref}: ${r.reason}`));
    setStatus("Done — review before submitting.");
  } catch (err) {
    setStatus("Fill failed.");
    log(String(err));
  }
});

loadCvs().catch((err) => {
  setStatus("Could not reach core API.");
  log(String(err));
});
restoreScanState();
