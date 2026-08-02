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

## Configuration

Settings live in `~/.centrifugue/config.json`, created with defaults on first
run. To change the output folder, open the extension popup, expand
**Settings**, and click **Choose Folder...** — a native folder chooser opens
and the selection is saved for you.

The chooser is opened by the native host rather than the extension, because a
browser extension can never see an absolute filesystem path. Opening it takes
focus, which closes the popup; the choice is still saved, and a notification
confirms it. Reopen the popup to see the new path.

```json
{
  "output_dir": "~/Downloads",
  "naming": { "style": "lowercase_ascii", "max_length": 80 },
  "write_info_json": true
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `output_dir` | string | `~/Downloads` | Where song folders are written. `~` is expanded. |
| `naming.style` | string | `lowercase_ascii` | Folder naming style. Only this value is supported today. |
| `naming.max_length` | int | `80` | Maximum folder-name length before truncation. |
| `write_info_json` | bool | `true` | Set to `false` to skip the `info.json` sidecar. |

A missing or malformed config falls back to the defaults rather than failing a
download.

### Output layout

Each song gets one folder, named from a normalized slug of the video title.
Stems are named by stem type:

```
~/Downloads/rockhard_foolio/
├── vocals.flac
├── drums.flac
├── bass.flac
└── info.json
```

Re-downloading the same song with the **same** genre and quality replaces the
folder. A **different** genre or quality creates a separate
`rockhard_foolio_rock_ultra/` so variants coexist. A folder without a readable
`info.json` is never overwritten.

MP3-only downloads honour `output_dir` but create no folder and no `info.json`.

### Using stems in Ableton Live

Set the output folder to `~/Music/Ableton/User Library/Centrifugue`. The User
Library is already a Place in Live's browser, so new song folders appear while a
project is open — no restart and no manual rescan. Stems are published
atomically (assembled in a hidden temp folder, then moved into place in one
operation), so Live never sees a half-written folder.

FLAC — the Ultra preset's output format — requires Live 11 or newer.

## `info.json` reference

Every song folder gets an `info.json` describing how the stems were produced.
Keys are always present; unavailable values are `null` rather than omitted.

| Key | Type | Description |
|-----|------|-------------|
| `schema_version` | int | Sidecar format version. Currently `1`. |
| `song.title` | string | Original video title, unmodified. |
| `song.slug` | string | Normalized name used for the folder. |
| `song.url` | string | Source URL. |
| `song.video_id` | string\|null | YouTube video id, `null` if not parsed. |
| `song.duration_seconds` | float\|null | Source audio duration. |
| `separation` | object\|null | Present for stem jobs. |
| `separation.genre_mode` | string | `full`, `hiphop`, or `rock`. |
| `separation.quality_preset` | string | `fast`, `balanced`, or `ultra`. |
| `separation.stems` | string[] | Stem keys produced. |
| `separation.models` | object[] | Model chain, in the order it ran. |
| `separation.models[].stage` | string | `vocals` or `instruments`. |
| `separation.models[].kind` | string | `bs-roformer` or `demucs`. |
| `separation.models[].name` | string | Model identifier. |
| `separation.models[].shifts` | int\|null | Demucs shift passes. |
| `separation.models[].overlap` | float\|null | Demucs overlap. |
| `audio.format` | string | Container/extension, e.g. `flac`. |
| `audio.codec` | string | Codec name. |
| `audio.sample_rate` | int\|null | Sample rate in Hz. |
| `audio.channels` | int\|null | Channel count. |
| `audio.bit_depth` | int\|null | `null` for lossy formats. |
| `files[].stem` | string | Stem key. |
| `files[].filename` | string | Filename within the folder. |
| `files[].bytes` | int | File size in bytes. |
| `timing.started_at` | string | UTC ISO-8601, `Z` suffix. |
| `timing.completed_at` | string | UTC ISO-8601, `Z` suffix. |
| `timing.download_seconds` | float\|null | Time spent in yt-dlp. |
| `timing.separation_seconds` | float\|null | Time spent in the models. |
| `timing.total_seconds` | float | Wall-clock total for the job. |
| `environment.centrifugue_version` | string | Centrifugue version. |
| `environment.python` | string | Interpreter version. |
| `environment.platform` | string | OS-release-architecture. |
| `environment.device` | string\|null | `mps`, `cuda`, or `cpu`. |
| `environment.demucs` | string\|null | Installed Demucs version. |
| `environment.audio_separator` | string\|null | Installed audio-separator version. |
| `environment.torch` | string\|null | Installed torch version. |
| `environment.yt_dlp` | string\|null | yt-dlp version. |

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
│   ├── centrifugue_host.py    # Python backend
│   ├── centrifugue_config.py  # User config (~/.centrifugue/config.json)
│   ├── centrifugue_naming.py  # Slug, collision, atomic publish
│   └── centrifugue_info.py    # info.json builder
├── tests/                  # pytest suite for the host modules
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
