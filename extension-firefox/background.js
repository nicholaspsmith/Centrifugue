/**
 * Background script for Centrifugue
 * Handles native messaging and polls for progress updates
 */

const NATIVE_HOST_NAME = "com.centrifugue.stemextractor";

// Polling state
let progressPollInterval = null;
let lastProgress = null;

/**
 * Send a message to the native host and return a promise
 */
async function sendToNativeHost(message) {
  try {
    return await browser.runtime.sendNativeMessage(NATIVE_HOST_NAME, message);
  } catch (error) {
    console.error("Native messaging error:", error);
    throw error;
  }
}

/**
 * Show a system notification
 */
async function showNotification(title, message, isError = false) {
  try {
    await browser.notifications.create({
      type: "basic",
      iconUrl: browser.runtime.getURL("icons/icon-96.png"),
      title: title,
      message: message
    });
  } catch (error) {
    console.error("Notification error:", error);
  }
}

/**
 * Update browser action badge to show download status
 */
function updateBadge(status, percent = null) {
  if (status === "downloading" || status === "processing") {
    const text = percent !== null ? `${percent}%` : "...";
    browser.browserAction.setBadgeText({ text });
    browser.browserAction.setBadgeBackgroundColor({ color: "#1565c0" });
  } else if (status === "complete") {
    browser.browserAction.setBadgeText({ text: "✓" });
    browser.browserAction.setBadgeBackgroundColor({ color: "#2e7d32" });
    setTimeout(() => browser.browserAction.setBadgeText({ text: "" }), 5000);
  } else if (status === "error") {
    browser.browserAction.setBadgeText({ text: "!" });
    browser.browserAction.setBadgeBackgroundColor({ color: "#c62828" });
    setTimeout(() => browser.browserAction.setBadgeText({ text: "" }), 5000);
  } else {
    browser.browserAction.setBadgeText({ text: "" });
  }
}

/**
 * Broadcast status update to all YouTube tabs
 */
async function broadcastStatus(status, text, progress = null, autoHide = false) {
  try {
    const tabs = await browser.tabs.query({ url: ["*://*.youtube.com/*", "*://*.youtu.be/*"] });
    for (const tab of tabs) {
      browser.tabs.sendMessage(tab.id, {
        type: "status_update",
        status,
        text,
        progress,
        autoHide
      }).catch(() => {}); // Ignore errors if content script not loaded
    }
  } catch (error) {
    console.error("Broadcast error:", error);
  }
}

/**
 * Format progress message for display
 */
function formatProgressMessage(progress) {
  const title = progress.video_title || "Processing";
  const shortTitle = title.length > 35 ? title.substring(0, 32) + "..." : title;
  const percent = progress.percent || 0;
  const stage = progress.stage || "processing";

  let stageText = "";
  switch (stage) {
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
      stageText = progress.message || "Processing...";
  }

  // Calculate remaining time if we have estimates
  let timeText = "";
  if (progress.estimated_seconds && percent > 0 && percent < 100) {
    const elapsed = (Date.now() / 1000) - (progress.timestamp || Date.now() / 1000);
    const totalEstimate = progress.estimated_seconds;
    const remaining = Math.max(0, totalEstimate - (totalEstimate * percent / 100));
    const remMins = Math.floor(remaining / 60);
    const remSecs = Math.floor(remaining % 60);
    timeText = remaining > 0
      ? (remMins > 0 ? `\n~${remMins}m ${remSecs}s remaining` : `\n~${remSecs}s remaining`)
      : "";
  }

  return `${shortTitle}\n${percent}% - ${stageText}${timeText}`;
}

/**
 * Poll for progress updates from native host
 */
async function pollProgress() {
  try {
    const response = await sendToNativeHost({ action: "get_progress" });

    if (!response.success) {
      console.error("Progress poll failed:", response.error);
      return;
    }

    const progress = response;
    const stage = progress.stage;

    // Check if status changed
    const statusChanged = !lastProgress || lastProgress.stage !== stage ||
                          lastProgress.percent !== progress.percent;

    if (statusChanged) {
      lastProgress = progress;

      if (stage === "idle") {
        // No active job
        stopProgressPolling();
        updateBadge("idle");
        broadcastStatus("idle", "Ready");
      } else if (stage === "downloading" || stage === "processing" || stage === "finalizing") {
        // Job in progress
        updateBadge("processing", progress.percent);
        broadcastStatus("downloading", formatProgressMessage(progress), progress.percent);
      } else if (stage === "complete") {
        // Job completed
        stopProgressPolling();
        updateBadge("complete");
        const successText = progress.video_title
          ? `Stems ready: ${progress.video_title}`
          : "Stems saved to Downloads";
        broadcastStatus("success", successText, 100, true);
        showNotification("Stems Ready", successText);
      } else if (stage === "error" || stage === "stale") {
        // Job failed
        stopProgressPolling();
        updateBadge("error");
        const errorText = progress.error || progress.message || "Processing failed";
        broadcastStatus("error", `Error: ${errorText}`, null, true);
        showNotification("Processing Failed", errorText, true);
      }
    }
  } catch (error) {
    console.error("Progress poll error:", error);
  }
}

/**
 * Start polling for progress updates
 */
function startProgressPolling() {
  if (progressPollInterval) return;

  // Poll immediately, then every 2 seconds
  pollProgress();
  progressPollInterval = setInterval(pollProgress, 2000);
}

/**
 * Stop polling for progress updates
 */
function stopProgressPolling() {
  if (progressPollInterval) {
    clearInterval(progressPollInterval);
    progressPollInterval = null;
  }
}

/**
 * Handle messages from popup and content scripts
 */
browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "download_mp3") {
    // MP3 download - handled synchronously by native host
    sendToNativeHost({
      action: "download_mp3",
      url: message.url
    }).then(result => {
      if (result.success) {
        updateBadge("complete");
        broadcastStatus("success", `Downloaded: ${result.filename}`, 100, true);
        showNotification("Download Complete", `MP3 saved: ${result.filename}`);
      } else {
        updateBadge("error");
        broadcastStatus("error", `Error: ${result.error}`, null, true);
        showNotification("Download Failed", result.error, true);
      }
      sendResponse(result);
    }).catch(error => {
      updateBadge("error");
      broadcastStatus("error", `Error: ${error.message}`, null, true);
      sendResponse({ success: false, error: error.message });
    });

    updateBadge("downloading");
    broadcastStatus("downloading", "Downloading MP3...", 0);
    return true; // Keep message channel open for async response
  }

  if (message.action === "download_stems") {
    // Stem separation - starts background job and returns immediately
    sendToNativeHost({
      action: "download_stems",
      url: message.url,
      quality: message.quality || "fast",
      genre: message.genre || "full"
    }).then(result => {
      if (result.success) {
        // Job started, begin polling
        startProgressPolling();
        sendResponse({
          success: true,
          job_id: result.job_id,
          video_title: result.video_title
        });
      } else {
        updateBadge("error");
        broadcastStatus("error", `Error: ${result.error}`, null, true);
        sendResponse(result);
      }
    }).catch(error => {
      updateBadge("error");
      broadcastStatus("error", `Error: ${error.message}`, null, true);
      sendResponse({ success: false, error: error.message });
    });

    updateBadge("downloading");
    return true; // Keep message channel open for async response
  }

  if (message.action === "get_progress") {
    // Get current progress
    sendToNativeHost({ action: "get_progress" })
      .then(result => sendResponse(result))
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  if (message.action === "cancel_job") {
    // Cancel the current job
    sendToNativeHost({ action: "cancel_job" })
      .then(result => {
        if (result.success) {
          stopProgressPolling();
          updateBadge("idle");
          broadcastStatus("idle", "Job cancelled");
        }
        sendResponse(result);
      })
      .catch(error => sendResponse({ success: false, error: error.message }));
    return true;
  }

  if (message.action === "check_status") {
    // Check if there's an active job and start polling if so
    sendToNativeHost({ action: "get_progress" })
      .then(result => {
        if (result.stage && result.stage !== "idle" && result.stage !== "complete" && result.stage !== "error") {
          startProgressPolling();
        }
        sendResponse(result);
      })
      .catch(error => sendResponse({ success: false, error: error.message, stage: "idle" }));
    return true;
  }

  return false;
});

// Check for active jobs when background script starts
sendToNativeHost({ action: "get_progress" })
  .then(result => {
    if (result.stage && ["downloading", "processing", "finalizing"].includes(result.stage)) {
      console.log("Found active job, starting progress polling");
      startProgressPolling();
    }
  })
  .catch(() => {});

console.log("Centrifugue background script loaded");
