```markdown
# EaseView

EaseView is a lightweight Windows screen colour overlay application designed to improve on-screen readability and visual comfort. It provides a fullscreen, click-through colour overlay with adjustable strength and colour density, making it suitable for accessibility support, exam arrangements, and prolonged screen use.

The application runs in the background, integrates with the system tray, and automatically restores user settings between sessions.

---

## Features

### Core Features
- **Multi-monitor support** - Overlay works across all displays
- Fullscreen, click-through colour overlay
- Preset and custom overlay colours
- Adjustable overlay strength (opacity)
- Colour density control
- Keyboard shortcuts for quick access
- System tray integration
- Persistent user settings
- Keyboard-accessible interface
- Windows-native styling

### Advanced Features
- **Single instance enforcement** - Prevents multiple app instances
- **Settings profiles** - Save and load different configurations
- **Export/Import settings** - Share configurations between installations
- **Windows startup integration** - Option to start with Windows
- **Scheduled overlay** - Automatically enable/disable on schedule
- **Hotkey customization** - Customize keyboard shortcuts (requires keyboard library)
- **Dark mode support** - Automatically adapts to Windows theme
- **Portable mode** - Store settings in application directory
- **Accessibility options** - High contrast mode and font scaling
- **Update checker** - Check for new versions
- **Window position persistence** - Remembers window location and size
- **Overlay monitoring** - Auto-recovery if overlay is destroyed
- **Asynchronous logging** - Non-blocking log file writes

---

## System Requirements

- Windows 10 or Windows 11
- Python 3.9 or later

---

## Dependencies

### Required
```bash
pip install pystray pillow
```

### Optional (for enhanced features)
```bash
pip install pywin32 keyboard requests
```

- `pystray` - System tray integration
- `pillow` - Image processing for tray icon
- `pywin32` - Windows API integration (multi-monitor, startup, dark mode detection)
- `keyboard` - Global hotkey support (optional)
- `requests` - Update checking (optional)

tkinter is included with standard Python installations on Windows.

---

## Running the Application

python screen_overlay.py

---

## Keyboard Shortcuts

Ctrl + Shift + O  Toggle overlay on or off  
Ctrl + Shift + Up  Increase overlay strength  
Ctrl + Shift + Down  Decrease overlay strength  
Ctrl + Shift + Right  Increase colour density  
Ctrl + Shift + Left  Decrease colour density  
Escape  Hide overlay  

---

## Project Structure

screen_overlay.py  
.easeview_settings.json  
.easeview.log  

---

## Building an Executable

pyinstaller --onefile --windowed screen_overlay.py

Optional icon files:

app_icon.ico  
tray_icon.png  

---

## Settings Profiles

EaseView supports saving and loading configuration profiles. Access profiles from the File menu:
- **Save Current as Profile** - Save current settings as a named profile
- **Load Profile** - Load a previously saved profile
- **Manage Profiles** - View and delete saved profiles

Profiles are stored in `.easeview_profiles/` directory.

## Portable Mode

To run EaseView in portable mode, create a file named `portable.ini` in the same directory as the executable. In portable mode, all settings and profiles are stored in the application directory instead of the user home directory.

## Keyboard Shortcuts

- `Ctrl + Shift + O` - Toggle overlay on or off
- `Ctrl + Shift + Up` - Increase overlay strength
- `Ctrl + Shift + Down` - Decrease overlay strength
- `Ctrl + Shift + Right` - Increase colour density
- `Ctrl + Shift + Left` - Decrease colour density
- `Escape` - Hide overlay (emergency)

Custom hotkeys can be configured in Settings > Hotkey Settings (requires keyboard library).

## Known Limitations

- Windows only
- Some fullscreen applications may override the overlay
- Global hotkeys require administrator privileges (keyboard library limitation)
- Multi-monitor support requires pywin32 for optimal detection

---

## License

MIT License

Copyright (c) 2026 Ross Paxton

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## Author

Ross Paxton  

