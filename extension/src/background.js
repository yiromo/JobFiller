const CORE_URL = "http://localhost:8000";

const JF_VERSION = `${browser.runtime.getManifest().version}-${JF_BUILD}`;

function logBg(action, details) {
  const parts = details
    ? Object.entries(details)
        .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
        .join(" ")
    : "";
  console.info(`[JobFiller ${JF_VERSION}] ${action}${parts ? ` ${parts}` : ""}`);
}

logBg("BACKGROUND_LOADED");

// Runs inside the page, injected via scripting.executeScript — cannot
// reference anything from this file's scope.
function scanPage(scanId) {
  let refCounter = 0;

  function isVisible(el) {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 || rect.height > 0 || el.offsetParent !== null;
  }

  // Honeypot traps are hidden from users but in the DOM; file inputs legitimately use
  // tabindex=-1 behind a styled upload button.
  function isHoneypot(el) {
    if (el.getAttribute("aria-hidden") === "true") return true;
    return el.type !== "file" && el.tabIndex === -1;
  }

  const CONTROL_SELECTOR =
    "input, select, textarea, [role='radio'], [role='combobox'], [role='checkbox']";

  const HIDDEN_SELECTOR =
    '[aria-hidden="true"], [data-testid*="screen-reader" i], .sr-only, .visually-hidden';

  const GENERIC_NAMES = new Set([
    "search",
    "select",
    "choose",
    "please select",
    "textbox",
    "combobox",
    "listbox",
    "dropdown",
    "option",
  ]);

  function cleanName(text) {
    const trimmed = (text || "").replace(/\s+/g, " ").trim();
    const bare = trimmed
      .replace(/[…:*]+$/, "")
      .replace(/\.{2,}$/, "")
      .trim();
    if (!bare || GENERIC_NAMES.has(bare.toLowerCase())) return "";
    return trimmed;
  }

  function resolveLabel(el) {
    if (el.id) {
      const byFor = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      const name = cleanName(byFor?.textContent);
      if (name) return name;
    }
    const closestLabel = cleanName(el.closest("label")?.textContent);
    if (closestLabel) return closestLabel;
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const name = cleanName(
        labelledBy
          .split(" ")
          .map((id) => document.getElementById(id)?.textContent?.trim())
          .filter(Boolean)
          .join(" "),
      );
      if (name) return name;
    }
    return cleanName(el.getAttribute("aria-label"));
  }

  function isRenderedBox(el) {
    const rect = el.getBoundingClientRect();
    return rect.width > 1 && rect.height > 1;
  }

  function overlaps(a, b) {
    const r1 = a.getBoundingClientRect();
    const r2 = b.getBoundingClientRect();
    return r1.left < r2.right && r2.left < r1.right && r1.top < r2.bottom && r2.top < r1.bottom;
  }

  function resolveSection(el) {
    let node = el;
    for (let depth = 0; depth < 8 && node && node !== document.body; depth++) {
      if (node.tagName === "FORM" || node.getAttribute?.("role") === "form") break;
      for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) {
        if (sib.matches(CONTROL_SELECTOR) || sib.querySelector(CONTROL_SELECTOR)) continue;
        if (sib.matches(HIDDEN_SELECTOR) || !isRenderedBox(sib)) continue;
        if (overlaps(sib, el)) continue;
        const text = (sib.innerText || "").replace(/\s+/g, " ").trim();
        if (text && text.length <= 200) return text;
        if (text) break;
      }
      node = node.parentElement;
    }
    return "";
  }

  function isShown(el) {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function scanRoots() {
    const tiers = [
      { selector: '[aria-modal="true"]', minControls: 1 },
      { selector: "dialog[open]", minControls: 1 },
      { selector: '[role="dialog"]', minControls: 2 },
    ];
    for (const { selector, minControls } of tiers) {
      const open = Array.from(document.querySelectorAll(selector)).filter(isShown);
      const outermost = open.filter((el) => !open.some((o) => o !== el && o.contains(el)));
      const withControls = outermost.filter(
        (root) => root.querySelectorAll("input, select, textarea").length,
      );
      const total = withControls.reduce(
        (n, root) => n + root.querySelectorAll("input, select, textarea").length,
        0,
      );
      if (withControls.length && total >= minControls) return withControls;
    }
    return [document];
  }

  const candidates = [];
  const seen = new Set();
  scanRoots().forEach((root) => {
    root.querySelectorAll("input, select, textarea").forEach((el) => {
      if (seen.has(el)) return;
      seen.add(el);
      candidates.push(el);
    });
  });

  const fields = [];
  candidates.forEach((el) => {
    // File inputs are routinely styled hidden behind a custom "Attach"/"Choose
    // a File" button — the input itself still works via el.files + a change
    // event regardless of CSS visibility, so don't skip it for that reason.
    if (isHoneypot(el) || el.disabled) return;
    if (el.type !== "file" && !isVisible(el)) return;
    if (["hidden", "submit", "button", "image"].includes(el.type)) return;

    const ref = `${scanId}-${el.id || `jf-${refCounter++}`}`;
    el.setAttribute("data-jf-ref", ref);

    fields.push({
      ref,
      tag: el.tagName.toLowerCase(),
      type: el.type || "",
      name: el.name || "",
      id: el.id || "",
      label: resolveLabel(el),
      section: resolveSection(el),
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

  // Finds the posting's own "About the company/role" blurb, separate from
  // page_text's blanket truncated dump — this is what actually grounds a
  // generated cover letter. Runs on the untruncated body text since an About
  // section can sit well past page_text's 15000-char cutoff. Only takes an
  // "About" line whose next non-empty line reads like real prose (long
  // enough), so it skips a bare nav link ("About" in the header) and finds
  // the real section heading instead.
  function extractAboutText(fullText) {
    const lines = fullText.split("\n").map((l) => l.trim());
    for (let i = 0; i < lines.length; i++) {
      if (!/^about\b/i.test(lines[i]) || lines[i].length >= 80) continue;
      let j = i + 1;
      while (j < lines.length && !lines[j]) j++;
      if (j >= lines.length || lines[j].length < 60) continue;

      const collected = [lines[i]];
      let chars = lines[i].length;
      for (; j < lines.length && chars < 1500; j++) {
        const line = lines[j];
        const looksLikeHeading = line.length > 0 && line.length < 60 && !/[.!?]$/.test(line);
        if (looksLikeHeading && chars > 40) break;
        collected.push(line);
        chars += line.length;
      }
      return collected.join(" ").replace(/\s+/g, " ").trim();
    }
    return "";
  }

  const fullBodyText = document.body.innerText;
  // Truncated: only meant to give the LLM job-posting context for open-ended
  // questions, not to reproduce the page.
  return {
    url: window.location.href,
    form_snapshot: fields,
    page_text: fullBodyText.slice(0, 15000),
    about_text: extractAboutText(fullBodyText),
  };
}

// Runs inside the page, injected via scripting.executeScript — cannot
// reference anything from this file's scope.
function attachGenerateButtons(fields, applicationId, pageText) {
  // Shared by every button's click handler (old and new) so a re-scan with a
  // different CV/application updates already-attached buttons too, not just
  // ones attached this call.
  window.__jfScanContext = { applicationId, pageText };

  for (const field of fields) {
    const el = document.querySelector(`[data-jf-ref="${CSS.escape(field.ref)}"]`);
    if (!el || el.dataset.jfAiAttached) continue;
    el.dataset.jfAiAttached = "1";
    const question = field.label || field.section || field.placeholder;
    if (!question) continue;

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Generate with AI";
    Object.assign(button.style, {
      display: "block",
      marginTop: "8px",
      padding: "8px 14px",
      fontFamily: 'Arial, Helvetica, "Helvetica Neue", sans-serif',
      fontSize: "14px",
      fontWeight: "700",
      color: "#000000",
      background: "#ffffff",
      border: "1px solid #ffffff",
      borderRadius: "0",
      cursor: "pointer",
    });

    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Generating...";
      try {
        const response = await browser.runtime.sendMessage({
          type: "generateAnswer",
          applicationId: window.__jfScanContext.applicationId,
          question,
          pageText: window.__jfScanContext.pageText,
        });
        if (!response?.ok) throw new Error(response?.error || "generation failed");
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype,
          "value",
        ).set;
        setter.call(el, response.text);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        button.textContent = "Regenerate with AI";
      } catch (err) {
        button.textContent = `Failed: ${err} (click to retry)`;
      } finally {
        button.disabled = false;
      }
    });

    el.insertAdjacentElement("afterend", button);
  }
}

// Runs inside the page. `plan` is the field_mapping array core returned;
// `fileByRef` maps a ref to { base64, filename, mimeType } for
// any "upload" actions — fetched by background.js beforehand, since content
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
  const nativeSelectSetter = Object.getOwnPropertyDescriptor(
    window.HTMLSelectElement.prototype,
    "value",
  ).set;
  const nativeCheckedSetter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "checked",
  ).set;

  function setValue(el, value) {
    const eventInit = { bubbles: true, cancelable: true };
    el.focus();
    el.dispatchEvent(new Event("keydown", eventInit));
    el.dispatchEvent(new Event("keypress", eventInit));
    if (el.tagName === "INPUT") {
      nativeInputSetter.call(el, value);
      el.setAttribute("value", value);
    } else if (el.tagName === "TEXTAREA") {
      nativeTextareaSetter.call(el, value);
    } else if (el.isContentEditable) {
      el.textContent = value;
    }
    el.dispatchEvent(new Event("textInput", eventInit));
    el.dispatchEvent(new Event("input", eventInit));
    el.dispatchEvent(new Event("keyup", eventInit));
    el.dispatchEvent(new Event("change", eventInit));
  }

  function isPageContainer(node) {
    if (!node || node === document.body || node === document.documentElement) return true;
    if (node.tagName === "DIALOG" || node.tagName === "FORM") return true;
    if ((node.getAttribute("role") || "").toLowerCase() === "dialog") return true;
    const rect = node.getBoundingClientRect();
    return rect.width * rect.height > window.innerWidth * window.innerHeight * 0.5;
  }

  function clickOption(optionEl) {
    if (!optionEl || isPageContainer(optionEl)) return false;
    for (const type of ["pointerdown", "mousedown", "mouseup", "click"]) {
      optionEl.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true }));
    }
    return true;
  }

  function fillText(el, value) {
    if (el.isContentEditable) {
      el.focus();
      el.textContent = value;
      el.dispatchEvent(new InputEvent("input", { bubbles: true, data: value }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return el.textContent.trim() === value.trim() ? "contenteditable" : null;
    }

    setValue(el, value);
    if (el.value === value) return "native-setter";

    el.focus();
    el.select?.();
    document.execCommand("insertText", false, value);
    if (el.value === value) return "exec-command";

    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return el.value === value ? "direct" : null;
  }

  const DISMISSING_KEYS = new Set(["Escape", "Enter"]);

  function pressKey(el, key, init = {}) {
    let dialog = null;
    if (DISMISSING_KEYS.has(key)) {
      dialog = el.closest?.("dialog[open]") || null;
      if (!dialog && document.querySelector("dialog[open]")) return;
    }
    for (const type of ["keydown", "keyup"]) {
      const event = new KeyboardEvent(type, { key, bubbles: true, cancelable: true, ...init });
      if (!dialog) {
        el.dispatchEvent(event);
        continue;
      }
      const stopAtDialog = (e) => {
        if (e === event) e.stopPropagation();
      };
      dialog.addEventListener(type, stopAtDialog);
      try {
        el.dispatchEvent(event);
      } finally {
        dialog.removeEventListener(type, stopAtDialog);
      }
    }
  }

  function closeWidget(el) {
    pressKey(el, "Escape");
    el.blur();
  }

  function isRendered(optionEl) {
    return (
      optionEl.getClientRects().length > 0 && getComputedStyle(optionEl).visibility !== "hidden"
    );
  }

  function widgetInstancePrefix(el) {
    const ids = `${el.id || ""} ${el.getAttribute("aria-describedby") || ""} ${
      el.getAttribute("aria-activedescendant") || ""
    }`.split(/\s+/);
    for (const id of ids) {
      const stem = id.replace(/-(placeholder|live-region|input)$/, "").replace(/-option-\d+$/, "");
      if (stem && stem !== id && !/["'\\]/.test(stem)) return stem;
    }
    return null;
  }

  function findOptions(el, before) {
    const container = el.closest('[role="combobox"], [aria-haspopup="listbox"]') || el;
    const controlsId = container.getAttribute("aria-controls") || container.getAttribute("aria-owns");
    const scope = controlsId ? document.getElementById(controlsId) : null;
    if (scope) {
      return Array.from(scope.querySelectorAll('[role="option"]')).filter(isRendered);
    }

    const prefix = widgetInstancePrefix(el);
    if (prefix) {
      const scoped = Array.from(document.querySelectorAll(`[id^="${prefix}-option"]`)).filter(
        isRendered,
      );
      if (scoped.length) return scoped;
    }

    return Array.from(document.querySelectorAll('[role="option"]'))
      .filter(isRendered)
      .filter((o) => !before.has(o));
  }

  function optionSnapshot() {
    return new Set(document.querySelectorAll('[role="option"]'));
  }

  function selectedText(el) {
    const control = el.closest('[role="combobox"]')?.parentElement || el.parentElement || el;
    return `${el.value || ""} ${control.textContent || ""}`.toLowerCase();
  }

  function normalize(text) {
    return (text || "")
      .trim()
      .toLowerCase()
      .replace(/['’]/g, "")
      .replace(/\s+/g, " ");
  }

  function bestMatch(options, value) {
    const target = normalize(value);
    if (!target) return null;
    const texts = options.map((o) => normalize(o.textContent));

    const exact = texts.indexOf(target);
    if (exact !== -1) return options[exact];

    const prefix = texts.findIndex(
      (t) => t.startsWith(target) && /[^a-z0-9]/.test(t.charAt(target.length)),
    );
    if (prefix !== -1) return options[prefix];

    if (target.length >= 4) {
      const contains = texts.findIndex((t) => t.includes(target));
      if (contains !== -1) return options[contains];
    }
    return null;
  }

  function sizedTarget(el) {
    let node = el;
    for (let i = 0; i < 5 && node; i++) {
      if (node !== el && isPageContainer(node)) return el;
      const rect = node.getBoundingClientRect();
      if (rect.width >= 10 && rect.height >= 10) return node;
      node = node.parentElement;
    }
    return el;
  }

  function scrollParent(node) {
    let cur = node?.parentElement;
    for (let i = 0; i < 6 && cur; i++) {
      if (cur.scrollHeight > cur.clientHeight + 10) return cur;
      cur = cur.parentElement;
    }
    return null;
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
    return Boolean(el.closest('[role="combobox"], [aria-haspopup="listbox"]'));
  }

  function summarizeOptions(texts) {
    return texts.slice(0, 10).map((t) => t.slice(0, 40));
  }

  async function selectValue(el, value) {
    if (el.tagName === "SELECT") {
      const options = Array.from(el.options);
      const match = bestMatch(options, value);
      if (!match) {
        return { status: "no-match", wanted: value, options: options.map((o) => o.text.trim()) };
      }
      el.value = match.value;
      if (el.value !== match.value) nativeSelectSetter.call(el, match.value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return el.value === match.value
        ? { status: "selected", via: "native-select" }
        : { status: "unverified", wanted: value, selected: match.text.trim(), via: "native-select" };
    }

    if (document.activeElement && document.activeElement !== el) {
      closeWidget(document.activeElement);
    }
    const before = optionSnapshot();
    const waitForOptions = (timeoutMs) =>
      waitFor(() => {
        const found = findOptions(el, before);
        return found.length > 0 ? found : null;
      }, timeoutMs);

    const target = sizedTarget(el);
    target.scrollIntoView({ block: "center" });
    el.focus();

    const openTactics = [
      ["click", () => clickOption(el)],
      ["click-box", () => target !== el && clickOption(target)],
      ["arrow", () => pressKey(el, "ArrowDown")],
      ["alt-arrow", () => pressKey(el, "ArrowDown", { altKey: true })],
      ["space", () => pressKey(el, " ")],
      ["typing", () => setValue(el, value.slice(0, 4))],
    ];

    const isExpanded = () =>
      (el.closest('[role="combobox"], [aria-haspopup="listbox"]') || el).getAttribute(
        "aria-expanded",
      ) === "true" || el.getAttribute("aria-expanded") === "true";

    let via = null;
    let options = null;
    let opened = null;
    for (const [name, open] of openTactics) {
      if (isExpanded()) {
        options = await waitForOptions(1200);
        if (options) via = opened || name;
        break;
      }
      open();
      opened = name;
      options = await waitForOptions(900);
      if (options) {
        via = name;
        break;
      }
    }
    if (!options) return { status: "no-options", wanted: value, expanded: isExpanded() };

    let match = bestMatch(options, value);
    if (!match) {
      for (let round = 0; round < 16 && !match; round++) {
        const box = scrollParent(findOptions(el, before)[0]);
        if (!box) break;
        const top = box.scrollTop;
        box.scrollTop = top + box.clientHeight;
        await new Promise((resolve) => setTimeout(resolve, 140));
        if (box.scrollTop <= top) break;
        match = bestMatch(findOptions(el, before), value);
      }
      if (match) via = `${via}+scroll`;
    }

    if (!match) {
      setValue(el, "");
      closeWidget(el);
      return {
        status: "no-match",
        wanted: value,
        options: options.map((o) => o.textContent.trim()),
        via,
      };
    }

    const wantedText = match.textContent.trim();
    match.scrollIntoView({ block: "center" });
    const commitTactics = [
      ["click", () => clickOption(match)],
      ["native-click", () => match.click?.()],
      ["enter", () => pressKey(el, "Enter")],
      [
        "type-enter",
        () => {
          setValue(el, wantedText);
          pressKey(el, "Enter");
        },
      ],
    ];

    for (const [name, commit] of commitTactics) {
      commit();
      const settled = await waitFor(() => {
        if (findOptions(el, before).length > 0) return null;
        return selectedText(el).includes(wantedText.toLowerCase()) || null;
      }, 700);
      if (settled) return { status: "selected", via: `${via}+${name}` };
    }

    closeWidget(el);
    return { status: "unverified", wanted: value, selected: wantedText, via };
  }

  function outcomeResult(ref, outcome) {
    if (outcome.status === "selected") return { ref, ok: true };
    if (outcome.status === "no-match") {
      const seen = summarizeOptions(outcome.options)
        .map((s) => `"${s}"`)
        .join(" | ");
      const via = outcome.via ? ` via=${outcome.via}` : "";
      return {
        ref,
        ok: false,
        reason: `no-matching-option wanted="${outcome.wanted}" saw=${seen || "(none)"}${via}`,
      };
    }
    if (outcome.status === "unverified") {
      return {
        ref,
        ok: false,
        reason: `selection-not-confirmed wanted="${outcome.wanted}" tried="${outcome.selected}" via=${outcome.via}`,
      };
    }
    return {
      ref,
      ok: false,
      reason: outcome.expanded
        ? `options-unreachable wanted="${outcome.wanted}" (widget reported open, no options found)`
        : `dropdown-never-opened wanted="${outcome.wanted}" (click/arrow/space/typing all tried)`,
    };
  }

  const results = [];
  const unresolved = [];
  function trackUnresolved(ref, outcome) {
    if (outcome.status === "no-match") {
      unresolved.push({ ref, wanted: outcome.wanted, options: outcome.options });
    }
  }

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
            const outcome = await selectValue(el, item.value);
            trackUnresolved(item.ref, outcome);
            results.push(outcomeResult(item.ref, outcome));
          } else {
            const tactic = fillText(el, item.value);
            results.push(
              tactic
                ? { ref: item.ref, ok: true }
                : { ref: item.ref, ok: false, reason: `value-did-not-stick wanted="${item.value}"` },
            );
          }
          break;
        case "select": {
          const outcome = await selectValue(el, item.value);
          trackUnresolved(item.ref, outcome);
          results.push(outcomeResult(item.ref, outcome));
          break;
        }
        case "check": {
          const want = Boolean(item.value);
          if (el.checked !== want) {
            sizedTarget(el).scrollIntoView({ block: "center" });
            el.focus();
            el.click();
          }
          if (el.checked !== want) {
            clickOption(el);
          }
          if (el.checked !== want) {
            nativeCheckedSetter.call(el, want);
            el.dispatchEvent(new Event("input", { bubbles: true }));
            el.dispatchEvent(new Event("change", { bubbles: true }));
          }
          results.push(
            el.checked === want
              ? { ref: item.ref, ok: true }
              : { ref: item.ref, ok: false, reason: `checkbox-did-not-toggle wanted=${want}` },
          );
          break;
        }
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
          el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
          window.jQuery?.(el).trigger("change");
          results.push(
            el.files.length
              ? { ref: item.ref, ok: true }
              : { ref: item.ref, ok: false, reason: "file-did-not-attach" },
          );
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
  return { results, unresolved };
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

function applyEeoSettings(formSnapshot, fieldMapping, eeoSettings, logLines) {
  if (!eeoSettings.length) return fieldMapping;
  const fieldsByRef = Object.fromEntries(formSnapshot.map((f) => [f.ref, f]));
  let filled = 0;
  let unmatched = 0;

  const result = fieldMapping.map((mapping) => {
    if (mapping.action !== "skip") return mapping;
    const field = fieldsByRef[mapping.ref];
    if (!field) return mapping;

    const haystack = [field.label, field.section, field.name, field.id, field.placeholder]
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

  if (filled) logLines.push(`Filled ${filled} field(s) from your Settings answers.`);
  if (unmatched) {
    logLines.push(`${unmatched} Settings answer(s) matched a field but not any of its options —`);
    logLines.push(`  adjust the answer's wording in Manage CVs > Settings to match this site.`);
  }
  return result;
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

async function fetchCvs() {
  const response = await fetch(`${CORE_URL}/api/v1/cvs/`);
  if (!response.ok) throw new Error(`core returned ${response.status}`);
  return response.json();
}

// Fetches the file bytes for every "upload" action in the plan, keyed by ref,
// so applyFillPlan (running in the page) can attach them via DataTransfer.
async function buildFileMap(plan) {
  const fileByRef = {};
  let cvsCache = null;
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
    if (!cvsCache) cvsCache = await fetchCvs();
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

async function handleScan(message, tabId) {
  const logLines = [];
  // allFrames catches ATS forms embedded in a cross-origin iframe (e.g.
  // Newton/gnewton career pages) — <all_urls> is a required permission now,
  // so this always has access.
  const scanId = `s${Date.now().toString(36)}`;
  let injectionResults;
  try {
    injectionResults = await browser.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: scanPage,
      args: [scanId],
    });
  } catch (err) {
    logBg("SCAN_ALLFRAMES_FAILED", { tabId, error: String(err) });
    console.error("[JobFiller] allFrames scan failed, retrying top frame only", err);
    logLines.push(`Could not scan every frame (${err.message || err}) — scanned the top frame only.`);
    injectionResults = await browser.scripting.executeScript({
      target: { tabId },
      func: scanPage,
      args: [scanId],
    });
  }

  const framesWithFields = injectionResults.filter(
    (r) => r.result && r.result.form_snapshot.length > 0,
  );
  const bestFrame = framesWithFields.reduce(
    (best, r) =>
      !best || r.result.form_snapshot.length > best.result.form_snapshot.length ? r : best,
    null,
  );
  // The "About" blurb can live in the top frame even when the form itself is
  // in an embedded ATS iframe — search every scanned frame (not just ones
  // with fields), lowest frameId (top frame) first.
  const aboutFrame = injectionResults
    .filter((r) => r.result && r.result.about_text)
    .sort((a, b) => a.frameId - b.frameId)[0];

  const refFrameMap = {};
  const formSnapshot = [];
  for (const { frameId, result } of framesWithFields) {
    for (const field of result.form_snapshot) {
      const ref = `${frameId}:${field.ref}`;
      refFrameMap[ref] = { frameId, localRef: field.ref };
      formSnapshot.push({ ...field, ref });
    }
  }
  logLines.push(`Found ${formSnapshot.length} fields across ${framesWithFields.length} frame(s).`);

  const pageText = bestFrame ? bestFrame.result.page_text : "";
  const aboutText = aboutFrame ? aboutFrame.result.about_text : "";
  const eeoSettings = await loadEeoSettings();
  const response = await fetch(`${CORE_URL}/api/v1/applications/scan/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: message.url,
      page_text: pageText,
      about_text: aboutText,
      form_snapshot: formSnapshot,
      cv_id: message.cvId,
      eeo_answers: eeoSettings,
    }),
  });
  if (!response.ok) throw new Error(`core returned ${response.status}`);

  const data = await response.json();
  const fieldMapping = applyEeoSettings(formSnapshot, data.field_mapping, eeoSettings, logLines);
  const skipped = fieldMapping.filter((f) => f.action === "skip").length;
  logLines.push(`Fill plan ready: ${fieldMapping.length - skipped} to fill, ${skipped} skipped.`);

  let buttonsAttached = 0;
  for (const { frameId, result } of framesWithFields) {
    const textareaFields = result.form_snapshot
      .filter((f) => f.tag === "textarea" && (f.label || f.section || f.placeholder))
      .map((f) => ({
        ref: f.ref,
        label: f.label,
        section: f.section,
        placeholder: f.placeholder,
      }));
    if (!textareaFields.length) continue;
    try {
      await browser.scripting.executeScript({
        target: { tabId, frameIds: [frameId] },
        func: attachGenerateButtons,
        args: [textareaFields, data.id, pageText],
      });
      buttonsAttached += textareaFields.length;
    } catch (err) {
      logLines.push(`Couldn't attach "Generate with AI" buttons in frame ${frameId}: ${err}`);
    }
  }
  if (buttonsAttached) {
    logLines.push(`Added ${buttonsAttached} "Generate with AI" button(s) on open-ended fields.`);
  }

  return {
    ok: true,
    applicationId: data.id,
    fieldMapping,
    refFrameMap,
    pageText,
    aboutText,
    logLines,
  };
}

async function handleFill(message, tabId) {
  const fileByRef = await buildFileMap(message.fieldMapping);

  // Each field's ref only resolves inside the frame it was scanned from —
  // group by frame and translate back to the un-prefixed ref that's actually
  // stamped on the element there.
  const itemsByFrame = new Map();
  for (const item of message.fieldMapping) {
    const info = message.refFrameMap[item.ref] || { frameId: 0, localRef: item.ref };
    if (!itemsByFrame.has(info.frameId)) itemsByFrame.set(info.frameId, []);
    itemsByFrame.get(info.frameId).push({ ...item, ref: info.localRef, globalRef: item.ref });
  }

  const allResults = [];
  const unresolvedByGlobalRef = new Map();
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
      target: { tabId, frameIds: [frameId] },
      func: applyFillPlan,
      args: [plan, localFileByRef],
    });
    allResults.push(...result.results.map((r) => ({ ...r, frameId })));

    const globalRefByLocalRef = new Map(items.map((item) => [item.ref, item.globalRef]));
    for (const u of result.unresolved) {
      unresolvedByGlobalRef.set(globalRefByLocalRef.get(u.ref), { ...u, frameId, localRef: u.ref });
    }
  }

  const { entries, error } = await resolveUnmatchedDropdowns(
    tabId,
    message.applicationId,
    unresolvedByGlobalRef,
    allResults,
  );

  const failed = allResults.filter((r) => !r.ok);
  const logLines = [`Filled ${allResults.length - failed.length}/${allResults.length}.`];
  for (const [frameId, items] of itemsByFrame) {
    for (const item of items) {
      if (item.action === "skip") continue;
      logLines.push(
        `  applied frame ${frameId} / ${item.ref}: ${item.action} ${JSON.stringify(String(item.value).slice(0, 60))}`,
      );
    }
  }
  failed.forEach((r) => logLines.push(`  frame ${r.frameId} / ${r.ref}: ${r.reason}`));
  if (failed.length && failed.every((r) => r.reason === "not-found")) {
    logLines.push(
      "None of the scanned fields are still on the page — it reloaded or re-rendered. Click Re-scan.",
    );
  }
  if (unresolvedByGlobalRef.size) {
    const picked = entries.filter((e) => e.action === "select" && e.value).length;
    logLines.push(
      error
        ? `Could not resolve ${unresolvedByGlobalRef.size} dropdown(s) via core: ${error}`
        : `Resolved ${picked}/${unresolvedByGlobalRef.size} dropdown(s) via core.`,
    );
  }
  return { ok: true, logLines, entries };
}

async function resolveUnmatchedDropdowns(tabId, applicationId, unresolvedByGlobalRef, allResults) {
  if (!unresolvedByGlobalRef.size) return { entries: [] };
  if (!applicationId) return { entries: [], error: "no application id — re-scan first" };

  const payloadFields = Array.from(unresolvedByGlobalRef, ([ref, u]) => ({
    ref,
    wanted: u.wanted,
    options: (u.options || []).map((o) => String(o).trim()).filter(Boolean),
  })).filter((f) => f.options.length);
  if (!payloadFields.length) {
    return { entries: [], error: "the page's dropdown listed no options to match against" };
  }

  let resolved;
  try {
    const response = await fetch(`${CORE_URL}/api/v1/applications/resolve-options/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ application_id: applicationId, fields: payloadFields }),
    });
    if (!response.ok) {
      const body = (await response.text().catch(() => "")).slice(0, 300);
      return { entries: [], error: `core returned ${response.status}${body ? ` — ${body}` : ""}` };
    }
    resolved = (await response.json()).fields;
  } catch (err) {
    return { entries: [], error: String(err) };
  }

  const planByFrame = new Map();
  for (const entry of resolved) {
    if (entry.action !== "select" || !entry.value) continue;
    const u = unresolvedByGlobalRef.get(entry.ref);
    if (!u) continue;
    if (!planByFrame.has(u.frameId)) planByFrame.set(u.frameId, []);
    planByFrame.get(u.frameId).push({ ref: u.localRef, value: entry.value, action: "select" });
  }

  for (const [frameId, plan] of planByFrame) {
    const [{ result }] = await browser.scripting.executeScript({
      target: { tabId, frameIds: [frameId] },
      func: applyFillPlan,
      args: [plan, {}],
    });
    for (const r of result.results) {
      const i = allResults.findIndex((x) => x.frameId === frameId && x.ref === r.ref);
      if (i !== -1) allResults[i] = { ...r, frameId };
    }
  }

  return { entries: resolved };
}

async function handleGenerateCoverLetter(message) {
  const response = await fetch(`${CORE_URL}/api/v1/applications/generate-cover-letter/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      application_id: message.applicationId,
      page_text: message.pageText,
      about_text: message.aboutText,
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `core returned ${response.status}`);
  return { ok: true, text: data.text, entries: data.entries };
}

async function handleAnalyze(message) {
  const response = await fetch(`${CORE_URL}/api/v1/applications/analyze/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      application_id: message.applicationId,
      page_text: message.pageText,
      about_text: message.aboutText,
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `core returned ${response.status}`);
  return { ok: true, analysis: data };
}

async function handleGenerateAnswer(message) {
  const response = await fetch(`${CORE_URL}/api/v1/applications/generate-answer/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      application_id: message.applicationId,
      question: message.question,
      page_text: message.pageText,
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || `core returned ${response.status}`);
  return { ok: true, text: data.text };
}

function scanStorageKey(tabId) {
  return `scan:${tabId}`;
}

function reportError(type, err) {
  console.error(`[JobFiller ${JF_VERSION}] ${type} failed:`, err);
  return { ok: false, error: String(err) };
}

function startKeepalive() {
  const interval = setInterval(() => {
    browser.storage.session.get("jf-keepalive-ping").catch(() => {});
  }, 20000);
  return () => clearInterval(interval);
}

browser.runtime.onMessage.addListener((message, sender) => {
  const tabId = sender.tab?.id;
  logBg("RECEIVE", { type: message.type, tabId, frameId: sender.frameId });

  const respond = (promise) => {
    const stopKeepalive = startKeepalive();
    return promise
      .then((result) => {
        logBg("RESPOND", { type: message.type, tabId, ok: result ? result.ok !== false : true });
        return result;
      })
      .finally(stopKeepalive);
  };

  switch (message.type) {
    case "whoami":
      return respond(Promise.resolve({ tabId }));
    case "saveState":
      return respond(
        browser.storage.session.set({ [scanStorageKey(tabId)]: message.state }).then(() => ({ ok: true })),
      );
    case "getState":
      return respond(
        browser.storage.session
          .get(scanStorageKey(tabId))
          .then((stored) => ({ entry: stored[scanStorageKey(tabId)] || null })),
      );
    case "loadCvs":
      return respond(fetchCvs().then((cvs) => ({ ok: true, cvs })));
    case "scan":
      return respond(handleScan(message, tabId).catch((err) => reportError("scan", err)));
    case "fill":
      return respond(handleFill(message, tabId).catch((err) => reportError("fill", err)));
    case "generateCoverLetter":
      return respond(handleGenerateCoverLetter(message).catch((err) => reportError("generateCoverLetter", err)));
    case "analyze":
      return respond(handleAnalyze(message).catch((err) => reportError("analyze", err)));
    case "generateAnswer":
      return respond(handleGenerateAnswer(message).catch((err) => reportError("generateAnswer", err)));
    case "openManage":
      return respond(
        browser.tabs
          .create({ url: browser.runtime.getURL("src/manage/manage.html") })
          .then((tab) => browser.tabs.setZoom(tab.id, 0.3))
          .then(() => ({ ok: true })),
      );
    default:
      logBg("UNKNOWN_MESSAGE_TYPE", { type: message.type, tabId });
      return undefined;
  }
});
