#!/bin/bash
# Centrifuge Installation Script
# Sets up the browser extension and native messaging host for stem separation

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NATIVE_HOST_DIR="$SCRIPT_DIR/native-host"
HOST_SCRIPT="$NATIVE_HOST_DIR/centrifuge_host.py"
MANIFEST_FILE="$NATIVE_HOST_DIR/com.centrifuge.stemextractor.json"
VENV_DIR="$SCRIPT_DIR/venv-demucs"

# Native messaging hosts directories
FIREFOX_NATIVE_DIR="$HOME/Library/Application Support/Mozilla/NativeMessagingHosts"
ZEN_NATIVE_DIR="$HOME/Library/Application Support/zen/NativeMessagingHosts"

echo "=========================================="
echo "  Centrifuge Installation"
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

echo

# Update the native messaging manifest
echo "Configuring native messaging host..."
cat > "$MANIFEST_FILE" << EOF
{
  "name": "com.centrifuge.stemextractor",
  "description": "Centrifuge native messaging host for audio stem separation",
  "path": "$HOST_SCRIPT",
  "type": "stdio",
  "allowed_extensions": ["centrifuge@nicholassmith.dev"]
}
EOF
echo "  Manifest created: $MANIFEST_FILE"

# Make host script executable
chmod +x "$HOST_SCRIPT"

# Create native messaging directories and symlinks
echo "Installing for browsers..."

mkdir -p "$FIREFOX_NATIVE_DIR"
ln -sf "$MANIFEST_FILE" "$FIREFOX_NATIVE_DIR/com.centrifuge.stemextractor.json"
echo "  [OK] Firefox: $FIREFOX_NATIVE_DIR"

mkdir -p "$ZEN_NATIVE_DIR"
ln -sf "$MANIFEST_FILE" "$ZEN_NATIVE_DIR/com.centrifuge.stemextractor.json"
echo "  [OK] Zen Browser: $ZEN_NATIVE_DIR"

echo
echo "=========================================="
echo "  Installation Complete!"
echo "=========================================="
echo
echo "To use Centrifuge:"
echo
echo "1. Open Firefox or Zen Browser"
echo "2. Go to: about:debugging#/runtime/this-firefox"
echo "3. Click 'Load Temporary Add-on'"
echo "4. Navigate to: $SCRIPT_DIR/extension"
echo "5. Select the manifest.json file"
echo
echo "A floating button will appear on YouTube video pages."
echo "Click it to download MP3 or extract stems!"
echo
echo "Stems will be saved to: ~/Downloads"
echo
