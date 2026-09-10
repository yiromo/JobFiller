const CORE_URL = "http://localhost:8000";

const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const scanBtn = document.getElementById("scan-btn");
const fillBtn = document.getElementById("fill-btn");

let lastFieldMapping = null;

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

// Runs inside the page. `plan` is the field_mapping array core returned.
function applyFillPlan(plan) {
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

    const response = await fetch(`${CORE_URL}/api/v1/applications/scan/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(result),
    });
    if (!response.ok) throw new Error(`core returned ${response.status}`);

    const data = await response.json();
    lastFieldMapping = data.field_mapping;
    const skipped = lastFieldMapping.filter((f) => f.action === "skip").length;
    log(`Fill plan ready: ${lastFieldMapping.length - skipped} to fill, ${skipped} skipped.`);
    setStatus("Scanned — review, then Fill.");
    fillBtn.disabled = false;
  } catch (err) {
    setStatus("Scan failed.");
    log(String(err));
  }
});

fillBtn.addEventListener("click", async () => {
  if (!lastFieldMapping) return;
  setStatus("Filling...");

  try {
    const tab = await getActiveTab();
    const [{ result }] = await browser.scripting.executeScript({
      target: { tabId: tab.id },
      func: applyFillPlan,
      args: [lastFieldMapping],
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
