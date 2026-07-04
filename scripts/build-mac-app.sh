#!/usr/bin/env bash
# Build Market Morning.app — menu bar + floating panel (macOS 13+)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAC_APP="$ROOT/mac-app"
BUILD_DIR="$ROOT/dist/mac-app"
APP_NAME="Market Morning.app"
APP_PATH="$BUILD_DIR/$APP_NAME"
BACKEND="$ROOT/backend"

echo "Market Morning — building native Mac app"
echo ""

if ! command -v swift >/dev/null 2>&1; then
  echo "Error: Swift toolchain not found. Install Xcode Command Line Tools:"
  echo "  xcode-select --install"
  exit 1
fi

cd "$BACKEND"
if [ ! -d .venv ]; then
  echo "Creating Python venv for bundled backend…"
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q -r requirements.txt
elif [ ! -x .venv/bin/uvicorn ]; then
  source .venv/bin/activate
  pip install -q -r requirements.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created backend/.env — add ANTHROPIC_API_KEY before using the app."
fi

echo "Compiling Swift shell…"
swift build --package-path "$MAC_APP" -c release

echo "Packaging .app bundle…"
rm -rf "$APP_PATH"
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources/web"

cp "$MAC_APP/.build/release/MarketMorning" "$APP_PATH/Contents/MacOS/MarketMorning"
cp "$MAC_APP/Resources/Info.plist" "$APP_PATH/Contents/Info.plist"
if [ -f "$MAC_APP/Resources/AppIcon.icns" ]; then
  cp "$MAC_APP/Resources/AppIcon.icns" "$APP_PATH/Contents/Resources/AppIcon.icns"
else
  echo "Warning: AppIcon.icns missing — run scripts/build-mac-icon.sh"
fi
cp -R "$ROOT/extension/dist/"* "$APP_PATH/Contents/Resources/web/"

# Symlink backend next to dist/mac-app so the app can spawn uvicorn in dev installs
mkdir -p "$BUILD_DIR"
ln -sfn "$BACKEND" "$BUILD_DIR/backend"

chmod +x "$APP_PATH/Contents/MacOS/MarketMorning"

echo ""
echo "Built: $APP_PATH"
echo "Backend symlink: $BUILD_DIR/backend -> $BACKEND"
echo ""
echo "Run:"
echo "  open \"$APP_PATH\""
echo ""
echo "First launch:"
echo "  • Sun icon appears in the menu bar"
echo "  • Click icon (or ⌘⇧M) to open the floating panel"
echo "  • Right-click icon for Always on Top, reload, quit"
echo ""
echo "Optional: drag to /Applications. Keep dist/mac-app/backend symlink valid or set MM_BACKEND_DIR."
