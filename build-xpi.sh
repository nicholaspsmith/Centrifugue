#!/bin/bash
# Centrifugue XPI Builder
# Packages extension-firefox/ into an installable .xpi for Firefox / Zen Browser

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/extension-firefox"
DIST_DIR="$SCRIPT_DIR/dist"
XPI_FILE="$DIST_DIR/centrifugue-firefox.xpi"

echo "=========================================="
echo "  Centrifugue XPI Builder"
echo "=========================================="
echo

if [ ! -f "$SOURCE_DIR/manifest.json" ]; then
    echo "  [ERROR] No manifest.json in $SOURCE_DIR"
    exit 1
fi

# Fail early on a malformed manifest rather than shipping a broken package
if ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SOURCE_DIR/manifest.json" 2>/dev/null; then
    echo "  [ERROR] manifest.json is not valid JSON"
    exit 1
fi

VERSION=$(python3 -c "import json;print(json.load(open('$SOURCE_DIR/manifest.json'))['version'])")
echo "  [OK] manifest.json valid (version $VERSION)"

mkdir -p "$DIST_DIR"
rm -f "$XPI_FILE"

# The archive must be rooted at the extension's files, NOT at the containing
# folder. Zipping the directory itself buries manifest.json one level down and
# Firefox/Zen then rejects the package as "corrupt". Hence the subshell cd.
(
    cd "$SOURCE_DIR"
    zip -r -q -X "$XPI_FILE" . \
        -x '.DS_Store' \
        -x '*/.DS_Store' \
        -x '__MACOSX/*' \
        -x '*.xpi'
)

# Verify the thing we just built is actually installable
if ! unzip -l "$XPI_FILE" | grep -qE '[[:space:]]manifest\.json$'; then
    echo "  [ERROR] manifest.json is not at the archive root - package would be rejected"
    exit 1
fi

echo "  [OK] manifest.json at archive root"
echo "  [OK] $(unzip -l "$XPI_FILE" | tail -1 | awk '{print $2}') files packaged"
echo
echo "  Built: $XPI_FILE"
echo
echo "=========================================="
echo "  Install in Firefox / Zen Browser"
echo "=========================================="
echo
echo "Permanent install (survives restarts):"
echo "  1. Open about:config and set:"
echo "       xpinstall.signatures.required = false"
echo "     (required because this add-on is not signed by Mozilla)"
echo "  2. Open about:addons"
echo "  3. Click the gear icon -> Install Add-on From File..."
echo "  4. Select: $XPI_FILE"
echo
echo "Temporary install (cleared on restart, no config change needed):"
echo "  1. Open about:debugging#/runtime/this-firefox"
echo "  2. Click 'Load Temporary Add-on'"
echo "  3. Select: $SOURCE_DIR/manifest.json"
echo
