# PyInstaller spec for EaseView. Bundles icon assets if present and adds
# hidden imports that PyInstaller's static analysis can miss when imports
# are guarded with try/except.

import os
from PyInstaller.utils.hooks import collect_submodules


def _optional(path, dest="."):
    return [(path, dest)] if os.path.exists(path) else []


datas = []
datas += _optional("app_icon.ico")
datas += _optional("tray_icon.png")

hiddenimports = []
for mod in ("keyboard", "astral", "astral.sun", "requests",
            "PIL", "PIL.Image", "PIL.ImageDraw", "pystray", "pystray._win32"):
    try:
        __import__(mod)
        hiddenimports.append(mod)
    except Exception:
        pass

hiddenimports += collect_submodules("pystray")


a = Analysis(
    ["screen_overlay.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EaseView",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=("app_icon.ico" if os.path.exists("app_icon.ico") else None),
)
