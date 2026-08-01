<p align="center">
  <img src="logo.svg" alt="Centrifugue Logo" width="120" height="120">
</p>

<h1 align="center">Centrifugue</h1>

<p align="center">
  <strong>AI-Powered Audio Stem Separation for YouTube</strong>
</p>

Centrifugue is a browser extension that extracts audio stems (vocals, drums, bass, other) from YouTube videos using [Demucs](https://github.com/facebookresearch/demucs), a state-of-the-art AI model from Meta.

## Requirements

- macOS (Apple Silicon recommended for GPU acceleration)
- Firefox, Zen Browser, or Google Chrome
- Python 3.9+
- [Homebrew](https://brew.sh) (for installing dependencies)

## Installation

### 1. Clone and Install Dependencies

```bash
git clone https://github.com/yourusername/centrifugue.git
cd centrifugue
./install.sh
```

This will:
- Check/install required dependencies (yt-dlp, ffmpeg)
- Create a Python virtual environment
- Install Demucs and its dependencies
- Configure native messaging hosts for all browsers

### 2. Load the Extension

#### Firefox / Zen Browser

**Permanent install (recommended — survives browser restarts)**

```bash
./build-xpi.sh
```

1. Open `about:config` and set `xpinstall.signatures.required` to `false`
   (this add-on is not signed by Mozilla, so the browser will otherwise reject it)
2. Open `about:addons`
3. Click the gear icon → **Install Add-on From File...**
4. Select `dist/centrifugue-firefox.xpi`

**Temporary install (cleared when the browser restarts)**

1. Open Firefox or Zen Browser
2. Go to `about:debugging#/runtime/this-firefox`
3. Click "Load Temporary Add-on"
4. Navigate to the `extension-firefox` folder
5. Select `manifest.json`

> **Note:** Build the `.xpi` with `./build-xpi.sh` rather than zipping the folder by
> hand. The archive must be rooted at `manifest.json`; zipping the `extension-firefox`
> directory itself nests everything one level down and the browser rejects the result
> with "this add-on appears to be corrupt."

#### Google Chrome

1. Open Chrome and go to `chrome://extensions`
2. Enable **Developer mode** (toggle in top right)
3. Click **Load unpacked**
4. Navigate to the `extension-chrome` folder
5. Go to a YouTube video and click the floating 🎵 button
6. A setup overlay will appear with a Terminal command - click **Copy** and run it
7. Reload the page

> **Note:** Chrome requires a one-time setup because unpacked extensions get a unique ID. The extension detects this and shows the setup instructions automatically.

## Features

- **One-Click MP3 Download** - Extract audio from any YouTube video
- **AI Stem Separation** - Split audio into individual stems using Demucs and BS-RoFormer
- **Genre Modes**:
  - **Full** - All 4 stems (vocals, drums, bass, other)
  - **Hip Hop** - Vocals + Beat (combined instrumental)
  - **Rock** - Vocals, Drums, Bass
- **Quality Presets**:
  - **Fast** (~2 min) - Quick processing (htdemucs)
  - **Detailed** (~4 min) - Higher quality separation (fine-tuned htdemucs_ft)
  - **Ultra** (~10 min) - Best quality: BS-RoFormer vocal separation +
    Demucs instrument split, lossless FLAC output
- **Floating Button** - Access directly from YouTube without opening the extension
- **Background Processing** - Continue browsing while stems are extracted
- **Real-time Progress** - See actual Demucs progress, not just estimates
- **Apple Silicon Optimized** - Uses MPS GPU acceleration on M1/M2/M3 Macs

## Usage

1. Navigate to any YouTube video
2. Click the floating **🎵** button in the bottom-right corner
3. Choose your options:
   - **Download MP3** - Quick audio download
   - **Download Stems** - AI-powered stem separation
4. For stems, select:
   - Genre mode (Full, Hip Hop, or Rock)
   - Quality preset (Fast, Detailed, or Ultra)
5. Click "Download Stems" and wait for processing

You can close the popup or navigate to other videos - processing continues in the background!

### Output Structure

**MP3 Download:**
```
~/Downloads/
└── Song Title.mp3
```

**Stems Download:**
```
~/Downloads/
└── Song Title - Stems/
    ├── Song Title - Vocals.mp3
    ├── Song Title - Drums.mp3
    ├── Song Title - Bass.mp3
    └── Song Title - Other.mp3
```

## Architecture

```
centrifugue/
├── extension-firefox/      # Firefox/Zen extension (Manifest V2)
│   ├── manifest.json       # Extension configuration
│   ├── background.js       # Native messaging & progress polling
│   ├── content.js          # Floating UI on YouTube pages
│   └── popup/              # Extension popup UI
├── extension-chrome/       # Chrome extension (Manifest V3)
│   ├── manifest.json       # Chrome extension configuration
│   ├── background.js       # Service worker for native messaging
│   ├── content.js          # Floating UI on YouTube pages
│   └── popup/              # Extension popup UI
├── native-host/            # Native messaging host
│   └── centrifugue_host.py  # Python backend
├── venv-demucs/            # Python venv (created by install.sh)
├── build-xpi.sh            # Packages extension-firefox/ into an .xpi
└── install.sh              # Installation script
```

The extension communicates with a Python native messaging host that:
1. Downloads audio using yt-dlp
2. Spawns an independent worker process for stem separation
3. Runs Demucs with real-time progress parsing
4. Reports progress via JSON files that the extension polls

## Troubleshooting

### "Demucs not found" error
Run `./install.sh` to set up the virtual environment with Demucs.

### "Native messaging host not found" (Chrome)
Make sure you've updated the Chrome native messaging manifest with your extension ID:
1. Go to `chrome://extensions` and copy your extension ID
2. Edit `native-host/com.centrifugue.stemextractor.chrome.json`
3. Replace `YOUR_EXTENSION_ID_HERE` with your extension ID

### Slow processing
- Use the "Fast" quality preset for quicker results
- Ensure you're on Apple Silicon for GPU acceleration (MPS)
- Close other GPU-intensive applications

### Extension not working (Firefox)
1. Check that the extension is loaded in `about:debugging`
2. Verify native messaging is set up:
   ```bash
   ls -la ~/Library/Application\ Support/Mozilla/NativeMessagingHosts/
   ```
3. Look for errors in the browser console (F12 → Console)

### Extension not working (Chrome)
1. Check that the extension is loaded in `chrome://extensions`
2. Verify native messaging is set up:
   ```bash
   ls -la ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/
   cat ~/Library/Application\ Support/Google/Chrome/NativeMessagingHosts/com.centrifugue.stemextractor.json
   ```
3. Ensure the extension ID in the manifest matches your loaded extension

### Download fails with 403 Forbidden
Centrifugue uses Firefox cookies to authenticate with YouTube (required due to YouTube's bot detection). If downloads fail:

1. **Make sure Firefox is your default browser** or at least has been used to browse YouTube recently
2. **Update yt-dlp**: `brew upgrade yt-dlp`
3. **Test directly**:
   ```bash
   yt-dlp --cookies-from-browser firefox -x --audio-format mp3 "https://www.youtube.com/watch?v=VIDEO_ID"
   ```

> **Note:** If you see errors about "SABR streaming" or "403 Forbidden", this is a YouTube restriction. The Firefox cookies workaround should resolve it.

## License

MIT License

## Credits

- [Demucs](https://github.com/facebookresearch/demucs) by Meta Research
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for video downloading
- [FFmpeg](https://ffmpeg.org/) for audio processing
