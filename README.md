<p align="center">
  <img src="logo.svg" alt="Centrifugue Logo" width="120" height="120">
</p>

<h1 align="center">Centrifugue</h1>

<p align="center">
  <strong>AI-Powered Audio Stem Separation for YouTube</strong>
</p>

Centrifugue is a Firefox/Zen Browser extension that extracts audio stems (vocals, drums, bass, other) from YouTube videos using [Demucs](https://github.com/facebookresearch/demucs), a state-of-the-art AI model from Meta.

## Features

- **One-Click MP3 Download** - Extract audio from any YouTube video
- **AI Stem Separation** - Split audio into individual stems using Demucs
- **Genre Modes**:
  - **Full** - All 4 stems (vocals, drums, bass, other)
  - **Hip Hop** - Vocals + Beat (combined instrumental)
  - **Rock** - Vocals, Drums, Bass
- **Quality Presets**:
  - **Fast** (~2 min) - Quick processing
  - **Balanced** (~5 min) - Good quality
  - **High** (~10 min) - Best quality, minimal stem bleed
- **Floating Button** - Access directly from YouTube without opening the extension
- **Background Processing** - Continue browsing while stems are extracted
- **Real-time Progress** - See actual Demucs progress, not just estimates
- **Apple Silicon Optimized** - Uses MPS GPU acceleration on M1/M2/M3 Macs

## Requirements

- macOS (Apple Silicon recommended for GPU acceleration)
- Firefox or Zen Browser
- Python 3.9+
- [Homebrew](https://brew.sh) (for installing dependencies)

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/centrifuge.git
   cd centrifuge
   ```

2. Run the install script:
   ```bash
   ./install.sh
   ```

   This will:
   - Check/install required dependencies (yt-dlp, ffmpeg)
   - Create a Python virtual environment
   - Install Demucs and its dependencies
   - Configure the native messaging host for Firefox/Zen

3. Load the extension in your browser:
   - Open Firefox/Zen Browser
   - Go to `about:debugging#/runtime/this-firefox`
   - Click "Load Temporary Add-on"
   - Navigate to the `extension` folder
   - Select `manifest.json`

## Usage

1. Navigate to any YouTube video
2. Click the floating **🎵** button in the bottom-right corner
3. Choose your options:
   - **Download MP3** - Quick audio download
   - **Download Stems** - AI-powered stem separation
4. For stems, select:
   - Genre mode (Full, Hip Hop, or Rock)
   - Quality preset (Fast, Balanced, or High)
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
├── extension/              # Browser extension
│   ├── manifest.json       # Extension configuration
│   ├── background.js       # Native messaging & progress polling
│   ├── content.js          # Floating UI on YouTube pages
│   └── popup/              # Extension popup UI
├── native-host/            # Native messaging host
│   └── centrifuge_host.py  # Python backend
├── venv-demucs/            # Python venv (created by install.sh)
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

### Slow processing
- Use the "Fast" quality preset for quicker results
- Ensure you're on Apple Silicon for GPU acceleration (MPS)
- Close other GPU-intensive applications

### Extension not working
1. Check that the extension is loaded in `about:debugging`
2. Verify native messaging is set up:
   ```bash
   ls -la ~/Library/Application\ Support/Mozilla/NativeMessagingHosts/
   ```
3. Look for errors in the browser console (F12 → Console)

### Download fails
- Update yt-dlp: `brew upgrade yt-dlp`
- Test directly:
  ```bash
  yt-dlp -x --audio-format mp3 "https://www.youtube.com/watch?v=VIDEO_ID"
  ```

## License

MIT License

## Credits

- [Demucs](https://github.com/facebookresearch/demucs) by Meta Research
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for video downloading
- [FFmpeg](https://ffmpeg.org/) for audio processing
