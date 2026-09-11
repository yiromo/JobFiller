const CORE_URL = "http://localhost:8000";

const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const scanBtn = document.getElementById("scan-btn");
const fillBtn = document.getElementById("fill-btn");
const cvSelect = document.getElementById("cv-select");
const manageCvsBtn = document.getElementById("manage-cvs-btn");

let lastFieldMapping = null;
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
    if (isHoneypot(el) || !isVisible(el) || el.disabled) return;
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
    });
  });

  return { url: window.location.href, form_snapshot: fields };
}

// Runs inside the page. `plan` is the field_mapping array core returned;
// `fileByRef` maps a ref to { base64, filename, mimeType } for
// any "upload" actions — fetched by popup.js beforehand, since content
// scripts can't reliably reach the core API without extra host permissions.
function applyFillPlan(plan, fileByRef) {
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

  return plan.map((item) => {
    const el = document.querySelector(`[data-jf-ref="${CSS.escape(item.ref)}"]`);
    if (!el) return { ref: item.ref, ok: false, reason: "not-found" };

    try {
      switch (item.action) {
        case "type":
          setValue(el, item.value);
          return { ref: item.ref, ok: true };
        case "select":
          if (el.tagName !== "SELECT") {
            return { ref: item.ref, ok: false, reason: "not-a-native-select" };
          }
          el.value = item.value;
          el.dispatchEvent(new Event("change", { bubbles: true }));
          return { ref: item.ref, ok: true };
        case "check":
          el.checked = Boolean(item.value);
          el.dispatchEvent(new Event("change", { bubbles: true }));
          return { ref: item.ref, ok: true };
        case "upload": {
          const fileInfo = fileByRef[item.ref];
          if (!fileInfo) return { ref: item.ref, ok: false, reason: "no-file-data" };
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
          return { ref: item.ref, ok: true };
        }
        case "skip":
          return { ref: item.ref, ok: true, reason: "skipped" };
        default:
          return { ref: item.ref, ok: false, reason: `unsupported-action:${item.action}` };
      }
    } catch (err) {
      return { ref: item.ref, ok: false, reason: String(err) };
    }
  });
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
    [scanStorageKey(tabId)]: { url, fieldMapping: lastFieldMapping, logText: logEl.textContent },
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

  try {
    const tab = await getActiveTab();
    const [{ result }] = await browser.scripting.executeScript({
      target: { tabId: tab.id },
      func: scanPage,
    });
    log(`Found ${result.form_snapshot.length} fields.`);

    const cvId = cvSelect.value ? Number(cvSelect.value) : null;
    const response = await fetch(`${CORE_URL}/api/v1/applications/scan/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...result, cv_id: cvId }),
    });
    if (!response.ok) throw new Error(`core returned ${response.status}`);

    const data = await response.json();
    lastFieldMapping = data.field_mapping;
    const skipped = lastFieldMapping.filter((f) => f.action === "skip").length;
    log(`Fill plan ready: ${lastFieldMapping.length - skipped} to fill, ${skipped} skipped.`);
    setStatus("Scanned — review, then Fill.");
    fillBtn.disabled = false;
    await saveScanState(tab.id, result.url);
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
    const [{ result }] = await browser.scripting.executeScript({
      target: { tabId: tab.id },
      func: applyFillPlan,
      args: [lastFieldMapping, fileByRef],
    });
    const failed = result.filter((r) => !r.ok);
    log(`Filled ${result.length - failed.length}/${result.length}.`);
    failed.forEach((r) => log(`  ${r.ref}: ${r.reason}`));
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
