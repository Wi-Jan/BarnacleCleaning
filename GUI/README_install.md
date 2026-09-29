# HullVanguard — Install & First-Run Guide

**HullVanguard 1.0.0** — desktop control GUI for the Barnacle Cleaning Robot.
Author: WEIJIAN.

This guide is for the lab team. It covers installation, first-run setup, log
locations, and troubleshooting.

---

## 1. Install

1. Double-click `HullVanguard-Setup-1.0.0.exe`.
2. Windows will show a **SmartScreen** warning ("Windows protected your PC").
   This is normal — the installer is not code-signed. Click
   **More info → Run anyway**.
3. Pick install location:
   - **Per-user** (no admin needed) → `%LOCALAPPDATA%\Programs\HullVanguard`
   - **Per-machine** (admin needed) → `C:\Program Files\HullVanguard`
4. Optional tasks (untick unless you need them):
   - **Desktop shortcut** — adds an icon to the desktop.
   - **Debug shortcut** — adds a Start Menu entry for the console build.
5. Finish. The app launches automatically if you leave the "Launch
   HullVanguard" checkbox ticked.

---

## 2. First-run setup

1. Plug in the two ESP32 boards (control + camera) and your Xbox controller
   **before** launching.
2. Press **Refresh** on the right of the connection rail.
3. Pick the correct COM port from each dropdown:
   - **CONTROL** → ESP32_1 (drives motors + drum)
   - **CAMERA**  → ESP32_3 (onboard camera)
4. Click **Connect** on the left, then **Connect Cam** on the middle.
5. If the AI model is installed, the **AI** button (top-right of the camera
   panel) turns on barnacle detection.

Your COM-port picks, window size, and zoom are remembered between launches.

---

## 3. Where your files live

| What                   | Where                                                                |
|------------------------|----------------------------------------------------------------------|
| Snapshots              | `%APPDATA%\HullVanguard\snapshots\snap_YYYYMMDD_HHMMSS.jpg`          |
| Event log              | `%APPDATA%\HullVanguard\logs\hullvanguard.log` (last 5 rotated)      |
| Crash log              | `%APPDATA%\HullVanguard\logs\crash.log`                              |
| Saved settings         | `%APPDATA%\HullVanguard\settings.json`                               |
| AI model (best.pt)     | `<install dir>\AI\runs\barnacle_detect_v2\weights\best.pt`           |

Type `%APPDATA%\HullVanguard` into the address bar of File Explorer to jump
straight there.

---

## 4. Controls

| Action            | Xbox controller   | Keyboard         |
|-------------------|-------------------|------------------|
| Left side forward | LT                | ↑                |
| Left side back    | LB                | ↓                |
| Right side fwd    | RT                | W                |
| Right side back   | RB                | S                |
| Drum on/off       | A                 | Enter            |
| E-STOP            | B                 | Esc              |
| Zoom UI           | —                 | Ctrl + = / − / 0 |

---

## 5. Troubleshooting

### SmartScreen blocks the installer
- Click **More info → Run anyway**. The installer is unsigned because this is
  an internal build (no code-signing cert).

### "HullVanguard is already running"
- Only one copy can run at a time (the COM ports are exclusive). Close the
  other instance from the system tray / Task Manager and try again.

### COM dropdowns are empty
- Plug the ESP32 in **before** launching, then press **Refresh**.
- If still empty: open Device Manager → look under **Ports (COM & LPT)** —
  if nothing shows, you're missing the **CP210x** or **CH340/CH343** USB-UART
  driver.

### AI button says "AI model not found"
- The installer ships `best.pt` if it was present at build time. If not,
  manually drop your `best.pt` here:
  `<install dir>\AI\runs\barnacle_detect_v2\weights\best.pt`.

### Something crashed and the window just disappeared
- Launch **HullVanguard (Debug)** from the Start Menu (the console build).
- A black console window will stay open showing the traceback.
- Send a screenshot of that, plus the contents of
  `%APPDATA%\HullVanguard\logs\crash.log`, to WEIJIAN.

### Controller / camera disconnects mid-run
- The event log will show the exact error. Camera USB cables sometimes
  brown-out — try a powered hub.

---

## 6. Uninstall

Settings → Apps → "HullVanguard" → Uninstall.
This removes the program but **leaves your settings, logs, and snapshots**
in `%APPDATA%\HullVanguard\` so a reinstall picks up where you left off.
Delete that folder manually if you want a fully clean wipe.
