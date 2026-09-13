(() => {
  if (window.__jfPanelMounted) return;
  window.__jfPanelMounted = true;

  // Inlined: a content script fetching its own extension files needs web_accessible_resources.
  const PANEL_CSS = `
:host {
  all: initial;
  font-family: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  font-size: 13px;
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
  width: 36px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #111111;
  color: #4ade80;
  border: 1px solid #2a2a2a;
  border-right: none;
  box-shadow: -4px 0 16px rgba(0, 0, 0, 0.4);
  cursor: pointer;
}

.jf-corner-tab:hover {
  background: #1a1a1a;
  border-color: #3a3a3a;
}

.jf-corner-tab[hidden] {
  display: none;
}

.jf-panel {
  position: fixed;
  top: 16px;
  right: 16px;
  bottom: 16px;
  width: 340px;
  max-width: calc(100vw - 32px);
  display: flex;
  flex-direction: column;
  background: #0a0a0a;
  color: #e5e5e5;
  border: 1px solid #2a2a2a;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.55);
  overflow-y: auto;
}

.jf-panel[hidden] {
  display: none;
}

.jf-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #2a2a2a;
  flex: none;
}

.jf-logo-wrap {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.jf-logo {
  font-weight: 600;
  letter-spacing: 0.08em;
  font-size: 12px;
  color: #4ade80;
}

.jf-version {
  font-size: 10px;
  color: #6b6b6b;
}

.jf-close {
  background: none;
  border: none;
  color: #a0a0a0;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 4px;
}

.jf-close:hover {
  color: #e5e5e5;
}

.jf-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.jf-row {
  display: flex;
  gap: 8px;
}

.jf-tabs {
  display: flex;
  border-bottom: 1px solid #2a2a2a;
  margin: 0 -16px;
  padding: 0 16px;
}

.jf-tab {
  flex: 1;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: #a0a0a0;
  padding: 10px 4px;
  font-family: inherit;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  cursor: pointer;
}

.jf-tab:hover {
  color: #e5e5e5;
}

.jf-tab[aria-selected="true"] {
  color: #4ade80;
  border-bottom-color: #4ade80;
}

.jf-tab-panel[hidden] {
  display: none;
}

.jf-tab-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.jf-big-btn {
  flex: none;
  width: 100%;
  padding: 14px 16px;
  font-size: 14px;
  font-weight: 600;
}

.jf-link-btn {
  align-self: flex-start;
  background: none;
  border: none;
  color: #6b6b6b;
  font-size: 11px;
  text-decoration: underline;
  cursor: pointer;
  padding: 0;
  font-family: inherit;
}

.jf-link-btn:hover {
  color: #e5e5e5;
}

.jf-link-btn[hidden] {
  display: none;
}

.jf-hint {
  margin: 0;
  color: #6b6b6b;
  font-size: 11px;
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
  background: #111111;
  color: #e5e5e5;
  border: 1px solid #2a2a2a;
  padding: 7px 10px;
  font-family: inherit;
  font-size: 12px;
}

.jf-btn {
  cursor: pointer;
  text-align: center;
}

.jf-btn:hover:not(:disabled) {
  border-color: #4ade80;
  color: #4ade80;
}

.jf-btn:disabled {
  cursor: default;
  opacity: 0.4;
}

.jf-btn-primary {
  border-color: #4ade80;
  color: #4ade80;
}

.jf-progress-btn {
  --jf-progress: 0%;
  background: linear-gradient(
    to right,
    rgba(74, 222, 128, 0.22) var(--jf-progress),
    #111111 var(--jf-progress)
  );
}

.jf-progress-btn.jf-progress-done {
  background: #4ade80;
  border-color: #4ade80;
  color: #000000;
}

.jf-progress-btn.jf-progress-done:hover:not(:disabled) {
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
  width: 32px;
  padding: 0;
}

.jf-status {
  margin: 0;
  color: #a0a0a0;
  font-size: 12px;
}

.jf-textarea {
  width: 100%;
  height: 130px;
  resize: vertical;
}

.jf-log {
  margin: 0;
  max-height: 200px;
  overflow-y: auto;
  background: #111111;
  border: 1px solid #2a2a2a;
  padding: 8px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 11px;
  color: #a0a0a0;
}

.jf-card {
  position: relative;
  background: #111111;
  border: 1px solid #2a2a2a;
  padding: 12px;
}

.jf-card[hidden] {
  display: none;
}

.jf-corner-frame::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.35;
  background-repeat: no-repeat;
  background-image:
    linear-gradient(#4ade80, #4ade80),
    linear-gradient(#4ade80, #4ade80),
    linear-gradient(#4ade80, #4ade80),
    linear-gradient(#4ade80, #4ade80),
    linear-gradient(#4ade80, #4ade80),
    linear-gradient(#4ade80, #4ade80),
    linear-gradient(#4ade80, #4ade80),
    linear-gradient(#4ade80, #4ade80);
  background-size:
    10px 1px, 1px 10px,
    10px 1px, 1px 10px,
    10px 1px, 1px 10px,
    10px 1px, 1px 10px;
  background-position:
    left top, left top,
    right top, right top,
    left bottom, left bottom,
    right bottom, right bottom;
}

.jf-article {
  padding: 18px;
}

.jf-score {
  font-size: 26px;
  font-weight: 600;
  color: #4ade80;
  margin-bottom: 6px;
}

.jf-summary {
  margin: 0 0 8px;
  color: #e5e5e5;
  line-height: 1.6;
}

.jf-section {
  margin-top: 12px;
}

.jf-section h2 {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #6b6b6b;
  margin: 0 0 6px;
  font-weight: 600;
}

.jf-section ul {
  margin: 0;
  padding-left: 16px;
}

.jf-section li {
  margin-bottom: 6px;
  line-height: 1.4;
}

.jf-source {
  font-size: 11px;
  color: #4ade80;
  text-decoration: none;
}

.jf-source:hover {
  text-decoration: underline;
}

.jf-log::-webkit-scrollbar,
.jf-panel::-webkit-scrollbar {
  width: 8px;
}

.jf-log::-webkit-scrollbar-track,
.jf-panel::-webkit-scrollbar-track {
  background: #0a0a0a;
}

.jf-log::-webkit-scrollbar-thumb,
.jf-panel::-webkit-scrollbar-thumb {
  background: #2a2a2a;
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
      [svgIcon("M4 4h16v3.2H4zM4 10.4h11.2v3.2H4zM4 16.8h16V20H4z", 16)],
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
        14,
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
    const tabs = h("div", { class: "jf-tabs", role: "tablist" }, [tabScan, tabAnalyze]);

    const scanBtn = h("button", {
      type: "button",
      id: "jf-scan-btn",
      class: "jf-btn jf-btn-primary jf-big-btn jf-progress-btn",
      "data-mode": "scan",
    });
    scanBtn.textContent = "Scan & Fill";
    const rescanBtn = h("button", { type: "button", id: "jf-rescan-btn", class: "jf-link-btn", hidden: "" });
    rescanBtn.textContent = "Re-scan";

    const generateClBtn = h("button", {
      type: "button",
      id: "jf-generate-cl-btn",
      class: "jf-btn jf-big-btn",
      disabled: "",
    });
    generateClBtn.textContent = "Generate cover letter";

    const coverLetterPreview = h("textarea", { id: "jf-cover-letter-preview", class: "jf-textarea", readonly: "", hidden: "" });

    const panelScan = h("div", { id: "jf-panel-scan", class: "jf-tab-panel", role: "tabpanel" }, [
      scanBtn,
      rescanBtn,
      generateClBtn,
      coverLetterPreview,
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

    const logEl = h("pre", { id: "jf-log", class: "jf-log" });

    const body = h("div", { class: "jf-body" }, [row, status, tabs, panelScan, panelAnalyze, logEl]);

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
  })) {
    host.style.setProperty(prop, value, "important");
  }
  document.body.appendChild(host);
  const shadow = host.attachShadow({ mode: "closed" });

  const $ = (id) => shadow.getElementById(id);

  function mount(css) {
    const style = document.createElement("style");
    style.textContent = css;
    shadow.appendChild(style);
    for (const node of buildPanel()) shadow.appendChild(node);
    wireUp();
    log(`BOOT version=${JF_VERSION} url=${window.location.href}`);
    loadCvs().catch((err) => {
      setStatus("Could not reach core API.");
      log(String(err));
    });
    restoreScanState();
  }

  function timestamp() {
    const d = new Date();
    return `${d.toTimeString().slice(0, 8)}.${String(d.getMilliseconds()).padStart(3, "0")}`;
  }

  function log(message) {
    const el = $("jf-log");
    el.textContent += `[${timestamp()}] ${message}\n`;
    el.scrollTop = el.scrollHeight;
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
    const isScan = tab !== "analyze";
    $("jf-tab-scan").setAttribute("aria-selected", String(isScan));
    $("jf-tab-analyze").setAttribute("aria-selected", String(!isScan));
    $("jf-panel-scan").hidden = !isScan;
    $("jf-panel-analyze").hidden = isScan;
  }

  function getActiveTab() {
    return $("jf-tab-analyze").getAttribute("aria-selected") === "true" ? "analyze" : "scan";
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
      scanBtn.textContent = "Fill application";
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
    });

    $("jf-tab-scan").addEventListener("click", () => {
      logEvent("CLICK", { id: "tab-scan" });
      setActiveTab("scan");
      saveScanState();
    });
    $("jf-tab-analyze").addEventListener("click", () => {
      logEvent("CLICK", { id: "tab-analyze" });
      setActiveTab("analyze");
      saveScanState();
    });

    async function runScan() {
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
        result.logLines.forEach(log);
        setStatus("Scanned — review, then Fill.");
        finishProgress(scanBtn);
        scanBtn.dataset.mode = "fill";
        scanBtn.textContent = "Fill application";
        $("jf-rescan-btn").hidden = false;
        $("jf-generate-cl-btn").disabled = false;
        $("jf-analyze-btn").disabled = false;
        $("jf-analyze-hint").hidden = true;
        await saveScanState();
      } catch (err) {
        resetProgress(scanBtn);
        scanBtn.textContent = "Scan & Fill";
        setStatus("Scan failed.");
        log(String(err));
      } finally {
        clearInterval(labelTicker);
        stop();
        scanBtn.disabled = false;
      }
    }

    async function runFill() {
      if (!lastFieldMapping) return;
      const scanBtn = $("jf-scan-btn");
      scanBtn.disabled = true;
      $("jf-rescan-btn").hidden = true;
      const doneText = scanBtn.textContent;
      scanBtn.textContent = "Filling...";
      setStatus("Filling...");

      try {
        const result = await send("fill", { fieldMapping: lastFieldMapping, refFrameMap });
        if (!result.ok) throw new Error(result.error);
        result.logLines.forEach(log);
        setStatus("Done — review before submitting.");
      } catch (err) {
        setStatus("Fill failed.");
        log(String(err));
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
          log("Cover letter generated — no cover-letter field detected on this page; copy it above.");
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
