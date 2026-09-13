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

.jf-logo {
  font-weight: 600;
  letter-spacing: 0.08em;
  font-size: 12px;
  color: #4ade80;
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

.jf-row,
.jf-actions {
  display: flex;
  gap: 8px;
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
  flex: 1;
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

.jf-score {
  font-size: 22px;
  font-weight: 600;
  color: #4ade80;
  margin-bottom: 6px;
}

.jf-summary {
  margin: 0 0 8px;
  color: #e5e5e5;
  line-height: 1.5;
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

    const header = h("div", { class: "jf-header" }, [logo, closeBtn]);

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

    const scanBtn = h("button", { type: "button", id: "jf-scan-btn", class: "jf-btn jf-btn-primary" });
    scanBtn.textContent = "Scan this page";
    const fillBtn = h("button", { type: "button", id: "jf-fill-btn", class: "jf-btn", disabled: "" });
    fillBtn.textContent = "Fill application";
    const scanActions = h("div", { class: "jf-actions" }, [scanBtn, fillBtn]);

    const generateClBtn = h("button", { type: "button", id: "jf-generate-cl-btn", class: "jf-btn", disabled: "" });
    generateClBtn.textContent = "Generate cover letter";
    const clActions = h("div", { class: "jf-actions" }, [generateClBtn]);

    const coverLetterPreview = h("textarea", { id: "jf-cover-letter-preview", class: "jf-textarea", readonly: "", hidden: "" });

    const analyzeBtn = h("button", { type: "button", id: "jf-analyze-btn", class: "jf-btn", disabled: "" });
    analyzeBtn.textContent = "Analyze application";
    const analyzeActions = h("div", { class: "jf-actions" }, [analyzeBtn]);

    const analysisResult = h("div", { id: "jf-analysis-result", class: "jf-card jf-corner-frame", hidden: "" });
    const logEl = h("pre", { id: "jf-log", class: "jf-log" });

    const body = h("div", { class: "jf-body" }, [
      row,
      status,
      scanActions,
      clActions,
      coverLetterPreview,
      analyzeActions,
      analysisResult,
      logEl,
    ]);

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
    loadCvs().catch((err) => {
      setStatus("Could not reach core API.");
      log(String(err));
    });
    restoreScanState();
  }

  function log(message) {
    $("jf-log").textContent += `${message}\n`;
  }

  function setStatus(message) {
    $("jf-status").textContent = message;
  }

  function send(type, payload) {
    return browser.runtime.sendMessage({ type, ...payload });
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
    $("jf-log").textContent = entry.logText || "";
    lastApplicationId = entry.applicationId || null;
    lastPageText = entry.pageText || "";
    lastAboutText = entry.aboutText || "";
    $("jf-fill-btn").disabled = !lastFieldMapping;
    $("jf-generate-cl-btn").disabled = !lastApplicationId;
    $("jf-analyze-btn").disabled = !lastApplicationId;
    if (entry.coverLetterText) {
      $("jf-cover-letter-preview").value = entry.coverLetterText;
      $("jf-cover-letter-preview").hidden = false;
    }
    lastAnalysis = entry.analysis || null;
    if (lastAnalysis) renderAnalysis(lastAnalysis);
    if (lastFieldMapping) setStatus("Restored previous scan — review, then Fill.");
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
    $("jf-corner-tab").addEventListener("click", openPanel);
    $("jf-corner-tab").addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") openPanel();
    });
    $("jf-close-btn").addEventListener("click", closePanel);

    $("jf-manage-btn").addEventListener("click", () => send("openManage", {}));

    $("jf-scan-btn").addEventListener("click", async () => {
      setStatus("Scanning...");
      $("jf-fill-btn").disabled = true;
      $("jf-generate-cl-btn").disabled = true;
      $("jf-analyze-btn").disabled = true;
      $("jf-cover-letter-preview").hidden = true;
      $("jf-analysis-result").hidden = true;
      lastAnalysis = null;
      lastFieldMapping = null;
      lastApplicationId = null;
      lastPageText = "";
      lastAboutText = "";
      refFrameMap = {};

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
        $("jf-fill-btn").disabled = false;
        $("jf-generate-cl-btn").disabled = false;
        $("jf-analyze-btn").disabled = false;
        await saveScanState();
      } catch (err) {
        setStatus("Scan failed.");
        log(String(err));
      }
    });

    $("jf-generate-cl-btn").addEventListener("click", async () => {
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

    $("jf-analyze-btn").addEventListener("click", async () => {
      if (!lastApplicationId) return;
      $("jf-analyze-btn").disabled = true;

      const startedAt = Date.now();
      const tick = () => {
        const elapsed = Math.round((Date.now() - startedAt) / 1000);
        setStatus(`Analyzing application... ${elapsed}s elapsed (searches the web, then writes the report)`);
      };
      tick();
      const ticker = setInterval(tick, 1000);

      try {
        const result = await send("analyze", {
          applicationId: lastApplicationId,
          pageText: lastPageText,
          aboutText: lastAboutText,
        });
        if (!result.ok) throw new Error(result.error);

        lastAnalysis = result.analysis;
        renderAnalysis(lastAnalysis);
        log("Analysis ready.");
        setStatus(`Analysis ready (took ${Math.round((Date.now() - startedAt) / 1000)}s).`);
        await saveScanState();
      } catch (err) {
        setStatus("Analysis failed.");
        log(String(err));
      } finally {
        clearInterval(ticker);
        $("jf-analyze-btn").disabled = false;
      }
    });

    $("jf-fill-btn").addEventListener("click", async () => {
      if (!lastFieldMapping) return;
      setStatus("Filling...");

      try {
        const result = await send("fill", { fieldMapping: lastFieldMapping, refFrameMap });
        if (!result.ok) throw new Error(result.error);
        result.logLines.forEach(log);
        setStatus("Done — review before submitting.");
      } catch (err) {
        setStatus("Fill failed.");
        log(String(err));
      }
    });
  }

  mount(PANEL_CSS);
})();
