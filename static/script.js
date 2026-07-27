const urlInput = document.getElementById("urlInput");
const fetchBtn = document.getElementById("fetchBtn");
const statusMsg = document.getElementById("statusMsg");
const result = document.getElementById("result");
const thumbnail = document.getElementById("thumbnail");
const videoTitle = document.getElementById("videoTitle");
const videoDuration = document.getElementById("videoDuration");
const formatsEl = document.getElementById("formats");
const progressContainer = document.getElementById("progressContainer");
const progressFill = document.getElementById("progressFill");
const progressLabel = document.getElementById("progressLabel");

const POLL_INTERVAL_MS = 500;

function formatDuration(totalSeconds) {
  if (!totalSeconds) return "";
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = Math.floor(totalSeconds % 60);
  const parts = h > 0 ? [h, m, s] : [m, s];
  return parts.map((p, i) => (i === 0 ? p : String(p).padStart(2, "0"))).join(":");
}

function setStatus(message, isError = false) {
  statusMsg.textContent = message;
  statusMsg.classList.toggle("error", isError);
}

function showProgress(percent, label) {
  progressContainer.classList.remove("hidden");
  progressFill.style.width = `${percent}%`;
  progressLabel.textContent = label ? `${label} ${percent}%` : `${percent}%`;
}

function hideProgress() {
  progressContainer.classList.add("hidden");
  progressFill.style.width = "0%";
}

function setFormatButtonsDisabled(disabled) {
  formatsEl.querySelectorAll(".format-btn").forEach((btn) => (btn.disabled = disabled));
}

function buildFormatButton(label, quality, sourceUrl) {
  const btn = document.createElement("button");
  btn.className = "format-btn";
  btn.textContent = label;
  btn.addEventListener("click", () => startDownload(quality, sourceUrl));
  return btn;
}

function pollProgress(jobId) {
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/api/progress/${jobId}`);
        const data = await res.json();

        if (!res.ok || data.status === "error") {
          clearInterval(timer);
          reject(new Error(data.error || "Download failed."));
          return;
        }

        const percent = data.percent ?? 0;
        const label = data.status === "processing" ? "Processing..." : "Downloading...";
        showProgress(percent, label);

        if (data.status === "finished") {
          clearInterval(timer);
          resolve();
        }
      } catch (err) {
        clearInterval(timer);
        reject(err);
      }
    }, POLL_INTERVAL_MS);
  });
}

async function fetchFinishedFile(jobId) {
  const response = await fetch(`/api/file/${jobId}`);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || "Could not retrieve the downloaded file.");
  }

  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : "video";

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

async function startDownload(quality, sourceUrl) {
  setFormatButtonsDisabled(true);
  showProgress(0, "Starting...");
  setStatus("");

  try {
    const params = new URLSearchParams({ url: sourceUrl, quality });
    const startRes = await fetch(`/api/start-download?${params.toString()}`);
    const startData = await startRes.json();
    if (!startRes.ok) {
      throw new Error(startData.error || "Could not start the download.");
    }

    await pollProgress(startData.job_id);
    showProgress(100, "Done!");
    await fetchFinishedFile(startData.job_id);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    hideProgress();
    setFormatButtonsDisabled(false);
  }
}

async function fetchVideoInfo() {
  const url = urlInput.value.trim();
  if (!url) {
    setStatus("Please paste a YouTube URL first.", true);
    return;
  }

  fetchBtn.disabled = true;
  result.classList.add("hidden");
  hideProgress();
  setStatus("Fetching video info...");

  try {
    const params = new URLSearchParams({ url });
    const response = await fetch(`/api/info?${params.toString()}`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Something went wrong.");
    }

    thumbnail.src = data.thumbnail || "";
    videoTitle.textContent = data.title || "Untitled";
    videoDuration.textContent = formatDuration(data.duration);

    formatsEl.innerHTML = "";
    formatsEl.appendChild(buildFormatButton("MP3", "mp3", url));
    (data.qualities || []).forEach((q) => {
      formatsEl.appendChild(buildFormatButton(`${q}p`, String(q), url));
    });

    result.classList.remove("hidden");
    setStatus("");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    fetchBtn.disabled = false;
  }
}

fetchBtn.addEventListener("click", fetchVideoInfo);
urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") fetchVideoInfo();
});
