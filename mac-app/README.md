# Market Morning — Mac app

Native menu bar + floating panel. See the [root README](../README.md) for setup, features, and sharing.

## Build

```bash
chmod +x scripts/build-mac-app.sh
./scripts/build-mac-app.sh
open "dist/mac-app/Market Morning.app"
```

Requires **macOS 13+** and Xcode Command Line Tools (`xcode-select --install`).

## Usage

| Action | How |
|--------|-----|
| Open / hide panel | Click the **sun** menu bar icon, or **⌘⇧M** |
| Always on top | Right-click menu bar icon → **Always on Top** |
| Reload UI | Right-click → **Reload UI** |
| Restart API | Right-click → **Restart Backend** |

The app:

1. Loads `extension/dist` UI inside a native web view
2. Starts `backend/.venv/bin/uvicorn` if nothing is listening on port **8742**
3. Reuses an existing backend if LaunchAgent is already running

## Backend location

After build, `dist/mac-app/backend` symlinks to `../../backend`.

If you move the `.app` elsewhere, set:

```bash
export MM_BACKEND_DIR=/path/to/market-morning/backend
```

Or keep `backend/` as a sibling folder next to the `.app`.

## Cmd+Tab / Dock

The app uses a normal activation policy so it appears in **⌘Tab** and the Dock while running. Closing the window hides the panel but keeps the app alive (menu bar sun icon remains). Quit from the menu bar right-click menu.

**⌘⇧M** works globally if macOS grants **Accessibility** access (System Settings → Privacy & Security → Accessibility → Market Morning). Without that, the shortcut works when the panel is focused.
