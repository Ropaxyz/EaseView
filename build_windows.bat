@echo off
setlocal ENABLEDELAYEDEXPANSION

echo Cleaning build folders...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo Installing dependencies...
python -m pip install --upgrade pip
python -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo Dependency install failed.
    exit /b 1
)

echo Running tests...
python -m unittest test_screen_overlay -v
if errorlevel 1 (
    echo Tests failed, not building.
    exit /b 1
)

echo Building EaseView.exe...
if exist EaseView.spec (
    python -m PyInstaller --noconfirm --clean EaseView.spec
) else (
    python -m PyInstaller --noconfirm --clean ^
        --onefile --windowed --name "EaseView" ^
        --icon=app_icon.ico ^
        --add-data "app_icon.ico;." ^
        --add-data "tray_icon.png;." ^
        screen_overlay.py
)
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo.
echo Done. Output: dist\EaseView.exe
pause
