const CORE_URL = "http://localhost:8000";

document.getElementById("jf-version").textContent = `v${browser.runtime.getManifest().version}-${JF_BUILD}`;

const statusEl = document.getElementById("status");
const cvListEl = document.getElementById("cv-list");
const cvFileInput = document.getElementById("cv-file-input");
const cvUploadBtn = document.getElementById("cv-upload-btn");

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
