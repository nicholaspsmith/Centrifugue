/**
 * Popup script for Centrifugue (Chrome)
 * Shows download options and current progress
 */

let currentUrl = null;
let selectedQuality = "fast";
let selectedGenre = "full";
let statusPollInterval = null;
// A conversion is running in the native host
let jobActive = false;
// A start/queue request is in flight, so a second click would double-submit
let submitting = false;
// Keeps a just-queued confirmation on screen instead of letting the progress
// poller overwrite it on its next tick
let noticeUntil = 0;

// Check if we're on a YouTube video page
async function checkYouTubePage() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];

  if (!tab || !tab.url) {
    updateStatus("Cannot access page URL", "error");
    return false;
  }

  const url = tab.url;
  const youtubeRegex = /^https?:\/\/(www\.)?(youtube\.com\/watch\?v=|youtu\.be\/)/;

  if (!youtubeRegex.test(url)) {
    updateStatus("Not a YouTube video page", "error");
    disableButtons(true);
    return false;
  }

  currentUrl = url;

  // Try to get video title from tab
  const titleElement = document.getElementById("videoTitle");
  if (tab.title) {
    titleElement.textContent = tab.title.replace(" - YouTube", "");
  }

  return true;
}

async function checkActiveJob() {
  try {
    const response = await chrome.runtime.sendMessage({ action: "get_progress" });

    if (response.stage && ["downloading", "processing", "finalizing"].includes(response.stage)) {
      // Job in progress
      displayProgress(response);
      disableButtons(true);
      startStatusPolling();
      return true;
    } else if (response.stage === "complete") {
      // Just completed
      updateStatus(`✓ ${response.message || "Complete!"}`, "success");
      disableButtons(false);
      return false;
    } else if (response.stage === "error") {
      // Error state
      updateStatus(`Error: ${response.error || response.message}`, "error");
      disableButtons(false);
      return false;
    } else {
      // Idle
      updateStatus("Ready to download", "");
      disableButtons(false);
      return false;
    }
  } catch (error) {
    updateStatus("Ready to download", "");
    disableButtons(false);
    return false;
  }
}

function displayProgress(progress) {
  const title = progress.video_title || "Processing";
  const shortTitle = title.length > 30 ? title.substring(0, 27) + "..." : title;
  const percent = progress.percent || 0;

  let stageText = "";
  switch (progress.stage) {
    case "downloading":
      stageText = "Downloading audio...";
      break;
    case "processing":
      stageText = progress.message || "Separating stems...";
      break;
    case "finalizing":
      stageText = "Organizing files...";
      break;
    default:
      stageText = "Processing...";
  }

  const qualityText = progress.quality ? ` (${progress.quality})` : "";
  const genreText = progress.genre && progress.genre !== "full" ? ` [${progress.genre}]` : "";

  updateStatus(
    `"${shortTitle}"\n${percent}% - ${stageText}${qualityText}${genreText}\nYou can close this popup.`,
    "downloading"
  );
}

function updateStatus(message, className) {
  const statusEl = document.getElementById("status");
  statusEl.textContent = message;
  statusEl.className = className || "";
}

function disableButtons(disabled) {
  jobActive = disabled;
  syncButtons();
}

/**
 * Reflect the current state on the buttons.
 *
 * The stems button stays clickable while a job runs: the native host appends
 * the request to its queue instead of rejecting it. Only the label changes, so
 * the button always says what pressing it will actually do. MP3 has no queue
 * behind it, so it still waits its turn.
 */
function syncButtons() {
  document.getElementById("downloadMp3Btn").disabled = jobActive || submitting;
  document.getElementById("downloadStemsBtn").disabled = submitting;
  document.getElementById("stemsBtnLabel").textContent =
    jobActive ? "Add to Queue" : "Download Stems";
  document.getElementById("cancelBtn").style.display = jobActive ? "block" : "none";
}

/** Show a message that survives a few progress ticks before it is replaced. */
function showNotice(message, className) {
  updateStatus(message, className);
  noticeUntil = Date.now() + 4000;
}

// Genre selection handling
document.querySelectorAll(".genre-option").forEach(option => {
  option.addEventListener("click", () => {
    document.querySelectorAll(".genre-option").forEach(o => o.classList.remove("selected"));
    option.classList.add("selected");
    selectedGenre = option.dataset.genre;
  });
});

// Quality selection handling
document.querySelectorAll(".quality-option").forEach(option => {
  option.addEventListener("click", () => {
    document.querySelectorAll(".quality-option").forEach(o => o.classList.remove("selected"));
    option.classList.add("selected");
    selectedQuality = option.dataset.quality;
  });
});

function startStatusPolling() {
  if (statusPollInterval) {
    clearInterval(statusPollInterval);
  }

  statusPollInterval = setInterval(async () => {
    try {
      const response = await chrome.runtime.sendMessage({ action: "get_progress" });

      if (response.stage === "complete") {
        clearInterval(statusPollInterval);
        statusPollInterval = null;
        disableButtons(false);
        updateStatus(`✓ ${response.message || "Complete!"}`, "success");
      } else if (response.stage === "error") {
        clearInterval(statusPollInterval);
        statusPollInterval = null;
        disableButtons(false);
        updateStatus(`Error: ${response.error || response.message}`, "error");
      } else if (response.stage === "idle") {
        clearInterval(statusPollInterval);
        statusPollInterval = null;
        disableButtons(false);
        updateStatus("Ready to download", "");
      } else if (Date.now() >= noticeUntil) {
        displayProgress(response);
      }
    } catch (error) {
      console.error("Status poll error:", error);
    }
  }, 1000);
}

async function downloadMP3() {
  if (!currentUrl) {
    updateStatus("No YouTube URL found", "error");
    return;
  }

  disableButtons(true);
  updateStatus("Starting MP3 download...", "downloading");

  try {
    const response = await chrome.runtime.sendMessage({
      action: "download_mp3",
      url: currentUrl
    });

    if (response.success) {
      updateStatus(`✓ Downloaded: ${response.filename}`, "success");
    } else {
      updateStatus(`Error: ${response.error}`, "error");
    }
    disableButtons(false);
  } catch (error) {
    console.error("Download error:", error);
    updateStatus(`Error: ${error.message}`, "error");
    disableButtons(false);
  }
}

async function downloadStems() {
  if (!currentUrl) {
    updateStatus("No YouTube URL found", "error");
    return;
  }
  if (submitting) return;

  submitting = true;
  syncButtons();
  const queueing = jobActive;
  updateStatus(queueing ? "Adding to queue..." : "Starting stem separation...",
               "downloading");

  try {
    const response = await chrome.runtime.sendMessage({
      action: "download_stems",
      url: currentUrl,
      quality: selectedQuality,
      genre: selectedGenre
    });

    if (response.success) {
      if (response.queued) {
        // Another job holds the slot. Leave its progress display alone -- this
        // one is only waiting, and the queue panel below shows where it sits.
        showNotice(`Queued: ${response.video_title || "stems"}`, "success");
      } else {
        updateStatus(`Processing: ${response.video_title || "stems"}...`, "downloading");
        disableButtons(true);
        startStatusPolling();
      }
      refreshQueue();
    } else {
      updateStatus(`Error: ${response.error}`, "error");
    }
  } catch (error) {
    console.error("Stems error:", error);
    updateStatus(`Error: ${error.message}`, "error");
  } finally {
    submitting = false;
    syncButtons();
  }
}

async function cancelJob() {
  try {
    const response = await chrome.runtime.sendMessage({ action: "cancel_job" });
    if (response.success) {
      updateStatus("Job cancelled", "");
      disableButtons(false);
      if (statusPollInterval) {
        clearInterval(statusPollInterval);
        statusPollInterval = null;
      }
    } else {
      updateStatus(`Cancel failed: ${response.error}`, "error");
    }
  } catch (error) {
    console.error("Cancel error:", error);
    updateStatus(`Error: ${error.message}`, "error");
  }
}

async function loadSettings() {
  try {
    const response = await chrome.runtime.sendMessage({ action: "get_config" });
    if (response && response.success) {
      document.getElementById("outputDir").value = response.config.output_dir;
    }
  } catch (error) {
    // Settings are non-critical: a failure here must not block downloads.
  }
}

async function browseForFolder() {
  const status = document.getElementById("settingsStatus");
  status.textContent = "Opening folder chooser...";
  try {
    const response = await chrome.runtime.sendMessage({ action: "pick_output_dir" });
    // Usually unreachable: the native dialog closes this popup. The background
    // script saves and notifies, so this only runs if the popup survived.
    if (response && response.success) {
      document.getElementById("outputDir").value = response.output_dir;
      status.textContent = "Saved";
    } else if (response && response.cancelled) {
      status.textContent = "";
    } else {
      status.textContent = `Error: ${response ? response.error : "no response"}`;
    }
  } catch (error) {
    status.textContent = `Error: ${error.message}`;
  }
}

const STATUS_LABEL = {
  queued: "Queued", running: "Running", paused: "Paused",
  complete: "Done", error: "Failed", cancelled: "Cancelled",
};

async function refreshQueue() {
  let response;
  try {
    response = await chrome.runtime.sendMessage({ action: "get_queue" });
  } catch (error) {
    return;
  }
  const list = document.getElementById("queueList");
  const count = document.getElementById("queueCount");
  if (!response || !response.success || !list) return;

  const jobs = response.jobs || [];

  // The queue is the authority on whether anything is running. The single-job
  // progress file goes quiet between one job finishing and the next starting,
  // so relying on it alone would leave the buttons stale mid-queue.
  const running = jobs.some(j => j.status === "running");
  if (running !== jobActive) {
    jobActive = running;
    syncButtons();
    if (running) startStatusPolling();
  }

  const pending = jobs.filter(j => j.status === "queued").length;
  count.textContent = pending ? `(${pending} waiting)` : "";

  if (!jobs.length) {
    list.textContent = "";
    const empty = document.createElement("div");
    empty.className = "queue-empty";
    empty.textContent = "Nothing queued.";
    list.appendChild(empty);
    return;
  }

  list.textContent = "";
  for (const job of jobs) {
    const progress = job.progress || {};
    const row = document.createElement("div");
    row.className = "queue-row";

    const title = document.createElement("div");
    title.className = "queue-title";
    title.textContent = job.title;
    row.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "queue-meta";
    meta.textContent = `${STATUS_LABEL[job.status] || job.status} - ` +
      `${job.genre}/${job.quality}` +
      (job.status === "running" && progress.message ? ` - ${progress.message}` : "") +
      (job.status === "error" && job.error ? ` - ${job.error}` : "");
    row.appendChild(meta);

    if (job.status === "running" || job.status === "paused") {
      const outer = document.createElement("div");
      outer.className = "queue-bar-outer";
      const inner = document.createElement("div");
      inner.className = "queue-bar-inner";
      inner.style.width = `${progress.percent || 0}%`;
      outer.appendChild(inner);
      row.appendChild(outer);
    }

    const actions = document.createElement("div");
    actions.className = "queue-actions";
    if (job.status === "running" || job.status === "queued") {
      actions.appendChild(queueButton("Pause", "pause_job", job.job_id));
    }
    if (job.status === "paused") {
      actions.appendChild(queueButton("Resume", "resume_job", job.job_id));
    }
    actions.appendChild(queueButton("Remove", "remove_job", job.job_id));
    row.appendChild(actions);

    list.appendChild(row);
  }
}

function queueButton(label, action, jobId) {
  const button = document.createElement("button");
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const result = await chrome.runtime.sendMessage({ action, job_id: jobId });
      if (result && !result.success) {
        updateStatus(`Error: ${result.error}`, "error");
      }
    } catch (error) {
      updateStatus(`Error: ${error.message}`, "error");
    }
    await refreshQueue();
  });
  return button;
}

// Event listeners
document.getElementById("downloadMp3Btn").addEventListener("click", downloadMP3);
document.getElementById("downloadStemsBtn").addEventListener("click", downloadStems);
document.getElementById("cancelBtn").addEventListener("click", cancelJob);
document.getElementById("browseBtn").addEventListener("click", browseForFolder);

loadSettings();
refreshQueue();
setInterval(refreshQueue, 2000);

// Initialize
checkActiveJob().then(hasActiveJob => {
  if (!hasActiveJob) {
    checkYouTubePage();
  }
});

// Cleanup on popup close
window.addEventListener("unload", () => {
  if (statusPollInterval) {
    clearInterval(statusPollInterval);
  }
});
