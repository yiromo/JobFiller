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

loadCvs().catch((err) => setStatus(`Could not reach core API: ${err}`));
