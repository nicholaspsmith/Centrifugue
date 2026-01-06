/**
 * Content script for Centrifugue
 * Displays a floating download button and status indicator on YouTube pages
 */

let floatingButton = null;
let menuElement = null;
let statusElement = null;
let hideTimeout = null;
let selectedQuality = "fast";
let selectedGenre = "full";
let isMenuOpen = false;
let currentVideoUrl = null;

// Check if we're on a YouTube video page
function isVideoPage() {
  return window.location.pathname === "/watch" &&
         new URLSearchParams(window.location.search).has("v");
}

function getCurrentVideoUrl() {
  if (isVideoPage()) {
    return window.location.href;
  }
  return null;
}

function getVideoTitle() {
  // Try different selectors for YouTube's video title
  const selectors = [
    "h1.ytd-video-primary-info-renderer yt-formatted-string",
    "h1.title yt-formatted-string",
    "#title h1 yt-formatted-string",
    "h1.ytd-watch-metadata yt-formatted-string"
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el && el.textContent) {
      return el.textContent.trim();
    }
  }

  // Fallback to document title
  return document.title.replace(" - YouTube", "").trim();
}

function injectStyles() {
  if (document.getElementById("centrifuge-styles")) return;

  const styles = document.createElement("style");
  styles.id = "centrifuge-styles";
  styles.textContent = `
    #centrifuge-floating-btn {
      position: fixed;
      bottom: 80px;
      right: 20px;
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: linear-gradient(135deg, #ff0000 0%, #cc0000 100%);
      color: white;
      border: none;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      z-index: 9998;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    #centrifuge-floating-btn:hover {
      transform: scale(1.1);
      box-shadow: 0 6px 16px rgba(0,0,0,0.4);
    }
    #centrifuge-floating-btn.processing {
      background: linear-gradient(135deg, #1565c0 0%, #0d47a1 100%);
      animation: centrifuge-pulse 2s ease-in-out infinite;
    }
    #centrifuge-floating-btn.hidden {
      display: none;
    }

    @keyframes centrifuge-pulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.05); }
    }

    #centrifuge-menu {
      position: fixed;
      bottom: 150px;
      right: 20px;
      width: 320px;
      background: #1a1a1a;
      border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      z-index: 9999;
      opacity: 0;
      transform: translateY(20px) scale(0.95);
      transition: opacity 0.2s, transform 0.2s;
      pointer-events: none;
      overflow: hidden;
    }
    #centrifuge-menu.visible {
      opacity: 1;
      transform: translateY(0) scale(1);
      pointer-events: auto;
    }

    .centrifuge-menu-header {
      background: linear-gradient(135deg, #ff0000 0%, #cc0000 100%);
      padding: 14px 16px;
      color: white;
    }
    .centrifuge-menu-title {
      font-weight: 600;
      font-size: 14px;
      margin-bottom: 4px;
    }
    .centrifuge-menu-subtitle {
      font-size: 11px;
      opacity: 0.85;
      line-height: 1.3;
      word-break: break-word;
    }

    .centrifuge-menu-body {
      padding: 16px;
    }

    .centrifuge-menu-btn {
      width: 100%;
      padding: 12px 16px;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 10px;
      transition: background 0.2s;
      margin-bottom: 12px;
    }
    .centrifuge-menu-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    #centrifuge-mp3-btn {
      background: #ff0000;
      color: white;
    }
    #centrifuge-mp3-btn:hover:not(:disabled) {
      background: #cc0000;
    }

    .centrifuge-section-title {
      font-size: 12px;
      color: #888;
      margin-bottom: 8px;
      font-weight: 500;
    }

    .centrifuge-options-row {
      display: flex;
      gap: 8px;
      margin-bottom: 12px;
    }

    .centrifuge-option {
      flex: 1;
      padding: 10px 8px;
      border: 2px solid #333;
      border-radius: 8px;
      background: #222;
      color: #fff;
      cursor: pointer;
      text-align: center;
      transition: all 0.2s;
    }
    .centrifuge-option:hover {
      border-color: #555;
    }
    .centrifuge-option.selected {
      border-color: #9c27b0;
      background: rgba(156, 39, 176, 0.2);
    }
    .centrifuge-genre-option.selected {
      border-color: #ff5722;
      background: rgba(255, 87, 34, 0.2);
    }
    .centrifuge-option-label {
      font-weight: 600;
      font-size: 12px;
    }
    .centrifuge-option-desc {
      font-size: 10px;
      color: #888;
      margin-top: 2px;
    }

    #centrifuge-stems-btn {
      background: #9c27b0;
      color: white;
      margin-bottom: 0;
    }
    #centrifuge-stems-btn:hover:not(:disabled) {
      background: #7b1fa2;
    }

    .centrifuge-menu-close {
      position: absolute;
      top: 10px;
      right: 10px;
      background: none;
      border: none;
      color: rgba(255,255,255,0.7);
      font-size: 20px;
      cursor: pointer;
      padding: 4px 8px;
      line-height: 1;
    }
    .centrifuge-menu-close:hover {
      color: #fff;
    }

    #centrifuge-status {
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: #1a1a1a;
      color: #fff;
      padding: 12px 16px;
      border-radius: 8px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 13px;
      display: flex;
      align-items: center;
      gap: 10px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      z-index: 9997;
      opacity: 0;
      transform: translateY(20px);
      transition: opacity 0.3s, transform 0.3s;
      max-width: 350px;
    }
    #centrifuge-status.visible {
      opacity: 1;
      transform: translateY(0);
    }
    #centrifuge-status.downloading {
      background: #1565c0;
    }
    #centrifuge-status.success {
      background: #2e7d32;
    }
    #centrifuge-status.error {
      background: #c62828;
    }
    .centrifuge-status-icon {
      width: 20px;
      height: 20px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    #centrifuge-status.downloading .centrifuge-status-icon {
      border: 2px solid rgba(255,255,255,0.3);
      border-top-color: #fff;
      animation: centrifuge-spin 1s linear infinite;
    }
    #centrifuge-status.success .centrifuge-status-icon::after {
      content: "\\2713";
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 14px;
    }
    #centrifuge-status.error .centrifuge-status-icon::after {
      content: "!";
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 14px;
      font-weight: bold;
    }
    .centrifuge-status-text {
      flex: 1;
      line-height: 1.4;
      white-space: pre-line;
    }
    .centrifuge-status-close {
      background: none;
      border: none;
      color: rgba(255,255,255,0.7);
      font-size: 18px;
      cursor: pointer;
      padding: 0 0 0 8px;
      line-height: 1;
    }
    .centrifuge-status-close:hover {
      color: #fff;
    }
    @keyframes centrifuge-spin {
      to { transform: rotate(360deg); }
    }

    .centrifuge-progress-section {
      background: #222;
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 12px;
    }
    .centrifuge-progress-title {
      font-size: 12px;
      color: #fff;
      margin-bottom: 8px;
      word-break: break-word;
    }
    .centrifuge-progress-bar-container {
      height: 6px;
      background: #333;
      border-radius: 3px;
      overflow: hidden;
      margin-bottom: 6px;
    }
    .centrifuge-progress-bar {
      height: 100%;
      background: linear-gradient(90deg, #1565c0, #42a5f5);
      border-radius: 3px;
      transition: width 0.3s ease;
    }
    .centrifuge-progress-text {
      font-size: 11px;
      color: #888;
    }
    #centrifuge-cancel-btn {
      width: 100%;
      padding: 10px;
      background: #444;
      color: #fff;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
      margin-top: 8px;
    }
    #centrifuge-cancel-btn:hover {
      background: #555;
    }
  `;
  document.head.appendChild(styles);
}

function createFloatingButton() {
  if (floatingButton) return floatingButton;

  injectStyles();

  floatingButton = document.createElement("button");
  floatingButton.id = "centrifuge-floating-btn";
  floatingButton.innerHTML = "🎵";
  floatingButton.title = "Download Audio";

  floatingButton.addEventListener("click", toggleMenu);

  document.body.appendChild(floatingButton);
  return floatingButton;
}

function createMenu() {
  if (menuElement) return menuElement;

  menuElement = document.createElement("div");
  menuElement.id = "centrifuge-menu";

  const videoTitle = getVideoTitle();
  const shortTitle = videoTitle.length > 50 ? videoTitle.substring(0, 47) + "..." : videoTitle;

  menuElement.innerHTML = `
    <div class="centrifuge-menu-header">
      <button class="centrifuge-menu-close">\u00D7</button>
      <div class="centrifuge-menu-title">Download Audio</div>
      <div class="centrifuge-menu-subtitle">${shortTitle}</div>
    </div>
    <div class="centrifuge-menu-body">
      <div id="centrifuge-progress-container" style="display: none;">
        <div class="centrifuge-progress-section">
          <div class="centrifuge-progress-title" id="centrifuge-progress-title">Processing...</div>
          <div class="centrifuge-progress-bar-container">
            <div class="centrifuge-progress-bar" id="centrifuge-progress-bar" style="width: 0%"></div>
          </div>
          <div class="centrifuge-progress-text" id="centrifuge-progress-text">Starting...</div>
        </div>
        <button id="centrifuge-cancel-btn">Cancel</button>
      </div>

      <div id="centrifuge-download-options">
        <button class="centrifuge-menu-btn" id="centrifuge-mp3-btn">
          <span>🎵</span>
          Download MP3
        </button>

        <div class="centrifuge-section-title">Genre Mode</div>
        <div class="centrifuge-options-row">
          <div class="centrifuge-option centrifuge-genre-option selected" data-genre="full">
            <div class="centrifuge-option-label">Full</div>
            <div class="centrifuge-option-desc">4 stems</div>
          </div>
          <div class="centrifuge-option centrifuge-genre-option" data-genre="hiphop">
            <div class="centrifuge-option-label">Hip Hop</div>
            <div class="centrifuge-option-desc">Vocals + Beat</div>
          </div>
          <div class="centrifuge-option centrifuge-genre-option" data-genre="rock">
            <div class="centrifuge-option-label">Rock</div>
            <div class="centrifuge-option-desc">Vox/Drums/Bass</div>
          </div>
        </div>

        <div class="centrifuge-section-title">Quality</div>
        <div class="centrifuge-options-row">
          <div class="centrifuge-option centrifuge-quality-option selected" data-quality="fast">
            <div class="centrifuge-option-label">Fast</div>
            <div class="centrifuge-option-desc">~2 min</div>
          </div>
          <div class="centrifuge-option centrifuge-quality-option" data-quality="balanced">
            <div class="centrifuge-option-label">Balanced</div>
            <div class="centrifuge-option-desc">~5 min</div>
          </div>
          <div class="centrifuge-option centrifuge-quality-option" data-quality="high">
            <div class="centrifuge-option-label">High</div>
            <div class="centrifuge-option-desc">~10 min</div>
          </div>
        </div>

        <button class="centrifuge-menu-btn" id="centrifuge-stems-btn">
          <span>🎛️</span>
          Download Stems
        </button>
      </div>
    </div>
  `;

  // Event listeners
  menuElement.querySelector(".centrifuge-menu-close").addEventListener("click", closeMenu);
  menuElement.querySelector("#centrifuge-mp3-btn").addEventListener("click", downloadMP3);
  menuElement.querySelector("#centrifuge-stems-btn").addEventListener("click", downloadStems);
  menuElement.querySelector("#centrifuge-cancel-btn").addEventListener("click", cancelJob);

  // Genre options
  menuElement.querySelectorAll(".centrifuge-genre-option").forEach(option => {
    option.addEventListener("click", () => {
      menuElement.querySelectorAll(".centrifuge-genre-option").forEach(o => o.classList.remove("selected"));
      option.classList.add("selected");
      selectedGenre = option.dataset.genre;
    });
  });

  // Quality options
  menuElement.querySelectorAll(".centrifuge-quality-option").forEach(option => {
    option.addEventListener("click", () => {
      menuElement.querySelectorAll(".centrifuge-quality-option").forEach(o => o.classList.remove("selected"));
      option.classList.add("selected");
      selectedQuality = option.dataset.quality;
    });
  });

  // Close menu when clicking outside
  document.addEventListener("click", (e) => {
    if (isMenuOpen && !menuElement.contains(e.target) && e.target !== floatingButton) {
      closeMenu();
    }
  });

  document.body.appendChild(menuElement);
  return menuElement;
}

function toggleMenu() {
  if (!menuElement) {
    createMenu();
  }

  if (isMenuOpen) {
    closeMenu();
  } else {
    openMenu();
  }
}

function openMenu() {
  if (!menuElement) createMenu();

  // Update video title
  const videoTitle = getVideoTitle();
  const shortTitle = videoTitle.length > 50 ? videoTitle.substring(0, 47) + "..." : videoTitle;
  menuElement.querySelector(".centrifuge-menu-subtitle").textContent = shortTitle;

  // Check for active job
  checkActiveJob();

  menuElement.classList.add("visible");
  isMenuOpen = true;
}

function closeMenu() {
  if (menuElement) {
    menuElement.classList.remove("visible");
  }
  isMenuOpen = false;
}

async function checkActiveJob() {
  try {
    const response = await browser.runtime.sendMessage({ action: "get_progress" });

    if (response.stage && ["downloading", "processing", "finalizing"].includes(response.stage)) {
      showProgressInMenu(response);
    } else {
      hideProgressInMenu();
    }
  } catch (error) {
    hideProgressInMenu();
  }
}

function showProgressInMenu(progress) {
  if (!menuElement) return;

  const progressContainer = menuElement.querySelector("#centrifuge-progress-container");
  const downloadOptions = menuElement.querySelector("#centrifuge-download-options");
  const progressTitle = menuElement.querySelector("#centrifuge-progress-title");
  const progressBar = menuElement.querySelector("#centrifuge-progress-bar");
  const progressText = menuElement.querySelector("#centrifuge-progress-text");

  progressContainer.style.display = "block";
  downloadOptions.style.display = "none";

  const title = progress.video_title || "Processing";
  const shortTitle = title.length > 40 ? title.substring(0, 37) + "..." : title;
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

  progressTitle.textContent = shortTitle;
  progressBar.style.width = `${percent}%`;
  progressText.textContent = `${percent}% - ${stageText}`;

  // Update floating button
  if (floatingButton) {
    floatingButton.classList.add("processing");
    floatingButton.innerHTML = `${percent}%`;
  }
}

function hideProgressInMenu() {
  if (!menuElement) return;

  const progressContainer = menuElement.querySelector("#centrifuge-progress-container");
  const downloadOptions = menuElement.querySelector("#centrifuge-download-options");

  if (progressContainer) progressContainer.style.display = "none";
  if (downloadOptions) downloadOptions.style.display = "block";

  // Reset floating button
  if (floatingButton) {
    floatingButton.classList.remove("processing");
    floatingButton.innerHTML = "🎵";
  }
}

function setButtonsDisabled(disabled) {
  if (!menuElement) return;

  const mp3Btn = menuElement.querySelector("#centrifuge-mp3-btn");
  const stemsBtn = menuElement.querySelector("#centrifuge-stems-btn");

  if (mp3Btn) mp3Btn.disabled = disabled;
  if (stemsBtn) stemsBtn.disabled = disabled;
}

async function downloadMP3() {
  currentVideoUrl = getCurrentVideoUrl();
  if (!currentVideoUrl) {
    showStatus("No YouTube video found", "error");
    return;
  }

  setButtonsDisabled(true);
  showStatus("Downloading MP3...", "downloading");

  try {
    const response = await browser.runtime.sendMessage({
      action: "download_mp3",
      url: currentVideoUrl
    });

    if (response.success) {
      showStatus(`Downloaded: ${response.filename}`, "success", true);
    } else {
      showStatus(`Error: ${response.error}`, "error", true);
    }
    setButtonsDisabled(false);
  } catch (error) {
    console.error("MP3 download error:", error);
    showStatus(`Error: ${error.message}`, "error", true);
    setButtonsDisabled(false);
  }
}

async function downloadStems() {
  currentVideoUrl = getCurrentVideoUrl();
  if (!currentVideoUrl) {
    showStatus("No YouTube video found", "error");
    return;
  }

  setButtonsDisabled(true);
  showStatus("Starting stem separation...", "downloading");

  try {
    const response = await browser.runtime.sendMessage({
      action: "download_stems",
      url: currentVideoUrl,
      quality: selectedQuality,
      genre: selectedGenre
    });

    if (response.success) {
      // Job started, show progress UI
      showProgressInMenu({
        stage: "downloading",
        video_title: response.video_title,
        percent: 0
      });
    } else {
      showStatus(`Error: ${response.error}`, "error", true);
      setButtonsDisabled(false);
    }
  } catch (error) {
    console.error("Stems download error:", error);
    showStatus(`Error: ${error.message}`, "error", true);
    setButtonsDisabled(false);
  }
}

async function cancelJob() {
  try {
    const response = await browser.runtime.sendMessage({ action: "cancel_job" });
    if (response.success) {
      hideProgressInMenu();
      setButtonsDisabled(false);
      showStatus("Job cancelled", "idle", true);
    } else {
      showStatus(`Cancel failed: ${response.error}`, "error", true);
    }
  } catch (error) {
    console.error("Cancel error:", error);
    showStatus(`Error: ${error.message}`, "error", true);
  }
}

function createStatusElement() {
  if (statusElement) return statusElement;

  statusElement = document.createElement("div");
  statusElement.id = "centrifuge-status";

  const iconEl = document.createElement("div");
  iconEl.className = "centrifuge-status-icon";

  const textEl = document.createElement("div");
  textEl.className = "centrifuge-status-text";
  textEl.textContent = "Ready";

  const closeBtn = document.createElement("button");
  closeBtn.className = "centrifuge-status-close";
  closeBtn.textContent = "\u00D7";
  closeBtn.addEventListener("click", hideStatus);

  statusElement.appendChild(iconEl);
  statusElement.appendChild(textEl);
  statusElement.appendChild(closeBtn);

  document.body.appendChild(statusElement);
  return statusElement;
}

function showStatus(message, type = "downloading", autoHide = false) {
  const el = createStatusElement();

  if (hideTimeout) {
    clearTimeout(hideTimeout);
    hideTimeout = null;
  }

  el.className = `visible ${type}`;
  el.querySelector(".centrifuge-status-text").textContent = message;

  if (autoHide && (type === "success" || type === "error" || type === "idle")) {
    hideTimeout = setTimeout(hideStatus, 5000);
  }
}

function hideStatus() {
  if (statusElement) {
    statusElement.classList.remove("visible");
  }
}

// Listen for messages from background script
browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "status_update") {
    const { status, text, progress, autoHide } = message;

    if (status === "hidden" || status === "idle") {
      hideStatus();
      hideProgressInMenu();
      setButtonsDisabled(false);
    } else if (status === "downloading") {
      // Update menu progress if it's open
      if (isMenuOpen && menuElement) {
        showProgressInMenu({
          stage: "processing",
          message: text,
          percent: progress || 0
        });
      }

      // Update floating button
      if (floatingButton) {
        floatingButton.classList.add("processing");
        if (progress !== null && progress !== undefined) {
          floatingButton.innerHTML = `${progress}%`;
        }
      }
    } else if (status === "success" || status === "error") {
      showStatus(text, status, autoHide);
      hideProgressInMenu();
      setButtonsDisabled(false);

      if (floatingButton) {
        floatingButton.classList.remove("processing");
        floatingButton.innerHTML = "🎵";
      }
    }
  }
  return false;
});

// Initialize when on a video page
function initialize() {
  if (isVideoPage()) {
    injectStyles();
    createFloatingButton();

    // Check if there's an active download
    browser.runtime.sendMessage({ action: "check_status" })
      .then(response => {
        if (response.stage && ["downloading", "processing", "finalizing"].includes(response.stage)) {
          if (floatingButton) {
            floatingButton.classList.add("processing");
            floatingButton.innerHTML = `${response.percent || 0}%`;
          }
        }
      })
      .catch(() => {});
  } else {
    // Remove floating button if not on video page
    if (floatingButton) {
      floatingButton.remove();
      floatingButton = null;
    }
    if (menuElement) {
      menuElement.remove();
      menuElement = null;
    }
  }
}

// Handle YouTube's SPA navigation
let lastUrl = location.href;
new MutationObserver(() => {
  const url = location.href;
  if (url !== lastUrl) {
    lastUrl = url;
    // Small delay to let YouTube update the DOM
    setTimeout(initialize, 500);
  }
}).observe(document, { subtree: true, childList: true });

// Initial setup
initialize();

console.log("Centrifugue content script loaded");
