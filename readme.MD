# EaseView

A lightweight Windows screen colour overlay application designed to improve on-screen readability and visual comfort.
![EaseView Application Interface](screenshots/app-ui.png)
EaseView provides a fullscreen, click-through colour overlay with adjustable strength and density, making it ideal for accessibility support, exam arrangements, and prolonged screen use. The application runs quietly in the background, integrates with the system tray, and automatically restores user settings between sessions.

## Features

**Core**
- Multi-monitor support across all displays
- Fullscreen, click-through colour overlay
- Preset and custom overlay colours
- Adjustable overlay strength (opacity) and colour density
- Keyboard shortcuts for quick access
- System tray integration with persistent settings
- Keyboard-accessible, Windows-native interface

**Advanced**
- Single instance enforcement
- Settings profiles with export/import functionality
- Windows startup integration
- Scheduled overlay (auto enable/disable)
- Customisable hotkeys (requires `keyboard` library)
- Dark mode support (adapts to Windows theme)
- Portable mode (store settings in application directory)
- Accessibility options (high contrast, font scaling)
- Update checker
- Window position persistence
- Overlay monitoring with auto-recovery
- Asynchronous logging

## System Requirements

- Windows 10 or Windows 11
- Python 3.9+

## Installation

### Required Dependencies
```bash
pip install pystray pillow
```

### Optional Dependencies
```bash
pip install pywin32 keyboard requests
```

| Package | Purpose |
|---------|---------|
| `pystray` | System tray integration |
| `pillow` | Image processing for tray icon |
| `pywin32` | Windows API (multi-monitor, startup, dark mode) |
| `keyboard` | Global hotkey support |
| `requests` | Update checking |

> **Note:** `tkinter` is included with standard Python installations on Windows.

## Usage
```bash
python screen_overlay.py
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl + Shift + O` | Toggle overlay on/off |
| `Ctrl + Shift + ↑` | Increase overlay strength |
| `Ctrl + Shift + ↓` | Decrease overlay strength |
| `Ctrl + Shift + →` | Increase colour density |
| `Ctrl + Shift + ←` | Decrease colour density |
| `Escape` | Hide overlay (emergency) |

Custom hotkeys can be configured in **Settings → Hotkey Settings** (requires `keyboard` library).

## Project Structure
```
EaseView/
├── screen_overlay.py
├── .easeview_settings.json
├── .easeview.log
└── .easeview_profiles/
```

## Building an Executable
```bash
pyinstaller --onefile --windowed screen_overlay.py
```

Optional icon files:
- `app_icon.ico`
- `tray_icon.png`

## Settings Profiles

EaseView supports saving and loading configuration profiles via the **File** menu:

- **Save Current as Profile** – Save current settings as a named profile
- **Load Profile** – Load a previously saved profile
- **Manage Profiles** – View and delete saved profiles

Profiles are stored in the `.easeview_profiles/` directory.

## Portable Mode

Create a file named `portable.ini` in the same directory as the executable. In portable mode, all settings and profiles are stored in the application directory instead of the user home directory.

## Known Limitations

- Windows only
- Some fullscreen applications may override the overlay
- Global hotkeys require administrator privileges (`keyboard` library limitation)
- Multi-monitor support requires `pywin32` for optimal detection

## License

MIT License © 2026 Ross Paxton

See [LICENSE](LICENSE) for full details.

## Author

**Ross Paxton**

