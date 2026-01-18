@echo off
echo Cleaning up previous builds...
:: These lines delete the old temporary folders and spec file
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist EaseView.spec del EaseView.spec

echo.
echo Installing required packages...
pip install pillow pystray pyinstaller

echo.
echo Creating professional icons...
:: Make sure this script actually runs and produces app_icon.ico
if exist create_icons.py (
    python create_icons.py
) else (
    echo create_icons.py not found, skipping icon creation...
)

echo.
echo Building EaseView executable...
:: Note: I removed the quotes around the icon path just in case, and added --clean
pyinstaller --noconfirm --onefile --windowed --clean --name "EaseView" ^
    --icon=app_icon.ico ^
    --add-data "app_icon.ico;." ^
    --add-data "tray_icon.png;." ^
    screen_overlay.py

echo.
echo Build complete! 
pause