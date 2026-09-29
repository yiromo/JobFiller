const CORE_URL = "http://localhost:8000";

document.getElementById("jf-version").textContent = `v${browser.runtime.getManifest().version}-${JF_BUILD}`;

const statusEl = document.getElementById("status");
const cvListEl = document.getElementById("cv-list");
const cvFileInput = document.getElementById("cv-file-input");
const cvUploadBtn = document.getElementById("cv-upload-btn");
const opportunitiesList = document.getElementById("opportunities-list");
const opportunitiesStatus = document.getElementById("opportunities-status");

async function loadOpportunities() {
  opportunitiesStatus.textContent = "Loading opportunities...";
  try {
    const response = await fetch(`${CORE_URL}/api/v1/opportunities/`);
    if (!response.ok) throw new Error(`core returned ${response.status}`);
    const items = await response.json();
    opportunitiesList.replaceChildren();
    for (const item of items) {
      const row = document.createElement("li");
      const link = document.createElement("a");
      link.href = item.url || item.source_links?.[0] || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = item.title || "Channel post";
      const info = document.createElement("span");
      info.textContent = ` — ${item.status.replaceAll("_", " ")}${item.match_score == null ? "" : ` · ${item.match_score}% fit`}`;
      const note = document.createElement("small");
      note.textContent = item.attempt_note || item.match_reason || "";
      row.append(link, info, document.createElement("br"), note);
      opportunitiesList.appendChild(row);
    }
    opportunitiesStatus.textContent = `${items.length} recent opportunity record(s).`;
  } catch (err) {
    opportunitiesStatus.textContent = `Could not load opportunities: ${err.message || err}`;
  }
}

document.getElementById("opportunities-refresh").addEventListener("click", loadOpportunities);
loadOpportunities();

const HUNTER_STATUS_LABELS = {
  ready: "Ready to send",
  applying: "Applying",
  applied: "Applied",
  needs_review: "Needs review",
  below_threshold: "Below threshold",
  skipped: "Skipped",
};
const hunterSection = document.getElementById("hunter-section");
const hunterFilter = document.getElementById("hunter-filter");
let hunterSnapshot = null;

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function externalLink(url, text) {
  const link = el("a", text);
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:" || parsed.protocol === "http:") link.href = parsed.href;
  } catch (err) {
    link.removeAttribute("href");
  }
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function renderHunterHeader(data) {
  const agent = data.agent || {};
  const phase = agent.phase === "sleeping" ? `sleeping until ${formatTime(agent.next_cycle_at)}` : agent.phase;
  document.getElementById("hunter-phase").textContent = `${phase}${agent.apply ? "" : " · dry run"}`;
  document.getElementById("hunter-summary").textContent =
    `Running on ${agent.host || "?"} (pid ${agent.pid ?? "?"}) since ${formatTime(agent.started_at)}, ` +
    `every ${agent.loop_minutes ?? "?"} min. ${agent.cycles ?? 0} cycle(s) finished; ` +
    `last heartbeat ${formatTime(agent.heartbeat_at)}.`;

  const cap = data.config?.max_applies_per_day;
  const stats = [[`${data.sent_last_day ?? 0}${cap ? ` / ${cap}` : ""}`, "Sent in 24h"]];
  for (const [status, label] of Object.entries(HUNTER_STATUS_LABELS)) {
    stats.push([data.counts?.[status] ?? 0, label]);
  }
  stats.push([data.total ?? 0, "Total seen"]);
  document.getElementById("hunter-stats").replaceChildren(
    ...stats.map(([value, label]) => {
      const card = el("div", null, "hunter-stat");
      card.append(el("strong", String(value)), el("span", label));
      return card;
    }),
  );

  const config = data.config || {};
  const summary = agent.last_summary || {};
  const rows = [
    ["Current cycle started", formatTime(agent.cycle_started_at)],
    ["Last cycle finished", formatTime(agent.cycle_finished_at)],
    ["Next cycle", formatTime(agent.next_cycle_at)],
    ["Last cycle found", `${summary.discovered ?? 0} new vacancies${summary.daily_cap_reached ? " · daily cap reached" : ""}`],
    ["Last error", agent.last_error || "none"],
    ["Sources", (config.sources || []).join("\n") || "—"],
    ["Linked résumés", (data.resumes || []).map((r) => `${r.cv_name} → ${r.title || r.resume_id}`).join("\n") || "none"],
    ["Min score", config.min_score],
    ["Per cycle", `${config.max_applies_per_run} sends, ${config.max_new_per_run} new vacancies`],
    ["Browser", String(config.headless)],
    ["Telegram alerts", config.notify_telegram ? "on" : "off"],
    ["hh.kz session saved", formatTime(data.session_saved_at)],
    ["Snapshot", formatTime(data.generated_at)],
  ];
  const details = document.getElementById("hunter-details");
  details.replaceChildren();
  for (const [label, value] of rows) {
    const dd = el("dd", String(value ?? "—"));
    dd.style.whiteSpace = "pre-line";
    if (label === "Last error" && agent.last_error) dd.className = "hunter-error";
    details.append(el("dt", label), dd);
  }

  const last = document.getElementById("hunter-last");
  last.replaceChildren();
  for (const [kind, items] of [["Applied", summary.applied || []], ["Needs review", summary.review || []]]) {
    for (const item of items) {
      const row = el("li");
      row.append(externalLink(item.url, item.title || item.external_id));
      row.append(el("span", ` — ${kind}${item.employer ? ` · ${item.employer}` : ""}`));
      if (item.note) row.append(el("small", item.note, "hunter-note"));
      last.appendChild(row);
    }
  }
  if (!last.children.length) last.appendChild(el("li", "Nothing sent or held in the last cycle.", "hunter-note"));

  document.getElementById("hunter-log").textContent = (agent.recent_log || []).join("\n");
}

function renderHunterVacancies() {
  const list = document.getElementById("hunter-vacancies");
  const wanted = hunterFilter.value;
  const items = (hunterSnapshot?.vacancies || []).filter((item) => !wanted || item.status === wanted);
  list.replaceChildren();
  for (const item of items) {
    const row = el("li");
    row.append(externalLink(item.url, item.title || item.external_id));
    const score = item.match_score == null ? "unscored" : `${item.match_score}% fit`;
    const when = item.applied_at ? ` · sent ${formatTime(item.applied_at)}` : ` · updated ${formatTime(item.updated_at)}`;
    row.append(
      el(
        "span",
        `${item.employer || "—"} · ${HUNTER_STATUS_LABELS[item.status] || item.status} · ${score}${item.cv_name ? ` · ${item.cv_name}` : ""}${when}`,
        "hunter-meta",
      ),
    );
    if (item.note) row.append(el("small", item.note, "hunter-note"));
    if (item.match_reason && item.match_reason !== item.note) {
      row.append(el("small", `Why: ${item.match_reason}`, "hunter-note"));
    }
    if (item.cover_letter) {
      const letter = el("details");
      letter.append(el("summary", "Cover letter"), el("pre", item.cover_letter));
      row.append(letter);
    }
    list.appendChild(row);
  }
  document.getElementById("hunter-status").textContent =
    `${items.length} of ${hunterSnapshot?.vacancies?.length || 0} most recently updated vacancies.`;
}

async function loadHunter() {
  let data = null;
  try {
    const response = await fetch(`${CORE_URL}/api/v1/hunter/`);
    if (response.ok) data = await response.json();
  } catch (err) {
    data = null;
  }
  if (!data?.up) {
    hunterSection.hidden = true;
    return;
  }
  hunterSnapshot = data;
  renderHunterHeader(data);
  renderHunterVacancies();
  hunterSection.hidden = false;
}

for (const [status, label] of Object.entries(HUNTER_STATUS_LABELS)) {
  const option = el("option", label);
  option.value = status;
  hunterFilter.appendChild(option);
}
hunterFilter.addEventListener("change", renderHunterVacancies);
document.getElementById("hunter-refresh").addEventListener("click", loadHunter);
loadHunter();
setInterval(loadHunter, 30000);

function setStatus(message) {
  statusEl.textContent = message;
}

async function loadCvs() {
  const response = await fetch(`${CORE_URL}/api/v1/cvs/`);
  if (!response.ok) throw new Error(`core returned ${response.status}`);
  const cvs = await response.json();

  renderGenSources(cvs);
  cvListEl.innerHTML = "";
  for (const cv of cvs) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "cv-name";
    name.textContent = cv.full_name || "(name unknown)";
    const filename = document.createElement("span");
    filename.className = "cv-filename";
    filename.textContent = cv.original_filename;
    const downloadBtn = document.createElement("button");
    downloadBtn.type = "button";
    downloadBtn.className = "cv-download-btn";
    downloadBtn.textContent = "Download";
    downloadBtn.addEventListener("click", () => downloadCv(cv.id, cv.original_filename));
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "cv-delete-btn";
    deleteBtn.textContent = "Delete";
    deleteBtn.addEventListener("click", () => deleteCv(cv.id, cv.original_filename));
    li.append(name, " — ", filename, downloadBtn, deleteBtn);
    cvListEl.appendChild(li);
  }
  setStatus(cvs.length ? `${cvs.length} CV(s) uploaded.` : "No CVs uploaded yet.");
}

async function downloadCv(cvId, filename) {
  setStatus(`Downloading ${filename}...`);
  let objectUrl = "";
  try {
    const response = await fetch(`${CORE_URL}/api/v1/cvs/${cvId}/file/`);
    if (!response.ok) throw new Error(`core returned ${response.status}`);
    objectUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setStatus(`Downloaded ${filename}.`);
  } catch (err) {
    setStatus(`Download failed: ${err}`);
  } finally {
    if (objectUrl) setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
  }
}

async function deleteCv(cvId, filename) {
  if (!confirm(`Delete "${filename}"? This can't be undone.`)) return;
  setStatus(`Deleting ${filename}...`);
  try {
    const response = await fetch(`${CORE_URL}/api/v1/cvs/${cvId}/`, { method: "DELETE" });
    if (!response.ok && response.status !== 404) {
      throw new Error(`core returned ${response.status}`);
    }
    await loadCvs();
  } catch (err) {
    setStatus(`Delete failed: ${err}`);
  }
}

cvUploadBtn.addEventListener("click", () => cvFileInput.click());

cvFileInput.addEventListener("change", async () => {
  const file = cvFileInput.files[0];
  if (!file) return;
  setStatus("Uploading CV...");
  try {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${CORE_URL}/api/v1/cvs/`, { method: "POST", body: formData });
    if (!response.ok) throw new Error(`core returned ${response.status}`);
    await loadCvs();
  } catch (err) {
    setStatus(`Upload failed: ${err}`);
  } finally {
    cvFileInput.value = "";
  }
});

const genSourceEl = document.getElementById("gen-source");
const genInstructionsEl = document.getElementById("gen-instructions");
const genPositionEl = document.getElementById("gen-position");
const genFilenameEl = document.getElementById("gen-filename");
const genBtn = document.getElementById("gen-btn");
const genStatusEl = document.getElementById("gen-status");
const genAddedEl = document.getElementById("gen-added");
const genAddedListEl = document.getElementById("gen-added-list");
const genWarningsEl = document.getElementById("gen-warnings");
const genWarningsListEl = document.getElementById("gen-warnings-list");

function renderGenSources(cvs) {
  const previous = genSourceEl.value;
  genSourceEl.innerHTML = "";
  for (const cv of cvs) {
    const option = document.createElement("option");
    option.value = cv.id;
    option.textContent = `${cv.full_name || "(name unknown)"} — ${cv.original_filename}`;
    genSourceEl.appendChild(option);
  }
  if (previous && cvs.some((cv) => String(cv.id) === previous)) genSourceEl.value = previous;
  genBtn.disabled = cvs.length === 0;
}

function renderList(container, listEl, items) {
  listEl.innerHTML = "";
  container.hidden = !items.length;
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    listEl.appendChild(li);
  }
}

genBtn.addEventListener("click", async () => {
  const sourceId = genSourceEl.value;
  const instructions = genInstructionsEl.value.trim();
  if (!sourceId) return;
  if (!instructions) {
    genStatusEl.textContent = "Say what should change first.";
    return;
  }

  genBtn.disabled = true;
  genAddedEl.hidden = true;
  genWarningsEl.hidden = true;
  genStatusEl.textContent = "Rewriting and typesetting — this takes up to a couple of minutes...";
  try {
    const response = await fetch(`${CORE_URL}/api/v1/cvs/${sourceId}/generate/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        instructions,
        position_text: genPositionEl.value.trim(),
        filename: genFilenameEl.value.trim(),
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `core returned ${response.status}`);
    }
    genStatusEl.textContent = `Saved as ${payload.original_filename}. Pick it in the panel's CV list.`;
    renderList(genAddedEl, genAddedListEl, payload.added_skills || []);
    renderList(genWarningsEl, genWarningsListEl, payload.warnings || []);
    await loadCvs();
  } catch (err) {
    genStatusEl.textContent = `Generation failed: ${err.message || err}`;
  } finally {
    genBtn.disabled = false;
  }
});

const EEO_STORAGE_KEY = "eeoAnswers";
const DEFAULT_EEO_ROWS = [
  { match: "gender", answer: "" },
  { match: "hispanic", answer: "" },
  { match: "race", answer: "" },
  { match: "veteran", answer: "" },
  { match: "disability", answer: "" },
];

const eeoRowsEl = document.getElementById("eeo-rows");
const eeoAddRowBtn = document.getElementById("eeo-add-row-btn");
const eeoSaveBtn = document.getElementById("eeo-save-btn");
const eeoStatusEl = document.getElementById("eeo-status");

function renderEeoRows(rows) {
  eeoRowsEl.innerHTML = "";
  for (const row of rows) {
    const rowEl = document.createElement("div");
    rowEl.className = "eeo-row";

    const matchInput = document.createElement("input");
    matchInput.className = "eeo-match";
    matchInput.placeholder = "matches label text, e.g. gender";
    matchInput.value = row.match;

    const answerInput = document.createElement("input");
    answerInput.className = "eeo-answer";
    answerInput.placeholder = "your answer, filled exactly as typed";
    answerInput.value = row.answer;

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", () => rowEl.remove());

    rowEl.append(matchInput, answerInput, removeBtn);
    eeoRowsEl.appendChild(rowEl);
  }
}

function readEeoRows() {
  return Array.from(eeoRowsEl.querySelectorAll(".eeo-row"))
    .map((rowEl) => ({
      match: rowEl.querySelector(".eeo-match").value.trim(),
      answer: rowEl.querySelector(".eeo-answer").value.trim(),
    }))
    .filter((row) => row.match);
}

async function loadEeoRows() {
  const stored = await browser.storage.local.get(EEO_STORAGE_KEY);
  renderEeoRows(stored[EEO_STORAGE_KEY] || DEFAULT_EEO_ROWS);
}

eeoAddRowBtn.addEventListener("click", () => {
  renderEeoRows([...readEeoRows(), { match: "", answer: "" }]);
});

eeoSaveBtn.addEventListener("click", async () => {
  await browser.storage.local.set({ [EEO_STORAGE_KEY]: readEeoRows() });
  eeoStatusEl.textContent = "Saved.";
});

loadCvs().catch((err) => setStatus(`Could not reach core API: ${err}`));
loadEeoRows();
