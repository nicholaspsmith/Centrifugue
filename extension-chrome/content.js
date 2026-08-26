/**
 * Content script for Centrifugue (Chrome)
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
// A conversion is running in the native host
let jobActive = false;
// A start/queue request is in flight, so a second click would double-submit
let submitting = false;
let contextInvalidated = false;

/**
 * True while this script's extension context is alive. Reloading/updating the
 * extension orphans injected scripts: their chrome.runtime binding is severed
 * (chrome.runtime.id becomes undefined) but the script and its DOM live on.
 */
function isExtensionContextValid() {
  try {
    return Boolean(chrome.runtime && chrome.runtime.id);
  } catch (error) {
    return false;
  }
}

function isContextInvalidatedError(error) {
  return Boolean(error && typeof error.message === "string" &&
                 error.message.includes("Extension context invalidated"));
}

/**
 * Neuter this orphaned copy of the script: stop watching navigation, remove
 * its UI, and optionally tell the user to refresh. The new extension
 * instance's background worker re-injects a fresh copy (see background.js),
 * so passive detection stays silent; only a user click shows the message.
 */
function handleInvalidatedContext(notify) {
  if (contextInvalidated) return;
  contextInvalidated = true;

  navigationObserver.disconnect();

  if (floatingButton) {
    floatingButton.remove();
    floatingButton = null;
  }
  if (menuElement) {
    menuElement.remove();
    menuElement = null;
  }
  isMenuOpen = false;
  hideSetupUI();

  if (notify) {
    showStatus("Centrifugue was updated — refresh this page to keep using it", "error");
  } else if (statusElement) {
    statusElement.remove();
    statusElement = null;
  }
}

/**
 * Send a message to the background worker, detecting extension reloads.
 * Returns null (after tearing down this orphaned script) if the extension
 * context is gone; callers must handle null.
 */
async function sendMessageSafe(message, notifyOnInvalid) {
  if (contextInvalidated || !isExtensionContextValid()) {
    handleInvalidatedContext(notifyOnInvalid);
    return null;
  }
  try {
    return await chrome.runtime.sendMessage(message);
  } catch (error) {
    if (isContextInvalidatedError(error)) {
      handleInvalidatedContext(notifyOnInvalid);
      return null;
    }
    throw error;
  }
}

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
  if (document.getElementById("centrifugue-styles")) return;

  const styles = document.createElement("style");
  styles.id = "centrifugue-styles";
  styles.textContent = `
    #centrifugue-floating-btn {
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
    #centrifugue-floating-btn:hover {
      transform: scale(1.1);
      box-shadow: 0 6px 16px rgba(0,0,0,0.4);
    }
    #centrifugue-floating-btn.processing {
      background: linear-gradient(135deg, #1565c0 0%, #0d47a1 100%);
      animation: centrifugue-pulse 2s ease-in-out infinite;
    }
    #centrifugue-floating-btn.hidden {
      display: none;
    }

    @keyframes centrifugue-pulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.05); }
    }

    #centrifugue-menu {
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
    #centrifugue-menu.visible {
      opacity: 1;
      transform: translateY(0) scale(1);
      pointer-events: auto;
    }

    .centrifugue-menu-header {
      background: linear-gradient(135deg, #ff0000 0%, #cc0000 100%);
      padding: 14px 16px;
      color: white;
    }
    .centrifugue-menu-title {
      font-weight: 600;
      font-size: 14px;
      margin-bottom: 4px;
    }
    .centrifugue-menu-subtitle {
      font-size: 11px;
      opacity: 0.85;
      line-height: 1.3;
      word-break: break-word;
    }

    .centrifugue-menu-body {
      padding: 16px;
    }

    .centrifugue-menu-btn {
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
    .centrifugue-menu-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    #centrifugue-mp3-btn {
      background: #ff0000;
      color: white;
    }
    #centrifugue-mp3-btn:hover:not(:disabled) {
      background: #cc0000;
    }

    .centrifugue-section-title {
      font-size: 12px;
      color: #888;
      margin-bottom: 8px;
      font-weight: 500;
    }

    .centrifugue-options-row {
      display: flex;
      gap: 8px;
      margin-bottom: 12px;
    }

    .centrifugue-option {
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
    .centrifugue-option:hover {
      border-color: #555;
    }
    .centrifugue-option.selected {
      border-color: #9c27b0;
      background: rgba(156, 39, 176, 0.2);
    }
    .centrifugue-genre-option.selected {
      border-color: #ff5722;
      background: rgba(255, 87, 34, 0.2);
    }
    .centrifugue-option-label {
      font-weight: 600;
      font-size: 12px;
    }
    .centrifugue-option-desc {
      font-size: 10px;
      color: #888;
      margin-top: 2px;
    }

    #centrifugue-stems-btn {
      background: #9c27b0;
      color: white;
      margin-bottom: 0;
    }
    #centrifugue-stems-btn:hover:not(:disabled) {
      background: #7b1fa2;
    }

    .centrifugue-menu-close {
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
    .centrifugue-menu-close:hover {
      color: #fff;
    }

    #centrifugue-status {
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
      pointer-events: none;
    }
    #centrifugue-status.visible {
      opacity: 1;
      transform: translateY(0);
      pointer-events: auto;
    }
    #centrifugue-status.downloading {
      background: #1565c0;
    }
    #centrifugue-status.success {
      background: #2e7d32;
    }
    #centrifugue-status.error {
      background: #c62828;
    }
    .centrifugue-status-icon {
      width: 20px;
      height: 20px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    #centrifugue-status.downloading .centrifugue-status-icon {
      border: 2px solid rgba(255,255,255,0.3);
      border-top-color: #fff;
      animation: centrifugue-spin 1s linear infinite;
    }
    #centrifugue-status.success .centrifugue-status-icon::after {
      content: "\\2713";
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 14px;
    }
    #centrifugue-status.error .centrifugue-status-icon::after {
      content: "!";
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 14px;
      font-weight: bold;
    }
    .centrifugue-status-text {
      flex: 1;
      line-height: 1.4;
      white-space: pre-line;
    }
    .centrifugue-status-close {
      background: none;
      border: none;
      color: rgba(255,255,255,0.7);
      font-size: 18px;
      cursor: pointer;
      padding: 0 0 0 8px;
      line-height: 1;
    }
    .centrifugue-status-close:hover {
      color: #fff;
    }
    @keyframes centrifugue-spin {
      to { transform: rotate(360deg); }
    }

    .centrifugue-progress-section {
      background: #222;
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 12px;
    }
    .centrifugue-progress-title {
      font-size: 12px;
      color: #fff;
      margin-bottom: 8px;
      word-break: break-word;
    }
    .centrifugue-progress-bar-container {
      height: 6px;
      background: #333;
      border-radius: 3px;
      overflow: hidden;
      margin-bottom: 6px;
    }
    .centrifugue-progress-bar {
      height: 100%;
      background: linear-gradient(90deg, #1565c0, #42a5f5);
      border-radius: 3px;
      transition: width 0.3s ease;
    }
    .centrifugue-progress-text {
      font-size: 11px;
      color: #888;
    }
    #centrifugue-cancel-btn {
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
    #centrifugue-cancel-btn:hover {
      background: #555;
    }

    #centrifugue-setup-overlay {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.85);
      z-index: 10000;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    .centrifugue-setup-modal {
      background: #1a1a1a;
      border-radius: 16px;
      padding: 24px;
      max-width: 500px;
      width: 90%;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    }
    .centrifugue-setup-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;
    }
    .centrifugue-setup-icon {
      font-size: 32px;
    }
    .centrifugue-setup-title {
      font-size: 20px;
      font-weight: 600;
      color: #fff;
    }
    .centrifugue-setup-subtitle {
      color: #888;
      font-size: 14px;
      margin-bottom: 20px;
      line-height: 1.5;
    }
    .centrifugue-setup-step {
      background: #222;
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 12px;
    }
    .centrifugue-setup-step-title {
      font-weight: 600;
      color: #fff;
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .centrifugue-setup-step-num {
      background: #ff0000;
      color: #fff;
      width: 24px;
      height: 24px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      font-weight: 700;
    }
    .centrifugue-setup-step-content {
      color: #aaa;
      font-size: 13px;
      line-height: 1.5;
    }
    .centrifugue-setup-code {
      background: #111;
      border: 1px solid #333;
      border-radius: 6px;
      padding: 12px;
      margin-top: 8px;
      font-family: 'SF Mono', Monaco, Consolas, monospace;
      font-size: 11px;
      color: #4fc3f7;
      word-break: break-all;
      position: relative;
    }
    .centrifugue-setup-copy-btn {
      position: absolute;
      top: 8px;
      right: 8px;
      background: #444;
      border: none;
      color: #fff;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 11px;
      cursor: pointer;
    }
    .centrifugue-setup-copy-btn:hover {
      background: #555;
    }
    .centrifugue-setup-copy-btn.copied {
      background: #2e7d32;
    }
    .centrifugue-setup-close {
      width: 100%;
      padding: 12px;
      background: #333;
      border: none;
      color: #fff;
      border-radius: 8px;
      font-size: 14px;
      cursor: pointer;
      margin-top: 8px;
    }
    .centrifugue-setup-close:hover {
      background: #444;
    }
  
  #centrifugue-queue { margin-top: 10px; }
  #centrifugue-queue { color: #fff; }
  .centrifugue-queue-row { border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; padding: 6px; margin-bottom: 6px; background: #222; }
  .centrifugue-queue-title { font-size: 11px; color: #fff; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .centrifugue-queue-meta { font-size: 10px; color: #bbb; margin-top: 2px; }
  .centrifugue-queue-actions { margin-top: 4px; display: flex; gap: 4px; }
  .centrifugue-queue-actions button { font-size: 10px; padding: 2px 6px; cursor: pointer; background: #444; color: #fff; border: none; border-radius: 4px; }
  .centrifugue-queue-actions button:hover:not(:disabled) { background: #555; }
  .centrifugue-queue-actions button:disabled { opacity: 0.5; cursor: default; }
  #centrifugue-queue .centrifugue-section-title { color: #888; }

  /* Fullscreen video: get the whole UI out of the way */
  body:fullscreen #centrifugue-floating-btn,
  body:fullscreen #centrifugue-menu,
  body:fullscreen #centrifugue-status,
  .centrifugue-hidden-fullscreen { display: none !important; }
`;
  document.head.appendChild(styles);
}

function createFloatingButton() {
  if (floatingButton) return floatingButton;

  injectStyles();

  floatingButton = document.createElement("button");
  floatingButton.id = "centrifugue-floating-btn";
  floatingButton.textContent = "🎵";
  floatingButton.title = "Download Audio";

  floatingButton.addEventListener("click", toggleMenu);

  document.body.appendChild(floatingButton);
  return floatingButton;
}

function createMenu() {
  if (menuElement) return menuElement;

  menuElement = document.createElement("div");
  menuElement.id = "centrifugue-menu";

  const videoTitle = getVideoTitle();
  const shortTitle = videoTitle.length > 50 ? videoTitle.substring(0, 47) + "..." : videoTitle;

  // Build menu using DOM methods instead of innerHTML for security
  const header = document.createElement("div");
  header.className = "centrifugue-menu-header";

  const closeBtn = document.createElement("button");
  closeBtn.className = "centrifugue-menu-close";
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", closeMenu);

  const title = document.createElement("div");
  title.className = "centrifugue-menu-title";
  title.textContent = "Download Audio";

  const subtitle = document.createElement("div");
  subtitle.className = "centrifugue-menu-subtitle";
  subtitle.textContent = shortTitle;

  header.appendChild(closeBtn);
  header.appendChild(title);
  header.appendChild(subtitle);

  const body = document.createElement("div");
  body.className = "centrifugue-menu-body";

  // Progress container
  const progressContainer = document.createElement("div");
  progressContainer.id = "centrifugue-progress-container";
  progressContainer.style.display = "none";

  const progressSection = document.createElement("div");
  progressSection.className = "centrifugue-progress-section";

  const progressTitle = document.createElement("div");
  progressTitle.className = "centrifugue-progress-title";
  progressTitle.id = "centrifugue-progress-title";
  progressTitle.textContent = "Processing...";

  const progressBarContainer = document.createElement("div");
  progressBarContainer.className = "centrifugue-progress-bar-container";

  const progressBar = document.createElement("div");
  progressBar.className = "centrifugue-progress-bar";
  progressBar.id = "centrifugue-progress-bar";
  progressBar.style.width = "0%";

  const progressText = document.createElement("div");
  progressText.className = "centrifugue-progress-text";
  progressText.id = "centrifugue-progress-text";
  progressText.textContent = "Starting...";

  progressBarContainer.appendChild(progressBar);
  progressSection.appendChild(progressTitle);
  progressSection.appendChild(progressBarContainer);
  progressSection.appendChild(progressText);

  const cancelBtn = document.createElement("button");
  cancelBtn.id = "centrifugue-cancel-btn";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", cancelJob);

  progressContainer.appendChild(progressSection);
  progressContainer.appendChild(cancelBtn);

  // Queue panel (populated by refreshQueuePanel)
  const queueContainer = document.createElement("div");
  queueContainer.id = "centrifugue-queue";
  queueContainer.style.display = "none";
  const queueTitle = document.createElement("div");
  queueTitle.className = "centrifugue-section-title";
  queueTitle.textContent = "Queue";
  const queueList = document.createElement("div");
  queueList.id = "centrifugue-queue-list";
  queueContainer.appendChild(queueTitle);
  queueContainer.appendChild(queueList);

  // Download options
  const downloadOptions = document.createElement("div");
  downloadOptions.id = "centrifugue-download-options";

  // MP3 button
  const mp3Btn = document.createElement("button");
  mp3Btn.className = "centrifugue-menu-btn";
  mp3Btn.id = "centrifugue-mp3-btn";
  const mp3Icon = document.createElement("span");
  mp3Icon.textContent = "🎵";
  mp3Btn.appendChild(mp3Icon);
  mp3Btn.appendChild(document.createTextNode(" Download MP3"));
  mp3Btn.addEventListener("click", downloadMP3);

  // Genre section
  const genreTitle = document.createElement("div");
  genreTitle.className = "centrifugue-section-title";
  genreTitle.textContent = "Genre Mode";

  const genreRow = document.createElement("div");
  genreRow.className = "centrifugue-options-row";

  const genres = [
    { value: "full", label: "Full", desc: "4 stems", selected: true },
    { value: "hiphop", label: "Hip Hop", desc: "Vocals + Beat", selected: false },
    { value: "rock", label: "Rock", desc: "Vox/Drums/Bass", selected: false }
  ];

  genres.forEach(g => {
    const opt = document.createElement("div");
    opt.className = "centrifugue-option centrifugue-genre-option" + (g.selected ? " selected" : "");
    opt.dataset.genre = g.value;

    const label = document.createElement("div");
    label.className = "centrifugue-option-label";
    label.textContent = g.label;

    const desc = document.createElement("div");
    desc.className = "centrifugue-option-desc";
    desc.textContent = g.desc;

    opt.appendChild(label);
    opt.appendChild(desc);
    opt.addEventListener("click", () => {
      genreRow.querySelectorAll(".centrifugue-genre-option").forEach(o => o.classList.remove("selected"));
      opt.classList.add("selected");
      selectedGenre = opt.dataset.genre;
    });
    genreRow.appendChild(opt);
  });

  // Quality section
  const qualityTitle = document.createElement("div");
  qualityTitle.className = "centrifugue-section-title";
  qualityTitle.textContent = "Quality";

  const qualityRow = document.createElement("div");
  qualityRow.className = "centrifugue-options-row";

  const qualities = [
    { value: "fast", label: "Fast", desc: "~2 min", selected: true },
    { value: "balanced", label: "Detailed", desc: "~4 min", selected: false },
    { value: "ultra", label: "Ultra", desc: "~10 min", selected: false }
  ];

  qualities.forEach(q => {
    const opt = document.createElement("div");
    opt.className = "centrifugue-option centrifugue-quality-option" + (q.selected ? " selected" : "");
    opt.dataset.quality = q.value;

    const label = document.createElement("div");
    label.className = "centrifugue-option-label";
    label.textContent = q.label;

    const desc = document.createElement("div");
    desc.className = "centrifugue-option-desc";
    desc.textContent = q.desc;

    opt.appendChild(label);
    opt.appendChild(desc);
    opt.addEventListener("click", () => {
      qualityRow.querySelectorAll(".centrifugue-quality-option").forEach(o => o.classList.remove("selected"));
      opt.classList.add("selected");
      selectedQuality = opt.dataset.quality;
    });
    qualityRow.appendChild(opt);
  });

  // Stems button
  const stemsBtn = document.createElement("button");
  stemsBtn.className = "centrifugue-menu-btn";
  stemsBtn.id = "centrifugue-stems-btn";
  const stemsIcon = document.createElement("span");
  stemsIcon.textContent = "🎛️";
  stemsBtn.appendChild(stemsIcon);
  const stemsLabel = document.createElement("span");
  stemsLabel.id = "centrifugue-stems-label";
  stemsLabel.textContent = "Download Stems";
  stemsBtn.appendChild(stemsLabel);
  stemsBtn.addEventListener("click", downloadStems);

  downloadOptions.appendChild(mp3Btn);
  downloadOptions.appendChild(genreTitle);
  downloadOptions.appendChild(genreRow);
  downloadOptions.appendChild(qualityTitle);
  downloadOptions.appendChild(qualityRow);
  downloadOptions.appendChild(stemsBtn);

  body.appendChild(progressContainer);
  body.appendChild(queueContainer);
  body.appendChild(downloadOptions);

  menuElement.appendChild(header);
  menuElement.appendChild(body);

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
  if (contextInvalidated || !isExtensionContextValid()) {
    handleInvalidatedContext(true);
    return;
  }

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
  menuElement.querySelector(".centrifugue-menu-subtitle").textContent = shortTitle;

  // Check if native messaging is configured
  checkNativeMessaging();

  // Check for active job
  checkActiveJob();

  menuElement.classList.add("visible");
  isMenuOpen = true;
}

async function checkNativeMessaging() {
  try {
    const response = await sendMessageSafe({ action: "check_native_messaging" });
    if (response && !response.configured) {
      const idResponse = await sendMessageSafe({ action: "get_extension_id" });
      if (idResponse && idResponse.extensionId) {
        showSetupUI(idResponse.extensionId);
      }
    }
  } catch (error) {
    console.error("Failed to check native messaging:", error);
  }
}

function closeMenu() {
  if (menuElement) {
    menuElement.classList.remove("visible");
  }
  isMenuOpen = false;
}

async function checkActiveJob() {
  try {
    const response = await sendMessageSafe({ action: "get_progress" });

    const running = Boolean(response && response.stage &&
      ["downloading", "processing", "finalizing"].includes(response.stage));
    setButtonsDisabled(running);
    if (running) {
      // showProgressInMenu refreshes the queue panel itself
      showProgressInMenu(response);
    } else {
      hideProgressInMenu();
      // Nothing is running, but jobs may still be queued or finished
      refreshQueuePanel();
    }
  } catch (error) {
    hideProgressInMenu();
  }
}

function showProgressInMenu(progress) {
  if (!menuElement) return;

  const progressContainer = menuElement.querySelector("#centrifugue-progress-container");
  const progressTitle = menuElement.querySelector("#centrifugue-progress-title");
  const progressBar = menuElement.querySelector("#centrifugue-progress-bar");
  const progressText = menuElement.querySelector("#centrifugue-progress-text");

  // The download options deliberately stay on screen: that is what lets a
  // second song be queued behind the one running
  progressContainer.style.display = "block";

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
    floatingButton.textContent = `${percent}%`;
  }

  refreshQueuePanel();
}

function hideProgressInMenu() {
  if (!menuElement) return;

  const progressContainer = menuElement.querySelector("#centrifugue-progress-container");

  if (progressContainer) progressContainer.style.display = "none";

  // Reset floating button
  if (floatingButton) {
    floatingButton.classList.remove("processing");
    floatingButton.textContent = "🎵";
  }
}

function setButtonsDisabled(disabled) {
  jobActive = disabled;
  syncMenuButtons();
}

/**
 * Reflect the current state on the menu buttons.
 *
 * The stems button stays clickable while a job runs: the native host appends
 * the request to its queue instead of rejecting it. Only the label changes, so
 * the button always says what pressing it will actually do. MP3 has no queue
 * behind it, so it still waits its turn.
 */
function syncMenuButtons() {
  if (!menuElement) return;

  const mp3Btn = menuElement.querySelector("#centrifugue-mp3-btn");
  const stemsBtn = menuElement.querySelector("#centrifugue-stems-btn");
  const stemsLabel = menuElement.querySelector("#centrifugue-stems-label");

  if (mp3Btn) mp3Btn.disabled = jobActive || submitting;
  if (stemsBtn) stemsBtn.disabled = submitting;
  if (stemsLabel) {
    stemsLabel.textContent = jobActive ? "Add to Queue" : "Download Stems";
  }
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
    const response = await sendMessageSafe({
      action: "download_mp3",
      url: currentVideoUrl
    }, true);
    if (!response) return;

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
  if (submitting) return;

  submitting = true;
  syncMenuButtons();
  const queueing = jobActive;
  showStatus(queueing ? "Adding to queue..." : "Starting stem separation...",
             "downloading");

  try {
    const response = await sendMessageSafe({
      action: "download_stems",
      url: currentVideoUrl,
      quality: selectedQuality,
      genre: selectedGenre
    }, true);
    if (!response) return;

    if (response.success) {
      if (response.queued) {
        // Another job holds the slot. Leave its progress display alone -- this
        // one is only waiting, and the queue panel shows where it sits.
        showStatus(`Queued: ${response.video_title || "stems"}`, "success", true);
        refreshQueuePanel();
      } else {
        setButtonsDisabled(true);
        showProgressInMenu({
          stage: "downloading",
          video_title: response.video_title,
          percent: 0
        });
      }
    } else {
      showStatus(`Error: ${response.error}`, "error", true);
    }
  } catch (error) {
    console.error("Stems download error:", error);
    showStatus(`Error: ${error.message}`, "error", true);
  } finally {
    submitting = false;
    syncMenuButtons();
  }
}

async function cancelJob() {
  try {
    const response = await sendMessageSafe({ action: "cancel_job" }, true);
    if (!response) return;

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
  statusElement.id = "centrifugue-status";

  const iconEl = document.createElement("div");
  iconEl.className = "centrifugue-status-icon";

  const textEl = document.createElement("div");
  textEl.className = "centrifugue-status-text";
  textEl.textContent = "Ready";

  const closeBtn = document.createElement("button");
  closeBtn.className = "centrifugue-status-close";
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", hideStatus);

  statusElement.appendChild(iconEl);
  statusElement.appendChild(textEl);
  statusElement.appendChild(closeBtn);

  document.body.appendChild(statusElement);
  return statusElement;
}

function showStatus(message, type, autoHide) {
  type = type || "downloading";
  autoHide = autoHide || false;
  
  const el = createStatusElement();

  if (hideTimeout) {
    clearTimeout(hideTimeout);
    hideTimeout = null;
  }

  el.className = "visible " + type;
  el.querySelector(".centrifugue-status-text").textContent = message;

  if (autoHide && (type === "success" || type === "error" || type === "idle")) {
    hideTimeout = setTimeout(hideStatus, 5000);
  }
}

function hideStatus() {
  if (statusElement) {
    statusElement.classList.remove("visible");
  }
}

// Setup UI for native messaging configuration
let setupOverlay = null;

function showSetupUI(extensionId) {
  if (setupOverlay) return; // Already showing

  injectStyles();

  setupOverlay = document.createElement("div");
  setupOverlay.id = "centrifugue-setup-overlay";

  const modal = document.createElement("div");
  modal.className = "centrifugue-setup-modal";

  // Header
  const header = document.createElement("div");
  header.className = "centrifugue-setup-header";

  const icon = document.createElement("span");
  icon.className = "centrifugue-setup-icon";
  icon.textContent = "🔧";

  const title = document.createElement("span");
  title.className = "centrifugue-setup-title";
  title.textContent = "Setup Required";

  header.appendChild(icon);
  header.appendChild(title);

  // Subtitle
  const subtitle = document.createElement("div");
  subtitle.className = "centrifugue-setup-subtitle";
  subtitle.textContent = "Centrifugue needs to connect to its native host for audio processing. Run this command in Terminal to complete setup:";

  // Step 1 - The command
  const step1 = document.createElement("div");
  step1.className = "centrifugue-setup-step";

  const step1Title = document.createElement("div");
  step1Title.className = "centrifugue-setup-step-title";

  const step1Num = document.createElement("span");
  step1Num.className = "centrifugue-setup-step-num";
  step1Num.textContent = "1";

  step1Title.appendChild(step1Num);
  step1Title.appendChild(document.createTextNode(" Copy and run in Terminal"));

  const step1Content = document.createElement("div");
  step1Content.className = "centrifugue-setup-step-content";

  const codeBlock = document.createElement("div");
  codeBlock.className = "centrifugue-setup-code";

  // The command to update the manifest
  const manifestPath = "~/Library/Application\\ Support/Google/Chrome/NativeMessagingHosts/com.centrifugue.stemextractor.json";
  const sedCommand = `sed -i '' 's/YOUR_EXTENSION_ID_HERE/${extensionId}/' ${manifestPath}`;

  codeBlock.textContent = sedCommand;

  const copyBtn = document.createElement("button");
  copyBtn.className = "centrifugue-setup-copy-btn";
  copyBtn.textContent = "Copy";
  copyBtn.addEventListener("click", () => {
    navigator.clipboard.writeText(sedCommand.replace(/\\ /g, " ")).then(() => {
      copyBtn.textContent = "Copied!";
      copyBtn.classList.add("copied");
      setTimeout(() => {
        copyBtn.textContent = "Copy";
        copyBtn.classList.remove("copied");
      }, 2000);
    });
  });

  codeBlock.appendChild(copyBtn);
  step1Content.appendChild(codeBlock);
  step1.appendChild(step1Title);
  step1.appendChild(step1Content);

  // Step 2 - Reload
  const step2 = document.createElement("div");
  step2.className = "centrifugue-setup-step";

  const step2Title = document.createElement("div");
  step2Title.className = "centrifugue-setup-step-title";

  const step2Num = document.createElement("span");
  step2Num.className = "centrifugue-setup-step-num";
  step2Num.textContent = "2";

  step2Title.appendChild(step2Num);
  step2Title.appendChild(document.createTextNode(" Reload this page"));

  const step2Content = document.createElement("div");
  step2Content.className = "centrifugue-setup-step-content";
  step2Content.textContent = "After running the command, refresh this page to start using Centrifugue.";

  step2.appendChild(step2Title);
  step2.appendChild(step2Content);

  // Extension ID info
  const idInfo = document.createElement("div");
  idInfo.className = "centrifugue-setup-step-content";
  idInfo.style.marginTop = "12px";
  idInfo.style.fontSize = "11px";
  idInfo.style.color = "#666";
  idInfo.textContent = `Extension ID: ${extensionId}`;

  // Close button
  const closeBtn = document.createElement("button");
  closeBtn.className = "centrifugue-setup-close";
  closeBtn.textContent = "Close";
  closeBtn.addEventListener("click", hideSetupUI);

  // Assemble modal
  modal.appendChild(header);
  modal.appendChild(subtitle);
  modal.appendChild(step1);
  modal.appendChild(step2);
  modal.appendChild(idInfo);
  modal.appendChild(closeBtn);

  setupOverlay.appendChild(modal);
  document.body.appendChild(setupOverlay);

  // Close on overlay click
  setupOverlay.addEventListener("click", (e) => {
    if (e.target === setupOverlay) {
      hideSetupUI();
    }
  });
}

function hideSetupUI() {
  if (setupOverlay) {
    setupOverlay.remove();
    setupOverlay = null;
  }
}

// Listen for messages from background script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "ping") {
    // Liveness check from background.js before re-injecting after a reload
    sendResponse({ pong: true });
    return false;
  }

  if (message.type === "setup_required") {
    showSetupUI(message.extensionId);
    return false;
  }

  if (message.type === "status_update") {
    const status = message.status;
    const text = message.text;
    const progress = message.progress;
    const autoHide = message.autoHide;

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
          floatingButton.textContent = progress + "%";
        }
      }
    } else if (status === "success" || status === "error") {
      showStatus(text, status, autoHide);
      hideProgressInMenu();
      setButtonsDisabled(false);

      if (floatingButton) {
        floatingButton.classList.remove("processing");
        floatingButton.textContent = "🎵";
      }
    }
  }
  return false;
});

/**
 * Remove UI elements left in the page by a previous (now orphaned) copy of
 * this script — Chromium keeps the old DOM across extension reloads, and the
 * re-injected copy runs in a fresh isolated world that can't see the old
 * script's variables, only its DOM.
 */
function removeOrphanedUi() {
  const ids = [
    "centrifugue-styles",
    "centrifugue-floating-btn",
    "centrifugue-menu",
    "centrifugue-status",
    "centrifugue-setup-overlay"
  ];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }
}

// Initialize when on a video page
function initialize() {
  if (contextInvalidated) return;

  if (isVideoPage()) {
    injectStyles();
    createFloatingButton();

    // Check if there's an active download
    sendMessageSafe({ action: "check_status" })
      .then(response => {
        if (response && response.stage && ["downloading", "processing", "finalizing"].includes(response.stage)) {
          if (floatingButton) {
            floatingButton.classList.add("processing");
            floatingButton.textContent = (response.percent || 0) + "%";
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
const navigationObserver = new MutationObserver(() => {
  const url = location.href;
  if (url !== lastUrl) {
    lastUrl = url;
    // Small delay to let YouTube update the DOM
    setTimeout(initialize, 500);
  }
});
navigationObserver.observe(document, { subtree: true, childList: true });

// Initial setup
removeOrphanedUi();
initialize();

console.log("Centrifugue content script loaded");

const CENTRIFUGUE_STATUS_LABEL = {
  queued: "Queued", running: "Running", paused: "Paused",
  complete: "Done", error: "Failed", cancelled: "Cancelled",
};

async function refreshQueuePanel() {
  const container = document.getElementById("centrifugue-queue");
  const list = document.getElementById("centrifugue-queue-list");
  if (!container || !list) return;

  let response;
  try {
    response = await chrome.runtime.sendMessage({ action: "get_queue" });
  } catch (error) {
    return;
  }
  if (!response || !response.success) return;

  const jobs = response.jobs || [];
  container.style.display = jobs.length ? "block" : "none";
  list.textContent = "";

  for (const job of jobs) {
    const progress = job.progress || {};
    const row = document.createElement("div");
    row.className = "centrifugue-queue-row";

    const title = document.createElement("div");
    title.className = "centrifugue-queue-title";
    title.textContent = job.title;
    row.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "centrifugue-queue-meta";
    meta.textContent =
      `${CENTRIFUGUE_STATUS_LABEL[job.status] || job.status}` +
      (job.status === "running" && progress.percent != null
        ? ` - ${progress.percent}%` : "");
    row.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "centrifugue-queue-actions";
    if (job.status === "running" || job.status === "queued") {
      actions.appendChild(makeQueueButton("Pause", "pause_job", job.job_id));
    }
    if (job.status === "paused") {
      actions.appendChild(makeQueueButton("Resume", "resume_job", job.job_id));
    }
    actions.appendChild(makeQueueButton("Remove", "remove_job", job.job_id));
    row.appendChild(actions);

    list.appendChild(row);
  }
}

function makeQueueButton(label, action, jobId) {
  const button = document.createElement("button");
  button.textContent = label;
  button.addEventListener("click", async (event) => {
    event.stopPropagation();
    button.disabled = true;
    try {
      await chrome.runtime.sendMessage({ action, job_id: jobId });
    } catch (error) {
      // A failed control action must not break the panel
    }
    await refreshQueuePanel();
  });
  return button;
}


// YouTube fullscreen should not have our UI floating over the video. The
// :fullscreen CSS rule covers the usual case; this also handles YouTube's
// own fullscreen handling, which does not always put body in :fullscreen.
function centrifugueIsFullscreen() {
  return Boolean(document.fullscreenElement || document.webkitFullscreenElement);
}

function updateFullscreenVisibility() {
  const hidden = centrifugueIsFullscreen();
  for (const el of [floatingButton, menuElement, statusElement]) {
    if (el) el.classList.toggle("centrifugue-hidden-fullscreen", hidden);
  }
  if (hidden && isMenuOpen) {
    closeMenu();
  }
}

document.addEventListener("fullscreenchange", updateFullscreenVisibility);
document.addEventListener("webkitfullscreenchange", updateFullscreenVisibility);
