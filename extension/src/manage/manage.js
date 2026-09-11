const CORE_URL = "http://localhost:8000";

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

  cvListEl.innerHTML = "";
  for (const cv of cvs) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "cv-name";
    name.textContent = cv.full_name || "(name unknown)";
    const filename = document.createElement("span");
    filename.className = "cv-filename";
    filename.textContent = cv.original_filename;
    li.append(name, " — ", filename);
    cvListEl.appendChild(li);
  }
  setStatus(cvs.length ? `${cvs.length} CV(s) uploaded.` : "No CVs uploaded yet.");
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

const grantAccessBtn = document.getElementById("grant-access-btn");
const accessStatusEl = document.getElementById("access-status");

async function refreshAccessStatus() {
  const granted = await browser.permissions.contains({ origins: ["<all_urls>"] });
  accessStatusEl.textContent = granted ? "Granted." : "Not granted yet.";
}

grantAccessBtn.addEventListener("click", async () => {
  const granted = await browser.permissions.request({ origins: ["<all_urls>"] });
  accessStatusEl.textContent = granted ? "Granted." : "Permission was not granted.";
});

loadCvs().catch((err) => setStatus(`Could not reach core API: ${err}`));
loadEeoRows();
refreshAccessStatus();
