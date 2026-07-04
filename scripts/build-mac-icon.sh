#!/usr/bin/env bash
# Build AppIcon.icns for Market Morning Mac app.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_PNG="$ROOT/extension/dist/icons/icon128.png"
SVG="$ROOT/extension/icons/designs/mm-monogram.svg"
ICONSET="$ROOT/mac-app/Resources/AppIcon.iconset"
ICNS="$ROOT/mac-app/Resources/AppIcon.icns"

if [ ! -f "$SRC_PNG" ] && [ -f "$SVG" ]; then
  python3 "$ROOT/scripts/build-icons.py" mm-monogram >/dev/null 2>&1 || true
fi

if [ ! -f "$SRC_PNG" ]; then
  echo "Error: missing $SRC_PNG — run: python3 scripts/build-icons.py mm-monogram"
  exit 1
fi

rm -rf "$ICONSET"
mkdir -p "$ICONSET"

make_icon() {
  sips -z "$2" "$2" "$SRC_PNG" --out "$ICONSET/icon_${1}.png" >/dev/null
}

make_icon "16x16" 16
make_icon "16x16@2x" 32
make_icon "32x32" 32
make_icon "32x32@2x" 64
make_icon "128x128" 128
make_icon "128x128@2x" 256
make_icon "256x256" 256
make_icon "256x256@2x" 512
make_icon "512x512" 512
make_icon "512x512@2x" 1024

iconutil -c icns "$ICONSET" -o "$ICNS"
echo "Built $ICNS"
