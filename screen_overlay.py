# EaseView - screen colour overlay for Windows
# Ross Paxton

from __future__ import annotations

import ctypes
import os
import sys


def _enable_dpi_awareness() -> None:
    # Tk has to be told the process is DPI-aware before any Tk() is created,
    # otherwise Windows bitmap-stretches it on >100% scaling.
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()

import atexit
import argparse
import json
import queue
import re
import shutil
import threading
import time
import traceback
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import tkinter as tk
from tkinter import (
    colorchooser,
    filedialog,
    messagebox,
    simpledialog,
    ttk,
    Menu,
)

# Optional dependencies. Anything that fails to import just disables a
# feature rather than crashing the app.
try:
    import pystray
    from PIL import Image, ImageDraw
    PYSTRAY_AVAILABLE = True
except Exception:
    PYSTRAY_AVAILABLE = False
    pystray = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]

try:
    import win32api  # type: ignore
    import win32con  # type: ignore
    import winreg  # type: ignore
    WIN32_AVAILABLE = True
except Exception:
    WIN32_AVAILABLE = False
    winreg = None  # type: ignore[assignment]

try:
    import keyboard as _keyboard  # type: ignore
    KEYBOARD_AVAILABLE = True
except Exception:
    KEYBOARD_AVAILABLE = False
    _keyboard = None  # type: ignore[assignment]

try:
    import requests  # type: ignore
    REQUESTS_AVAILABLE = True
except Exception:
    REQUESTS_AVAILABLE = False
    requests = None  # type: ignore[assignment]

try:
    from astral import LocationInfo  # type: ignore
    from astral.sun import sun  # type: ignore
    ASTRAL_AVAILABLE = True
except Exception:
    ASTRAL_AVAILABLE = False


# --- constants --------------------------------------------------------------
VERSION = "3.2.1"
GITHUB_OWNER = "Ropaxyz"
GITHUB_REPO = "EaseView"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_API_ALL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"

SETTINGS_VERSION = 6

LIGHT_COLOURS = {
    'accent':           '#0067C0',
    'accent_hover':     '#005A9E',
    'background':       '#F5F5F5',
    'surface':          '#FFFFFF',
    'surface_hover':    '#F0F0F0',
    'surface_active':   '#E3F2FD',
    'text_primary':     '#202020',
    'text_secondary':   '#5C5C5C',
    'border':           '#E0E0E0',
    'border_active':    '#0067C0',
    'divider':          '#E8E8E8',
    'focus':            '#0067C0',
    'success':          '#107C10',
    'warning':          '#A56B00',
    'inactive':         '#A0A0A0',
    'banner_bg':        '#FFF4CE',
    'banner_fg':        '#5C3D00',
}

DARK_COLOURS = {
    'accent':           '#4CC2FF',
    'accent_hover':     '#62CDFF',
    'background':       '#202020',
    'surface':          '#2D2D2D',
    'surface_hover':    '#383838',
    'surface_active':   '#1A3A5C',
    'text_primary':     '#FFFFFF',
    'text_secondary':   '#CCCCCC',
    'border':           '#404040',
    'border_active':    '#4CC2FF',
    'divider':          '#353535',
    'focus':            '#4CC2FF',
    'success':          '#6CCB5F',
    'warning':          '#FCE100',
    'inactive':         '#707070',
    'banner_bg':        '#4A3A00',
    'banner_fg':        '#FFE48A',
}

BASE_FONTS = {
    'title':    ('Segoe UI', 15, 'normal'),
    'subtitle': ('Segoe UI', 9,  'normal'),
    'section':  ('Segoe UI', 10, 'normal'),
    'body':     ('Segoe UI', 10, 'normal'),
    'button':   ('Segoe UI', 10, 'normal'),
    'footer':   ('Segoe UI', 8,  'normal'),
}

SPACING = {
    'window_padding':           20,
    'section_gap':              16,
    'row_gap':                  2,
    'button_padding_x':         14,
    'button_padding_y':         10,
    'colour_indicator_width':   36,
    'active_indicator_width':   4,
}

WINDOW = {
    'width':      480,
    'height':     680,
    'min_width':  380,
    'min_height': 540,
}


def _exe_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _detect_portable_mode() -> bool:
    for name in ('portable.ini', 'portable.txt'):
        if os.path.exists(os.path.join(_exe_dir(), name)):
            return True
    return False


PORTABLE_MODE = _detect_portable_mode()
SETTINGS_DIR = _exe_dir() if PORTABLE_MODE else os.path.expanduser('~')
SETTINGS_FILE = os.path.join(SETTINGS_DIR, '.easeview_settings.json')
LOG_FILE = os.path.join(SETTINGS_DIR, '.easeview.log')
LOCK_FILE = os.path.join(SETTINGS_DIR, '.easeview.lock')
PROFILES_DIR = os.path.join(SETTINGS_DIR, '.easeview_profiles')

try:
    os.makedirs(PROFILES_DIR, exist_ok=True)
except Exception:
    pass


# --- logging ----------------------------------------------------------------
class AsyncLogger:
    """Background-thread file logger. Trims occasionally rather than every write."""

    def __init__(self, log_file: str = LOG_FILE, max_lines: int = 2000,
                 trim_every: int = 100) -> None:
        self.log_file = log_file
        self.max_lines = max_lines
        self.trim_every = max(1, trim_every)
        self.queue: queue.Queue[Optional[str]] = queue.Queue()
        self.running = True
        self._writes_since_trim = 0
        self.worker = threading.Thread(target=self._worker, daemon=True,
                                       name="EaseViewLogger")
        self.worker.start()
        atexit.register(self.stop)

    def _worker(self) -> None:
        while True:
            try:
                entry = self.queue.get(timeout=1.0)
            except queue.Empty:
                if not self.running:
                    return
                continue
            if entry is None:  # sentinel
                self.queue.task_done()
                return
            try:
                with open(self.log_file, 'a', encoding='utf-8') as fh:
                    fh.write(entry)
                self._writes_since_trim += 1
                if self._writes_since_trim >= self.trim_every:
                    self._trim()
                    self._writes_since_trim = 0
            except Exception:
                pass
            finally:
                self.queue.task_done()

    def _trim(self) -> None:
        try:
            if not os.path.exists(self.log_file):
                return
            with open(self.log_file, 'r', encoding='utf-8', errors='replace') as fh:
                lines = fh.readlines()
            if len(lines) > self.max_lines:
                with open(self.log_file, 'w', encoding='utf-8') as fh:
                    fh.writelines(lines[-self.max_lines:])
        except Exception:
            pass

    def log(self, level: str, message: str) -> None:
        if not self.running:
            return
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.queue.put(f"[{ts}] [{level:<5}] {message}\n")
        except Exception:
            pass

    def info(self, msg: str) -> None:    self.log("INFO", msg)
    def warning(self, msg: str) -> None: self.log("WARN", msg)
    def error(self, msg: str) -> None:   self.log("ERROR", msg)
    def debug(self, msg: str) -> None:   self.log("DEBUG", msg)

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        try:
            self.queue.put_nowait(None)
        except Exception:
            pass
        try:
            self.worker.join(timeout=2.0)
        except Exception:
            pass


logger = AsyncLogger()


def _install_excepthooks() -> None:
    def _hook(exc_type: type, exc: BaseException, tb) -> None:
        logger.error("Uncaught exception: " + "".join(
            traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = _hook
    if hasattr(threading, "excepthook"):
        def _t_hook(args: "threading.ExceptHookArgs") -> None:
            logger.error("Uncaught thread exception in {}: {}".format(
                args.thread.name if args.thread else "unknown",
                "".join(traceback.format_exception(args.exc_type, args.exc_value,
                                                   args.exc_traceback))))
        threading.excepthook = _t_hook  # type: ignore[assignment]


_install_excepthooks()


# --- single instance --------------------------------------------------------
class InstanceLocker:
    """Named mutex on Windows, PID lockfile fallback elsewhere."""

    _mutex_handle: Optional[int] = None
    _used_mutex = False

    @classmethod
    def acquire_lock(cls) -> bool:
        if os.name == "nt":
            try:
                ERROR_ALREADY_EXISTS = 183
                name = "Local\\EaseView_SingleInstance_Mutex"
                kernel32 = ctypes.windll.kernel32
                kernel32.CreateMutexW.restype = ctypes.c_void_p
                kernel32.CreateMutexW.argtypes = [ctypes.c_void_p,
                                                  ctypes.c_bool,
                                                  ctypes.c_wchar_p]
                handle = kernel32.CreateMutexW(None, True, name)
                err = ctypes.get_last_error()
                if handle and err != ERROR_ALREADY_EXISTS:
                    cls._mutex_handle = handle
                    cls._used_mutex = True
                    return True
                if handle:
                    kernel32.CloseHandle(handle)
                return False
            except Exception as exc:
                logger.warning(f"Mutex unavailable, falling back to file lock: {exc}")

        try:
            if os.path.exists(LOCK_FILE):
                try:
                    with open(LOCK_FILE, 'r') as fh:
                        pid = int(fh.read().strip())
                    if cls._pid_alive(pid):
                        return False
                except Exception:
                    pass
                try:
                    os.remove(LOCK_FILE)
                except Exception:
                    pass
            with open(LOCK_FILE, 'w') as fh:
                fh.write(str(os.getpid()))
            return True
        except Exception as exc:
            logger.error(f"Failed to acquire lock: {exc}")
            return True

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if os.name == "nt":
            try:
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    @classmethod
    def release_lock(cls) -> None:
        if cls._used_mutex and cls._mutex_handle:
            try:
                ctypes.windll.kernel32.ReleaseMutex(cls._mutex_handle)
                ctypes.windll.kernel32.CloseHandle(cls._mutex_handle)
            except Exception:
                pass
            cls._mutex_handle = None
            cls._used_mutex = False
            return
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        except Exception:
            pass


# --- monitors ---------------------------------------------------------------
class MonitorDetector:
    """Returns a list of monitors with their virtual-screen rectangles."""

    @staticmethod
    def get_monitors() -> List[Dict[str, int]]:
        monitors: List[Dict[str, int]] = []
        if WIN32_AVAILABLE:
            try:
                for mon in win32api.EnumDisplayMonitors():
                    handle = mon[0]
                    info = win32api.GetMonitorInfo(handle)
                    r = info['Monitor']
                    w = info['Work']
                    monitors.append({
                        'x': int(r[0]), 'y': int(r[1]),
                        'width': int(r[2] - r[0]),
                        'height': int(r[3] - r[1]),
                        'work_x': int(w[0]), 'work_y': int(w[1]),
                        'work_width': int(w[2] - w[0]),
                        'work_height': int(w[3] - w[1]),
                        'is_primary': bool(info.get('Flags', 0) & 1),
                    })
            except Exception as exc:
                logger.warning(f"win32 monitor enumeration failed: {exc}")

        if not monitors and os.name == "nt":
            monitors = MonitorDetector._enum_via_ctypes()

        if not monitors:
            try:
                root = tk.Tk()
                root.withdraw()
                w, h = root.winfo_screenwidth(), root.winfo_screenheight()
                root.destroy()
            except Exception:
                w, h = 1920, 1080
            monitors.append({
                'x': 0, 'y': 0, 'width': w, 'height': h,
                'work_x': 0, 'work_y': 0,
                'work_width': w, 'work_height': h,
                'is_primary': True,
            })
        return monitors

    @staticmethod
    def _enum_via_ctypes() -> List[Dict[str, int]]:
        # Used when pywin32 isn't installed.
        try:
            user32 = ctypes.windll.user32

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_ulong),
                            ("rcMonitor", RECT),
                            ("rcWork", RECT),
                            ("dwFlags", ctypes.c_ulong)]

            MonitorEnumProc = ctypes.WINFUNCTYPE(
                ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(RECT), ctypes.c_double)
            collected: List[Dict[str, int]] = []

            def cb(hmon, _hdc, _rect_ptr, _data):
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                    m = info.rcMonitor
                    w = info.rcWork
                    collected.append({
                        'x': m.left, 'y': m.top,
                        'width': m.right - m.left,
                        'height': m.bottom - m.top,
                        'work_x': w.left, 'work_y': w.top,
                        'work_width': w.right - w.left,
                        'work_height': w.bottom - w.top,
                        'is_primary': bool(info.dwFlags & 1),
                    })
                return 1

            user32.EnumDisplayMonitors(None, None, MonitorEnumProc(cb), 0)
            return collected
        except Exception as exc:
            logger.warning(f"ctypes monitor enumeration failed: {exc}")
            return []

    @staticmethod
    def primary(monitors: Optional[List[Dict[str, int]]] = None) -> Dict[str, int]:
        if monitors is None:
            monitors = MonitorDetector.get_monitors()
        for m in monitors:
            if m.get('is_primary'):
                return m
        return monitors[0]


# --- Windows integration ----------------------------------------------------
class WindowsIntegration:
    """Startup registry entry, dark-mode detection, palette."""

    APP_NAME = "EaseView"
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def _startup_command(start_minimized: bool) -> str:
        if getattr(sys, 'frozen', False):
            cmd = f'"{sys.executable}"'
        else:
            cmd = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
        if start_minimized:
            cmd += " --minimized"
        return cmd

    @classmethod
    def set_startup(cls, enabled: bool, start_minimized: bool = False) -> bool:
        if not WIN32_AVAILABLE:
            return False
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.RUN_KEY, 0,
                                 winreg.KEY_SET_VALUE)
            try:
                if enabled:
                    winreg.SetValueEx(key, cls.APP_NAME, 0, winreg.REG_SZ,
                                      cls._startup_command(start_minimized))
                    logger.info("Added to Windows startup")
                else:
                    try:
                        winreg.DeleteValue(key, cls.APP_NAME)
                        logger.info("Removed from Windows startup")
                    except FileNotFoundError:
                        pass
            finally:
                winreg.CloseKey(key)
            return True
        except Exception as exc:
            logger.error(f"Failed to modify startup: {exc}")
            return False

    @classmethod
    def is_startup_enabled(cls) -> bool:
        if not WIN32_AVAILABLE:
            return False
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.RUN_KEY, 0,
                                 winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, cls.APP_NAME)
                return True
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    @staticmethod
    def is_dark_mode() -> bool:
        if not WIN32_AVAILABLE:
            return False
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                 winreg.KEY_READ)
            try:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return value == 0
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    @staticmethod
    def get_palette() -> Dict[str, str]:
        return DARK_COLOURS.copy() if WindowsIntegration.is_dark_mode() \
                                   else LIGHT_COLOURS.copy()


# --- update checker ---------------------------------------------------------
class UpdateChecker:
    """Compares local version to the latest GitHub release."""

    _SEMVER_RE = re.compile(r"^[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[.\-_]?(.*))?$")

    @classmethod
    def parse_version(cls, raw: str) -> Optional[Tuple[Tuple[int, int, int], str]]:
        if not raw:
            return None
        m = cls._SEMVER_RE.match(raw.strip())
        if not m:
            return None
        major = int(m.group(1) or 0)
        minor = int(m.group(2) or 0)
        patch = int(m.group(3) or 0)
        suffix = (m.group(4) or "").strip()
        return ((major, minor, patch), suffix)

    @classmethod
    def is_newer(cls, candidate: str, current: str) -> bool:
        c = cls.parse_version(candidate)
        cur = cls.parse_version(current)
        if not c or not cur:
            return False
        if c[0] != cur[0]:
            return c[0] > cur[0]
        # Numeric tuple ties: a pre-release suffix counts as older.
        if c[1] == cur[1]:
            return False
        if not c[1]:
            return True
        if not cur[1]:
            return False
        return c[1] > cur[1]

    @staticmethod
    def fetch_latest(include_prereleases: bool = False,
                     timeout: float = 6.0) -> Optional[Dict[str, Any]]:
        if not REQUESTS_AVAILABLE:
            return None
        try:
            if include_prereleases:
                resp = requests.get(GITHUB_API_ALL, timeout=timeout,
                                    headers={"Accept": "application/vnd.github+json"})
                resp.raise_for_status()
                releases = [r for r in resp.json() if not r.get('draft', False)]
                if not releases:
                    return None
                rel = releases[0]
            else:
                resp = requests.get(GITHUB_API_LATEST, timeout=timeout,
                                    headers={"Accept": "application/vnd.github+json"})
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                rel = resp.json()
            return {
                'tag_name': rel.get('tag_name', ''),
                'name': rel.get('name', ''),
                'html_url': rel.get('html_url', ''),
                'body': rel.get('body', ''),
                'prerelease': rel.get('prerelease', False),
                'published_at': rel.get('published_at', ''),
                'assets': rel.get('assets', []),
            }
        except Exception as exc:
            logger.warning(f"Update check failed: {exc}")
            return None

    @classmethod
    def check(cls, current_version: str = VERSION,
              include_prereleases: bool = False) -> Optional[Dict[str, Any]]:
        latest = cls.fetch_latest(include_prereleases=include_prereleases)
        if not latest:
            return None
        if cls.is_newer(latest['tag_name'], current_version):
            return {
                'available': True,
                'latest_version': latest['tag_name'].lstrip('vV'),
                'current_version': current_version,
                'url': latest.get('html_url', ''),
                'notes': latest.get('body', ''),
                'prerelease': latest.get('prerelease', False),
                'assets': latest.get('assets', []),
            }
        return {'available': False, 'current_version': current_version,
                'latest_version': latest['tag_name'].lstrip('vV')}


# --- global hotkeys ---------------------------------------------------------
class HotkeyManager:
    """Thin wrapper over the ``keyboard`` library.

    The library fires callbacks on its own thread, so every callback is
    pushed through ``dispatch`` to land on the Tk main thread.
    """

    _TK_TO_KB = {
        'control': 'ctrl', 'ctrl': 'ctrl',
        'shift': 'shift', 'alt': 'alt', 'win': 'windows',
        'super': 'windows', 'meta': 'windows',
        'up': 'up', 'down': 'down', 'left': 'left', 'right': 'right',
        'space': 'space', 'return': 'enter', 'enter': 'enter',
        'esc': 'esc', 'escape': 'esc',
    }

    def __init__(self, callbacks: Dict[str, Callable[[], None]],
                 dispatch: Optional[Callable[[Callable[[], None]], None]] = None) -> None:
        self.callbacks = callbacks
        # Inline dispatch is only safe for unit tests.
        self.dispatch: Callable[[Callable[[], None]], None] = (
            dispatch if dispatch is not None else (lambda fn: fn()))
        self.registered: Dict[str, str] = {}
        self.available = KEYBOARD_AVAILABLE
        if not self.available:
            logger.info("keyboard library unavailable - hotkeys disabled")

    @classmethod
    def tk_to_keyboard(cls, hotkey: str) -> str:
        parts = [p.strip().lower() for p in hotkey.replace('-', '+').split('+') if p.strip()]
        out = [cls._TK_TO_KB.get(p, p) for p in parts]
        return '+'.join(out)

    def _wrap_for_main_thread(self, name: str,
                              callback: Callable[[], None]) -> Callable[[], None]:
        def wrapper() -> None:
            try:
                self.dispatch(callback)
            except Exception as exc:
                logger.error(f"Hotkey '{name}' dispatch failed: {exc}")
        return wrapper

    def register(self, name: str, hotkey: str, callback: Callable[[], None]) -> bool:
        if not self.available:
            return False
        kb_str = self.tk_to_keyboard(hotkey)
        if not kb_str:
            logger.warning(f"Empty hotkey for '{name}', skipping")
            return False
        try:
            self.unregister(name)
            wrapped = self._wrap_for_main_thread(name, callback)
            _keyboard.add_hotkey(kb_str, wrapped, suppress=False)
            self.registered[name] = kb_str
            logger.info(f"Registered global hotkey {name}: {kb_str}")
            return True
        except Exception as exc:
            logger.error(f"Failed to register hotkey {name}={kb_str}: {exc}")
            return False

    def unregister(self, name: str) -> None:
        if name not in self.registered:
            return
        try:
            _keyboard.remove_hotkey(self.registered[name])
        except Exception as exc:
            logger.warning(f"Failed to unregister hotkey {name}: {exc}")
        finally:
            self.registered.pop(name, None)

    def register_all(self, hotkeys: Dict[str, str]) -> None:
        for name, hk in hotkeys.items():
            cb = self.callbacks.get(name)
            if cb is not None:
                self.register(name, hk, cb)

    def stop(self) -> None:
        for name in list(self.registered):
            self.unregister(name)
        if self.available:
            try:
                _keyboard.unhook_all()
            except Exception:
                pass


# --- settings ---------------------------------------------------------------
class SettingsManager:
    """JSON settings on disk, with validation, versioning and atomic save."""

    DEFAULT_SETTINGS: Dict[str, Any] = {
        'version': SETTINGS_VERSION,
        'preset_name': None,
        'custom_color': None,
        'opacity': 0.3,
        'density': 1.0,
        'overlay_enabled': False,
        'recent_colors': [],
        'window_geometry': {
            'x': None, 'y': None,
            'width': WINDOW['width'],
            'height': WINDOW['height'],
        },
        'hotkeys': {
            'toggle':            'ctrl+shift+o',
            'increase_opacity':  'ctrl+shift+up',
            'decrease_opacity':  'ctrl+shift+down',
            'increase_density':  'ctrl+shift+right',
            'decrease_density':  'ctrl+shift+left',
        },
        'auto_startup': False,
        'start_minimized': False,
        'minimize_to_tray': True,
        'close_to_tray': True,
        'enable_notifications': True,
        'enable_fade': True,
        # System-wide hotkeys need admin and the 'keyboard' package;
        # in-window shortcuts always work, so this stays opt-in.
        'enable_global_hotkeys': False,
        'check_updates_on_startup': True,
        'include_prereleases': False,
        'skipped_version': '',
        'theme': 'system',  # 'system' | 'light' | 'dark'
        'schedule': {
            'enabled': False,
            'mode': 'fixed',          # 'fixed' | 'sunset'
            'start_time': '09:00',
            'end_time': '17:00',
            'location': {
                'latitude': 55.9533,
                'longitude': -3.1883,
                'timezone': 'Europe/London',
            },
        },
        'accessibility': {
            'high_contrast': False,
            'font_scale': 1.0,
        },
        'current_profile': None,
    }

    def __init__(self, settings_file: str = SETTINGS_FILE) -> None:
        self.settings_file = settings_file
        self.settings: Dict[str, Any] = self._deep_copy(self.DEFAULT_SETTINGS)
        self._save_pending = False
        self._lock = threading.RLock()
        self.load()

    @staticmethod
    def _deep_copy(d: Dict[str, Any]) -> Dict[str, Any]:
        return json.loads(json.dumps(d))

    def load(self) -> None:
        try:
            if not os.path.exists(self.settings_file):
                logger.info("No settings file, using defaults")
                return
            with open(self.settings_file, 'r', encoding='utf-8') as fh:
                loaded = json.load(fh)
            file_version = loaded.get('version', 1)
            if file_version < SETTINGS_VERSION:
                loaded = self._migrate(loaded, file_version)
            self._validate_and_apply(loaded)
            logger.info(f"Settings loaded (file v{file_version})")
        except json.JSONDecodeError as exc:
            logger.error(f"Corrupt settings file: {exc}")
            self._backup_and_reset()
        except Exception as exc:
            logger.error(f"Failed to load settings: {exc}")

    def _migrate(self, settings: Dict[str, Any], from_version: int) -> Dict[str, Any]:
        out = self._deep_copy(self.DEFAULT_SETTINGS)
        for k, v in settings.items():
            out[k] = v
        sch = settings.get('schedule') or {}
        if sch.get('use_sunset'):
            out.setdefault('schedule', {}).update({'mode': 'sunset'})
        if 'last_color' in settings and not settings.get('custom_color'):
            out['custom_color'] = settings['last_color']
        hk = out.get('hotkeys') or {}
        out['hotkeys'] = {k: HotkeyManager.tk_to_keyboard(v) for k, v in hk.items()}
        out['version'] = SETTINGS_VERSION
        logger.info(f"Migrated settings v{from_version} -> v{SETTINGS_VERSION}")
        return out

    def _validate_and_apply(self, loaded: Dict[str, Any]) -> None:
        self.settings = self._deep_copy(self.DEFAULT_SETTINGS)

        def _f(key: str, lo: float, hi: float, default: float) -> float:
            v = loaded.get(key, default)
            try:
                return max(lo, min(hi, float(v)))
            except Exception:
                return default

        self.settings['opacity'] = _f('opacity', 0.1, 0.6, 0.3)
        self.settings['density'] = _f('density', 0.5, 1.5, 1.0)

        for key in ('preset_name', 'custom_color', 'current_profile', 'theme',
                    'skipped_version'):
            v = loaded.get(key)
            if v is None or isinstance(v, str):
                self.settings[key] = v
        if self.settings['theme'] not in ('system', 'light', 'dark'):
            self.settings['theme'] = 'system'

        cc = self.settings.get('custom_color')
        if isinstance(cc, str) and not re.match(r'^#[0-9A-Fa-f]{6}$', cc):
            self.settings['custom_color'] = None

        for bkey in ('overlay_enabled', 'auto_startup', 'start_minimized',
                     'minimize_to_tray', 'close_to_tray', 'enable_notifications',
                     'enable_fade', 'enable_global_hotkeys',
                     'check_updates_on_startup', 'include_prereleases'):
            self.settings[bkey] = bool(loaded.get(bkey, self.settings[bkey]))

        rc = loaded.get('recent_colors', [])
        if isinstance(rc, list):
            self.settings['recent_colors'] = [
                c for c in rc[:10]
                if isinstance(c, str) and re.match(r'^#[0-9A-Fa-f]{6}$', c)
            ]

        geom = loaded.get('window_geometry') or {}
        if isinstance(geom, dict):
            try:
                self.settings['window_geometry'] = {
                    'x': geom.get('x') if isinstance(geom.get('x'), int) else None,
                    'y': geom.get('y') if isinstance(geom.get('y'), int) else None,
                    'width': max(WINDOW['min_width'], int(geom.get('width', WINDOW['width']))),
                    'height': max(WINDOW['min_height'], int(geom.get('height', WINDOW['height']))),
                }
            except Exception:
                pass

        hk = loaded.get('hotkeys') or {}
        if isinstance(hk, dict):
            cleaned = {}
            for k, v in hk.items():
                if isinstance(v, str) and v.strip():
                    cleaned[k] = HotkeyManager.tk_to_keyboard(v)
            if cleaned:
                self.settings['hotkeys'].update(cleaned)

        sch = loaded.get('schedule') or {}
        if isinstance(sch, dict):
            for k in ('enabled',):
                if k in sch:
                    self.settings['schedule'][k] = bool(sch[k])
            for k in ('mode', 'start_time', 'end_time'):
                v = sch.get(k)
                if isinstance(v, str):
                    self.settings['schedule'][k] = v
            loc = sch.get('location') or {}
            if isinstance(loc, dict):
                self.settings['schedule']['location'].update({
                    'latitude': float(loc.get('latitude', 55.9533)),
                    'longitude': float(loc.get('longitude', -3.1883)),
                    'timezone': str(loc.get('timezone', 'Europe/London')),
                })
            if self.settings['schedule']['mode'] not in ('fixed', 'sunset'):
                self.settings['schedule']['mode'] = 'fixed'

        acc = loaded.get('accessibility') or {}
        if isinstance(acc, dict):
            self.settings['accessibility'] = {
                'high_contrast': bool(acc.get('high_contrast', False)),
                'font_scale': max(0.8, min(2.0,
                                           float(acc.get('font_scale', 1.0))))
            }

    def _backup_and_reset(self) -> None:
        try:
            backup = self.settings_file + f'.corrupt.{int(time.time())}.bak'
            if os.path.exists(self.settings_file):
                shutil.move(self.settings_file, backup)
                logger.warning(f"Backed up corrupt settings to {backup}")
        except Exception as exc:
            logger.error(f"Failed to backup corrupt settings: {exc}")
        self.settings = self._deep_copy(self.DEFAULT_SETTINGS)

    def save(self) -> None:
        with self._lock:
            try:
                tmp = self.settings_file + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as fh:
                    json.dump(self.settings, fh, indent=2)
                    fh.flush()
                    try:
                        os.fsync(fh.fileno())
                    except Exception:
                        pass
                os.replace(tmp, self.settings_file)
                self._save_pending = False
            except Exception as exc:
                logger.error(f"Failed to save settings: {exc}")

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.settings.get(key, default)

    def set(self, key: str, value: Any, save_immediately: bool = True) -> None:
        with self._lock:
            self.settings[key] = value
            self._save_pending = True
        if save_immediately:
            self.save()

    def save_pending(self) -> None:
        if self._save_pending:
            self.save()

    def export_settings(self, filepath: str) -> bool:
        try:
            with open(filepath, 'w', encoding='utf-8') as fh:
                json.dump(self.settings, fh, indent=2)
            return True
        except Exception as exc:
            logger.error(f"Export settings failed: {exc}")
            return False

    def import_settings(self, filepath: str) -> bool:
        try:
            with open(filepath, 'r', encoding='utf-8') as fh:
                loaded = json.load(fh)
            self._validate_and_apply(loaded)
            self.save()
            return True
        except Exception as exc:
            logger.error(f"Import settings failed: {exc}")
            return False

    def save_profile(self, name: str, data: Optional[Dict[str, Any]] = None) -> bool:
        if not name or not re.match(r'^[\w\- ]+$', name):
            logger.error(f"Refusing invalid profile name: {name!r}")
            return False
        try:
            payload = data if data is not None else self.settings
            path = os.path.join(PROFILES_DIR, f"{name}.json")
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, indent=2)
            return True
        except Exception as exc:
            logger.error(f"Save profile failed: {exc}")
            return False

    def load_profile(self, name: str) -> bool:
        try:
            path = os.path.join(PROFILES_DIR, f"{name}.json")
            if not os.path.exists(path):
                return False
            with open(path, 'r', encoding='utf-8') as fh:
                loaded = json.load(fh)
            self._validate_and_apply(loaded)
            self.set('current_profile', name, save_immediately=False)
            self.save()
            return True
        except Exception as exc:
            logger.error(f"Load profile failed: {exc}")
            return False

    def list_profiles(self) -> List[str]:
        try:
            if not os.path.isdir(PROFILES_DIR):
                return []
            return sorted(
                f[:-5] for f in os.listdir(PROFILES_DIR) if f.endswith('.json')
            )
        except Exception as exc:
            logger.error(f"List profiles failed: {exc}")
            return []

    def delete_profile(self, name: str) -> bool:
        try:
            path = os.path.join(PROFILES_DIR, f"{name}.json")
            if os.path.exists(path):
                os.remove(path)
                return True
            return False
        except Exception as exc:
            logger.error(f"Delete profile failed: {exc}")
            return False


# --- overlay ----------------------------------------------------------------
class OverlayManager:
    """One click-through Toplevel per monitor, refreshed on hot-plug."""

    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.overlay_windows: List[tk.Toplevel] = []
        self.is_active = False
        self.current_color: Optional[str] = None
        self.current_opacity: float = 0.3
        self.current_density: float = 1.0
        self.enable_fade: bool = True
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_running = False
        self._last_monitor_signature: Optional[Tuple] = None
        self._fade_after_id: Optional[str] = None
        self._lock = threading.RLock()

    @staticmethod
    def _signature(monitors: List[Dict[str, int]]) -> Tuple:
        return tuple((m['x'], m['y'], m['width'], m['height']) for m in monitors)

    @staticmethod
    def _apply_density(hex_color: str, density: float) -> str:
        try:
            hc = hex_color.lstrip('#')
            r, g, b = int(hc[0:2], 16), int(hc[2:4], 16), int(hc[4:6], 16)
            if density < 1.0:
                f = density
                r = int(r * f + 255 * (1 - f))
                g = int(g * f + 255 * (1 - f))
                b = int(b * f + 255 * (1 - f))
            else:
                f = (density - 1.0) * 2
                grey = (r + g + b) // 3
                r = int(r + (r - grey) * f)
                g = int(g + (g - grey) * f)
                b = int(b + (b - grey) * f)
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            return f'#{r:02x}{g:02x}{b:02x}'
        except Exception:
            return hex_color

    def create(self, color: str, opacity: float, density: float = 1.0) -> bool:
        with self._lock:
            self.current_color = color
            self.current_opacity = opacity
            self.current_density = density
            # Sweep any tagged Toplevels that escaped our list, then drop
            # the ones we know about. Belt and braces.
            self._purge_orphan_overlays()
            self._destroy_internal()
            monitors = MonitorDetector.get_monitors()
            if not monitors:
                logger.error("No monitors detected")
                return False
            self._last_monitor_signature = self._signature(monitors)
            adjusted = self._apply_density(color, density)
            created = 0
            for m in monitors:
                try:
                    o = tk.Toplevel(self.root)
                    setattr(o, '_easeview_overlay', True)
                    # +1 px covers seams between monitors at mismatched DPI.
                    o.geometry(f"{m['width']+1}x{m['height']+1}+{m['x']}+{m['y']}")
                    o.overrideredirect(True)
                    o.attributes('-topmost', True)
                    o.attributes('-alpha', opacity)
                    o.configure(bg=adjusted)
                    o.update_idletasks()
                    if not self._make_click_through(o):
                        logger.warning(f"Click-through failed for monitor {m['x']},{m['y']}")
                    self.overlay_windows.append(o)
                    created += 1
                except Exception as exc:
                    logger.error(f"Overlay create failed for monitor {m}: {exc}")
            if created == 0:
                logger.error("No overlay windows created")
                return False
            self.is_active = True
            logger.info(f"Overlay created across {created} monitor(s), color={color}")
            self._start_monitor_thread()
            return True

    def _purge_orphan_overlays(self) -> None:
        try:
            known = set(id(w) for w in self.overlay_windows)
            for child in self.root.winfo_children():
                if getattr(child, '_easeview_overlay', False) and id(child) not in known:
                    try:
                        logger.warning("Purging orphan overlay window")
                        child.destroy()
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning(f"Orphan sweep failed: {exc}")

    def _make_click_through(self, win: tk.Toplevel) -> bool:
        try:
            hwnd = win.winfo_id()
            user32 = ctypes.windll.user32
            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.GetParent.restype = ctypes.c_void_p
            user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                  ctypes.c_ssize_t]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            parent = user32.GetParent(hwnd)
            target = parent if parent else hwnd
            style = user32.GetWindowLongPtrW(target, self.GWL_EXSTYLE)
            new = style | self.WS_EX_LAYERED | self.WS_EX_TRANSPARENT \
                       | self.WS_EX_TOOLWINDOW | self.WS_EX_NOACTIVATE
            ctypes.windll.kernel32.SetLastError(0)
            user32.SetWindowLongPtrW(target, self.GWL_EXSTYLE, new)
            err = ctypes.windll.kernel32.GetLastError()
            if err not in (0,):
                logger.error(f"SetWindowLongPtrW error {err}")
                return False
            return True
        except Exception as exc:
            logger.error(f"Click-through setup failed: {exc}")
            return False

    def update_opacity(self, opacity: float) -> None:
        with self._lock:
            self.current_opacity = opacity
            for w in self.overlay_windows:
                try:
                    w.attributes('-alpha', opacity)
                except Exception:
                    pass

    def update_density(self, density: float) -> None:
        with self._lock:
            self.current_density = density
            if not self.current_color:
                return
            colour = self._apply_density(self.current_color, density)
            for w in self.overlay_windows:
                try:
                    w.configure(bg=colour)
                except Exception:
                    pass

    def show(self, use_fade: Optional[bool] = None) -> None:
        if not self.overlay_windows:
            return
        if use_fade is None:
            use_fade = self.enable_fade
        if use_fade:
            self._animate_fade(target=self.current_opacity, hide_at_end=False)
        else:
            for w in self.overlay_windows:
                try:
                    w.deiconify()
                    w.attributes('-alpha', self.current_opacity)
                except Exception:
                    pass
            self.is_active = True

    def hide(self, use_fade: Optional[bool] = None) -> None:
        if not self.overlay_windows:
            return
        if use_fade is None:
            use_fade = self.enable_fade
        if use_fade and self.is_active:
            self._animate_fade(target=0.0, hide_at_end=True)
        else:
            for w in self.overlay_windows:
                try:
                    w.withdraw()
                except Exception:
                    pass
            self.is_active = False

    def _animate_fade(self, target: float, hide_at_end: bool,
                      duration: float = 0.25) -> None:
        if self._fade_after_id:
            try:
                self.root.after_cancel(self._fade_after_id)
            except Exception:
                pass
            self._fade_after_id = None
        steps = max(1, int(duration * 30))
        try:
            current = float(self.overlay_windows[0].attributes('-alpha'))
        except Exception:
            current = 0.0
        delta = (target - current) / steps

        def step(i: int = 0, cur: float = current) -> None:
            cur = cur + delta
            for w in self.overlay_windows:
                try:
                    if i == 0 and not hide_at_end:
                        w.deiconify()
                    w.attributes('-alpha', max(0.0, min(1.0, cur)))
                except Exception:
                    pass
            if i + 1 >= steps:
                if hide_at_end:
                    for w in self.overlay_windows:
                        try:
                            w.withdraw()
                        except Exception:
                            pass
                    self.is_active = False
                else:
                    for w in self.overlay_windows:
                        try:
                            w.attributes('-alpha', target)
                        except Exception:
                            pass
                    self.is_active = True
                self._fade_after_id = None
                return
            self._fade_after_id = self.root.after(33,
                                                  lambda: step(i + 1, cur))

        step()

    def toggle(self) -> bool:
        if self.is_active:
            self.hide()
        elif self.overlay_windows:
            self.show()
        return self.is_active

    def _start_monitor_thread(self) -> None:
        if self._monitor_running:
            return
        self._monitor_running = True

        def loop() -> None:
            while self._monitor_running:
                try:
                    monitors = MonitorDetector.get_monitors()
                    sig = self._signature(monitors)
                    if sig != self._last_monitor_signature and self.is_active and self.current_color:
                        self._last_monitor_signature = sig
                        logger.info("Monitor layout changed, rebuilding overlays")
                        self.root.after(0, self._rebuild_for_current)
                    if self.is_active and self.overlay_windows:
                        self.root.after(0, self._reassert_topmost)
                except Exception as exc:
                    logger.warning(f"Monitor loop: {exc}")
                for _ in range(20):
                    if not self._monitor_running:
                        return
                    time.sleep(0.1)

        self._monitor_thread = threading.Thread(target=loop, daemon=True,
                                                 name="EaseViewMonitorWatch")
        self._monitor_thread.start()

    def _reassert_topmost(self) -> None:
        for w in self.overlay_windows:
            try:
                w.attributes('-topmost', True)
            except Exception:
                pass

    def _rebuild_for_current(self) -> None:
        if not (self.is_active and self.current_color):
            return
        self.create(self.current_color, self.current_opacity, self.current_density)

    def _stop_monitor_thread(self) -> None:
        self._monitor_running = False
        t = self._monitor_thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._monitor_thread = None

    def _destroy_internal(self) -> None:
        for w in self.overlay_windows:
            try:
                w.destroy()
            except Exception:
                pass
        self.overlay_windows = []

    def destroy(self) -> None:
        self._stop_monitor_thread()
        with self._lock:
            self._destroy_internal()
            self.is_active = False


# --- schedule ---------------------------------------------------------------
class ScheduleManager:
    """Enable/disable overlay on a fixed time range or sunset-to-sunrise."""

    def __init__(self, app: "EaseViewApp") -> None:
        self.app = app
        self._thread: Optional[threading.Thread] = None
        self._running = False

    @staticmethod
    def _in_range(now: dt_time, start: dt_time, end: dt_time) -> bool:
        if start == end:
            return False
        if start < end:
            return start <= now <= end
        return now >= start or now <= end  # overnight

    def _resolve_range(self) -> Optional[Tuple[dt_time, dt_time]]:
        sch = self.app.settings.get('schedule', {})
        mode = sch.get('mode', 'fixed')
        if mode == 'sunset' and ASTRAL_AVAILABLE:
            try:
                loc = sch['location']
                info = LocationInfo("EaseView", "EaseView",
                                    loc.get('timezone', 'UTC'),
                                    loc.get('latitude', 0.0),
                                    loc.get('longitude', 0.0))
                today = sun(info.observer, date=datetime.now().date())
                return today['sunset'].time(), today['sunrise'].time()
            except Exception as exc:
                logger.warning(f"Astral sunset calc failed: {exc}")
                return None
        try:
            return (dt_time.fromisoformat(sch.get('start_time', '09:00')),
                    dt_time.fromisoformat(sch.get('end_time', '17:00')))
        except Exception:
            return None

    def start(self) -> None:
        self.stop()
        if not self.app.settings.get('schedule', {}).get('enabled', False):
            return
        self._running = True

        def loop() -> None:
            while self._running:
                try:
                    rng = self._resolve_range()
                    if rng:
                        start, end = rng
                        in_range = self._in_range(datetime.now().time(), start, end)
                        if in_range and not self.app.overlay.is_active and self.app.current_color():
                            self.app.root.after(0, self.app.overlay.show)
                        elif not in_range and self.app.overlay.is_active:
                            self.app.root.after(0, self.app.overlay.hide)
                except Exception as exc:
                    logger.error(f"Schedule loop error: {exc}")
                # 30s tick, but check stop flag often
                for _ in range(60):
                    if not self._running:
                        return
                    time.sleep(0.5)

        self._thread = threading.Thread(target=loop, daemon=True,
                                         name="EaseViewSchedule")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._thread = None


# --- system tray ------------------------------------------------------------
class TrayManager:
    """System tray icon. Icon and menu refresh as state changes."""

    def __init__(self, app: "EaseViewApp") -> None:
        self.app = app
        self.icon: Any = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self.available = PYSTRAY_AVAILABLE
        if not self.available:
            logger.info("pystray unavailable - tray icon disabled")

    def _resource_path(self, rel: str) -> str:
        base = getattr(sys, '_MEIPASS', _exe_dir())
        return os.path.join(base, rel)

    def _build_image(self, color: Optional[str],
                     overlay_active: bool = True) -> Optional[Any]:
        if not self.available:
            return None
        try:
            png = self._resource_path('tray_icon.png')
            if color is None and os.path.exists(png):
                return Image.open(png).convert('RGBA')
            base = color or LIGHT_COLOURS['accent']
            img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([4, 4, 60, 60], fill=base, outline='white', width=3)
            if not overlay_active:
                # White pip in the centre = overlay off
                draw.ellipse([24, 24, 40, 40], fill='white',
                             outline=(64, 64, 64, 255), width=1)
            return img
        except Exception as exc:
            logger.warning(f"Tray icon image build failed: {exc}")
            return None

    def _build_menu(self) -> Any:
        items: List[Any] = []

        items.append(pystray.MenuItem(self._state_line(), None, enabled=False))
        items.append(pystray.Menu.SEPARATOR)

        items.append(pystray.MenuItem(
            "Show / Hide overlay",
            lambda icon, _it: self.app.toggle_overlay(),
            default=True))

        pause_items = [
            pystray.MenuItem("10 seconds", lambda icon, _it: self.app.pause_overlay(10)),
            pystray.MenuItem("30 seconds", lambda icon, _it: self.app.pause_overlay(30)),
            pystray.MenuItem("1 minute",   lambda icon, _it: self.app.pause_overlay(60)),
            pystray.MenuItem("5 minutes",  lambda icon, _it: self.app.pause_overlay(300)),
        ]
        items.append(pystray.MenuItem(
            "Pause overlay", pystray.Menu(*pause_items),
            enabled=self.app.overlay.is_active))

        try:
            colour_items = []
            for name, data in self.app.PRESETS.items():
                colour_items.append(pystray.MenuItem(
                    name,
                    lambda icon, _it, n=name, c=data['color']:
                        self.app.select_preset(n, c),
                    checked=lambda _it, n=name: self.app.active_preset == n,
                    radio=True))
            items.append(pystray.MenuItem("Quick colour",
                                          pystray.Menu(*colour_items)))
        except Exception as exc:
            logger.warning(f"Building colour submenu failed: {exc}")

        try:
            profiles = self.app.settings.list_profiles()
            if profiles:
                pitems = [
                    pystray.MenuItem(
                        p, lambda icon, _it, name=p: self.app.load_profile_by_name(name))
                    for p in profiles
                ]
                items.append(pystray.MenuItem("Profiles", pystray.Menu(*pitems)))
        except Exception:
            pass

        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Open settings...",
                                       lambda icon, _it: self.app.show_window()))
        items.append(pystray.MenuItem("Check for updates...",
                                       lambda icon, _it: self.app.check_updates_async(manual=True)))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Exit EaseView",
                                       lambda icon, _it: self.app.quit_app()))
        return pystray.Menu(*items)

    def _state_line(self) -> str:
        try:
            active = self.app.overlay.is_active
            label = self.app.active_preset
            if not label and self.app.custom_color:
                label = self.app.custom_color
            if active and label:
                return f"EaseView - ON  ({label})"
            if active:
                return "EaseView - ON"
            return "EaseView - OFF"
        except Exception:
            return "EaseView"

    def create(self, color: Optional[str] = None) -> None:
        if not self.available:
            return
        with self._lock:
            if self.icon is not None:
                # Just refresh the icon image + menu
                self.update_color(color)
                return
            try:
                image = self._build_image(color)
                menu = self._build_menu()
                self.icon = pystray.Icon("easeview", image, "EaseView", menu)
                self._thread = threading.Thread(target=self._run_safe, daemon=True,
                                                 name="EaseViewTray")
                self._thread.start()
                logger.info("Tray icon created")
            except Exception as exc:
                logger.error(f"Failed to create tray icon: {exc}")
                self.icon = None

    def _run_safe(self) -> None:
        try:
            self.icon.run()
        except Exception as exc:
            logger.error(f"Tray icon run() error: {exc}")

    def update_color(self, color: Optional[str]) -> None:
        if not self.available or self.icon is None:
            return
        try:
            active = bool(getattr(self.app.overlay, 'is_active', False))
            self.icon.icon = self._build_image(color, overlay_active=active)
            label = self.app.active_preset or (color or '')
            self.icon.title = f"EaseView - {'ON' if active else 'OFF'}" + (
                f" - {label}" if label else "")
        except Exception as exc:
            logger.warning(f"Failed to update tray icon colour: {exc}")

    def rebuild_menu(self) -> None:
        if not self.available or self.icon is None:
            return
        try:
            self.icon.menu = self._build_menu()
            self.icon.update_menu()
        except Exception as exc:
            logger.warning(f"Failed to rebuild tray menu: {exc}")

    def stop(self) -> None:
        if self.icon is None:
            return
        try:
            self.icon.visible = False
            self.icon.stop()
        except Exception as exc:
            logger.warning(f"Tray stop error: {exc}")
        self.icon = None


# --- widgets ----------------------------------------------------------------
class AccessibleButton(tk.Frame):
    """Full-width clickable row with an active state."""

    def __init__(self, parent: tk.Widget, colours: Dict[str, str], fonts: Dict[str, tuple],
                 text: str, colour_hex: str, command: Callable[[], None],
                 is_active: bool = False) -> None:
        super().__init__(parent, bg=colours['surface'], cursor="hand2")
        self.colours = colours
        self.command = command
        self._is_active = is_active

        self.configure(takefocus=True, highlightthickness=2,
                       highlightcolor=colours['focus'],
                       highlightbackground=colours['border'])

        self.active_indicator = tk.Frame(self,
            bg=colours['accent'] if is_active else colours['surface'],
            width=SPACING['active_indicator_width'])
        self.active_indicator.pack(side=tk.LEFT, fill=tk.Y)
        self.active_indicator.pack_propagate(False)

        self.indicator = tk.Frame(self, bg=colour_hex,
                                  width=SPACING['colour_indicator_width'])
        self.indicator.pack(side=tk.LEFT, fill=tk.Y)
        self.indicator.pack_propagate(False)

        self.label = tk.Label(self, text=text, font=fonts['button'],
                              bg=colours['surface'], fg=colours['text_primary'],
                              anchor='w',
                              padx=SPACING['button_padding_x'],
                              pady=SPACING['button_padding_y'])
        self.label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for w in (self, self.active_indicator, self.indicator, self.label):
            w.bind("<Button-1>", self._on_click)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
        self.bind("<Return>", self._on_click)
        self.bind("<space>", self._on_click)
        self.bind("<FocusIn>",
                  lambda _e: self.configure(highlightbackground=colours['focus']))
        self.bind("<FocusOut>",
                  lambda _e: self.configure(highlightbackground=colours['border']))
        if is_active:
            self._apply_active()

    def set_active(self, active: bool) -> None:
        self._is_active = active
        if active: self._apply_active()
        else:      self._apply_inactive()

    def _apply_active(self) -> None:
        self.active_indicator.configure(bg=self.colours['accent'])
        self.configure(bg=self.colours['surface_active'])
        self.label.configure(bg=self.colours['surface_active'])

    def _apply_inactive(self) -> None:
        self.active_indicator.configure(bg=self.colours['surface'])
        self.configure(bg=self.colours['surface'])
        self.label.configure(bg=self.colours['surface'])

    def _on_click(self, _e=None):
        if self.command:
            try:
                self.command()
            except Exception as exc:
                logger.error(f"Button command error: {exc}")

    def _on_enter(self, _e=None):
        if not self._is_active:
            self.configure(bg=self.colours['surface_hover'])
            self.label.configure(bg=self.colours['surface_hover'])

    def _on_leave(self, _e=None):
        if self._is_active:
            self._apply_active()
        else:
            self.configure(bg=self.colours['surface'])
            self.label.configure(bg=self.colours['surface'])


class CustomColourButton(AccessibleButton):
    """Custom colour picker row."""

    def __init__(self, parent: tk.Widget, colours: Dict[str, str],
                 fonts: Dict[str, tuple], command: Callable[[], None],
                 is_active: bool = False, color: Optional[str] = None) -> None:
        super().__init__(parent, colours, fonts,
                         text="Choose custom colour",
                         colour_hex=(color or colours['background']),
                         command=command, is_active=is_active)
        self.plus = tk.Label(self.indicator, text="+",
                             font=('Segoe UI', 14, 'normal'),
                             bg=(color or colours['background']),
                             fg=colours['text_secondary'])
        self.plus.place(relx=0.5, rely=0.5, anchor='center')
        if color:
            self.indicator.configure(bg=color)
            self.plus.configure(bg=color)

    def set_active(self, active: bool, color: Optional[str] = None) -> None:  # type: ignore[override]
        super().set_active(active)
        if color:
            self.indicator.configure(bg=color)
            self.plus.configure(bg=color)
        else:
            self.indicator.configure(bg=self.colours['background'])
            self.plus.configure(bg=self.colours['background'])


class ToggleButton(tk.Frame):
    """Big on/off bar at the top of the window."""

    def __init__(self, parent: tk.Widget, colours: Dict[str, str], fonts: Dict[str, tuple],
                 text_on: str, text_off: str, command: Callable[[], None],
                 is_on: bool = False) -> None:
        super().__init__(parent, bg=colours['surface'], cursor="hand2")
        self.colours = colours
        self.text_on = text_on
        self.text_off = text_off
        self.command = command
        self._is_on = is_on

        self.configure(takefocus=True, highlightthickness=2,
                       highlightcolor=colours['focus'],
                       highlightbackground=colours['border'])

        self.status = tk.Frame(self,
            bg=colours['success'] if is_on else colours['inactive'],
            width=8)
        self.status.pack(side=tk.LEFT, fill=tk.Y)
        self.status.pack_propagate(False)

        self.label = tk.Label(self, text=text_on if is_on else text_off,
                              font=fonts['button'],
                              bg=colours['surface'], fg=colours['text_primary'],
                              anchor='w',
                              padx=SPACING['button_padding_x'],
                              pady=SPACING['button_padding_y'])
        self.label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for w in (self, self.status, self.label):
            w.bind("<Button-1>", self._on_click)
            w.bind("<Enter>", lambda _e: (self.configure(bg=colours['surface_hover']),
                                          self.label.configure(bg=colours['surface_hover'])))
            w.bind("<Leave>", lambda _e: (self.configure(bg=colours['surface']),
                                          self.label.configure(bg=colours['surface'])))
        self.bind("<Return>", self._on_click)
        self.bind("<space>", self._on_click)

    def set_state(self, is_on: bool) -> None:
        self._is_on = is_on
        self.status.configure(
            bg=self.colours['success'] if is_on else self.colours['inactive'])
        self.label.configure(text=self.text_on if is_on else self.text_off)

    def _on_click(self, _e=None):
        if self.command:
            try:
                self.command()
            except Exception as exc:
                logger.error(f"Toggle command error: {exc}")


class Tooltip:
    """Hover tooltip on any widget."""

    def __init__(self, widget: tk.Widget, text: str,
                 delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._tip: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide,     add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self) -> None:
        if self._tip or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            t = tk.Toplevel(self.widget)
            t.wm_overrideredirect(True)
            t.wm_geometry(f"+{x}+{y}")
            tk.Label(t, text=self.text, justify='left',
                     bg="#FFFFE0", fg="#202020",
                     relief='solid', borderwidth=1,
                     font=('Segoe UI', 8, 'normal'),
                     padx=6, pady=3).pack()
            self._tip = t
        except Exception:
            self._tip = None

    def _hide(self, _e=None) -> None:
        self._cancel()
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class UpdateBanner(tk.Frame):
    """Yellow banner that appears when a newer release is available."""

    def __init__(self, parent: tk.Widget, colours: Dict[str, str], fonts: Dict[str, tuple]):
        super().__init__(parent, bg=colours['banner_bg'])
        self.colours = colours
        self.fonts = fonts
        self._version: str = ''
        self._url: str = ''
        self.label = tk.Label(self, text='', anchor='w',
                              font=fonts['body'],
                              bg=colours['banner_bg'], fg=colours['banner_fg'])
        self.label.pack(side=tk.LEFT, padx=12, pady=8, fill=tk.X, expand=True)
        btn_open = tk.Button(self, text="Download", relief=tk.FLAT,
                             bg=colours['accent'], fg='white', cursor='hand2',
                             command=self._open)
        btn_open.pack(side=tk.RIGHT, padx=(4, 8), pady=6)
        btn_skip = tk.Button(self, text="Skip", relief=tk.FLAT,
                             bg=colours['banner_bg'], fg=colours['banner_fg'],
                             cursor='hand2', command=self._skip)
        btn_skip.pack(side=tk.RIGHT, padx=4, pady=6)
        btn_close = tk.Button(self, text="Dismiss", relief=tk.FLAT,
                              bg=colours['banner_bg'], fg=colours['banner_fg'],
                              cursor='hand2', command=self.pack_forget)
        btn_close.pack(side=tk.RIGHT, padx=4, pady=6)
        self.on_skip: Optional[Callable[[str], None]] = None

    def _open(self):
        if not self._url:
            return
        try:
            import webbrowser
            webbrowser.open(self._url, new=2)
        except Exception as exc:
            logger.warning(f"Failed to open browser: {exc}")

    def _skip(self):
        if self.on_skip and self._version:
            self.on_skip(self._version)
        self.pack_forget()

    def show_for(self, version: str, url: str, current_version: str) -> None:
        self._version = version
        self._url = url
        self.label.configure(
            text=f"Update available: v{version} (you have v{current_version}).")


# --- main application -------------------------------------------------------
class EaseViewApp:

    PRESETS: Dict[str, Dict[str, str]] = {
        "Amber":   {"color": "#FFD54F", "description": "Warm yellow tint"},
        "Blue":    {"color": "#81D4FA", "description": "Cool blue tint"},
        "Green":   {"color": "#A5D6A7", "description": "Soft green tint"},
        "Pink":    {"color": "#F8BBD9", "description": "Light pink tint"},
        "Purple":  {"color": "#CE93D8", "description": "Gentle purple tint"},
        "Grey":    {"color": "#BDBDBD", "description": "Neutral grey tint"},
        "Cream":   {"color": "#FFF8E1", "description": "Soft cream"},
        "Mint":    {"color": "#C8E6C9", "description": "Light mint"},
    }

    def __init__(self, cli_args: Optional[argparse.Namespace] = None) -> None:
        if not InstanceLocker.acquire_lock():
            try:
                root = tk.Tk(); root.withdraw()
                messagebox.showwarning(
                    "EaseView",
                    "EaseView is already running.\nLook for the icon in the system tray.")
                root.destroy()
            except Exception:
                pass
            sys.exit(0)

        self.cli_args = cli_args or argparse.Namespace(minimized=False)

        self.settings = SettingsManager()
        self.colours = self._resolve_palette()
        self.fonts = self._resolve_fonts()

        self.root = tk.Tk()
        self.root.title("EaseView")
        try:
            self.root.tk.call('tk', 'scaling',
                              self.settings.get('accessibility', {}).get('font_scale', 1.0)
                              * self._auto_tk_scaling())
        except Exception:
            pass

        self.overlay = OverlayManager(self.root)
        self.overlay.enable_fade = self.settings.get('enable_fade', True)
        self.tray = TrayManager(self)
        self.schedule_manager = ScheduleManager(self)
        self.hotkey_manager = HotkeyManager(
            callbacks={
                'toggle': self.toggle_overlay,
                'increase_opacity': lambda: self.adjust_opacity(5),
                'decrease_opacity': lambda: self.adjust_opacity(-5),
                'increase_density': lambda: self.adjust_density(10),
                'decrease_density': lambda: self.adjust_density(-10),
            },
            dispatch=self._dispatch_to_main,
        )

        self.colour_buttons: Dict[str, AccessibleButton] = {}
        self.custom_button: Optional[CustomColourButton] = None
        self.toggle_button: Optional[ToggleButton] = None
        self.update_banner: Optional[UpdateBanner] = None
        self.active_preset: Optional[str] = self.settings.get('preset_name')
        self.custom_color: Optional[str] = self.settings.get('custom_color')

        self._set_window_icon()
        self._build_window()
        self._build_menu()
        self._bind_shortcuts()
        self._update_selection_ui()

        # Always create the tray icon so the user can always find the app.
        self.tray.create(self._current_color_hex())

        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.root.bind("<Map>", self._on_window_map)

        self._restore_window_geometry()
        self._setup_hotkeys_from_settings()

        if self.settings.get('auto_startup', False):
            WindowsIntegration.set_startup(True,
                start_minimized=self.settings.get('start_minimized', False))

        self._restore_overlay_state()

        if self.settings.get('schedule', {}).get('enabled', False):
            self.schedule_manager.start()

        if self.settings.get('check_updates_on_startup', True):
            self.root.after(1500, lambda: self.check_updates_async(manual=False))

        start_min = (self.cli_args.minimized
                     or self.settings.get('start_minimized', False))
        if start_min:
            self.root.after(50, self.root.withdraw)

        logger.info(f"EaseView v{VERSION} started "
                    f"(portable={PORTABLE_MODE}, dark={WindowsIntegration.is_dark_mode()})")

    def _resolve_palette(self) -> Dict[str, str]:
        theme = self.settings.get('theme', 'system')
        if theme == 'dark':
            return DARK_COLOURS.copy()
        if theme == 'light':
            return LIGHT_COLOURS.copy()
        return WindowsIntegration.get_palette()

    def _resolve_fonts(self) -> Dict[str, tuple]:
        scale = float(self.settings.get('accessibility', {}).get('font_scale', 1.0))
        scale = max(0.8, min(2.0, scale))
        scaled = {}
        for k, (family, size, style) in BASE_FONTS.items():
            scaled[k] = (family, max(7, int(size * scale)), style)
        return scaled

    @staticmethod
    def _auto_tk_scaling() -> float:
        if os.name != "nt":
            return 1.0
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            return max(1.0, dpi / 96.0)
        except Exception:
            return 1.0

    @staticmethod
    def _resource_path(rel: str) -> str:
        base = getattr(sys, '_MEIPASS', _exe_dir())
        return os.path.join(base, rel)

    def _set_window_icon(self) -> None:
        try:
            ico = self._resource_path('app_icon.ico')
            if os.path.exists(ico):
                self.root.iconbitmap(ico)
        except Exception as exc:
            logger.warning(f"Could not set window icon: {exc}")

    def current_color(self) -> Optional[str]:
        if self.active_preset:
            return self.PRESETS.get(self.active_preset, {}).get('color')
        return self.custom_color

    def _current_color_hex(self) -> Optional[str]:
        return self.current_color()

    def _build_menu(self) -> None:
        menubar = Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Toggle overlay", command=self.toggle_overlay,
                              accelerator="Ctrl+Shift+O")
        file_menu.add_separator()
        prof = Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Profiles", menu=prof)
        prof.add_command(label="Save current as profile...",
                         command=self._save_profile_dialog)
        prof.add_command(label="Load profile...",
                         command=self._load_profile_dialog)
        prof.add_separator()
        prof.add_command(label="Manage profiles...",
                         command=self._manage_profiles_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Export settings...", command=self._export_settings)
        file_menu.add_command(label="Import settings...", command=self._import_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Reset all settings to defaults...",
                              command=self._reset_to_defaults)
        file_menu.add_separator()
        file_menu.add_command(label="Hide to tray", command=self._hide_to_tray)
        file_menu.add_command(label="Exit", command=self.quit_app)

        settings_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="Startup options...", command=self._startup_options)
        settings_menu.add_command(label="Hotkey settings...", command=self._hotkey_settings)
        settings_menu.add_command(label="Schedule overlay...", command=self._schedule_settings)
        settings_menu.add_command(label="Accessibility...", command=self._accessibility_settings)
        settings_menu.add_separator()
        theme_menu = Menu(settings_menu, tearoff=0)
        settings_menu.add_cascade(label="Theme", menu=theme_menu)
        self._theme_var = tk.StringVar(value=self.settings.get('theme', 'system'))
        for label, value in (("Follow system", "system"),
                             ("Light", "light"),
                             ("Dark", "dark")):
            theme_menu.add_radiobutton(label=label, value=value,
                                       variable=self._theme_var,
                                       command=self._on_theme_change)

        help_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Keyboard shortcuts", command=self.show_shortcuts)
        help_menu.add_command(label="How to use", command=self.show_help)
        help_menu.add_separator()
        help_menu.add_command(label="Check for updates...",
                              command=lambda: self.check_updates_async(manual=True))
        help_menu.add_command(label="View log file",
                              command=lambda: self._open_path(LOG_FILE))
        help_menu.add_command(label="Open settings folder",
                              command=lambda: self._open_path(SETTINGS_DIR))
        help_menu.add_separator()
        help_menu.add_command(label="About EaseView", command=self.show_about)

    def _on_theme_change(self) -> None:
        self.settings.set('theme', self._theme_var.get())
        messagebox.showinfo("Theme", "Theme will fully apply after restart.")

    def _build_window(self) -> None:
        c = self.colours
        f = self.fonts

        self.root.configure(bg=c['background'])
        self.root.minsize(WINDOW['min_width'], WINDOW['min_height'])

        # Header
        header = tk.Frame(self.root, bg=c['surface'])
        header.pack(fill=tk.X)
        hi = tk.Frame(header, bg=c['surface'])
        hi.pack(fill=tk.X, padx=SPACING['window_padding'], pady=14)
        tk.Label(hi, text="EaseView", font=f['title'],
                 bg=c['surface'], fg=c['text_primary'], anchor='w').pack(anchor='w')
        tk.Label(hi, text="Screen colour overlay for easier reading",
                 font=f['subtitle'], bg=c['surface'], fg=c['text_secondary'],
                 anchor='w').pack(anchor='w', pady=(2, 0))

        tk.Frame(self.root, bg=c['divider'], height=1).pack(fill=tk.X)

        # Reserved row for the update banner. We pack it now (empty) so the
        # banner appears in the right place when we later pack it in.
        self._banner_slot = tk.Frame(self.root, bg=c['background'])
        self._banner_slot.pack(fill=tk.X, side=tk.TOP)
        self.update_banner = UpdateBanner(self._banner_slot, c, f)
        self.update_banner.on_skip = self._on_update_skipped

        # Scrollable content so the whole UI is reachable when shrunk.
        outer = tk.Frame(self.root, bg=c['background'])
        outer.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(outer, bg=c['background'], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        content = tk.Frame(canvas, bg=c['background'])
        content_id = canvas.create_window((0, 0), window=content, anchor='nw')

        def _on_content_configure(_e=None):
            canvas.configure(scrollregion=canvas.bbox('all'))

        def _on_canvas_configure(e):
            canvas.itemconfigure(content_id, width=e.width)

        content.bind('<Configure>', _on_content_configure)
        canvas.bind('<Configure>', _on_canvas_configure)

        def _on_mousewheel(e):
            try:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
            except Exception:
                pass
        canvas.bind_all('<MouseWheel>', _on_mousewheel)

        inner = tk.Frame(content, bg=c['background'])
        inner.pack(fill=tk.BOTH, expand=True,
                   padx=SPACING['window_padding'], pady=SPACING['window_padding'])

        self.toggle_button = ToggleButton(
            inner, c, f,
            text_on="Overlay is ON  (click to disable)",
            text_off="Overlay is OFF  (click to enable)",
            command=self.toggle_overlay,
            is_on=self.overlay.is_active)
        self.toggle_button.pack(fill=tk.X, pady=(0, SPACING['section_gap']))

        tk.Label(inner, text="Overlay colour", font=f['section'],
                 bg=c['background'], fg=c['text_secondary'],
                 anchor='w').pack(anchor='w', pady=(0, 6))

        colours_box = tk.Frame(inner, bg=c['background'])
        colours_box.pack(fill=tk.X)
        for name, data in self.PRESETS.items():
            is_active = (self.active_preset == name)
            btn = AccessibleButton(colours_box, c, f, name, data['color'],
                                   lambda n=name, col=data['color']:
                                       self.select_preset(n, col),
                                   is_active=is_active)
            btn.pack(fill=tk.X, pady=(0, SPACING['row_gap']))
            self.colour_buttons[name] = btn
            Tooltip(btn, f"{name}  {data['color'].upper()}\n{data.get('description', '')}")

        custom_active = (self.active_preset is None and self.custom_color is not None)
        self.custom_button = CustomColourButton(
            colours_box, c, f, command=self.choose_custom_color,
            is_active=custom_active, color=self.custom_color)
        self.custom_button.pack(fill=tk.X, pady=(0, SPACING['row_gap']))
        Tooltip(self.custom_button,
                "Pick any colour" +
                (f"   (current: {self.custom_color.upper()})"
                 if self.custom_color else ""))

        recents = self.settings.get('recent_colors', []) or []
        if recents:
            rec_frame = tk.Frame(inner, bg=c['background'])
            rec_frame.pack(fill=tk.X, pady=(8, 0))
            tk.Label(rec_frame, text="Recent:", font=f['footer'],
                     bg=c['background'], fg=c['text_secondary']).pack(side=tk.LEFT)
            for hexc in recents[:8]:
                sw = tk.Label(rec_frame, text='   ', bg=hexc, bd=1, relief='solid',
                              cursor='hand2')
                sw.pack(side=tk.LEFT, padx=3)
                sw.bind('<Button-1>', lambda _e, col=hexc: self._apply_recent_color(col))

        self._build_slider_section(
            inner, "Overlay strength", "opacity_var", "opacity_value_label",
            initial=self.settings.get('opacity', 0.3) * 100,
            lo=10, hi=60, on_change=self.on_opacity_change,
            quick_presets=(20, 30, 40, 50))

        self._build_slider_section(
            inner, "Colour density", "density_var", "density_value_label",
            initial=self.settings.get('density', 1.0) * 100,
            lo=50, hi=150, on_change=self.on_density_change,
            quick_presets=(75, 100, 125))

        tk.Label(inner,
                 text="Tip: Ctrl+Shift+O toggles, Esc hides immediately.",
                 font=f['footer'],
                 bg=c['background'], fg=c['text_secondary'],
                 anchor='w').pack(anchor='w', pady=(SPACING['section_gap'], 0))

        footer = tk.Frame(self.root, bg=c['surface'])
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Frame(footer, bg=c['divider'], height=1).pack(fill=tk.X)
        fi = tk.Frame(footer, bg=c['surface'])
        fi.pack(fill=tk.X, padx=SPACING['window_padding'], pady=8)

        monitors_count = len(MonitorDetector.get_monitors())
        modes = []
        if WIN32_AVAILABLE:    modes.append("win32")
        if KEYBOARD_AVAILABLE: modes.append("hotkeys")
        if REQUESTS_AVAILABLE: modes.append("updates")
        if ASTRAL_AVAILABLE:   modes.append("astral")
        if PORTABLE_MODE:      modes.append("portable")
        status = f"v{VERSION}   |   {monitors_count} monitor{'s' if monitors_count != 1 else ''}"
        if modes:
            status += "   |   " + ", ".join(modes)
        tk.Label(fi, text=status, font=f['footer'],
                 bg=c['surface'], fg=c['text_secondary'],
                 anchor='w').pack(side=tk.LEFT)

    def _build_slider_section(self, parent: tk.Widget, title: str,
                              var_attr: str, label_attr: str, initial: float,
                              lo: float, hi: float,
                              on_change: Callable[[Any], None],
                              quick_presets: Iterable[int]) -> None:
        c = self.colours
        f = self.fonts
        section = tk.Frame(parent, bg=c['background'])
        section.pack(fill=tk.X, pady=(SPACING['section_gap'], 0))
        header = tk.Frame(section, bg=c['background'])
        header.pack(fill=tk.X)
        tk.Label(header, text=title, font=f['section'],
                 bg=c['background'], fg=c['text_secondary'],
                 anchor='w').pack(side=tk.LEFT)
        value_label = tk.Label(header, text=f"{int(initial)}%", font=f['section'],
                               bg=c['background'], fg=c['text_primary'])
        value_label.pack(side=tk.RIGHT)
        setattr(self, label_attr, value_label)

        var = tk.DoubleVar(value=initial)
        setattr(self, var_attr, var)
        slider = tk.Scale(section, from_=lo, to=hi, orient=tk.HORIZONTAL,
                          variable=var, command=on_change,
                          showvalue=False, bg=c['background'],
                          fg=c['text_primary'], troughcolor=c['surface'],
                          activebackground=c['accent'], highlightthickness=0,
                          relief=tk.FLAT, bd=0, sliderlength=20)
        slider.pack(fill=tk.X, pady=(10, 0))

        quick_frame = tk.Frame(section, bg=c['background'])
        quick_frame.pack(fill=tk.X, pady=(6, 0))
        tk.Label(quick_frame, text="Quick:", font=f['footer'],
                 bg=c['background'], fg=c['text_secondary']).pack(side=tk.LEFT,
                                                                   padx=(0, 4))
        for v in quick_presets:
            btn = tk.Button(quick_frame, text=f"{v}%",
                            command=lambda val=v: (var.set(val), on_change(val)),
                            font=f['footer'], width=5,
                            bg=c['surface'], fg=c['text_primary'],
                            relief=tk.FLAT, bd=1, cursor='hand2',
                            activebackground=c['surface_hover'])
            btn.pack(side=tk.LEFT, padx=2)

    def _restore_window_geometry(self) -> None:
        try:
            self.root.update_idletasks()
            req_w = max(WINDOW['min_width'],  self.root.winfo_reqwidth())
            req_h = max(WINDOW['min_height'], self.root.winfo_reqheight())

            monitors = MonitorDetector.get_monitors()
            primary = MonitorDetector.primary(monitors)
            work_x, work_y = primary['work_x'], primary['work_y']
            work_w, work_h = primary['work_width'], primary['work_height']

            saved = self.settings.get('window_geometry', {}) or {}
            width = saved.get('width') or req_w
            height = saved.get('height') or req_h
            width = max(WINDOW['min_width'],  min(width,  work_w - 40))
            height = max(WINDOW['min_height'], min(height, work_h - 60))

            x = saved.get('x')
            y = saved.get('y')

            # Saved position must be at least partly on some monitor.
            valid = False
            if x is not None and y is not None:
                for m in monitors:
                    if (x < m['x'] + m['width'] and x + width > m['x']
                            and y < m['y'] + m['height'] and y + height > m['y']):
                        valid = True
                        break
            if not valid:
                x = work_x + (work_w - width) // 2
                y = work_y + (work_h - height) // 2

            self.root.geometry(f"{int(width)}x{int(height)}+{int(x)}+{int(y)}")
            self.root.bind('<Configure>', self._on_window_configure)
        except Exception as exc:
            logger.warning(f"Geometry restore failed: {exc}")
            try:
                self.root.geometry(f"{WINDOW['width']}x{WINDOW['height']}")
            except Exception:
                pass

    def _on_window_configure(self, event: Optional[tk.Event] = None) -> None:
        if not event or event.widget is not self.root:
            return
        try:
            geom = self.root.geometry()
            m = re.match(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", geom)
            if not m:
                return
            w, h, x, y = (int(g) for g in m.groups())
            self.settings.set('window_geometry',
                              {'x': x, 'y': y, 'width': w, 'height': h},
                              save_immediately=False)
            if hasattr(self, '_geom_timer'):
                try:
                    self.root.after_cancel(self._geom_timer)
                except Exception:
                    pass
            self._geom_timer = self.root.after(1500, self.settings.save_pending)
        except Exception:
            pass

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-Shift-o>", lambda _e: self.toggle_overlay())
        self.root.bind_all("<Control-Shift-O>", lambda _e: self.toggle_overlay())
        self.root.bind_all("<Escape>", lambda _e: self.hide_overlay())
        self.root.bind_all("<Control-Shift-Up>",    lambda _e: self.adjust_opacity(5))
        self.root.bind_all("<Control-Shift-Down>",  lambda _e: self.adjust_opacity(-5))
        self.root.bind_all("<Control-Shift-Right>", lambda _e: self.adjust_density(10))
        self.root.bind_all("<Control-Shift-Left>",  lambda _e: self.adjust_density(-10))

    def _setup_hotkeys_from_settings(self) -> None:
        # In-window shortcuts are always live via _bind_shortcuts(). Global
        # system-wide hotkeys are opt-in.
        if not self.settings.get('enable_global_hotkeys', False):
            logger.info("Global hotkeys disabled (opt in via Settings -> Hotkeys)")
            return
        if not KEYBOARD_AVAILABLE:
            logger.info("Global hotkeys requested but 'keyboard' is unavailable")
            return
        hk = self.settings.get('hotkeys', {}) or {}
        if not hk:
            return
        self.hotkey_manager.register_all(hk)

    def _dispatch_to_main(self, fn: Callable[[], None]) -> None:
        # Used by HotkeyManager so callbacks always run on the Tk thread.
        try:
            self.root.after(0, fn)
        except Exception as exc:
            logger.error(f"Main-thread dispatch failed: {exc}")

    def on_opacity_change(self, value: Any) -> None:
        opacity = max(0.1, min(0.6, float(value) / 100))
        self.settings.set('opacity', opacity, save_immediately=False)
        if hasattr(self, 'opacity_value_label'):
            self.opacity_value_label.configure(text=f"{int(float(value))}%")
        self.overlay.update_opacity(opacity)
        if hasattr(self, '_op_timer'):
            try: self.root.after_cancel(self._op_timer)
            except Exception: pass
        self._op_timer = self.root.after(500, self.settings.save_pending)

    def on_density_change(self, value: Any) -> None:
        density = max(0.5, min(1.5, float(value) / 100))
        self.settings.set('density', density, save_immediately=False)
        if hasattr(self, 'density_value_label'):
            self.density_value_label.configure(text=f"{int(float(value))}%")
        self.overlay.update_density(density)
        if hasattr(self, '_de_timer'):
            try: self.root.after_cancel(self._de_timer)
            except Exception: pass
        self._de_timer = self.root.after(500, self.settings.save_pending)

    def adjust_opacity(self, delta_pct: float) -> None:
        cur = self.settings.get('opacity', 0.3) * 100
        v = max(10, min(60, cur + delta_pct))
        if hasattr(self, 'opacity_var'):
            self.opacity_var.set(v)
        self.on_opacity_change(v)

    def adjust_density(self, delta_pct: float) -> None:
        cur = self.settings.get('density', 1.0) * 100
        v = max(50, min(150, cur + delta_pct))
        if hasattr(self, 'density_var'):
            self.density_var.set(v)
        self.on_density_change(v)

    def _update_selection_ui(self) -> None:
        for name, btn in self.colour_buttons.items():
            btn.set_active(name == self.active_preset)
        if self.custom_button is not None:
            is_custom = (self.active_preset is None and self.custom_color is not None)
            self.custom_button.set_active(is_custom,
                                          self.custom_color if is_custom else None)

    def select_preset(self, name: str, color: str) -> None:
        if name not in self.PRESETS:
            logger.warning(f"Unknown preset: {name}")
            return
        self.active_preset = name
        self.custom_color = None
        self.settings.set('preset_name', name, save_immediately=False)
        self.settings.set('custom_color', None, save_immediately=False)
        self.settings.save_pending()
        self._update_selection_ui()
        self.apply_overlay(color)

    def choose_custom_color(self) -> None:
        initial = self.custom_color or '#FFD54F'
        try:
            res = colorchooser.askcolor(title="Choose overlay colour",
                                        initialcolor=initial,
                                        parent=self.root)
        except Exception as exc:
            logger.error(f"Colour picker failed: {exc}")
            messagebox.showerror("EaseView", f"Unable to open colour picker:\n{exc}")
            return
        if not res or not res[1]:
            return
        hexc = res[1]
        if not re.match(r'^#[0-9A-Fa-f]{6}$', hexc):
            messagebox.showerror("EaseView", "Invalid colour returned.")
            return
        self._apply_recent_color(hexc, record=True, become_custom=True)

    def _apply_recent_color(self, hexc: str, record: bool = True,
                            become_custom: bool = True) -> None:
        if become_custom:
            self.active_preset = None
            self.custom_color = hexc
            self.settings.set('preset_name', None, save_immediately=False)
            self.settings.set('custom_color', hexc, save_immediately=False)
        if record:
            recents = [c for c in self.settings.get('recent_colors', []) if c != hexc]
            recents.insert(0, hexc)
            self.settings.set('recent_colors', recents[:10],
                              save_immediately=False)
        self.settings.save_pending()
        self._update_selection_ui()
        self.apply_overlay(hexc)

    def apply_overlay(self, color: str) -> None:
        if not color:
            return
        opacity = float(self.settings.get('opacity', 0.3))
        density = float(self.settings.get('density', 1.0))
        self.overlay.enable_fade = self.settings.get('enable_fade', True)
        ok = self.overlay.create(color, opacity, density)
        if not ok:
            messagebox.showerror(
                "EaseView",
                "Could not create the overlay.\n"
                "Try disabling other overlay tools or graphics utilities "
                "and try again.\nDetails in the log file.")
            return
        self.settings.set('overlay_enabled', True, save_immediately=False)
        self.settings.save_pending()
        if self.toggle_button:
            self.toggle_button.set_state(True)
        self.tray.update_color(color)
        self.tray.rebuild_menu()

    def toggle_overlay(self) -> None:
        if self.overlay.is_active:
            self.hide_overlay()
            return
        color = self.current_color()
        if not color:
            messagebox.showinfo(
                "EaseView", "Select a colour first, then toggle the overlay.")
            return
        # Existing windows already match the current selection: just show.
        if (self.overlay.overlay_windows
                and self.overlay.current_color == color):
            self.overlay.show()
            self.settings.set('overlay_enabled', True, save_immediately=False)
            if self.toggle_button:
                self.toggle_button.set_state(True)
            self.tray.update_color(color)
            self.tray.rebuild_menu()
            return
        # Otherwise rebuild so the right colour is guaranteed.
        self.apply_overlay(color)

    def hide_overlay(self) -> None:
        self.overlay.hide()
        self.settings.set('overlay_enabled', False, save_immediately=False)
        self.settings.save_pending()
        if self.toggle_button:
            self.toggle_button.set_state(False)
        self.tray.update_color(self._current_color_hex())
        self.tray.rebuild_menu()

    def pause_overlay(self, seconds: int) -> None:
        """Hide briefly, then auto-restore. Handy for screenshots / video calls."""
        if not self.overlay.is_active:
            messagebox.showinfo("EaseView",
                                "The overlay is not active, nothing to pause.")
            return
        if getattr(self, '_pause_after_id', None):
            try:
                self.root.after_cancel(self._pause_after_id)
            except Exception:
                pass
        self.overlay.hide(use_fade=False)
        if self.toggle_button:
            self.toggle_button.set_state(False)
        self.tray.update_color(self._current_color_hex())
        self.tray.rebuild_menu()
        logger.info(f"Overlay paused for {seconds}s")
        self._pause_after_id = self.root.after(
            int(seconds * 1000), self._resume_after_pause)

    def _resume_after_pause(self) -> None:
        self._pause_after_id = None
        # If the user toggled off during the pause, leave it off.
        if not self.settings.get('overlay_enabled', False):
            color = self.current_color()
            if not color:
                return
            self.apply_overlay(color)
        else:
            self.overlay.show()
            if self.toggle_button:
                self.toggle_button.set_state(True)
            self.tray.update_color(self._current_color_hex())
            self.tray.rebuild_menu()

    def _restore_overlay_state(self) -> None:
        try:
            if not self.settings.get('overlay_enabled', False):
                return
            color = self.current_color()
            if not color:
                return
            opacity = float(self.settings.get('opacity', 0.3))
            density = float(self.settings.get('density', 1.0))
            if self.overlay.create(color, opacity, density):
                if self.toggle_button:
                    self.toggle_button.set_state(True)
                self.tray.update_color(color)
        except Exception as exc:
            logger.error(f"Failed to restore overlay state: {exc}")

    def show_window(self) -> None:
        try:
            self.root.deiconify()
            self.root.state('normal')
            self.root.lift()
            self.root.focus_force()
            # Briefly topmost, then drop it so it doesn't stick.
            self.root.attributes('-topmost', True)
            self.root.after(120, lambda: self.root.attributes('-topmost', False))
        except Exception as exc:
            logger.warning(f"Failed to show window: {exc}")

    def _on_window_close(self) -> None:
        if self.settings.get('close_to_tray', True):
            self._hide_to_tray()
        else:
            self.quit_app()

    def _hide_to_tray(self) -> None:
        try:
            self.tray.create(self._current_color_hex())
            self.root.withdraw()
            if self.settings.get('enable_notifications', True):
                logger.info("Hidden to tray")
        except Exception as exc:
            logger.warning(f"Hide to tray failed: {exc}")

    def _on_window_map(self, _event: Optional[tk.Event] = None) -> None:
        # Refresh tray on restore from minimised state.
        try:
            if self.root.state() == 'normal':
                self.tray.update_color(self._current_color_hex())
        except Exception:
            pass

    def quit_app(self) -> None:
        logger.info("EaseView shutting down")
        try:
            self.hotkey_manager.stop()
        except Exception:
            pass
        try:
            self.schedule_manager.stop()
        except Exception:
            pass
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.overlay.destroy()
        except Exception:
            pass
        try:
            self.settings.save_pending()
            self.settings.save()
        except Exception:
            pass
        InstanceLocker.release_lock()
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass
        try:
            logger.stop()
        except Exception:
            pass
        # os._exit skips daemon-thread shutdown which sometimes blocks on Windows.
        os._exit(0)

    def load_profile_by_name(self, name: str) -> None:
        if self.settings.load_profile(name):
            self.active_preset = self.settings.get('preset_name')
            self.custom_color = self.settings.get('custom_color')
            self._update_selection_ui()
            if hasattr(self, 'opacity_var'):
                self.opacity_var.set(self.settings.get('opacity', 0.3) * 100)
            if hasattr(self, 'density_var'):
                self.density_var.set(self.settings.get('density', 1.0) * 100)
            if self.settings.get('overlay_enabled'):
                color = self.current_color()
                if color:
                    self.apply_overlay(color)
            messagebox.showinfo("EaseView", f"Profile '{name}' loaded.")
        else:
            messagebox.showerror("EaseView", f"Failed to load profile '{name}'.")

    def _save_profile_dialog(self) -> None:
        name = simpledialog.askstring("Save profile", "Profile name:",
                                       parent=self.root)
        if not name:
            return
        if self.settings.save_profile(name):
            messagebox.showinfo("EaseView", f"Profile '{name}' saved.")
            self.tray.rebuild_menu()
        else:
            messagebox.showerror("EaseView",
                                 "Could not save profile.\n"
                                 "Use letters, numbers, dashes or spaces only.")

    def _load_profile_dialog(self) -> None:
        profiles = self.settings.list_profiles()
        if not profiles:
            messagebox.showinfo("EaseView", "No saved profiles found.")
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Load profile")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("320x360")
        tk.Label(dlg, text="Select a profile:", font=self.fonts['section']
                 ).pack(pady=10)
        lb = tk.Listbox(dlg, height=14)
        lb.pack(fill=tk.BOTH, expand=True, padx=10)
        for p in profiles:
            lb.insert(tk.END, p)

        def do_load():
            sel = lb.curselection()
            if not sel:
                return
            name = lb.get(sel[0])
            dlg.destroy()
            self.load_profile_by_name(name)

        bar = tk.Frame(dlg)
        bar.pack(fill=tk.X, pady=8, padx=10)
        tk.Button(bar, text="Load", command=do_load).pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT)

    def _manage_profiles_dialog(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("Manage profiles")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("360x400")
        tk.Label(dlg, text="Saved profiles:", font=self.fonts['section']
                 ).pack(pady=10)
        lb = tk.Listbox(dlg, height=14)
        lb.pack(fill=tk.BOTH, expand=True, padx=10)
        for p in self.settings.list_profiles():
            lb.insert(tk.END, p)

        def do_delete():
            sel = lb.curselection()
            if not sel:
                return
            name = lb.get(sel[0])
            if messagebox.askyesno("Confirm", f"Delete profile '{name}'?"):
                if self.settings.delete_profile(name):
                    lb.delete(sel[0])
                    self.tray.rebuild_menu()
                else:
                    messagebox.showerror("EaseView", "Delete failed.")

        bar = tk.Frame(dlg)
        bar.pack(fill=tk.X, pady=8, padx=10)
        tk.Button(bar, text="Delete", command=do_delete).pack(side=tk.LEFT)
        tk.Button(bar, text="Close", command=dlg.destroy).pack(side=tk.RIGHT)

    def _reset_to_defaults(self) -> None:
        if not messagebox.askyesno(
                "Reset EaseView",
                "Reset ALL settings, hotkeys, and the overlay to defaults?\n\n"
                "Saved profiles are kept. The overlay will be hidden."):
            return
        try:
            self.overlay.destroy()
            self.settings.settings = SettingsManager._deep_copy(
                SettingsManager.DEFAULT_SETTINGS)
            self.settings.save()
            self.active_preset = None
            self.custom_color = None
            self._update_selection_ui()
            if hasattr(self, 'opacity_var'):
                self.opacity_var.set(self.settings.get('opacity', 0.3) * 100)
            if hasattr(self, 'density_var'):
                self.density_var.set(self.settings.get('density', 1.0) * 100)
            if self.toggle_button:
                self.toggle_button.set_state(False)
            self.tray.update_color(None)
            self.tray.rebuild_menu()
            messagebox.showinfo("EaseView", "Settings reset to defaults.")
            logger.info("Settings reset to defaults by user")
        except Exception as exc:
            logger.error(f"Reset to defaults failed: {exc}")
            messagebox.showerror("EaseView", f"Reset failed: {exc}")

    def _export_settings(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".json", title="Export settings",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            parent=self.root)
        if not path: return
        if self.settings.export_settings(path):
            messagebox.showinfo("EaseView", f"Settings exported to:\n{path}")
        else:
            messagebox.showerror("EaseView", "Failed to export settings.")

    def _import_settings(self) -> None:
        if not messagebox.askyesno("EaseView",
                                    "Importing will replace your current settings.\n"
                                    "Continue?"):
            return
        path = filedialog.askopenfilename(
            defaultextension=".json", title="Import settings",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            parent=self.root)
        if not path: return
        if self.settings.import_settings(path):
            messagebox.showinfo("EaseView",
                                "Settings imported successfully.\n"
                                "Some changes need a restart to take effect.")
            self.active_preset = self.settings.get('preset_name')
            self.custom_color = self.settings.get('custom_color')
            self._update_selection_ui()
        else:
            messagebox.showerror("EaseView", "Failed to import settings.")

    def _startup_options(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("Startup options")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("360x250")

        auto_v   = tk.BooleanVar(value=self.settings.get('auto_startup', False))
        min_v    = tk.BooleanVar(value=self.settings.get('start_minimized', False))
        min_tray = tk.BooleanVar(value=self.settings.get('minimize_to_tray', True))
        close_tray = tk.BooleanVar(value=self.settings.get('close_to_tray', True))

        for var, text in (
            (auto_v,   "Start EaseView with Windows"),
            (min_v,    "Start minimised (hide to tray on launch)"),
            (min_tray, "Minimise hides to tray"),
            (close_tray, "Close button (X) hides to tray"),
        ):
            tk.Checkbutton(dlg, text=text, variable=var,
                           font=self.fonts['body']).pack(anchor='w', padx=20, pady=4)

        def save():
            self.settings.set('auto_startup',     auto_v.get(), save_immediately=False)
            self.settings.set('start_minimized',  min_v.get(),  save_immediately=False)
            self.settings.set('minimize_to_tray', min_tray.get(), save_immediately=False)
            self.settings.set('close_to_tray',    close_tray.get(), save_immediately=False)
            self.settings.save()
            WindowsIntegration.set_startup(auto_v.get(), min_v.get())
            messagebox.showinfo("EaseView", "Startup settings saved.")
            dlg.destroy()

        bar = tk.Frame(dlg)
        bar.pack(fill=tk.X, pady=8, padx=10, side=tk.BOTTOM)
        tk.Button(bar, text="Save", command=save).pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT)

    def _hotkey_settings(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("Hotkey settings")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("520x430")

        tk.Label(dlg, justify='left', wraplength=480,
                 font=self.fonts['body'],
                 text=("In-window shortcuts (Ctrl+Shift+O, Esc, Ctrl+Shift+arrows) "
                       "always work when EaseView is focused. They need no extras.\n\n"
                       "Global system-wide hotkeys (active even when EaseView is "
                       "not focused) require the 'keyboard' package and admin "
                       "privileges on Windows. They are OFF by default.")
                 ).pack(anchor='w', padx=12, pady=(12, 8))

        global_v = tk.BooleanVar(
            value=self.settings.get('enable_global_hotkeys', False))

        global_chk = tk.Checkbutton(
            dlg, text="Enable global system-wide hotkeys"
                     + ("" if KEYBOARD_AVAILABLE
                        else "  (install the 'keyboard' package first)"),
            variable=global_v, font=self.fonts['body'])
        global_chk.pack(anchor='w', padx=12)
        if not KEYBOARD_AVAILABLE:
            global_chk.configure(state='disabled')
            global_v.set(False)

        tk.Label(dlg, text="Format: 'ctrl', 'shift', 'alt' joined by '+'.\n"
                            "Example: ctrl+shift+o",
                 font=self.fonts['subtitle'], justify='left',
                 fg=self.colours['text_secondary'],
                 bg=dlg.cget('bg')
                 ).pack(anchor='w', padx=12, pady=(6, 4))

        rows = (
            ('toggle',           "Toggle overlay"),
            ('increase_opacity', "Increase strength"),
            ('decrease_opacity', "Decrease strength"),
            ('increase_density', "Increase density"),
            ('decrease_density', "Decrease density"),
        )
        entries: Dict[str, tk.StringVar] = {}
        body = tk.Frame(dlg)
        body.pack(fill=tk.X, padx=12, pady=4)
        current = self.settings.get('hotkeys', {})
        for r, (key, label) in enumerate(rows):
            tk.Label(body, text=label, font=self.fonts['body']
                     ).grid(row=r, column=0, sticky='w', pady=4)
            v = tk.StringVar(value=current.get(key, ''))
            entries[key] = v
            entry = tk.Entry(body, textvariable=v, width=24)
            entry.grid(row=r, column=1, sticky='ew', padx=8)
            if not KEYBOARD_AVAILABLE:
                entry.configure(state='disabled')
        body.grid_columnconfigure(1, weight=1)

        def save():
            new_map: Dict[str, str] = {}
            for k, v in entries.items():
                norm = HotkeyManager.tk_to_keyboard(v.get().strip())
                if norm:
                    new_map[k] = norm
            self.settings.set('hotkeys', new_map, save_immediately=False)
            self.settings.set('enable_global_hotkeys', global_v.get())
            for name in list(self.hotkey_manager.registered):
                self.hotkey_manager.unregister(name)
            self._setup_hotkeys_from_settings()
            messagebox.showinfo("EaseView",
                                "Hotkey settings saved.\n"
                                "In-window shortcuts work immediately; "
                                "global hotkeys may require admin privileges.")
            dlg.destroy()

        bar = tk.Frame(dlg)
        bar.pack(fill=tk.X, pady=10, padx=12, side=tk.BOTTOM)
        tk.Button(bar, text="Save", command=save).pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT)

    def _schedule_settings(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("Schedule overlay")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("440x420")

        sch = self.settings.get('schedule', {})
        enabled_v   = tk.BooleanVar(value=sch.get('enabled', False))
        mode_v      = tk.StringVar(value=sch.get('mode', 'fixed'))
        start_v     = tk.StringVar(value=sch.get('start_time', '09:00'))
        end_v       = tk.StringVar(value=sch.get('end_time', '17:00'))
        loc = sch.get('location', {})
        lat_v = tk.DoubleVar(value=loc.get('latitude', 55.9533))
        lon_v = tk.DoubleVar(value=loc.get('longitude', -3.1883))
        tz_v  = tk.StringVar(value=loc.get('timezone', 'Europe/London'))

        tk.Checkbutton(dlg, text="Enable scheduled overlay", variable=enabled_v,
                       font=self.fonts['body']).pack(anchor='w', padx=14, pady=6)
        mode_frame = tk.LabelFrame(dlg, text="Mode")
        mode_frame.pack(fill=tk.X, padx=12, pady=6)
        tk.Radiobutton(mode_frame, text="Fixed times (overnight supported)",
                       variable=mode_v, value='fixed').pack(anchor='w', padx=8, pady=2)
        sunset_btn = tk.Radiobutton(mode_frame, text="Sunset to sunrise (uses location)",
                                     variable=mode_v, value='sunset')
        sunset_btn.pack(anchor='w', padx=8, pady=2)
        if not ASTRAL_AVAILABLE:
            sunset_btn.configure(state='disabled')
            tk.Label(mode_frame, text="Install 'astral' to enable sunset mode.",
                     font=self.fonts['footer']).pack(anchor='w', padx=8)

        tf = tk.LabelFrame(dlg, text="Fixed times")
        tf.pack(fill=tk.X, padx=12, pady=6)
        tk.Label(tf, text="Start (HH:MM):", font=self.fonts['body']
                 ).grid(row=0, column=0, padx=6, pady=4, sticky='w')
        tk.Entry(tf, textvariable=start_v, width=10).grid(row=0, column=1, padx=6)
        tk.Label(tf, text="End (HH:MM):", font=self.fonts['body']
                 ).grid(row=0, column=2, padx=6, pady=4, sticky='w')
        tk.Entry(tf, textvariable=end_v, width=10).grid(row=0, column=3, padx=6)

        lf = tk.LabelFrame(dlg, text="Location (for sunset mode)")
        lf.pack(fill=tk.X, padx=12, pady=6)
        for r, (label, var) in enumerate((("Latitude:", lat_v),
                                          ("Longitude:", lon_v),
                                          ("Timezone:", tz_v))):
            tk.Label(lf, text=label, font=self.fonts['body']
                     ).grid(row=r, column=0, padx=6, pady=2, sticky='w')
            tk.Entry(lf, textvariable=var, width=20).grid(row=r, column=1,
                                                          padx=6, pady=2, sticky='w')

        def save():
            try:
                if mode_v.get() == 'fixed':
                    dt_time.fromisoformat(start_v.get())
                    dt_time.fromisoformat(end_v.get())
            except ValueError:
                messagebox.showerror("EaseView", "Invalid time. Use HH:MM (24-hour).")
                return
            self.settings.set('schedule', {
                'enabled': enabled_v.get(),
                'mode': mode_v.get(),
                'start_time': start_v.get(),
                'end_time': end_v.get(),
                'location': {
                    'latitude': float(lat_v.get()),
                    'longitude': float(lon_v.get()),
                    'timezone': str(tz_v.get()),
                },
            })
            self.schedule_manager.stop()
            if enabled_v.get():
                self.schedule_manager.start()
            messagebox.showinfo("EaseView", "Schedule saved.")
            dlg.destroy()

        bar = tk.Frame(dlg)
        bar.pack(fill=tk.X, pady=8, padx=12, side=tk.BOTTOM)
        tk.Button(bar, text="Save", command=save).pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT)

    def _accessibility_settings(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("Accessibility")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("400x320")

        acc = self.settings.get('accessibility', {})
        scale_v = tk.DoubleVar(value=acc.get('font_scale', 1.0))
        high_v  = tk.BooleanVar(value=acc.get('high_contrast', False))
        fade_v  = tk.BooleanVar(value=self.settings.get('enable_fade', True))
        notif_v = tk.BooleanVar(value=self.settings.get('enable_notifications', True))
        upd_v   = tk.BooleanVar(value=self.settings.get('check_updates_on_startup', True))
        pre_v   = tk.BooleanVar(value=self.settings.get('include_prereleases', False))

        scale_label = tk.Label(dlg, text=f"Font scale: {scale_v.get():.1f}x",
                                font=self.fonts['body'])
        scale_label.pack(pady=(10, 0))
        tk.Scale(dlg, from_=0.8, to=2.0, resolution=0.1, orient=tk.HORIZONTAL,
                 variable=scale_v,
                 command=lambda v: scale_label.config(text=f"Font scale: {float(v):.1f}x")
                 ).pack(fill=tk.X, padx=24)
        tk.Checkbutton(dlg, text="High contrast mode (uses dark palette)",
                       variable=high_v, font=self.fonts['body']
                       ).pack(anchor='w', padx=20, pady=4)
        tk.Checkbutton(dlg, text="Enable fade animations", variable=fade_v,
                       font=self.fonts['body']).pack(anchor='w', padx=20, pady=4)
        tk.Checkbutton(dlg, text="Enable in-app notifications", variable=notif_v,
                       font=self.fonts['body']).pack(anchor='w', padx=20, pady=4)
        tk.Checkbutton(dlg, text="Check for updates on startup", variable=upd_v,
                       font=self.fonts['body']).pack(anchor='w', padx=20, pady=4)
        tk.Checkbutton(dlg, text="Include pre-releases when checking updates",
                       variable=pre_v, font=self.fonts['body']
                       ).pack(anchor='w', padx=20, pady=4)

        def save():
            self.settings.set('accessibility',
                              {'high_contrast': high_v.get(),
                               'font_scale': scale_v.get()},
                              save_immediately=False)
            self.settings.set('enable_fade', fade_v.get(), save_immediately=False)
            self.settings.set('enable_notifications', notif_v.get(), save_immediately=False)
            self.settings.set('check_updates_on_startup', upd_v.get(), save_immediately=False)
            self.settings.set('include_prereleases', pre_v.get(), save_immediately=False)
            self.settings.save()
            self.overlay.enable_fade = fade_v.get()
            messagebox.showinfo("EaseView",
                                "Settings saved. Font scaling takes effect after restart.")
            dlg.destroy()

        bar = tk.Frame(dlg)
        bar.pack(fill=tk.X, pady=8, padx=12, side=tk.BOTTOM)
        tk.Button(bar, text="Save", command=save).pack(side=tk.RIGHT, padx=4)
        tk.Button(bar, text="Cancel", command=dlg.destroy).pack(side=tk.RIGHT)

    def check_updates_async(self, manual: bool) -> None:
        if not REQUESTS_AVAILABLE:
            if manual:
                messagebox.showinfo("EaseView",
                                    "Update checks require the 'requests' package.\n"
                                    "Install with: pip install requests")
            return

        include_pre = bool(self.settings.get('include_prereleases', False))
        skip_version = self.settings.get('skipped_version', '')

        def worker():
            try:
                result = UpdateChecker.check(VERSION, include_prereleases=include_pre)
            except Exception as exc:
                logger.warning(f"Update check exception: {exc}")
                result = None
            self.root.after(0, lambda: self._on_update_result(result, manual,
                                                                skip_version))

        threading.Thread(target=worker, daemon=True,
                         name="EaseViewUpdate").start()

    def _on_update_result(self, result: Optional[Dict[str, Any]],
                          manual: bool, skip_version: str) -> None:
        if result is None:
            if manual:
                messagebox.showwarning(
                    "EaseView",
                    "Could not contact the update server.\n"
                    "Please check your internet connection and try again.")
            return
        if not result.get('available'):
            if manual:
                messagebox.showinfo("EaseView",
                                    f"You are running the latest version ({VERSION}).")
            return
        new_v = result['latest_version']
        if not manual and new_v == skip_version:
            return
        if self.update_banner is not None:
            self.update_banner.show_for(new_v, result.get('url', ''), VERSION)
            self.update_banner.pack(fill=tk.X)
        if manual:
            if messagebox.askyesno(
                "Update available",
                f"EaseView v{new_v} is available "
                f"(you have v{VERSION}).\n\nOpen the download page?"):
                try:
                    import webbrowser
                    webbrowser.open(result.get('url', ''), new=2)
                except Exception:
                    pass

    def _on_update_skipped(self, version: str) -> None:
        self.settings.set('skipped_version', version)
        logger.info(f"User skipped version {version}")

    def show_about(self) -> None:
        messagebox.showinfo(
            "About EaseView",
            f"EaseView - Screen Colour Overlay\n\n"
            f"Version {VERSION}\n"
            f"Portable mode: {'yes' if PORTABLE_MODE else 'no'}\n"
            f"Dark mode: {'yes' if WindowsIntegration.is_dark_mode() else 'no'}\n\n"
            f"Project: https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}\n"
            f"Contact: Ross.paxton@south-ayrshire.gov.uk")

    def show_help(self) -> None:
        messagebox.showinfo(
            "How to use EaseView",
            "1. Pick a colour from the list (or click 'Choose custom colour').\n"
            "2. Adjust 'Overlay strength' for transparency.\n"
            "3. Adjust 'Colour density' for vibrancy.\n"
            "4. Use the toggle, the tray icon, or Ctrl+Shift+O to enable.\n"
            "5. Press Esc at any time to instantly hide the overlay.\n\n"
            "EaseView remembers your settings across sessions and across "
            "monitor changes.")

    def show_shortcuts(self) -> None:
        messagebox.showinfo(
            "Keyboard shortcuts",
            "Inside EaseView window:\n"
            "  Ctrl+Shift+O   Toggle overlay\n"
            "  Ctrl+Shift+↑/↓ Increase/decrease strength\n"
            "  Ctrl+Shift+←/→ Decrease/increase density\n"
            "  Esc            Hide overlay immediately\n"
            "  Tab            Move between controls\n"
            "  Enter / Space  Activate focused control\n\n"
            "Global hotkeys can be customised under Settings → Hotkey "
            "settings (requires the 'keyboard' package, admin on Windows).")

    @staticmethod
    def _open_path(path: str) -> None:
        try:
            if os.path.isdir(path):
                target = path
            else:
                target = os.path.dirname(path) or '.'
                if not os.path.exists(path):
                    Path(path).touch(exist_ok=True)
            if os.name == "nt":
                os.startfile(target)  # type: ignore[attr-defined]
            else:
                import webbrowser
                webbrowser.open('file://' + os.path.abspath(target))
        except Exception as exc:
            logger.warning(f"Open path failed: {exc}")

    def run(self) -> None:
        try:
            self.root.mainloop()
        except Exception as exc:
            logger.error(f"Mainloop crash: {exc}\n{traceback.format_exc()}")
            try:
                messagebox.showerror("EaseView - fatal error", str(exc))
            except Exception:
                pass


# --- entry point ------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="EaseView - Screen Colour Overlay")
    p.add_argument("--minimized", "--minimised", action="store_true",
                   dest="minimized", help="Start hidden to the system tray.")
    p.add_argument("--version", action="version",
                   version=f"EaseView {VERSION}")
    args, _ = p.parse_known_args()
    return args


def main() -> int:
    args = parse_args()
    try:
        app = EaseViewApp(args)
        app.run()
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        logger.error(f"Fatal error: {exc}\n{traceback.format_exc()}")
        try:
            tk_root = tk.Tk(); tk_root.withdraw()
            messagebox.showerror("EaseView - fatal error",
                                  f"{exc}\n\nSee log file:\n{LOG_FILE}")
            tk_root.destroy()
        except Exception:
            print(f"Fatal error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
