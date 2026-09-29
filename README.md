# ConsoleMode 🎮

Turn your Windows gaming PC into a console with one button.

ConsoleMode lets you save your couch / TV setup as a **profile** — the display
layout, the audio output, and the apps you want running — and switch into it
instantly. Exit console mode and everything reverts to how it was.

## ✨ Features

- **Profiles** — Save display layouts, audio devices, and application shortcuts.
- **Display Management** — Change resolution, refresh rate, HDR, and primary monitor.
- **Window Placement** — Apps that open on a secondary screen are automatically
  moved onto the primary display (per-profile toggle).
- **Audio Switching** — Change the default audio output device.
- **Console Mode** — Launch a profile, then revert all settings on exit.
- **Applications** — See every app across all profiles, launch them, add them to
  a profile, or pick from Windows-installed programs.
- **Installed Programs Discovery** — A read-only, Revo Uninstaller-style engine
  that finds programs from the registry (64/32-bit), MSI, Microsoft Store
  (AppX/MSIX), services, startup entries, scheduled tasks, and shortcuts — then
  deduplicates and classifies them. See [DISCOVERY.md](DISCOVERY.md).
- **Controller** — Detect Xbox-style controllers via XInput.
- **Hotkeys** — Global shortcuts (launch / exit / show window) via the Windows
  `RegisterHotKey` API.
- **Settings** — Real Windows autostart (Run key) and a configurable profiles folder.
- **Logs** — A live, timestamped application log (also written to `logs/consolemode.log`).

## 🚀 Installation

```bash
git clone https://github.com/iAhmed707/ConsoleMode.git
cd ConsoleMode
pip install -r requirements.txt
python Main.py
```

> **Windows only** — ConsoleMode uses Win32 display APIs and COM for audio.

## 🕹️ Usage

1. Create a new profile (e.g. **"TV Mode"**).
2. Capture your current display layout and audio device.
3. Add applications to launch (emulators, launchers, etc.).
4. Click **Launch Profile** to apply the settings and start your apps.
5. Click **Exit Console Mode** to revert the changes and close the apps.

## 🧭 Pages

| Page | What it does |
|------|--------------|
| Dashboard | One-button launch / exit and status overview |
| Profiles | Create, capture, edit, and manage profiles |
| Displays | Resolution, refresh rate, HDR, primary monitor |
| Audio | Default output device selection |
| Applications | Launch / add apps and browse installed programs |
| Controller | Xbox controller detection |
| Hotkeys | Global keyboard shortcuts |
| Settings | Autostart and profiles folder |
| Logs | Live application log |

## 🏗️ Project Structure

```
ConsoleMode/
├── Main.py                 # Entry point, window, theme and navigation
├── app/
│   ├── discovery/          # Installed Programs Discovery Engine (read-only)
│   │   └── scanners/       # Registry / MSI / AppX / Service / Startup /
│   │                       #   ScheduledTask / Shortcut / Portable / PE / Sig
│   ├── managers/           # Core logic (display, audio, profiles, settings,
│   │                       #   controller, hotkeys, logging, paths)
│   └── pages/              # One UI page per sidebar section
├── tests/                  # Unit tests (python -m unittest discover -s tests)
├── profiles/               # Profile data (created automatically at first run)
├── settings.json           # Autostart, profiles folder, hotkeys
├── DISCOVERY.md            # Discovery engine architecture, APIs and limits
└── requirements.txt
```

## 🧪 Tests

```powershell
python -m unittest discover -s tests -v
```

## ⚠️ Notes

- Only works on **Windows** (uses Win32 display APIs and COM for audio).
- HDR support requires Windows 10/11 with an HDR-capable display.
- Audio switching requires `pycaw` and `comtypes`.

## 🛠️ Troubleshooting

- **"Graphics driver rejected the change"** — Ensure your graphics drivers are
  up-to-date.
- **Audio not switching** — Verify that `pycaw` and `comtypes` are installed.
- **Missing profiles** — The `profiles/` folder is created automatically on first run.
