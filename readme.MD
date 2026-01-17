# EaseView

EaseView is a professional, lightweight screen overlay tool for Windows designed to enhance digital accessibility and visual comfort. It creates a customizable, click-through colour tint over the entire screen to reduce eye strain and assist users with reading difficulties.

Built with a focus on accessibility, the application features a Windows 11-inspired UI, keyboard navigation support, and system tray integration.

## Use Cases

- **Visual Stress & Irlen Syndrome:** Reduces contrast and glare to make reading easier.
- **Dyslexia:** Colour overlays can help stabilize text for some readers.
- **Eye Strain:** Reduces blue light and screen harshness during prolonged use.
- **Exam Arrangements:** Suitable for controlled environments requiring screen tinting software.

## Features

- **Click-Through Overlay:** The overlay sits on top of all windows but allows you to click and interact with applications underneath.
- **Customizable Aesthetics:**
  - 6 Calibrated Presets (Amber, Blue, Green, Pink, Purple, Grey).
  - Custom Colour Picker for specific needs.
- **Granular Control:**
  - **Strength (Opacity):** Controls how transparent the overlay is.
  - **Density:** Controls the saturation/intensity of the colour without changing transparency.
- **System Integration:** Minimizes to system tray, auto-saves settings, and supports global keyboard shortcuts.
- **Accessibility:** Fully navigable via keyboard (Tab/Enter) with high-contrast focus states.

## System Requirements

- **OS:** Windows 10 or Windows 11
- **Runtime:** No installation required if using the executable
- **Development:** Python 3.9+ required to run from source

## Installation & Running

### Option 1: Running from Source

1. Clone this repository.
2. Install the required dependencies:
   ```bash
   pip install pystray pillow

(Note: tkinter is included with standard Python installations).
3. Run the application:
code Bash

python screen_overlay.py

Option 2: Building an Executable

To create a standalone .exe file that includes the necessary icons, use the following PyInstaller command.

Note: Ensure you have app_icon.ico and tray_icon.png in the source directory, or remove the --add-data flags if you are building without custom icons.
code Bash

pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name "EaseView" --add-data "app_icon.ico;." --add-data "tray_icon.png;." --icon "app_icon.ico" screen_overlay.py

Keyboard Shortcuts

EaseView is designed to be controlled quickly without opening the main window.
Shortcut	Action
Ctrl + Shift + O	Toggle the overlay On or Off
Ctrl + Shift + Up	Increase Overlay Strength (Opacity)
Ctrl + Shift + Down	Decrease Overlay Strength (Opacity)
Ctrl + Shift + Right	Increase Colour Density
Ctrl + Shift + Left	Decrease Colour Density
Esc	Emergency Hide (Immediately hides overlay)
Configuration

EaseView automatically saves your preferences (last colour, opacity, density) to a generic JSON file located in your user directory.

    Settings: C:\Users\%USERNAME%\.easeview_settings.json

    Logs: C:\Users\%USERNAME%\.easeview.log

Troubleshooting & Notes

    Fullscreen Games: Some exclusive-fullscreen games may override the overlay. Run games in "Windowed Borderless" mode for best results.

    Antivirus: Because this tool uses Python and modifies window styles (to achieve the click-through effect), some antivirus software may flag the .exe as a false positive.

    Multi-Monitor: The overlay attempts to cover the active screen area. Results may vary depending on DPI scaling settings across different monitors.

License

MIT License

Copyright (c) 2026 Ross Paxton

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
