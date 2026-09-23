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

  function deepQueryAll(selector, root) {
    const out = [];
    const visit = (node) => {
      if (!node || !node.querySelectorAll) return;
      out.push(...node.querySelectorAll(selector));
      node.querySelectorAll("*").forEach((el) => el.shadowRoot && visit(el.shadowRoot));
    };
    visit(root || document);
    return out;
  }

  function deepQueryOne(selector, root) {
    return deepQueryAll(selector, root)[0] || null;
  }


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
      const byFor = deepQueryOne(`label[for="${CSS.escape(el.id)}"]`, el.getRootNode());
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
          .map((id) => deepQueryOne(`#${CSS.escape(id)}`, el.getRootNode())?.textContent?.trim())
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
      node = node.parentElement || node.getRootNode()?.host || null;
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
      { selector: '.jobs-easy-apply-modal[role="dialog"], .jobs-easy-apply-modal[aria-modal="true"]', minControls: 1 },
      { selector: '[aria-modal="true"]', minControls: 1 },
      { selector: "dialog[open]", minControls: 1 },
      { selector: '[role="dialog"]', minControls: 2 },
    ];
    for (const { selector, minControls } of tiers) {
      const open = deepQueryAll(selector).filter(isShown);
      const outermost = open.filter((el) => !open.some((o) => o !== el && o.contains(el)));
      const withControls = outermost.filter(
        (root) => deepQueryAll("input, select, textarea", root).length,
      );
      const total = withControls.reduce(
        (n, root) => n + deepQueryAll("input, select, textarea", root).length,
        0,
      );
      if (withControls.length && total >= minControls) return withControls;
    }
    return [document];
  }

  const roots = scanRoots();
  const easyApplyModal = roots.some((root) => root !== document && (
    root.matches?.(".jobs-easy-apply-modal") ||
    root.querySelector?.(".jobs-easy-apply-content, .jobs-easy-apply-form-section__grouping") ||
    /easy apply|application/i.test(root.getAttribute?.("aria-label") || "")
  ));
  const candidates = [];
  const seen = new Set();
  roots.forEach((root) => {
    deepQueryAll("input, select, textarea", root).forEach((el) => {
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

    const label = resolveLabel(el);
    fields.push({
      ref,
      tag: el.tagName.toLowerCase(),
      type: el.type || "",
      name: el.name || "",
      id: el.id || "",
      label,
      section: resolveSection(el),
      placeholder: el.placeholder || "",
      options: el.tagName === "SELECT" ? Array.from(el.options).map((o) => o.textContent.trim()) : [],
      required: el.required || el.getAttribute("aria-required") === "true" || /\*\s*$/.test(label),
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
    easy_apply_modal: Boolean(easyApplyModal),
    form_snapshot: fields,
    page_text: fullBodyText.slice(0, 15000),
    about_text: extractAboutText(fullBodyText),
  };
}

// Runs inside the page, injected via scripting.executeScript — cannot
// reference anything from this file's scope.
function attachGenerateButtons(fields, applicationId, pageText) {
  function deepQueryAll(selector, root) {
    const out = [];
    const visit = (node) => {
      if (!node || !node.querySelectorAll) return;
      out.push(...node.querySelectorAll(selector));
      node.querySelectorAll("*").forEach((el) => el.shadowRoot && visit(el.shadowRoot));
    };
    visit(root || document);
    return out;
  }

  function deepQueryOne(selector, root) {
    return deepQueryAll(selector, root)[0] || null;
  }
  // Shared by every button's click handler (old and new) so a re-scan with a
  // different CV/application updates already-attached buttons too, not just
  // ones attached this call.
  window.__jfScanContext = { applicationId, pageText };

  for (const field of fields) {
    const el = deepQueryOne(`[data-jf-ref="${CSS.escape(field.ref)}"]`);
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
  function deepQueryAll(selector, root) {
    const out = [];
    const visit = (node) => {
      if (!node || !node.querySelectorAll) return;
      out.push(...node.querySelectorAll(selector));
      node.querySelectorAll("*").forEach((el) => el.shadowRoot && visit(el.shadowRoot));
    };
    visit(root || document);
    return out;
  }

  function deepQueryOne(selector, root) {
    return deepQueryAll(selector, root)[0] || null;
  }
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
    const rect = optionEl.getBoundingClientRect();
    const init = {
      bubbles: true,
      cancelable: true,
      composed: true,
      view: window,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
      button: 0,
      detail: 1,
    };
    for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
      const down = type.endsWith("down");
      const event = type.startsWith("pointer")
        ? new PointerEvent(type, {
            ...init,
            pointerId: 1,
            pointerType: "mouse",
            isPrimary: true,
            buttons: down ? 1 : 0,
          })
        : new MouseEvent(type, { ...init, buttons: down ? 1 : 0 });
      optionEl.dispatchEvent(event);
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
      if (!dialog && deepQueryOne("dialog[open]")) return;
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
    const ids = [el, container].flatMap((node) =>
      [node.getAttribute("aria-controls"), node.getAttribute("aria-owns")]
        .filter(Boolean)
        .flatMap((value) => value.split(/\s+/)),
    );
    const scopes = [...new Set(ids)]
      .map((id) => el.getRootNode().getElementById?.(id) || deepQueryOne(`#${CSS.escape(id)}`))
      .filter(Boolean);
    const selectable = (option) =>
      isRendered(option) &&
      option.getAttribute("aria-disabled") !== "true" &&
      !option.matches(":disabled");
    if (scopes.length) {
      return [...new Set(scopes.flatMap((scope) => deepQueryAll('[role="option"]', scope)))].filter(
        selectable,
      );
    }

    const prefix = widgetInstancePrefix(el);
    if (prefix) {
      const scoped = deepQueryAll(`[id^="${prefix}-option-"]`).filter(selectable);
      if (scoped.length) return scoped;
    }

    return deepQueryAll('[role="option"]')
      .filter(selectable)
      .filter((option) => !before.has(option));
  }

  function optionSnapshot() {
    return new Set(deepQueryAll('[role="option"]').filter(isRendered));
  }

  function selectionLabels(el) {
    let control = el;
    for (let depth = 0; depth < 4; depth++) {
      const parent = control.parentElement || control.getRootNode()?.host;
      if (!parent || isPageContainer(parent)) break;
      if (
        deepQueryAll(
          'input:not([type="hidden"]), select, textarea, [role="combobox"]',
          parent,
        ).some((node) => node !== el && !node.contains(el) && !el.contains(node))
      )
        break;
      control = parent;
    }
    const labels = [];
    const visit = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        if (node.textContent.trim()) labels.push(normalize(node.textContent));
        return;
      }
      if (
        node.nodeType !== Node.ELEMENT_NODE ||
        node.matches(
          'input, textarea, label, [role="listbox"], [role="option"], [aria-live], [aria-hidden="true"]',
        ) ||
        !isRendered(node)
      )
        return;
      for (const child of node.childNodes) visit(child);
      if (node.shadowRoot) for (const child of node.shadowRoot.childNodes) visit(child);
    };
    visit(control);
    return labels;
  }

  function normalize(text) {
    return (text || "").trim().toLowerCase().replace(/['’]/g, "").replace(/\s+/g, " ");
  }

  function bestMatch(options, value) {
    const target = normalize(value);
    if (!target) return null;
    const texts = options.map((o) => normalize(o.textContent));

    const exact = texts.indexOf(target);
    if (exact !== -1) return options[exact];

    const boundary = (character) => !/[\p{L}\p{N}]/u.test(character);
    const prefixes = texts
      .map((text, index) => ({ text, index }))
      .filter(({ text }) => text.startsWith(target) && boundary(text.charAt(target.length)));
    if (prefixes.length === 1) return options[prefixes[0].index];

    if (target.length >= 4) {
      const containing = texts
        .map((text, index) => ({ text, index }))
        .filter(({ text }) => {
          const start = text.indexOf(target);
          return (
            start >= 0 &&
            boundary(text.charAt(start - 1)) &&
            boundary(text.charAt(start + target.length))
          );
        });
      if (containing.length === 1) return options[containing[0].index];
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
      const options = Array.from(el.options).filter((option) => !option.matches(":disabled"));
      const match = bestMatch(options, value) || options.find((option) => option.value === value);
      if (!match) {
        return { status: "no-match", wanted: value, options: options.map((o) => o.text.trim()) };
      }
      nativeSelectSetter.call(el, match.value);
      el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
      el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
      await new Promise((resolve) => setTimeout(resolve, 100));
      return match.selected && el.value === match.value
        ? { status: "selected", via: "native-select" }
        : {
            status: "unverified",
            wanted: value,
            selected: match.text.trim(),
            via: "native-select",
          };
    }

    if (document.activeElement && document.activeElement !== el) {
      closeWidget(document.activeElement);
    }
    const before = optionSnapshot();
    const originalValue = el.value || "";
    const originalLabels = selectionLabels(el);
    const searchable = el.tagName === "INPUT" && !el.readOnly && !el.disabled;
    let typed = false;
    const seen = new Set();
    const readOptions = () => {
      const options = findOptions(el, before);
      options.forEach((option) => {
        const text = option.textContent.trim();
        if (text) seen.add(text);
      });
      return options;
    };
    const waitForOptions = (timeoutMs) =>
      waitFor(() => {
        const options = readOptions();
        return options.length ? options : null;
      }, timeoutMs);
    const typeSearch = (text) => {
      typed = true;
      el.focus();
      nativeInputSetter.call(el, text);
      el.dispatchEvent(
        new InputEvent("input", {
          bubbles: true,
          composed: true,
          data: text,
          inputType: "insertText",
        }),
      );
    };
    const target = sizedTarget(el);
    target.scrollIntoView({ block: "center" });
    el.focus();
    const isExpanded = () =>
      (el.closest('[role="combobox"], [aria-haspopup="listbox"]') || el).getAttribute(
        "aria-expanded",
      ) === "true" || el.getAttribute("aria-expanded") === "true";
    let via = "already-open";
    let options = isExpanded() ? await waitForOptions(900) : null;
    const openTactics = [
      ["click", () => clickOption(el)],
      ["click-box", () => target !== el && clickOption(target)],
      ["arrow", () => pressKey(el, "ArrowDown")],
      ["alt-arrow", () => pressKey(el, "ArrowDown", { altKey: true })],
      ["space", () => !searchable && pressKey(el, " ")],
    ];
    for (const [name, open] of openTactics) {
      if (options || isExpanded()) break;
      open();
      via = name;
      options = await waitForOptions(900);
    }
    let match = bestMatch(options || [], value);
    if (!match && searchable) {
      typeSearch(value);
      via += "+search";
      match = await waitFor(() => bestMatch(readOptions(), value), 2500);
      if (!match) {
        typeSearch("");
        options = await waitForOptions(1500);
        match = bestMatch(options || [], value);
      }
    }
    if (!match) {
      for (let round = 0; round < 32 && !match; round++) {
        const current = readOptions();
        match = bestMatch(current, value);
        if (match) break;
        const box = scrollParent(current[0]);
        if (!box || isPageContainer(box)) break;
        const top = box.scrollTop;
        box.scrollTop = round === 0 ? 0 : top + Math.max(1, box.clientHeight * 0.8);
        box.dispatchEvent(new Event("scroll"));
        await new Promise((resolve) => setTimeout(resolve, 140));
        match = bestMatch(readOptions(), value);
        if (round > 0 && box.scrollTop <= top) break;
      }
      if (match) via += "+scroll";
    }
    if (!match) {
      if (typed) typeSearch(originalValue);
      const expanded = isExpanded();
      closeWidget(el);
      return seen.size
        ? { status: "no-match", wanted: value, options: [...seen], via }
        : { status: "no-options", wanted: value, expanded };
    }

    const wantedText = match.textContent.trim();
    const wanted = normalize(wantedText);
    let committedInput = false;
    let clicked = false;
    let closing = false;
    const onCommit = () => {
      committedInput = true;
    };
    const confirmed = () => {
      const current = readOptions().find((option) => normalize(option.textContent) === wanted);
      if (
        current?.getAttribute("aria-selected") === "true" ||
        current?.getAttribute("aria-checked") === "true"
      ) return "option";
      const labels = selectionLabels(el);
      if (labels.includes(wanted) && (!originalLabels.includes(wanted) || !isExpanded())) {
        return "label";
      }
      if (
        (!typed || committedInput || (clicked && !closing)) &&
        normalize(el.value) === wanted &&
        (el.value !== originalValue || committedInput) &&
        !isExpanded() && readOptions().length === 0
      ) return "input";
      return null;
    };
    if (confirmed()) {
      closeWidget(el);
      return { status: "selected", via: `${via}+already-selected` };
    }
    match.scrollIntoView({ block: "nearest" });
    el.addEventListener("input", onCommit);
    el.addEventListener("change", onCommit);
    let settled = false;
    try {
      clicked = clickOption(match);
      settled = await waitFor(confirmed, 1000);
      if (!settled) {
        const activeId = el.getAttribute("aria-activedescendant");
        const active =
          activeId &&
          (el.getRootNode().getElementById?.(activeId) || deepQueryOne(`#${CSS.escape(activeId)}`));
        if (active && readOptions().includes(active) && normalize(active.textContent) === wanted) {
          pressKey(el, "Enter");
          settled = await waitFor(confirmed, 700);
        }
      }
      closing = true;
      closeWidget(el);
      await new Promise((resolve) => setTimeout(resolve, 100));
      settled = settled === "input" ? normalize(el.value) === wanted : settled || confirmed();
    } finally {
      el.removeEventListener("input", onCommit);
      el.removeEventListener("change", onCommit);
    }
    if (settled) {
      return { status: "selected", via: `${via}+commit` };
    }
    if (typed) {
      typeSearch(originalValue);
      closeWidget(el);
    }
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
    const el = deepQueryOne(`[data-jf-ref="${CSS.escape(item.ref)}"]`);
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
                : {
                    ref: item.ref,
                    ok: false,
                    reason: `value-did-not-stick wanted="${item.value}"`,
                  },
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
  const unmatchedLabels = [];

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
        unmatchedLabels.push(field.label || field.section || field.name || "Unnamed field");
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
  if (unmatchedLabels.length) {
    logLines.push(`Settings answer(s) did not match options for: ${unmatchedLabels.join("; ").slice(0, 250)} —`);
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

function framesWithApplicationFields(injectionResults) {
  const frames = injectionResults.filter(
    (r) => r.result && r.result.form_snapshot.length > 0,
  );
  // LinkedIn's job page can contain unrelated iframe inputs (ads/widgets).
  // Once Easy Apply is open, only the top-frame dialog belongs to this step.
  const topEasyApply = frames.find((r) => r.frameId === 0 && r.result.easy_apply_modal);
  return topEasyApply ? [topEasyApply] : frames;
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

  const framesWithFields = framesWithApplicationFields(injectionResults);
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
  let screenshot = "";
  if (formSnapshot.length) {
    try {
      screenshot = await browser.tabs.captureTab(tabId, { format: "jpeg", quality: 65 });
      if (screenshot.length > 1900000) {
        screenshot = "";
        logLines.push("Vision screenshot was too large; continuing with text fields.");
      }
    } catch (err) {
      logLines.push(`Vision screenshot unavailable: ${err.message || err}`);
    }
  }
  const eeoSettings = await loadEeoSettings();
  const response = await fetch(`${CORE_URL}/api/v1/applications/scan/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: message.url,
      page_text: pageText,
      about_text: aboutText,
      screenshot,
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
    formSnapshot,
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
  return { ok: true, logLines, entries, failedCount: failed.length };
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
    case "fillLinkedInSteps":
      return respond(fillLinkedInSteps(tabId, message.cvId, false).catch((err) => reportError("fillLinkedInSteps", err)));
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

// The extension uses the same scan/fill path as the manual panel. A browser
// must be open for this worker to process the server's daily queue.
async function waitForTab(tabId) {
  const current = await browser.tabs.get(tabId);
  if (current.status === "complete") return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      browser.tabs.onUpdated.removeListener(onUpdated);
      reject(new Error("Job page did not finish loading"));
    }, 30000);
    function onUpdated(id, change) {
      if (id !== tabId || change.status !== "complete") return;
      clearTimeout(timer);
      browser.tabs.onUpdated.removeListener(onUpdated);
      resolve();
    }
    browser.tabs.onUpdated.addListener(onUpdated);
  });
}

function findApplyLink() {
  const links = Array.from(document.querySelectorAll("a[href]"));
  const matches = links.filter((a) => {
    const label = (a.innerText || a.getAttribute("aria-label") || "").trim();
    return /^(apply|apply now|apply for this job|apply to this job)$/i.test(label);
  });
  if (matches.length !== 1) return null;
  const url = new URL(matches[0].href, location.href);
  return ["http:", "https:"].includes(url.protocol) ? url.href : null;
}

// Runs in the page. Only controls in LinkedIn's visible Easy Apply dialog are
// eligible; search filters and the JobFiller panel must never be treated as steps.
function linkedInEasyApply(action) {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
  };
  const label = (el) => (el.innerText || el.value || el.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim();
  if (action === "open") {
    const candidates = Array.from(document.querySelectorAll("button.jobs-apply-button, button[aria-label*='Easy Apply' i]"))
      .filter((el) => !el.disabled && visible(el) && /easy apply/i.test(`${label(el)} ${el.getAttribute("aria-label") || ""}`));
    if (candidates.length !== 1) return { ok: false, reason: `Found ${candidates.length} Easy Apply buttons` };
    candidates[0].click();
    return { ok: true };
  }
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"]'))
    .filter((el) => visible(el) && (el.matches(".jobs-easy-apply-modal") || el.querySelector(".jobs-easy-apply-content, .jobs-easy-apply-form-section__grouping") || /easy apply|application/i.test(el.getAttribute("aria-label") || "")));
  const dialog = dialogs.find((el) => !dialogs.some((other) => other !== el && other.contains(el)));
  if (!dialog) return { ok: false, reason: "LinkedIn Easy Apply dialog is not open" };
  const buttons = Array.from(dialog.querySelectorAll("button, input[type='submit']"))
    .filter((el) => !el.disabled && visible(el));
  const pick = (pattern) => buttons.filter((el) => pattern.test(label(el)));
  const submit = pick(/^submit( application)?$/i);
  const review = pick(/^review( your)? application$|^review$/i);
  const next = pick(/^(continue( to next step)?|next)$/i)
    .concat(buttons.filter((el) => el.hasAttribute("data-easy-apply-next-button")))
    .filter((el, i, all) => all.indexOf(el) === i);
  const choices = submit.length ? submit : review.length ? review : next;
  const kind = submit.length ? "submit" : review.length ? "review" : next.length ? "next" : "unknown";
  const text = (dialog.innerText || "").replace(/\s+/g, " ").slice(0, 5000);
  const signature = JSON.stringify({
    progress: text.match(/\b\d+\s*\/\s*\d+\s*pages?\b/i)?.[0] ||
      dialog.querySelector('[role="progressbar"]')?.getAttribute("aria-valuenow") || "",
    headings: Array.from(dialog.querySelectorAll("h1, h2, h3")).map((el) => label(el)).slice(0, 5),
    fields: Array.from(dialog.querySelectorAll("input, select, textarea"))
      .filter(visible).map((el) => [el.id, el.name, el.type, el.getAttribute("aria-label"),
        el.id ? dialog.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.innerText : ""]),
    kind,
  });
  const fieldCount = Array.from(dialog.querySelectorAll("input, select, textarea"))
    .filter((el) => !el.disabled && (visible(el) || el.type === "file") && !["hidden", "submit", "button"].includes(el.type)).length;
  if (action === "inspect") return { ok: true, kind, signature, fieldCount };
  if (action === "diagnose") {
    const feedback = Array.from(dialog.querySelectorAll(
      '.artdeco-inline-feedback--error, .fb-dash-form-element__error-field, [role="alert"]',
    )).filter(visible).map((el) => label(el)).filter(Boolean);
    const invalid = Array.from(dialog.querySelectorAll('input, select, textarea, [role="combobox"]'))
      .filter((el) => visible(el) && (el.getAttribute("aria-invalid") === "true" ||
        (el.willValidate && !el.checkValidity())))
      .map((el) => el.getAttribute("aria-label") ||
        (el.id && dialog.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.innerText) ||
        el.closest("label")?.innerText || el.name || "Unnamed field");
    return { ok: true, issues: [...new Set([...feedback, ...invalid])].slice(0, 8) };
  }
  if (choices.length !== 1) return { ok: false, reason: `Found ${choices.length} ${kind} buttons in Easy Apply` };
  if (action !== kind) return { ok: false, reason: `Expected ${action}, found ${kind}` };
  const invalid = Array.from(dialog.querySelectorAll("input, select, textarea"))
    .filter((el) => visible(el) && el.willValidate && !el.checkValidity());
  if (invalid.length) return { ok: false, reason: `${invalid.length} required or invalid fields remain` };
  choices[0].click();
  return { ok: true, signature };
}

async function linkedInStep(tabId, action) {
  const [{ result }] = await browser.scripting.executeScript({
    target: { tabId }, func: linkedInEasyApply, args: [action],
  });
  return result;
}

async function waitForLinkedInStep(tabId, previousSignature) {
  let candidate = "";
  for (let attempt = 0; attempt < 40; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    const state = await linkedInStep(tabId, "inspect");
    if (!state.ok || state.kind === "unknown" || state.signature === previousSignature) {
      candidate = "";
      continue;
    }
    if (candidate === state.signature) return state;
    candidate = state.signature;
  }
  const diagnosis = await linkedInStep(tabId, "diagnose").catch(() => null);
  if (diagnosis?.issues?.length) {
    throw new Error(`Easy Apply did not advance: ${diagnosis.issues.join("; ").slice(0, 400)}`);
  }
  throw new Error("Easy Apply did not advance; check the open dialog for validation errors");
}

// Runs in a scanned frame after filling. A skipped required field may already
// have an answer supplied by the applicant or their saved LinkedIn profile.
function unansweredLinkedInFields(refs) {
  return refs.filter((ref) => {
    const el = document.querySelector(`[data-jf-ref="${CSS.escape(ref)}"]`);
    if (!el) return true;
    if (el.type === "radio") {
      if (!el.name) return !el.checked;
      return !Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`))
        .some((option) => option.checked);
    }
    if (el.type === "checkbox") return !el.checked;
    if (el.type === "file") return !el.files?.length;
    if (el.tagName === "SELECT") {
      const option = el.selectedOptions[0];
      return !option?.value || (el.options.length > 1 && el.selectedIndex === 0);
    }
    return !String(el.value || "").trim();
  });
}

async function unansweredLinkedInRequired(tabId, scan, entries) {
  const byFrame = new Map();
  const missingRefs = [];
  for (const entry of entries) {
    const info = scan.refFrameMap?.[entry.ref];
    if (!info) {
      missingRefs.push(entry.ref);
      continue;
    }
    if (!byFrame.has(info.frameId)) byFrame.set(info.frameId, []);
    byFrame.get(info.frameId).push({ globalRef: entry.ref, localRef: info.localRef });
  }
  for (const [frameId, entriesInFrame] of byFrame) {
    const [{ result }] = await browser.scripting.executeScript({
      target: { tabId, frameIds: [frameId] }, func: unansweredLinkedInFields,
      args: [entriesInFrame.map((entry) => entry.localRef)],
    });
    for (const entry of entriesInFrame) {
      if (result.includes(entry.localRef)) missingRefs.push(entry.globalRef);
    }
  }
  return missingRefs;
}

async function fillLinkedInSteps(tabId, cvId, autoSubmit) {
  const tab = await browser.tabs.get(tabId);
  if (new URL(tab.url).hostname !== "www.linkedin.com") throw new Error("This is not a LinkedIn page");
  if (!cvId) throw new Error("Select a CV first");
  let state = await linkedInStep(tabId, "inspect");
  if (!state.ok) {
    const opened = await linkedInStep(tabId, "open");
    if (!opened.ok) throw new Error(opened.reason);
    state = await waitForLinkedInStep(tabId, "");
  }
  const logLines = [];
  for (let step = 1; step <= 12; step++) {
    if (!state.ok) throw new Error(state.reason);
    if (state.kind === "unknown") throw new Error("No recognized Easy Apply step button");
    // The final review page can have no fields. Do not scan the search form
    // behind the dialog in that case.
    if (state.fieldCount) {
      const scan = await handleScan({ url: tab.url, cvId }, tabId);
      if (!scan.formSnapshot.length) throw new Error(`Step ${step}: visible fields were not scanned`);
      const requiredRefs = new Set(scan.formSnapshot.filter((field) => field.required).map((field) => field.ref));
      const requiredSkipped = scan.fieldMapping.filter(
        (entry) => requiredRefs.has(entry.ref) && entry.action === "skip",
      );
      const filled = await handleFill(scan, tabId);
      if (filled.failedCount) throw new Error(`Step ${step}: ${filled.failedCount} fields failed to fill`);
      logLines.push(`Step ${step}: ${filled.logLines[0]}`);
      const unanswered = await unansweredLinkedInRequired(tabId, scan, requiredSkipped);
      if (unanswered.length) {
        const labels = scan.formSnapshot.filter((field) => unanswered.includes(field.ref))
          .map((field) => field.label || field.section || field.name || "Unnamed field");
        throw new Error(`Step ${step}: answer required field${unanswered.length === 1 ? "" : "s"}: ${labels.join("; ").slice(0, 300)}`);
      }
    }
    // A human-initiated run leaves the final submission to the applicant.
    if (state.kind === "submit" && !autoSubmit) {
      return { ok: true, status: "ready_to_submit", logLines };
    }
    if (state.kind === "submit") {
      const before = await browser.scripting.executeScript({
        target: { tabId, allFrames: true }, func: submittedConfirmation,
      });
      if (before.some((frame) => frame.result)) throw new Error("Submission confirmation was already visible");
      const submitted = await linkedInStep(tabId, "submit");
      if (!submitted.ok) throw new Error(submitted.reason);
      await new Promise((resolve) => setTimeout(resolve, 4000));
      const confirmation = await browser.scripting.executeScript({
        target: { tabId, allFrames: true }, func: submittedConfirmation,
      });
      if (!confirmation.some((frame) => frame.result)) throw new Error("Submit clicked, but no confirmation was detected");
      return { ok: true, status: "applied", logLines };
    }
    const advanced = await linkedInStep(tabId, state.kind);
    if (!advanced.ok) throw new Error(`Step ${step}: ${advanced.reason}`);
    state = await waitForLinkedInStep(tabId, advanced.signature);
  }
  throw new Error("Easy Apply exceeded 12 steps; inspect the open dialog");
}

function submitJobForm() {
  const visible = (el) => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.display !== "none" && style.visibility !== "hidden";
  };
  const buttons = Array.from(document.querySelectorAll('button, input[type="submit"]'))
    .filter((el) => !el.disabled && visible(el))
    .filter((el) => /^(submit( application)?|send application|apply now)$/i.test(
      (el.innerText || el.value || el.getAttribute("aria-label") || "").trim(),
    ));
  if (buttons.length !== 1) return { clicked: false, reason: `Found ${buttons.length} final submit buttons` };
  const form = buttons[0].closest("form");
  if (form && !form.checkValidity()) return { clicked: false, reason: "The form has invalid required fields" };
  buttons[0].click();
  return { clicked: true };
}

function submittedConfirmation() {
  const text = (document.body?.innerText || "").slice(0, 10000);
  return /application (has been )?(submitted|received|sent)|thank you for applying|we (have )?received your application/i.test(text)
    || /\/(thank-you|application-submitted)(\/|\?|$)/i.test(location.pathname);
}

async function finishOpportunity(item, status, note) {
  await fetch(`${CORE_URL}/api/v1/opportunities/${item.id}/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, note }),
  });
}

async function applyOpportunity(item) {
  let tab;
  try {
    tab = await browser.tabs.create({ url: item.url, active: false });
    await waitForTab(tab.id);
    if (new URL(item.url).hostname === "www.linkedin.com") {
      const result = await fillLinkedInSteps(tab.id, item.cv_id, true);
      await finishOpportunity(item, "applied", `LinkedIn Easy Apply: ${result.logLines.join("; ")}`);
      return;
    }
    let scan = await handleScan({ url: item.url, cvId: item.cv_id }, tab.id);
    if (!scan.fieldMapping?.length) {
      const [{ result: applyUrl }] = await browser.scripting.executeScript({
        target: { tabId: tab.id }, func: findApplyLink,
      });
      if (!applyUrl) throw new Error("No application form or single Apply link was found");
      await browser.tabs.update(tab.id, { url: applyUrl });
      await waitForTab(tab.id);
      scan = await handleScan({ url: applyUrl, cvId: item.cv_id }, tab.id);
    }
    if (!scan.fieldMapping?.length) throw new Error("No application fields were found");
    const requiredRefs = new Set(scan.formSnapshot.filter((field) => field.required).map((field) => field.ref));
    const requiredSkipped = scan.fieldMapping.filter(
      (entry) => requiredRefs.has(entry.ref) && entry.action === "skip",
    );
    // A skipped answer can contain consent or logistics the applicant has to
    // decide. Never submit a form with any such unanswered field.
    if (requiredSkipped.length) throw new Error(`${requiredSkipped.length} fields need an answer`);
    const filled = await handleFill(scan, tab.id);
    if (filled.failedCount) throw new Error(`${filled.failedCount} fields failed to fill`);
    const frameCounts = new Map();
    for (const frame of Object.values(scan.refFrameMap)) {
      frameCounts.set(frame.frameId, (frameCounts.get(frame.frameId) || 0) + 1);
    }
    const frameId = [...frameCounts].sort((a, b) => b[1] - a[1])[0]?.[0] ?? 0;
    const before = await browser.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true }, func: submittedConfirmation,
    });
    if (before.some((frame) => frame.result)) {
      throw new Error("The page already shows a submission confirmation");
    }
    const [{ result }] = await browser.scripting.executeScript({
      target: { tabId: tab.id, frameIds: [frameId] }, func: submitJobForm,
    });
    if (!result.clicked) throw new Error(result.reason);
    await new Promise((resolve) => setTimeout(resolve, 4000));
    const confirmation = await browser.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true }, func: submittedConfirmation,
    });
    if (!confirmation.some((frame) => frame.result)) {
      throw new Error("Submit was clicked, but no confirmation was detected; inspect the open tab");
    }
    await finishOpportunity(item, "applied", "Confirmation detected after submission");
  } catch (err) {
    logBg("AUTO_APPLY_REVIEW", { id: item.id, error: String(err) });
    await finishOpportunity(item, "needs_review", String(err));
  }
}

let opportunityPollRunning = false;
async function processOpportunityQueue() {
  if (opportunityPollRunning) return;
  opportunityPollRunning = true;
  try {
    const response = await fetch(`${CORE_URL}/api/v1/opportunities/next/`, { method: "POST" });
    if (response.status === 204) return;
    if (!response.ok) throw new Error(`core returned ${response.status}`);
    await applyOpportunity(await response.json());
  } catch (err) {
    logBg("OPPORTUNITY_POLL_FAILED", { error: String(err) });
  } finally {
    opportunityPollRunning = false;
  }
}

browser.alarms.create("job-filler-opportunities", { periodInMinutes: 30 });
browser.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "job-filler-opportunities") processOpportunityQueue();
});
processOpportunityQueue();
