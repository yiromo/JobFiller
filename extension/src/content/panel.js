(() => {
  if (window.__jfPanelMounted) return;
  window.__jfPanelMounted = true;

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
      { id: "jf-corner-tab", class: "jf-corner-tab", role: "button", tabindex: "0", "aria-label": "Open Job Filler", title: "Job Filler" },
      [svgIcon("M4 4h16v3.2H4zM4 10.4h11.2v3.2H4zM4 16.8h16V20H4z", 16)],
    );

    const closeBtn = h("button", { type: "button", id: "jf-close-btn", class: "jf-close", "aria-label": "Close" });
    closeBtn.textContent = "×";

    const logo = h("span", { class: "jf-logo" });
    logo.textContent = "JOB FILLER";

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
  document.documentElement.appendChild(host);
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

  function scanStorageKey(tabId) {
    return `scan:${tabId}`;
  }

  async function saveScanState() {
    if (myTabId == null) return;
    await browser.storage.session.set({
      [scanStorageKey(myTabId)]: {
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

    const key = scanStorageKey(myTabId);
    const stored = await browser.storage.session.get(key);
    const entry = stored[key];
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
      setStatus("Analyzing application...");
      $("jf-analyze-btn").disabled = true;

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
        setStatus("Analysis ready.");
        await saveScanState();
      } catch (err) {
        setStatus("Analysis failed.");
        log(String(err));
      } finally {
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

  fetch(browser.runtime.getURL("src/content/panel.css"))
    .then((r) => r.text())
    .then(mount)
    .catch((err) => console.error("Job Filler panel failed to load:", err));
})();
