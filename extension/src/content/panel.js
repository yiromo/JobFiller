(() => {
  if (window.__jfPanelMounted) return;
  window.__jfPanelMounted = true;

  // Inlined: a content script fetching its own extension files needs web_accessible_resources.
  const PANEL_CSS = `
:host {
  all: initial;
  font-family: Arial, Helvetica, "Helvetica Neue", sans-serif;
  font-size: 15px;
  -webkit-font-smoothing: antialiased;
}

* {
  box-sizing: border-box;
}

.jf-corner-tab {
  position: fixed;
  top: 50%;
  right: 0;
  transform: translateY(-50%);
  width: 44px;
  height: 76px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #161616;
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-right: none;
  box-shadow: -4px 0 16px rgba(0, 0, 0, 0.5);
  cursor: pointer;
  opacity: 1;
  transition:
    transform 260ms cubic-bezier(0.22, 1, 0.36, 1) 80ms,
    opacity 160ms ease 80ms,
    visibility 0s;
}

.jf-corner-tab:hover {
  background: #000000;
  border-color: #ffffff;
}

.jf-corner-tab[hidden] {
  display: flex;
  visibility: hidden;
  pointer-events: none;
  opacity: 0;
  transform: translate(calc(100% + 8px), -50%);
  transition:
    transform 200ms cubic-bezier(0.4, 0, 1, 1),
    opacity 140ms ease,
    visibility 0s linear 200ms;
}

.jf-panel {
  position: fixed;
  top: 16px;
  right: 16px;
  bottom: 16px;
  width: 440px;
  max-width: calc(100vw - 32px);
  display: flex;
  flex-direction: column;
  background: #161616;
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.3);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6);
  overflow-y: auto;
  opacity: 1;
  transform: translateX(0);
  transition:
    transform 280ms cubic-bezier(0.22, 1, 0.36, 1),
    opacity 200ms ease,
    visibility 0s;
}

.jf-panel[hidden] {
  display: flex;
  visibility: hidden;
  pointer-events: none;
  opacity: 0;
  transform: translateX(calc(100% + 32px));
  transition:
    transform 240ms cubic-bezier(0.55, 0, 1, 0.45),
    opacity 180ms ease,
    visibility 0s linear 240ms;
}

@media (prefers-reduced-motion: reduce) {
  .jf-corner-tab,
  .jf-corner-tab[hidden],
  .jf-panel,
  .jf-panel[hidden] {
    transition: none;
  }
}

.jf-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  flex: none;
}

.jf-logo-wrap {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.jf-logo {
  font-weight: 700;
  letter-spacing: 0.1em;
  font-size: 15px;
  color: #ffffff;
}

.jf-version {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}

.jf-close {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.6);
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 6px;
}

.jf-close:hover {
  color: #ffffff;
}

.jf-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.jf-row {
  display: flex;
  gap: 10px;
}

.jf-row > .jf-btn {
  flex: 1;
}

.jf-tabs {
  display: flex;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  margin: 0 -20px;
  padding: 0 20px;
}

.jf-tab {
  flex: 1;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: rgba(255, 255, 255, 0.6);
  padding: 13px 6px;
  font-family: inherit;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  cursor: pointer;
}

.jf-tab:hover {
  color: #ffffff;
}

.jf-tab[aria-selected="true"] {
  color: #ffffff;
  border-bottom-color: #ffffff;
}

.jf-tab-panel[hidden] {
  display: none;
}

.jf-tab-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.jf-big-btn {
  flex: none;
  width: 100%;
  padding: 17px 18px;
  font-size: 16px;
  font-weight: 700;
}

.jf-link-btn {
  align-self: flex-start;
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.6);
  font-size: 13px;
  text-decoration: underline;
  cursor: pointer;
  padding: 0;
  font-family: inherit;
}

.jf-link-btn:hover {
  color: #ffffff;
}

.jf-link-btn[hidden] {
  display: none;
}


.jf-hint {
  margin: 0;
  color: rgba(255, 255, 255, 0.6);
  font-size: 13px;
  line-height: 1.5;
}

.jf-hint[hidden] {
  display: none;
}

.jf-select {
  flex: 1;
  min-width: 0;
}

.jf-select,
.jf-btn,
.jf-textarea {
  background: #000000;
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.3);
  padding: 11px 14px;
  font-family: inherit;
  font-size: 14px;
}

.jf-btn {
  cursor: pointer;
  text-align: center;
}

.jf-btn:hover:not(:disabled) {
  border-color: #ffffff;
  background: rgba(255, 255, 255, 0.08);
}

.jf-btn:disabled {
  cursor: default;
  opacity: 0.4;
}

.jf-btn-primary {
  border-color: #ffffff;
}

.jf-progress-btn {
  --jf-progress: 0%;
  background: linear-gradient(
    to right,
    rgba(255, 255, 255, 0.18) var(--jf-progress),
    #000000 var(--jf-progress)
  );
}

.jf-progress-btn.jf-progress-done,
.jf-progress-btn.jf-progress-done:hover:not(:disabled) {
  background: #ffffff;
  border-color: #ffffff;
  color: #000000;
}

.jf-btn.jf-busy:disabled {
  opacity: 1;
  cursor: progress;
}

.jf-icon-btn {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  padding: 0;
}

.jf-status {
  margin: 0;
  color: rgba(255, 255, 255, 0.6);
  font-size: 14px;
  line-height: 1.5;
}

.jf-textarea {
  width: 100%;
  height: 180px;
  resize: vertical;
  line-height: 1.6;
}

.jf-log {
  margin: 0;
  max-height: 240px;
  overflow-y: auto;
  background: #000000;
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 10px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  letter-spacing: normal;
  color: rgba(255, 255, 255, 0.6);
}

.jf-log-full {
  max-height: 520px;
}

.jf-log-mini {
  max-height: 170px;
}

.jf-card {
  position: relative;
  background: #000000;
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 14px;
}

.jf-card[hidden] {
  display: none;
}

.jf-corner-frame::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.6;
  background-repeat: no-repeat;
  background-image:
    linear-gradient(#ffffff, #ffffff),
    linear-gradient(#ffffff, #ffffff),
    linear-gradient(#ffffff, #ffffff),
    linear-gradient(#ffffff, #ffffff),
    linear-gradient(#ffffff, #ffffff),
    linear-gradient(#ffffff, #ffffff),
    linear-gradient(#ffffff, #ffffff),
    linear-gradient(#ffffff, #ffffff);
  background-size:
    12px 1px, 1px 12px,
    12px 1px, 1px 12px,
    12px 1px, 1px 12px,
    12px 1px, 1px 12px;
  background-position:
    left top, left top,
    right top, right top,
    left bottom, left bottom,
    right bottom, right bottom;
}

.jf-article {
  padding: 20px;
}

.jf-score {
  font-size: 30px;
  font-weight: 700;
  color: #ffffff;
  margin-bottom: 8px;
}

.jf-summary {
  margin: 0 0 10px;
  color: #ffffff;
  font-size: 14px;
  line-height: 1.65;
}

.jf-section {
  margin-top: 16px;
}

.jf-section h2 {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(255, 255, 255, 0.6);
  margin: 0 0 8px;
  font-weight: 700;
}

.jf-section ul {
  margin: 0;
  padding-left: 18px;
}

.jf-section li {
  margin-bottom: 8px;
  font-size: 14px;
  line-height: 1.55;
}

.jf-section p {
  margin: 0;
  font-size: 14px;
  line-height: 1.55;
}

.jf-source {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.6);
  text-decoration: underline;
}

.jf-source:hover {
  color: #ffffff;
}

.jf-log::-webkit-scrollbar,
.jf-panel::-webkit-scrollbar {
  width: 10px;
}

.jf-log::-webkit-scrollbar-track,
.jf-panel::-webkit-scrollbar-track {
  background: #161616;
}

.jf-log::-webkit-scrollbar-thumb,
.jf-panel::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.3);
}
`;

  const SVG_NS = "http://www.w3.org/2000/svg";
  const JF_VERSION = `${browser.runtime.getManifest().version}-${JF_BUILD}`;

  // Builds DOM nodes directly (no innerHTML/HTML-string parsing) so the
  // panel skeleton is constructed the same safe way as everything else this
  // extension renders.
  function h(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) node.setAttribute(key, value);
    for (const child of children) node.append(child);
    return node;
  }

  function svgIcon(pathData, size) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", String(size));
    svg.setAttribute("height", String(size));
    svg.setAttribute("fill", "currentColor");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", pathData);
    svg.appendChild(path);
    return svg;
  }

  function buildPanel() {
    const cornerTab = h(
      "div",
      { id: "jf-corner-tab", class: "jf-corner-tab", role: "button", tabindex: "0", "aria-label": "Open JobFiller", title: "JobFiller" },
      [svgIcon("M4 4h16v3.2H4zM4 10.4h11.2v3.2H4zM4 16.8h16V20H4z", 20)],
    );

    const closeBtn = h("button", { type: "button", id: "jf-close-btn", class: "jf-close", "aria-label": "Close" });
    closeBtn.textContent = "×";

    const logo = h("span", { class: "jf-logo" });
    logo.textContent = "JOBFILLER";

    const version = h("span", { id: "jf-version", class: "jf-version" });
    version.textContent = `v${JF_VERSION}`;

    const logoWrap = h("div", { class: "jf-logo-wrap" }, [logo, version]);

    const header = h("div", { class: "jf-header" }, [logoWrap, closeBtn]);

    const cvSelect = h("select", { id: "jf-cv-select", class: "jf-select" });
    const noCvOption = document.createElement("option");
    noCvOption.value = "";
    noCvOption.textContent = "No CV selected";
    cvSelect.appendChild(noCvOption);

    const manageBtn = h("button", {
      type: "button",
      id: "jf-manage-btn",
      class: "jf-icon-btn",
      title: "Manage CVs & Settings",
      "aria-label": "Manage CVs & Settings",
    }, [
      svgIcon(
        "M19.14 12.94a7.14 7.14 0 0 0 .06-.94 7.14 7.14 0 0 0-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.03 7.03 0 0 0-1.62-.94l-.36-2.54a.5.5 0 0 0-.5-.42h-3.84a.5.5 0 0 0-.5.42l-.36 2.54c-.59.24-1.13.56-1.62.94l-2.39-.96a.5.5 0 0 0-.6.22L2.71 8.84a.5.5 0 0 0 .12.64l2.03 1.58c-.04.31-.06.62-.06.94s.02.63.06.94l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.14.24.42.32.6.22l2.39-.96c.49.38 1.03.7 1.62.94l.36 2.54c.05.24.26.42.5.42h3.84c.24 0 .45-.18.5-.42l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.24.1.5 0 .6-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58ZM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7Z",
        18,
      ),
    ]);

    const row = h("div", { class: "jf-row" }, [cvSelect, manageBtn]);

    const status = h("p", { id: "jf-status", class: "jf-status" });
    status.textContent = "Ready.";

    const tabScan = h("button", {
      type: "button",
      id: "jf-tab-scan",
      class: "jf-tab",
      role: "tab",
      "aria-selected": "true",
    });
    tabScan.textContent = "Scanner/Filler";
    const tabAnalyze = h("button", {
      type: "button",
      id: "jf-tab-analyze",
      class: "jf-tab",
      role: "tab",
      "aria-selected": "false",
    });
    tabAnalyze.textContent = "Analyze application";
    const tabLogs = h("button", {
      type: "button",
      id: "jf-tab-logs",
      class: "jf-tab",
      role: "tab",
      "aria-selected": "false",
    });
    tabLogs.textContent = "Logs";
    const tabs = h("div", { class: "jf-tabs", role: "tablist" }, [tabScan, tabAnalyze, tabLogs]);

    const scanBtn = h("button", {
      type: "button",
      id: "jf-scan-btn",
      class: "jf-btn jf-btn-primary jf-big-btn jf-progress-btn",
      "data-mode": "scan",
      disabled: "",
    });
    scanBtn.textContent = "Scan & Fill";
    const rescanBtn = h("button", { type: "button", id: "jf-rescan-btn", class: "jf-link-btn", hidden: "" });
    rescanBtn.textContent = "Re-scan";
    const linkedInStepsBtn = h("button", {
      type: "button", id: "jf-linkedin-steps-btn", class: "jf-btn jf-big-btn",
      hidden: "", disabled: "",
    });
    linkedInStepsBtn.textContent = "Fill Easy Apply steps";

    const generateClBtn = h("button", {
      type: "button",
      id: "jf-generate-cl-btn",
      class: "jf-btn jf-big-btn",
      disabled: "",
    });
    generateClBtn.textContent = "Generate cover letter";

    const coverLetterPreview = h("textarea", { id: "jf-cover-letter-preview", class: "jf-textarea", readonly: "", hidden: "" });

    const scanLogEl = h("pre", { id: "jf-scan-log", class: "jf-log jf-log-mini", hidden: "" });

    const panelScan = h("div", { id: "jf-panel-scan", class: "jf-tab-panel", role: "tabpanel" }, [
      scanBtn,
      rescanBtn,
      linkedInStepsBtn,
      generateClBtn,
      coverLetterPreview,
      scanLogEl,
    ]);

    const analyzeBtn = h("button", {
      type: "button",
      id: "jf-analyze-btn",
      class: "jf-btn jf-btn-primary jf-big-btn jf-progress-btn",
      disabled: "",
    });
    analyzeBtn.textContent = "Analyze application";
    const analyzeHint = h("p", { id: "jf-analyze-hint", class: "jf-hint" });
    analyzeHint.textContent = "Scan the page in Scanner/Filler first.";
    const analysisResult = h("div", { id: "jf-analysis-result", class: "jf-card jf-corner-frame jf-article", hidden: "" });
    const analyzeAgainBtn = h("button", { type: "button", id: "jf-analyze-again-btn", class: "jf-link-btn", hidden: "" });
    analyzeAgainBtn.textContent = "Analyze again";

    const panelAnalyze = h("div", { id: "jf-panel-analyze", class: "jf-tab-panel", role: "tabpanel", hidden: "" }, [
      analyzeBtn,
      analyzeHint,
      analysisResult,
      analyzeAgainBtn,
    ]);

    const copyLogsBtn = h("button", { type: "button", id: "jf-copy-logs-btn", class: "jf-btn" });
    copyLogsBtn.textContent = "Copy logs";
    const downloadLogsBtn = h("button", { type: "button", id: "jf-download-logs-btn", class: "jf-btn" });
    downloadLogsBtn.textContent = "Download .txt";
    const logsActions = h("div", { class: "jf-row" }, [copyLogsBtn, downloadLogsBtn]);
    const logEl = h("pre", { id: "jf-log", class: "jf-log jf-log-full" });

    const panelLogs = h("div", { id: "jf-panel-logs", class: "jf-tab-panel", role: "tabpanel", hidden: "" }, [
      logsActions,
      logEl,
    ]);

    const body = h("div", { class: "jf-body" }, [row, status, tabs, panelScan, panelAnalyze, panelLogs]);

    const panel = h("div", { id: "jf-panel", class: "jf-panel", hidden: "" }, [header, body]);

    return [cornerTab, panel];
  }

  let myTabId = null;
  let lastFieldMapping = null;
  let refFrameMap = {};
  let cvsCache = [];
  let lastApplicationId = null;
  let lastPageText = "";
  let lastAboutText = "";
  let lastAnalysis = null;

  const host = document.createElement("div");
  host.id = "job-filler-panel-host";
  // Inline + !important, not a :host{} rule in the shadow stylesheet — a page's own
  // stylesheet can out-specificity :host, but almost never beats an inline style.
  for (const [prop, value] of Object.entries({
    position: "fixed",
    top: "0",
    left: "0",
    "z-index": "2147483647",
    "font-family": 'Arial, Helvetica, "Helvetica Neue", sans-serif',
    "font-size": "15px",
    "font-weight": "400",
    "font-style": "normal",
    color: "#ffffff",
    "line-height": "normal",
    "letter-spacing": "normal",
    "word-spacing": "normal",
    "text-transform": "none",
    "text-indent": "0",
    "white-space": "normal",
    direction: "ltr",
  })) {
    host.style.setProperty(prop, value, "important");
  }
  document.body.appendChild(host);
  const shadow = host.attachShadow({ mode: "closed" });

  const SUPPORTS_MODAL_SELECTOR = CSS.supports("selector(:modal)");
  const anchorObserver = new MutationObserver(queueHostSync);
  let hostSyncQueued = false;

  function topmostModalDialog() {
    if (!SUPPORTS_MODAL_SELECTOR) return null;
    let found = null;
    for (const dialog of document.querySelectorAll("dialog[open]")) {
      if (dialog.matches(":modal")) found = dialog;
    }
    return found;
  }

  function syncHostParent() {
    const target = topmostModalDialog() || document.body;
    anchorObserver.disconnect();
    if (host.parentElement !== target) target.appendChild(host);
    if (target !== document.body && target.parentNode) {
      anchorObserver.observe(target.parentNode, { childList: true });
    }
  }

  function queueHostSync() {
    if (hostSyncQueued) return;
    hostSyncQueued = true;
    requestAnimationFrame(() => {
      hostSyncQueued = false;
      syncHostParent();
    });
  }

  new MutationObserver(queueHostSync).observe(document.documentElement, {
    subtree: true,
    attributes: true,
    attributeFilter: ["open"],
  });

  syncHostParent();

  const $ = (id) => shadow.getElementById(id);

  function mount(css) {
    const style = document.createElement("style");
    style.textContent = css;
    shadow.appendChild(style);
    for (const node of buildPanel()) shadow.appendChild(node);
    wireUp();
    $("jf-linkedin-steps-btn").hidden = window.location.hostname !== "www.linkedin.com";
    log(`BOOT version=${JF_VERSION} url=${window.location.href}`);
    loadCvs()
      .then(() => {
        if ($("jf-scan-btn").dataset.mode === "scan") {
          $("jf-scan-btn").disabled = !$("jf-cv-select").value;
        }
        $("jf-linkedin-steps-btn").disabled = !$("jf-cv-select").value;
      })
      .catch((err) => {
        setStatus("Could not reach core API.");
        log(String(err));
      });
    restoreScanState();
  }

  function timestamp() {
    const d = new Date();
    return `${d.toTimeString().slice(0, 8)}.${String(d.getMilliseconds()).padStart(3, "0")}`;
  }

  function log(message, mirrorId) {
    const line = `[${timestamp()}] ${message}\n`;
    const el = $("jf-log");
    el.textContent += line;
    el.scrollTop = el.scrollHeight;
    if (mirrorId) {
      const mirrorEl = $(mirrorId);
      mirrorEl.hidden = false;
      mirrorEl.textContent += line;
      mirrorEl.scrollTop = mirrorEl.scrollHeight;
    }
  }

  function logEvent(action, details) {
    const parts = details
      ? Object.entries(details)
          .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
          .join(" ")
      : "";
    log(`${action}${parts ? ` ${parts}` : ""}`);
  }

  function setStatus(message) {
    $("jf-status").textContent = message;
  }

  async function send(type, payload) {
    logEvent("SEND", { type });
    try {
      const result = await browser.runtime.sendMessage({ type, ...payload });
      logEvent("RECV", { type, ok: result ? result.ok !== false : true });
      return result;
    } catch (err) {
      logEvent("RECV_ERROR", { type, error: String(err && err.message ? err.message : err) });
      throw err;
    }
  }

  function runProgress(btn, tau) {
    btn.classList.remove("jf-progress-done");
    btn.classList.add("jf-busy");
    const startedAt = Date.now();
    const tick = () => {
      const elapsed = (Date.now() - startedAt) / 1000;
      const pct = 92 * (1 - Math.exp(-elapsed / tau));
      btn.style.setProperty("--jf-progress", `${pct.toFixed(1)}%`);
    };
    tick();
    const interval = setInterval(tick, 100);
    return {
      stop: () => {
        clearInterval(interval);
        btn.classList.remove("jf-busy");
      },
      startedAt,
    };
  }

  function finishProgress(btn) {
    btn.style.setProperty("--jf-progress", "100%");
    btn.classList.add("jf-progress-done");
  }

  function resetProgress(btn) {
    btn.style.setProperty("--jf-progress", "0%");
    btn.classList.remove("jf-progress-done");
  }

  function setActiveTab(tab) {
    const target = ["scan", "analyze", "logs"].includes(tab) ? tab : "scan";
    for (const name of ["scan", "analyze", "logs"]) {
      $(`jf-tab-${name}`).setAttribute("aria-selected", String(name === target));
      $(`jf-panel-${name}`).hidden = name !== target;
    }
  }

  function getActiveTab() {
    for (const name of ["scan", "analyze", "logs"]) {
      if ($(`jf-tab-${name}`).getAttribute("aria-selected") === "true") return name;
    }
    return "scan";
  }

  async function saveScanState() {
    if (myTabId == null) return;
    await send("saveState", {
      state: {
        url: window.location.href,
        fieldMapping: lastFieldMapping,
        refFrameMap,
        logText: $("jf-log").textContent,
        applicationId: lastApplicationId,
        pageText: lastPageText,
        aboutText: lastAboutText,
        coverLetterText: $("jf-cover-letter-preview").hidden
          ? ""
          : $("jf-cover-letter-preview").value,
        analysis: lastAnalysis,
        activeTab: getActiveTab(),
        panelOpen: !$("jf-panel").hidden,
      },
    });
  }

  async function restoreScanState() {
    const { tabId } = await send("whoami", {});
    myTabId = tabId;
    if (myTabId == null) return;

    const { entry } = await send("getState", {});
    if (!entry || entry.url !== window.location.href) return;

    lastFieldMapping = entry.fieldMapping;
    refFrameMap = entry.refFrameMap || {};
    $("jf-log").textContent = (entry.logText || "") + $("jf-log").textContent;
    lastApplicationId = entry.applicationId || null;
    lastPageText = entry.pageText || "";
    lastAboutText = entry.aboutText || "";

    const scanBtn = $("jf-scan-btn");
    if (lastFieldMapping) {
      scanBtn.dataset.mode = "fill";
      scanBtn.textContent = window.location.hostname === "www.linkedin.com"
        ? "Fill & continue Easy Apply" : "Fill application";
      scanBtn.disabled = false;
      finishProgress(scanBtn);
      $("jf-rescan-btn").hidden = false;
    }
    $("jf-generate-cl-btn").disabled = !lastApplicationId;
    $("jf-analyze-btn").disabled = !lastApplicationId;
    $("jf-analyze-hint").hidden = Boolean(lastApplicationId);

    if (entry.coverLetterText) {
      $("jf-cover-letter-preview").value = entry.coverLetterText;
      $("jf-cover-letter-preview").hidden = false;
    }

    lastAnalysis = entry.analysis || null;
    if (lastAnalysis) {
      renderAnalysis(lastAnalysis);
      $("jf-analyze-btn").hidden = true;
      $("jf-analyze-again-btn").hidden = false;
    }

    if (lastFieldMapping) setStatus("Restored previous scan — review, then Fill.");
    setActiveTab(entry.activeTab || "scan");
    if (entry.panelOpen) openPanel();
  }

  function openPanel() {
    $("jf-panel").hidden = false;
    $("jf-corner-tab").hidden = true;
    saveScanState();
  }

  function closePanel() {
    $("jf-panel").hidden = true;
    $("jf-corner-tab").hidden = false;
    saveScanState();
  }

  async function loadCvs(selectId) {
    const { ok, cvs, error } = await send("loadCvs", {});
    if (!ok) throw new Error(error);
    cvsCache = cvs;

    const select = $("jf-cv-select");
    select.innerHTML = '<option value="">No CV selected</option>';
    for (const cv of cvsCache) {
      const option = document.createElement("option");
      option.value = String(cv.id);
      option.textContent = `${cv.full_name || cv.original_filename} — ${cv.original_filename}`;
      select.appendChild(option);
    }
    if (selectId) select.value = String(selectId);
  }

  function safeExternalUrl(url) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.href;
    } catch (err) {
      return null;
    }
    return null;
  }

  // Built via textContent, never innerHTML — these strings trace back to web search results.
  function appendSourcedList(container, title, items) {
    if (!items || items.length === 0) return;
    const section = document.createElement("div");
    section.className = "jf-section";
    const heading = document.createElement("h2");
    heading.textContent = title;
    section.appendChild(heading);

    const list = document.createElement("ul");
    for (const item of items) {
      const li = document.createElement("li");
      li.appendChild(document.createTextNode(item.point || ""));
      const url = safeExternalUrl(item.url);
      if (url) {
        li.appendChild(document.createTextNode(" "));
        const link = document.createElement("a");
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.className = "jf-source";
        link.textContent = item.published_date ? `source (${item.published_date})` : "source";
        li.appendChild(link);
      }
      list.appendChild(li);
    }
    section.appendChild(list);
    container.appendChild(section);
  }

  function renderAnalysis(data) {
    const container = $("jf-analysis-result");
    while (container.firstChild) container.removeChild(container.firstChild);

    const score = document.createElement("div");
    score.className = "jf-score";
    score.textContent = `Fit score: ${data.fit_score}/100`;
    container.appendChild(score);

    const summary = document.createElement("p");
    summary.className = "jf-summary";
    summary.textContent = data.fit_summary || "";
    container.appendChild(summary);

    appendSourcedList(container, "Company insights", data.company_insights);
    appendSourcedList(container, "Market stats", data.market_stats);

    if (data.apply_timing) {
      const section = document.createElement("div");
      section.className = "jf-section";
      const heading = document.createElement("h2");
      heading.textContent = "When to apply";
      section.appendChild(heading);
      const p = document.createElement("p");
      p.textContent = data.apply_timing;
      section.appendChild(p);
      container.appendChild(section);
    }

    if (data.suggestions && data.suggestions.length) {
      const section = document.createElement("div");
      section.className = "jf-section";
      const heading = document.createElement("h2");
      heading.textContent = "Other ideas";
      section.appendChild(heading);
      const list = document.createElement("ul");
      for (const suggestion of data.suggestions) {
        const li = document.createElement("li");
        li.textContent = suggestion;
        list.appendChild(li);
      }
      section.appendChild(list);
      container.appendChild(section);
    }

    container.hidden = false;
  }

  function wireUp() {
    $("jf-corner-tab").addEventListener("click", () => {
      logEvent("CLICK", { id: "corner-tab" });
      openPanel();
    });
    $("jf-corner-tab").addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        logEvent("CLICK", { id: "corner-tab", via: "keydown" });
        openPanel();
      }
    });
    $("jf-close-btn").addEventListener("click", () => {
      logEvent("CLICK", { id: "close-btn" });
      closePanel();
    });

    $("jf-manage-btn").addEventListener("click", () => {
      logEvent("CLICK", { id: "manage-btn" });
      send("openManage", {});
    });

    $("jf-cv-select").addEventListener("change", (e) => {
      logEvent("CHANGE", { id: "cv-select", value: e.target.value });
      if ($("jf-scan-btn").dataset.mode === "scan") {
        $("jf-scan-btn").disabled = !e.target.value;
      }
      $("jf-linkedin-steps-btn").disabled = !e.target.value;
    });

    function switchTab(tab, sourceId) {
      logEvent("CLICK", { id: sourceId });
      setActiveTab(tab);
      saveScanState();
    }

    $("jf-tab-scan").addEventListener("click", () => switchTab("scan", "tab-scan"));
    $("jf-tab-analyze").addEventListener("click", () => switchTab("analyze", "tab-analyze"));
    $("jf-tab-logs").addEventListener("click", () => switchTab("logs", "tab-logs"));

    $("jf-copy-logs-btn").addEventListener("click", async () => {
      logEvent("CLICK", { id: "copy-logs-btn" });
      const text = $("jf-log").textContent;
      try {
        await navigator.clipboard.writeText(text);
        setStatus("Logs copied to clipboard.");
      } catch (err) {
        setStatus("Could not copy logs.");
        log(String(err));
      }
    });

    $("jf-download-logs-btn").addEventListener("click", () => {
      logEvent("CLICK", { id: "download-logs-btn" });
      const text = $("jf-log").textContent;
      const blob = new Blob([text], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `jobfiller-log-${Date.now()}.txt`;
      link.click();
      URL.revokeObjectURL(url);
    });

    async function runScan() {
      if (!$("jf-cv-select").value) {
        setStatus("Select a CV first.");
        return;
      }
      const scanBtn = $("jf-scan-btn");
      scanBtn.disabled = true;
      scanBtn.textContent = "Scanning...";
      scanBtn.dataset.mode = "scan";
      setStatus("Scanning...");
      $("jf-rescan-btn").hidden = true;
      $("jf-generate-cl-btn").disabled = true;
      $("jf-analyze-btn").disabled = true;
      $("jf-analyze-btn").hidden = false;
      $("jf-analyze-again-btn").hidden = true;
      $("jf-analyze-hint").hidden = false;
      $("jf-cover-letter-preview").hidden = true;
      $("jf-analysis-result").hidden = true;
      lastAnalysis = null;
      lastFieldMapping = null;
      lastApplicationId = null;
      lastPageText = "";
      lastAboutText = "";
      refFrameMap = {};
      $("jf-scan-log").textContent = "";
      $("jf-scan-log").hidden = true;

      // Scan has no incremental progress to report, so this approaches (never
      // reaches) 92% on an easing curve — a real finish always jumps the rest
      // of the way to 100%, so the bar never looks "done" before it is.
      const { stop, startedAt } = runProgress(scanBtn, 12);
      const labelTick = () => {
        const elapsed = Math.round((Date.now() - startedAt) / 1000);
        scanBtn.textContent = elapsed > 2 ? `Scanning... ${elapsed}s` : "Scanning...";
      };
      const labelTicker = setInterval(labelTick, 1000);

      try {
        const cvId = $("jf-cv-select").value ? Number($("jf-cv-select").value) : null;
        const result = await send("scan", { url: window.location.href, cvId });
        if (!result.ok) throw new Error(result.error);

        lastApplicationId = result.applicationId;
        lastFieldMapping = result.fieldMapping;
        refFrameMap = result.refFrameMap;
        lastPageText = result.pageText;
        lastAboutText = result.aboutText;
        result.logLines.forEach((line) => log(line, "jf-scan-log"));
        setStatus("Scanned — review, then Fill.");
        finishProgress(scanBtn);
        scanBtn.dataset.mode = "fill";
        scanBtn.textContent = window.location.hostname === "www.linkedin.com"
          ? "Fill & continue Easy Apply" : "Fill application";
        $("jf-rescan-btn").hidden = false;
        $("jf-generate-cl-btn").disabled = false;
        $("jf-analyze-btn").disabled = false;
        $("jf-analyze-hint").hidden = true;
        await saveScanState();
      } catch (err) {
        resetProgress(scanBtn);
        scanBtn.textContent = "Scan & Fill";
        setStatus("Scan failed.");
        log(String(err), "jf-scan-log");
      } finally {
        clearInterval(labelTicker);
        stop();
        scanBtn.disabled = scanBtn.dataset.mode === "scan" ? !$("jf-cv-select").value : false;
      }
    }

    async function runFill() {
      if (window.location.hostname === "www.linkedin.com") {
        await runLinkedInSteps();
        return;
      }
      if (!lastFieldMapping) return;
      const scanBtn = $("jf-scan-btn");
      scanBtn.disabled = true;
      $("jf-rescan-btn").hidden = true;
      const doneText = scanBtn.textContent;
      scanBtn.textContent = "Filling...";
      setStatus("Filling...");

      try {
        const result = await send("fill", {
          fieldMapping: lastFieldMapping,
          refFrameMap,
          applicationId: lastApplicationId,
        });
        if (!result.ok) throw new Error(result.error);
        result.logLines.forEach((line) => log(line, "jf-scan-log"));
        if (result.entries?.length) {
          const entriesByRef = Object.fromEntries(result.entries.map((e) => [e.ref, e]));
          lastFieldMapping = lastFieldMapping.map((item) => entriesByRef[item.ref] || item);
        }
        setStatus("Done — review before submitting.");
      } catch (err) {
        setStatus("Fill failed.");
        log(String(err), "jf-scan-log");
      } finally {
        scanBtn.textContent = doneText;
        scanBtn.disabled = false;
        if (scanBtn.dataset.mode === "fill") $("jf-rescan-btn").hidden = false;
      }
    }

    $("jf-scan-btn").addEventListener("click", () => {
      const mode = $("jf-scan-btn").dataset.mode;
      logEvent("CLICK", { id: "scan-btn", mode });
      if (mode === "fill") runFill();
      else runScan();
    });
    $("jf-rescan-btn").addEventListener("click", () => {
      logEvent("CLICK", { id: "rescan-btn" });
      runScan();
    });
    async function runLinkedInSteps() {
      const btn = $("jf-linkedin-steps-btn");
      const cvId = Number($("jf-cv-select").value);
      if (!cvId) return;
      btn.disabled = true;
      $("jf-scan-btn").disabled = true;
      btn.textContent = "Filling Easy Apply...";
      setStatus("Filling Easy Apply steps...");
      lastFieldMapping = null;
      lastApplicationId = null;
      lastPageText = "";
      lastAboutText = "";
      refFrameMap = {};
      $("jf-scan-btn").dataset.mode = "scan";
      $("jf-scan-btn").textContent = "Scan & Fill";
      $("jf-rescan-btn").hidden = true;
      $("jf-generate-cl-btn").disabled = true;
      $("jf-analyze-btn").disabled = true;
      try {
        const result = await send("fillLinkedInSteps", { cvId });
        if (!result.ok) throw new Error(result.error);
        result.logLines.forEach((line) => log(line, "jf-scan-log"));
        setStatus("Easy Apply filled — review and submit in LinkedIn.");
        await saveScanState();
      } catch (err) {
        setStatus(`Easy Apply paused — ${String(err).replace(/^(Error:\s*)+/, "")}`);
        log(String(err), "jf-scan-log");
        $("jf-scan-btn").dataset.mode = "fill";
        $("jf-scan-btn").textContent = "Continue Easy Apply";
      } finally {
        btn.textContent = "Fill Easy Apply steps";
        btn.disabled = false;
        $("jf-scan-btn").disabled = !$("jf-cv-select").value;
      }
    }
    $("jf-linkedin-steps-btn").addEventListener("click", runLinkedInSteps);

    $("jf-generate-cl-btn").addEventListener("click", async () => {
      logEvent("CLICK", { id: "generate-cl-btn" });
      if (!lastApplicationId) return;
      setStatus("Generating cover letter...");
      $("jf-generate-cl-btn").disabled = true;

      try {
        const result = await send("generateCoverLetter", {
          applicationId: lastApplicationId,
          pageText: lastPageText,
          aboutText: lastAboutText,
        });
        if (!result.ok) throw new Error(result.error);

        $("jf-cover-letter-preview").value = result.text;
        $("jf-cover-letter-preview").hidden = false;

        if (result.entries.length && lastFieldMapping) {
          const entriesByRef = Object.fromEntries(result.entries.map((e) => [e.ref, e]));
          lastFieldMapping = lastFieldMapping.map((item) => entriesByRef[item.ref] || item);
          log(`Cover letter regenerated — applied to ${result.entries.length} field(s), Fill will use it.`);
        } else {
          log("Cover letter generated — no cover-letter field detected on this page; it's in the preview box.");
        }
        setStatus("Cover letter ready.");
        await saveScanState();
      } catch (err) {
        setStatus("Cover letter generation failed.");
        log(String(err));
      } finally {
        $("jf-generate-cl-btn").disabled = false;
      }
    });

    async function runAnalyze() {
      if (!lastApplicationId) return;
      const analyzeBtn = $("jf-analyze-btn");
      analyzeBtn.disabled = true;
      analyzeBtn.hidden = false;
      $("jf-analysis-result").hidden = true;
      $("jf-analyze-again-btn").hidden = true;

      const { stop, startedAt } = runProgress(analyzeBtn, 18);
      const labelTick = () => {
        const elapsed = Math.round((Date.now() - startedAt) / 1000);
        analyzeBtn.textContent = `Analyzing... ${elapsed}s`;
      };
      labelTick();
      const labelTicker = setInterval(labelTick, 1000);
      setStatus("Analyzing application (searches the web, then writes the report)...");

      try {
        const result = await send("analyze", {
          applicationId: lastApplicationId,
          pageText: lastPageText,
          aboutText: lastAboutText,
        });
        if (!result.ok) throw new Error(result.error);

        lastAnalysis = result.analysis;
        finishProgress(analyzeBtn);
        renderAnalysis(lastAnalysis);
        analyzeBtn.hidden = true;
        $("jf-analyze-again-btn").hidden = false;
        log("Analysis ready.");
        setStatus(`Analysis ready (took ${Math.round((Date.now() - startedAt) / 1000)}s).`);
        await saveScanState();
      } catch (err) {
        resetProgress(analyzeBtn);
        analyzeBtn.textContent = "Analyze application";
        setStatus("Analysis failed.");
        log(String(err));
      } finally {
        clearInterval(labelTicker);
        stop();
        analyzeBtn.disabled = false;
      }
    }

    $("jf-analyze-btn").addEventListener("click", () => {
      logEvent("CLICK", { id: "analyze-btn" });
      runAnalyze();
    });
    $("jf-analyze-again-btn").addEventListener("click", () => {
      logEvent("CLICK", { id: "analyze-again-btn" });
      runAnalyze();
    });
  }

  mount(PANEL_CSS);
})();
