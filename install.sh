#!/bin/bash
# Centrifugue Installation Script
# Sets up the browser extension and native messaging host for stem separation

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NATIVE_HOST_DIR="$SCRIPT_DIR/native-host"
HOST_SCRIPT="$NATIVE_HOST_DIR/centrifugue_host.py"
MANIFEST_FILE="$NATIVE_HOST_DIR/com.centrifugue.stemextractor.json"
VENV_DIR="$SCRIPT_DIR/venv-demucs"

# Native messaging hosts directories
FIREFOX_NATIVE_DIR="$HOME/Library/Application Support/Mozilla/NativeMessagingHosts"
ZEN_NATIVE_DIR="$HOME/Library/Application Support/zen/NativeMessagingHosts"
CHROME_NATIVE_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
ARC_NATIVE_DIR="$HOME/Library/Application Support/Arc/User Data/NativeMessagingHosts"
BRAVE_NATIVE_DIR="$HOME/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts"
CHROME_MANIFEST_FILE="$NATIVE_HOST_DIR/com.centrifugue.stemextractor.chrome.json"

echo "=========================================="
echo "  Centrifugue Installation"
echo "  AI-Powered Audio Stem Separation"
echo "=========================================="
echo

# Check system requirements
echo "Checking system requirements..."
echo

# Check for Python 3
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1)
    echo "  [OK] $PYTHON_VERSION"
else
    echo "  [ERROR] Python 3 not found!"
    echo "  Please install Python 3.9 or later"
    exit 1
fi

# Check for yt-dlp
if command -v yt-dlp &> /dev/null; then
    echo "  [OK] yt-dlp found: $(which yt-dlp)"
else
    echo "  [WARNING] yt-dlp not found!"
    echo "  Installing with Homebrew..."
    if command -v brew &> /dev/null; then
        brew install yt-dlp
    else
        echo "  [ERROR] Homebrew not found. Please install yt-dlp manually:"
        echo "  brew install yt-dlp"
        exit 1
    fi
fi

# Check for ffmpeg
if command -v ffmpeg &> /dev/null; then
    echo "  [OK] ffmpeg found: $(which ffmpeg)"
else
    echo "  [WARNING] ffmpeg not found!"
    echo "  Installing with Homebrew..."
    if command -v brew &> /dev/null; then
        brew install ffmpeg
    else
        echo "  [ERROR] Homebrew not found. Please install ffmpeg manually:"
        echo "  brew install ffmpeg"
        exit 1
    fi
fi

echo

# Set up Python virtual environment with Demucs
echo "Setting up Demucs AI environment..."
if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/python" ]; then
    echo "  Virtual environment already exists"

    # Check if demucs is installed
    if "$VENV_DIR/bin/python" -c "import demucs" 2>/dev/null; then
        echo "  [OK] Demucs is installed"
    else
        echo "  Installing Demucs..."
        "$VENV_DIR/bin/pip" install --upgrade demucs
    fi
else
    echo "  Creating virtual environment..."
    python3 -m venv "$VENV_DIR"

    echo "  Upgrading pip..."
    "$VENV_DIR/bin/pip" install --upgrade pip

    echo "  Installing Demucs (this may take a few minutes)..."
    "$VENV_DIR/bin/pip" install demucs

    echo "  [OK] Demucs installed successfully"
fi

# Install audio-separator for BS-RoFormer (Ultra preset).
# torch/torchaudio/torchvision stay pinned as a matched set: audio-separator
# resolves torch on its own and can pull a build torchaudio doesn't match.
# torchcodec (pinned to the torch 2.13-compatible release) is required by
# torchaudio.save, which demucs uses for FLAC output in the Ultra preset.
echo "  Installing audio-separator (BS-RoFormer support)..."
"$VENV_DIR/bin/pip" install --quiet "audio-separator[cpu]" \
    "torch==2.13.0" "torchaudio==2.11.0" "torchvision==0.28.*" "torchcodec==0.15.*"
echo "  [OK] audio-separator installed"

# Pre-download the BS-RoFormer model so the first Ultra run doesn't stall
MODEL_CACHE_DIR="$SCRIPT_DIR/.cache/audio-separator-models"
mkdir -p "$MODEL_CACHE_DIR"
if [ -f "$MODEL_CACHE_DIR/model_bs_roformer_ep_317_sdr_12.9755.ckpt" ]; then
    echo "  [OK] BS-RoFormer model already downloaded"
else
    echo "  Pre-downloading BS-RoFormer model (~640 MB, one-time)..."
    "$VENV_DIR/bin/audio-separator" --download_model_only \
        -m model_bs_roformer_ep_317_sdr_12.9755.ckpt \
        --model_file_dir "$MODEL_CACHE_DIR" \
        || echo "  [WARN] Model pre-download failed (offline?) - it will download on first Ultra run"
fi

echo

# Update the native messaging manifest
echo "Configuring native messaging host..."
cat > "$MANIFEST_FILE" << EOF
{
  "name": "com.centrifugue.stemextractor",
  "description": "Centrifugue native messaging host for audio stem separation",
  "path": "$HOST_SCRIPT",
  "type": "stdio",
  "allowed_extensions": ["centrifugue@nicholassmith.dev"]
}
EOF
echo "  Manifest created: $MANIFEST_FILE"

# Make host script executable
chmod +x "$HOST_SCRIPT"

# Create native messaging directories and symlinks
echo "Installing for browsers..."

mkdir -p "$FIREFOX_NATIVE_DIR"
ln -sf "$MANIFEST_FILE" "$FIREFOX_NATIVE_DIR/com.centrifugue.stemextractor.json"
echo "  [OK] Firefox: $FIREFOX_NATIVE_DIR"

mkdir -p "$ZEN_NATIVE_DIR"
ln -sf "$MANIFEST_FILE" "$ZEN_NATIVE_DIR/com.centrifugue.stemextractor.json"
echo "  [OK] Zen Browser: $ZEN_NATIVE_DIR"

# Create Chrome-specific manifest (uses allowed_origins instead of allowed_extensions)
# Keep the extension ID from a previous run if one was already configured;
# otherwise use a placeholder the user must replace after loading the extension
EXTENSION_ID="YOUR_EXTENSION_ID_HERE"
if [ -f "$CHROME_MANIFEST_FILE" ]; then
    EXISTING_ID=$(sed -n 's|.*chrome-extension://\([a-p]\{32\}\)/.*|\1|p' "$CHROME_MANIFEST_FILE")
    if [ -n "$EXISTING_ID" ]; then
        EXTENSION_ID="$EXISTING_ID"
    fi
fi
cat > "$CHROME_MANIFEST_FILE" << EOF
{
  "name": "com.centrifugue.stemextractor",
  "description": "Centrifugue native messaging host for audio stem separation",
  "path": "$HOST_SCRIPT",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://$EXTENSION_ID/"]
}
EOF

mkdir -p "$CHROME_NATIVE_DIR"
ln -sf "$CHROME_MANIFEST_FILE" "$CHROME_NATIVE_DIR/com.centrifugue.stemextractor.json"
echo "  [OK] Chrome: $CHROME_NATIVE_DIR (requires extension ID update)"

mkdir -p "$ARC_NATIVE_DIR"
ln -sf "$CHROME_MANIFEST_FILE" "$ARC_NATIVE_DIR/com.centrifugue.stemextractor.json"
echo "  [OK] Arc: $ARC_NATIVE_DIR (requires extension ID update)"

mkdir -p "$BRAVE_NATIVE_DIR"
ln -sf "$CHROME_MANIFEST_FILE" "$BRAVE_NATIVE_DIR/com.centrifugue.stemextractor.json"
echo "  [OK] Brave: $BRAVE_NATIVE_DIR (requires extension ID update)"

echo
echo "=========================================="
echo "  Installation Complete!"
echo "=========================================="
echo
echo "=== Firefox / Zen Browser ==="
echo
echo "1. Open Firefox or Zen Browser"
echo "2. Go to: about:debugging#/runtime/this-firefox"
echo "3. Click 'Load Temporary Add-on'"
echo "4. Navigate to: $SCRIPT_DIR/extension-firefox"
echo "5. Select the manifest.json file"
echo
echo "=== Google Chrome / Brave / Arc ==="
echo
echo "1. Open the browser and go to: chrome://extensions (brave://extensions in Brave)"
echo "2. Enable 'Developer mode' (top right)"
echo "3. Click 'Load unpacked'"
echo "4. Navigate to: $SCRIPT_DIR/extension-chrome"
echo "5. Copy the extension ID shown under the extension name"
echo "6. Edit: $CHROME_MANIFEST_FILE"
echo "7. Replace YOUR_EXTENSION_ID_HERE with your extension ID"
echo
echo "A floating button will appear on YouTube video pages."
echo "Click it to download MP3 or extract stems!"
echo
echo "Stems will be saved to: ~/Downloads"
echo
