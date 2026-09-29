# ConsoleMode 🎮

Turn your gaming PC into a console with one button.

## Features

- **Profiles**: Save display layouts, audio devices, and application shortcuts.
- **Display Management**: Change resolution, refresh rate, HDR, and set primary monitor.
- **Window Placement**: Apps launched by a profile that open on a secondary screen (e.g. launchers that remember their last window position) are automatically moved onto the primary display. Per-profile toggle in the Profiles page.
- **Audio Switching**: Change the default audio output device.
- **Console Mode**: Launch profiles and revert settings on exit.
- **Applications**: See every app across all profiles, launch them, add them to a profile, or pick from your Windows-installed applications — discovered Revo Uninstaller-style from the registry (64/32-bit), MSI, Microsoft Store (AppX/MSIX), services, startup entries, scheduled tasks and shortcuts, then deduplicated and classified. See [DISCOVERY.md](DISCOVERY.md).
- **Controller**: Detect connected Xbox-style controllers via XInput.
- **Hotkeys**: Global keyboard shortcuts (launch/exit console mode, show the window) via the Windows RegisterHotKey API.
- **Settings**: Real Windows autostart (Run key) and a configurable profiles folder.
- **Logs**: A live, timestamped application log (also written to `logs/consolemode.log`).

## Installation

1. Clone or download this repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
```

3. Run the application:

```
python Main.py
```

## Usage

1. Create a new profile (e.g., "TV Mode").
2. Capture your current display layout and audio device.
3. Add applications to launch (emulators, launchers, etc.).
4. Click **Launch Profile** to apply the settings and start your apps.
5. Click **Exit Console Mode** to revert changes and close the apps.

## Project Structure

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
├── profiles/               # Profile data (profiles.json)
├── settings.json           # Autostart, profiles folder, hotkeys
├── DISCOVERY.md            # Discovery engine architecture, APIs and limits
└── requirements.txt
```

## Notes

- Only works on **Windows** (uses Win32 display APIs and COM for audio).
- HDR support requires Windows 10/11 with HDR-capable displays.
- Audio switching requires `pycaw` and `comtypes`.

## Troubleshooting

- **"Graphics driver rejected the change"**: Ensure your graphics drivers are up-to-date. If setting a primary display, the app now handles this correctly.
- **Audio not switching**: Verify that `pycaw` and `comtypes` are installed.
- **Missing profiles**: The `profiles/` folder will be created automatically.

