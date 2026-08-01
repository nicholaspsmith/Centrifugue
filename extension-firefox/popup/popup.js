/**
 * Popup script for Centrifugue
 * Shows download options and current progress
 */

let currentUrl = null;
let selectedQuality = "fast";
let selectedGenre = "full";
let statusPollInterval = null;

// Check if we're on a YouTube video page
async function checkYouTubePage() {
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
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
    const response = await browser.runtime.sendMessage({ action: "get_progress" });

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
  document.getElementById("downloadMp3Btn").disabled = disabled;
  document.getElementById("downloadStemsBtn").disabled = disabled;
  document.getElementById("cancelBtn").style.display = disabled ? "block" : "none";
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
      const response = await browser.runtime.sendMessage({ action: "get_progress" });

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
      } else {
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
    const response = await browser.runtime.sendMessage({
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

  disableButtons(true);
  updateStatus("Starting stem separation...", "downloading");

  try {
    const response = await browser.runtime.sendMessage({
      action: "download_stems",
      url: currentUrl,
      quality: selectedQuality,
      genre: selectedGenre
    });

    if (response.success) {
      // Job started, begin polling
      updateStatus(`Processing: ${response.video_title || "stems"}...`, "downloading");
      startStatusPolling();
    } else {
      updateStatus(`Error: ${response.error}`, "error");
      disableButtons(false);
    }
  } catch (error) {
    console.error("Stems error:", error);
    updateStatus(`Error: ${error.message}`, "error");
    disableButtons(false);
  }
}

async function cancelJob() {
  try {
    const response = await browser.runtime.sendMessage({ action: "cancel_job" });
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

// Event listeners
document.getElementById("downloadMp3Btn").addEventListener("click", downloadMP3);
document.getElementById("downloadStemsBtn").addEventListener("click", downloadStems);
document.getElementById("cancelBtn").addEventListener("click", cancelJob);

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
