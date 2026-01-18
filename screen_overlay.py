# ============================================================================
# EaseView - Screen Colour Overlay Tool
# R.Paxton 2025
# ============================================================================

import tkinter as tk
from tkinter import colorchooser, Menu, messagebox, filedialog, ttk, simpledialog
import pystray
from PIL import Image, ImageDraw
import threading
import sys
import ctypes
import os
import json
import queue
import time
import atexit
from datetime import datetime, time as dt_time
from pathlib import Path

# Optional imports with fallbacks
try:
    import win32api
    import win32con
    import winreg
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from win10toast import ToastNotifier
    TOAST_AVAILABLE = True
except ImportError:
    TOAST_AVAILABLE = False

try:
    from astral import LocationInfo
    from astral.sun import sun
    ASTRAL_AVAILABLE = True
except ImportError:
    ASTRAL_AVAILABLE = False

import argparse
import glob
import shutil

# ============================================================================
# DESIGN CONSTANTS
# ============================================================================
# Colour palette - Windows 11 inspired, minimal and calm
COLOURS = {
    'accent': '#0067C0',
    'accent_hover': '#005A9E',
    'background': '#F5F5F5',
    'surface': '#FFFFFF',
    'surface_hover': '#F0F0F0',
    'surface_active': '#E3F2FD',      # Light blue for active selection
    'text_primary': '#202020',
    'text_secondary': '#5C5C5C',
    'border': '#E0E0E0',
    'border_active': '#0067C0',       # Accent border for active item
    'divider': '#E8E8E8',
    'focus': '#0067C0',
    'success': '#107C10',             # For active overlay indicator
    'inactive': '#A0A0A0',
}

# Typography - Segoe UI only
FONTS = {
    'title': ('Segoe UI', 15, 'normal'),
    'subtitle': ('Segoe UI', 9, 'normal'),
    'section': ('Segoe UI', 9, 'normal'),
    'body': ('Segoe UI', 10, 'normal'),
    'button': ('Segoe UI', 10, 'normal'),
    'footer': ('Segoe UI', 8, 'normal'),
}

# Spacing constants
SPACING = {
    'window_padding': 20,
    'section_gap': 16,
    'row_gap': 2,
    'button_padding_x': 14,
    'button_padding_y': 10,
    'colour_indicator_width': 36,
    'active_indicator_width': 4,
}

# Window dimensions
WINDOW = {
    'width': 480,
    'height': 750,
    'min_width': 360,
    'min_height': 560,
}

# Settings
# Check for portable mode
PORTABLE_MODE = os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'portable.ini'))
if PORTABLE_MODE:
    SETTINGS_DIR = os.path.dirname(os.path.abspath(__file__))
else:
    SETTINGS_DIR = os.path.expanduser('~')

SETTINGS_FILE = os.path.join(SETTINGS_DIR, '.easeview_settings.json')
LOG_FILE = os.path.join(SETTINGS_DIR, '.easeview.log')
LOCK_FILE = os.path.join(SETTINGS_DIR, '.easeview.lock')
PROFILES_DIR = os.path.join(SETTINGS_DIR, '.easeview_profiles')
SETTINGS_VERSION = 5  # Incremented for new features
VERSION = "3.0"

# Create profiles directory if needed
os.makedirs(PROFILES_DIR, exist_ok=True)


# ============================================================================
# ASYNC LOGGER
# ============================================================================
class AsyncLogger:
    """Asynchronous file logger to avoid blocking UI."""

    def __init__(self, log_file=LOG_FILE, max_lines=500):
        self.log_file = log_file
        self.max_lines = max_lines
        self.queue = queue.Queue()
        self.running = True
        
        # Start worker thread
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()
        
        # Register cleanup
        atexit.register(self.stop)

    def _worker(self):
        """Worker thread that writes log entries."""
        while self.running:
            try:
                entry = self.queue.get(timeout=1)
                try:
                    with open(self.log_file, 'a', encoding='utf-8') as f:
                        f.write(entry)
                    self._trim_log()
                except Exception:
                    pass  # Logger must never crash the app
                self.queue.task_done()
            except queue.Empty:
                continue

    def log(self, level, message):
        """Queue a log entry (non-blocking)."""
        if not self.running:
            return
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = f"[{timestamp}] [{level}] {message}\n"
            self.queue.put(entry)
        except Exception:
            pass  # Logger must never crash the app

    def error(self, message):
        self.log("ERROR", message)

    def warning(self, message):
        self.log("WARN", message)

    def info(self, message):
        self.log("INFO", message)

    def _trim_log(self):
        """Keep log file manageable."""
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if len(lines) > self.max_lines:
                with open(self.log_file, 'w', encoding='utf-8') as f:
                    f.writelines(lines[-self.max_lines:])
        except Exception:
            pass

    def stop(self):
        """Stop logger and flush queue."""
        self.running = False
        # Wait for queue to empty (with timeout)
        try:
            self.queue.join()
        except Exception:
            pass


# Global logger instance
logger = AsyncLogger()


# ============================================================================
# INSTANCE LOCKER
# ============================================================================
class InstanceLocker:
    """Prevents multiple instances of the application."""
    
    @staticmethod
    def acquire_lock():
        """Try to acquire instance lock. Returns True if successful."""
        try:
            if os.path.exists(LOCK_FILE):
                # Check if process is still alive
                try:
                    with open(LOCK_FILE, 'r') as f:
                        pid = int(f.read().strip())
                    # Try to signal process 0 (check if exists)
                    os.kill(pid, 0)
                    # Process exists, another instance is running
                    return False
                except (OSError, ValueError):
                    # Process doesn't exist or invalid PID, remove stale lock
                    try:
                        os.remove(LOCK_FILE)
                    except Exception:
                        pass
            
            # Create lock file
            with open(LOCK_FILE, 'w') as f:
                f.write(str(os.getpid()))
            return True
        except Exception as e:
            logger.error(f"Failed to acquire lock: {e}")
            return True  # Allow to continue if lock fails
    
    @staticmethod
    def release_lock():
        """Release instance lock."""
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        except Exception:
            pass


# ============================================================================
# MONITOR DETECTION
# ============================================================================
class MonitorDetector:
    """Detects available monitors and their properties."""
    
    @staticmethod
    def get_monitors():
        """Get list of monitors with their dimensions and positions."""
        monitors = []
        
        if WIN32_AVAILABLE:
            try:
                # Use win32api for monitor detection
                for monitor in win32api.EnumDisplayMonitors():
                    device = monitor[0]
                    monitor_info = win32api.GetMonitorInfo(device)
                    rect = monitor_info['Monitor']
                    work_area = monitor_info['Work']
                    monitors.append({
                        'x': rect[0],
                        'y': rect[1],
                        'width': rect[2] - rect[0],
                        'height': rect[3] - rect[1],
                        'work_x': work_area[0],
                        'work_y': work_area[1],
                        'work_width': work_area[2] - work_area[0],
                        'work_height': work_area[3] - work_area[1]
                    })
            except Exception as e:
                logger.warning(f"Failed to enumerate monitors: {e}")
        
        if not monitors:
            # Fallback to single monitor
            try:
                root = tk.Tk()
                root.withdraw()
                width = root.winfo_screenwidth()
                height = root.winfo_screenheight()
                root.destroy()
                monitors.append({
                    'x': 0, 'y': 0,
                    'width': width, 'height': height,
                    'work_x': 0, 'work_y': 0,
                    'work_width': width, 'work_height': height
                })
            except Exception:
                monitors.append({
                    'x': 0, 'y': 0,
                    'width': 1920, 'height': 1080,
                    'work_x': 0, 'work_y': 0,
                    'work_width': 1920, 'work_height': 1080
                })
        
        return monitors


# ============================================================================
# WINDOWS INTEGRATION UTILITIES
# ============================================================================
class WindowsIntegration:
    """Utilities for Windows system integration."""
    
    @staticmethod
    def set_startup(enabled=True):
        """Add or remove application from Windows startup."""
        if not WIN32_AVAILABLE:
            return False
        
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            
            app_name = "EaseView"
            if enabled:
                # Get current executable path
                if getattr(sys, 'frozen', False):
                    exe_path = sys.executable
                else:
                    exe_path = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
                logger.info("Added to Windows startup")
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                    logger.info("Removed from Windows startup")
                except FileNotFoundError:
                    pass  # Already not in startup
            
            winreg.CloseKey(key)
            return True
        except Exception as e:
            logger.error(f"Failed to modify startup: {e}")
            return False
    
    @staticmethod
    def is_startup_enabled():
        """Check if application is in Windows startup."""
        if not WIN32_AVAILABLE:
            return False
        
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, "EaseView")
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False
        except Exception:
            return False
    
    @staticmethod
    def is_dark_mode():
        """Detect if Windows is in dark mode."""
        if not WIN32_AVAILABLE:
            return False
        
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
            value = winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
            winreg.CloseKey(key)
            return value == 0  # 0 = dark mode, 1 = light mode
        except Exception:
            return False
    
    @staticmethod
    def get_windows_colors():
        """Get Windows system colors for theme-aware UI."""
        if not WIN32_AVAILABLE:
            return COLOURS
        
        try:
            dark_mode = WindowsIntegration.is_dark_mode()
            if dark_mode:
                return {
                    'accent': '#0D7BD6',
                    'accent_hover': '#1A8EE6',
                    'background': '#202020',
                    'surface': '#2D2D2D',
                    'surface_hover': '#383838',
                    'surface_active': '#1A3A5C',
                    'text_primary': '#FFFFFF',
                    'text_secondary': '#CCCCCC',
                    'border': '#404040',
                    'border_active': '#0D7BD6',
                    'divider': '#353535',
                    'focus': '#0D7BD6',
                    'success': '#107C10',
                    'inactive': '#707070',
                }
        except Exception:
            pass
        
        return COLOURS  # Return default light theme


# ============================================================================
# HOTKEY MANAGER
# ============================================================================
class HotkeyManager:
    """Manages global hotkey registration and handling."""
    
    def __init__(self, callbacks):
        self.callbacks = callbacks
        self.registered_hotkeys = {}
        self.hotkey_thread = None
        self.running = False
        
        if KEYBOARD_AVAILABLE:
            self._start_hotkey_thread()
    
    def _start_hotkey_thread(self):
        """Start thread for global hotkey detection."""
        if self.running:
            return
        
        self.running = True
        
        def hotkey_thread():
            try:
                while self.running:
                    time.sleep(0.1)  # Check frequently
            except Exception:
                pass
        
        self.hotkey_thread = threading.Thread(target=hotkey_thread, daemon=True)
        self.hotkey_thread.start()
    
    def register_hotkey(self, hotkey_name, hotkey_string, callback):
        """Register a global hotkey."""
        if not KEYBOARD_AVAILABLE:
            return False
        
        try:
            # Unregister existing if any
            if hotkey_name in self.registered_hotkeys:
                self.unregister_hotkey(hotkey_name)
            
            # Register new hotkey
            keyboard.add_hotkey(hotkey_string, callback, suppress=True)
            self.registered_hotkeys[hotkey_name] = (hotkey_string, callback)
            logger.info(f"Registered hotkey: {hotkey_name} = {hotkey_string}")
            return True
        except Exception as e:
            logger.error(f"Failed to register hotkey {hotkey_name}: {e}")
            return False
    
    def unregister_hotkey(self, hotkey_name):
        """Unregister a global hotkey."""
        if hotkey_name not in self.registered_hotkeys:
            return
        
        try:
            hotkey_string, callback = self.registered_hotkeys[hotkey_name]
            keyboard.remove_hotkey(hotkey_string)
            del self.registered_hotkeys[hotkey_name]
            logger.info(f"Unregistered hotkey: {hotkey_name}")
        except Exception as e:
            logger.error(f"Failed to unregister hotkey {hotkey_name}: {e}")
    
    def register_all(self, hotkeys_dict):
        """Register multiple hotkeys from dictionary."""
        for name, hotkey_string in hotkeys_dict.items():
            if name in self.callbacks:
                self.register_hotkey(name, hotkey_string, self.callbacks[name])
    
    def stop(self):
        """Stop hotkey manager and unregister all."""
        self.running = False
        for hotkey_name in list(self.registered_hotkeys.keys()):
            self.unregister_hotkey(hotkey_name)


# ============================================================================
# UPDATE CHECKER
# ============================================================================
class UpdateChecker:
    """Check for application updates."""
    
    # Update this URL to point to your version endpoint
    VERSION_URL = "https://api.github.com/repos/yourusername/easeview/releases/latest"
    
    @staticmethod
    def check_for_updates(current_version=VERSION):
        """Check for available updates."""
        if not REQUESTS_AVAILABLE:
            return None
        
        try:
            response = requests.get(UpdateChecker.VERSION_URL, timeout=5)
            if response.status_code == 200:
                data = response.json()
                latest_version = data.get('tag_name', '').lstrip('v')
                if latest_version and latest_version != current_version:
                    return {
                        'available': True,
                        'latest_version': latest_version,
                        'current_version': current_version,
                        'url': data.get('html_url', '')
                    }
        except Exception as e:
            logger.warning(f"Update check failed: {e}")
        
        return None


# ============================================================================
# SCHEDULE MANAGER
# ============================================================================
class ScheduleManager:
    """Manages scheduled overlay enable/disable."""
    
    def __init__(self, app):
        self.app = app
        self.schedule_thread = None
        self.running = False
    
    def start(self):
        """Start schedule monitoring."""
        if self.running:
            return
        
        schedule = self.app.settings.get('schedule', {})
        if not schedule.get('enabled', False):
            return
        
        self.running = True
        
        def schedule_loop():
            while self.running:
                try:
                    schedule = self.app.settings.get('schedule', {})
                    if not schedule.get('enabled', False):
                        self.running = False
                        break
                    
                    now = datetime.now().time()
                    start_time = dt_time.fromisoformat(schedule.get('start_time', '09:00'))
                    end_time = dt_time.fromisoformat(schedule.get('end_time', '17:00'))
                    
                    # Enable overlay if within scheduled time
                    if start_time <= now <= end_time:
                        if not self.app.overlay.is_active and self.app.overlay.current_color:
                            self.app.root.after(0, self.app.overlay.show)
                    else:
                        # Disable overlay if outside scheduled time
                        if self.app.overlay.is_active:
                            self.app.root.after(0, self.app.overlay.hide)
                    
                    time.sleep(60)  # Check every minute
                    
                except Exception as e:
                    logger.error(f"Schedule loop error: {e}")
                    time.sleep(60)
        
        self.schedule_thread = threading.Thread(target=schedule_loop, daemon=True)
        self.schedule_thread.start()
    
    def stop(self):
        """Stop schedule monitoring."""
        self.running = False


# ============================================================================
# SETTINGS MANAGER
# ============================================================================
class SettingsManager:
    """Handles persistent settings with validation and versioning."""

    DEFAULT_SETTINGS = {
        'version': SETTINGS_VERSION,
        'preset_name': None,
        'custom_color': None,
        'opacity': 0.3,
        'density': 1.0,
        'overlay_enabled': False,
        'recent_colors': [],  # Max 10 recent custom colors
        'window_geometry': {
            'x': None, 'y': None,
            'width': WINDOW['width'],
            'height': WINDOW['height']
        },
        'hotkeys': {
            'toggle': 'Control+Shift+O',
            'increase_opacity': 'Control+Shift+Up',
            'decrease_opacity': 'Control+Shift+Down',
            'increase_density': 'Control+Shift+Right',
            'decrease_density': 'Control+Shift+Left',
        },
        'auto_startup': False,
        'start_minimized': False,
        'enable_notifications': True,
        'enable_fade': True,
        'schedule': {
            'enabled': False,
            'start_time': '09:00',
            'end_time': '17:00',
            'use_sunset': False,  # Use sunset/sunrise instead of fixed times
            'location': {
                'latitude': 55.9533,  # Edinburgh default
                'longitude': -3.1883,
                'timezone': 'Europe/London'
            }
        },
        'accessibility': {
            'high_contrast': False,
            'font_scale': 1.0
        },
        'current_profile': None,
        'auto_backup': True,  # Enable automatic backups
        'backup_interval_hours': 24  # Backup every 24 hours
    }

    def __init__(self, settings_file=SETTINGS_FILE):
        self.settings_file = settings_file
        self.settings = self.DEFAULT_SETTINGS.copy()
        self._save_pending = False
        self.load()

    def load(self):
        """Load and validate settings from file."""
        try:
            if not os.path.exists(self.settings_file):
                logger.info("No settings file found, using defaults")
                return

            with open(self.settings_file, 'r', encoding='utf-8') as f:
                loaded = json.load(f)

            # Version migration
            file_version = loaded.get('version', 1)
            if file_version < SETTINGS_VERSION:
                loaded = self._migrate_settings(loaded, file_version)

            # Validate and apply
            self._validate_and_apply(loaded)
            logger.info("Settings loaded successfully")

        except json.JSONDecodeError as e:
            logger.error(f"Corrupted settings file: {e}")
            self._backup_and_reset()
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")

    def _migrate_settings(self, settings, from_version):
        """Migrate old settings format to current."""
        if from_version == 1:
            # v1 had 'last_color' instead of 'preset_name'/'custom_color'
            old_color = settings.get('last_color')
            if old_color:
                settings['custom_color'] = old_color
            settings['preset_name'] = None
        if from_version < 3:
            # v3 adds density setting
            settings['density'] = 1.0
        if from_version < 4:
            # v4 adds new features
            settings.setdefault('window_geometry', {
                'x': None, 'y': None,
                'width': WINDOW['width'],
                'height': WINDOW['height']
            })
            settings.setdefault('hotkeys', self.DEFAULT_SETTINGS['hotkeys'].copy())
            settings.setdefault('auto_startup', False)
            settings.setdefault('schedule', self.DEFAULT_SETTINGS['schedule'].copy())
            settings.setdefault('accessibility', self.DEFAULT_SETTINGS['accessibility'].copy())
            settings.setdefault('current_profile', None)
        if from_version < 5:
            # v5 adds new features
            settings.setdefault('recent_colors', [])
            settings.setdefault('start_minimized', False)
            settings.setdefault('enable_notifications', True)
            settings.setdefault('enable_fade', True)
            if 'schedule' in settings:
                settings['schedule'].setdefault('use_sunset', False)
                settings['schedule'].setdefault('location', self.DEFAULT_SETTINGS['schedule']['location'].copy())
            settings.setdefault('auto_backup', True)
            settings.setdefault('backup_interval_hours', 24)
        settings['version'] = SETTINGS_VERSION
        logger.info(f"Migrated settings from v{from_version} to v{SETTINGS_VERSION}")
        return settings

    def _validate_and_apply(self, loaded):
        """Validate loaded settings and apply safe values."""
        # Opacity: clamp to valid range
        opacity = loaded.get('opacity', 0.3)
        if isinstance(opacity, (int, float)):
            self.settings['opacity'] = max(0.1, min(0.6, float(opacity)))

        # Density: clamp to valid range (0.5 to 1.5)
        density = loaded.get('density', 1.0)
        if isinstance(density, (int, float)):
            self.settings['density'] = max(0.5, min(1.5, float(density)))

        # Preset name
        preset = loaded.get('preset_name')
        if preset is None or isinstance(preset, str):
            self.settings['preset_name'] = preset

        # Custom color: validate hex format
        custom = loaded.get('custom_color')
        if custom is None or (isinstance(custom, str) and custom.startswith('#')):
            self.settings['custom_color'] = custom

        # Overlay enabled state
        self.settings['overlay_enabled'] = bool(loaded.get('overlay_enabled', False))

    def _backup_and_reset(self):
        """Backup corrupted settings and reset to defaults."""
        try:
            backup_path = self.settings_file + '.backup'
            if os.path.exists(self.settings_file):
                os.rename(self.settings_file, backup_path)
                logger.warning(f"Backed up corrupted settings to {backup_path}")
        except Exception as e:
            logger.error(f"Failed to backup settings: {e}")
        self.settings = self.DEFAULT_SETTINGS.copy()

    def save(self):
        """Save current settings to file."""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
            self._save_pending = False
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value, save_immediately=True):
        """Set a setting value. Set save_immediately=False for batch updates."""
        self.settings[key] = value
        self._save_pending = True
        if save_immediately:
            self.save()
    
    def save_pending(self):
        """Save if there are pending changes."""
        if self._save_pending:
            self.save()
    
    def export_settings(self, filepath):
        """Export current settings to a file."""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
            logger.info(f"Settings exported to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export settings: {e}")
            return False
    
    def import_settings(self, filepath):
        """Import settings from a file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            
            # Validate imported settings
            file_version = loaded.get('version', 1)
            if file_version < SETTINGS_VERSION:
                loaded = self._migrate_settings(loaded, file_version)
            
            self._validate_and_apply(loaded)
            self.save()
            logger.info(f"Settings imported from {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to import settings: {e}")
            return False
    
    def save_profile(self, profile_name, profile_data=None):
        """Save current settings as a profile."""
        try:
            if profile_data is None:
                profile_data = self.settings.copy()
            
            profile_path = os.path.join(PROFILES_DIR, f"{profile_name}.json")
            with open(profile_path, 'w', encoding='utf-8') as f:
                json.dump(profile_data, f, indent=2)
            logger.info(f"Profile saved: {profile_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save profile: {e}")
            return False
    
    def load_profile(self, profile_name):
        """Load a profile and apply settings."""
        try:
            profile_path = os.path.join(PROFILES_DIR, f"{profile_name}.json")
            if not os.path.exists(profile_path):
                logger.error(f"Profile not found: {profile_name}")
                return False
            
            with open(profile_path, 'r', encoding='utf-8') as f:
                profile_data = json.load(f)
            
            # Validate and apply
            file_version = profile_data.get('version', 1)
            if file_version < SETTINGS_VERSION:
                profile_data = self._migrate_settings(profile_data, file_version)
            
            self._validate_and_apply(profile_data)
            self.set('current_profile', profile_name, save_immediately=False)
            self.save()
            logger.info(f"Profile loaded: {profile_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to load profile: {e}")
            return False
    
    def list_profiles(self):
        """List all available profiles."""
        try:
            profiles = []
            for filename in os.listdir(PROFILES_DIR):
                if filename.endswith('.json'):
                    profile_name = filename[:-5]  # Remove .json
                    profiles.append(profile_name)
            return sorted(profiles)
        except Exception as e:
            logger.error(f"Failed to list profiles: {e}")
            return []
    
    def delete_profile(self, profile_name):
        """Delete a profile."""
        try:
            profile_path = os.path.join(PROFILES_DIR, f"{profile_name}.json")
            if os.path.exists(profile_path):
                os.remove(profile_path)
                logger.info(f"Profile deleted: {profile_name}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete profile: {e}")
            return False


# ============================================================================
# OVERLAY MANAGER
# ============================================================================
class OverlayManager:
    """Manages the fullscreen overlay window lifecycle with multi-monitor support."""

    def __init__(self, root):
        self.root = root
        self.overlay_windows = []  # List of overlay windows for multi-monitor
        self.is_active = False
        self.current_color = None
        self.current_opacity = 0.3
        self.current_density = 1.0
        self.monitoring = False
        self.monitor_thread = None
        self.fade_animation_id = None
        self.enable_fade = True

    def create(self, color, opacity, density=1.0):
        """Create or update the overlay windows for all monitors."""
        self.current_color = color
        self.current_opacity = opacity
        self.current_density = density

        # Destroy existing overlays
        self.destroy()

        try:
            # Get all monitors
            monitors = MonitorDetector.get_monitors()
            if not monitors:
                logger.error("No monitors detected")
                return False

            # Create overlay for each monitor
            for monitor in monitors:
                try:
                    overlay = tk.Toplevel(self.root)
                    
                    # Position and size for this monitor
                    overlay.geometry(f"{monitor['width']}x{monitor['height']}+{monitor['x']}+{monitor['y']}")
                    overlay.attributes('-topmost', True)
                    overlay.attributes('-alpha', opacity)
                    overlay.overrideredirect(True)

                    # Apply density-adjusted color
                    adjusted_color = self._apply_density(color, density)
                    overlay.configure(bg=adjusted_color)

                    # Make click-through
                    overlay.update()
                    success = self._make_click_through(overlay)

                    if not success:
                        logger.warning(f"Failed to make overlay click-through for monitor {monitor['x']},{monitor['y']}")
                        try:
                            overlay.destroy()
                        except Exception:
                            pass
                        continue

                    self.overlay_windows.append(overlay)
                    logger.info(f"Overlay created for monitor: {monitor['x']},{monitor['y']} ({monitor['width']}x{monitor['height']})")

                except Exception as e:
                    logger.error(f"Failed to create overlay for monitor {monitor['x']},{monitor['y']}: {e}")

            if not self.overlay_windows:
                logger.error("Failed to create any overlay windows")
                return False

            self.is_active = True
            logger.info(f"Overlay created: {len(self.overlay_windows)} monitors, color={color}, opacity={opacity}, density={density}")
            
            # Start monitoring for window destruction
            self._start_monitoring()
            
            return True

        except Exception as e:
            logger.error(f"Failed to create overlay: {e}")
            self.destroy()
            return False

    def _apply_density(self, hex_color, density):
        """
        Adjust color saturation based on density value.
        Density 0.5 = lighter/less saturated, 1.5 = more saturated/intense.
        """
        try:
            # Parse hex color
            hex_color = hex_color.lstrip('#')
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)

            # Convert to HSL-like adjustment via blending with grey
            # At density 1.0, color is unchanged
            # At density < 1.0, blend toward white (lighter)
            # At density > 1.0, increase saturation toward pure color
            if density < 1.0:
                # Blend toward white
                factor = density
                r = int(r * factor + 255 * (1 - factor))
                g = int(g * factor + 255 * (1 - factor))
                b = int(b * factor + 255 * (1 - factor))
            else:
                # Increase saturation by moving away from grey
                factor = (density - 1.0) * 2  # 0 to 1 for density 1.0 to 1.5
                grey = (r + g + b) // 3
                r = int(r + (r - grey) * factor)
                g = int(g + (g - grey) * factor)
                b = int(b + (b - grey) * factor)

            # Clamp values
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))

            return f'#{r:02x}{g:02x}{b:02x}'
        except Exception as e:
            logger.warning(f"Failed to apply density: {e}")
            return hex_color

    def _make_click_through(self, overlay_window):
        """Make overlay window click-through using Windows API."""
        if not overlay_window:
            return False

        try:
            # Get window handle
            hwnd = overlay_window.winfo_id()
            if not hwnd:
                logger.error("Could not get window handle")
                return False

            # Try getting parent HWND (more reliable for Tk)
            parent_hwnd = ctypes.windll.user32.GetParent(hwnd)
            target_hwnd = parent_hwnd if parent_hwnd else hwnd

            # Set extended window style
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020

            # Clear last error before API call
            ctypes.windll.kernel32.SetLastError(0)
            
            style = ctypes.windll.user32.GetWindowLongW(target_hwnd, GWL_EXSTYLE)
            new_style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            result = ctypes.windll.user32.SetWindowLongW(target_hwnd, GWL_EXSTYLE, new_style)

            # Check for error - SetWindowLongW returns 0 on error, but we need to check GetLastError
            if result == 0:
                error = ctypes.windll.kernel32.GetLastError()
                if error != 0:
                    logger.error(f"SetWindowLongW failed with error code: {error}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Click-through setup failed: {e}")
            return False
    
    def _start_monitoring(self):
        """Start monitoring overlay windows for destruction."""
        if self.monitoring:
            return
        
        self.monitoring = True
        
        def monitor_loop():
            while self.monitoring and self.overlay_windows:
                try:
                    # Check if any overlay was destroyed
                    valid_windows = []
                    for overlay in self.overlay_windows:
                        try:
                            if overlay.winfo_exists():
                                valid_windows.append(overlay)
                            else:
                                logger.warning("Overlay window was destroyed externally")
                        except tk.TclError:
                            logger.warning("Overlay window check failed")
                    
                    # If windows were destroyed and we should be active, recreate
                    if len(valid_windows) < len(self.overlay_windows) and self.is_active and self.current_color:
                        self.overlay_windows = valid_windows
                        if not self.overlay_windows:
                            # All destroyed, recreate
                            logger.info("All overlays destroyed, recreating...")
                            self.root.after(0, lambda: self.create(
                                self.current_color, 
                                self.current_opacity, 
                                self.current_density
                            ))
                    
                    self.overlay_windows = valid_windows
                    time.sleep(1)  # Check every second
                    
                except Exception as e:
                    logger.error(f"Monitor loop error: {e}")
                    time.sleep(1)
        
        self.monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def _stop_monitoring(self):
        """Stop monitoring overlay windows."""
        self.monitoring = False

    def update_opacity(self, opacity):
        """Update overlay opacity for all windows."""
        self.current_opacity = opacity
        if self.overlay_windows and self.is_active:
            for overlay in self.overlay_windows:
                try:
                    overlay.attributes('-alpha', opacity)
                except Exception as e:
                    logger.warning(f"Failed to update opacity: {e}")

    def update_density(self, density):
        """Update overlay density (color intensity) for all windows."""
        self.current_density = density
        if self.overlay_windows and self.is_active and self.current_color:
            adjusted_color = self._apply_density(self.current_color, density)
            for overlay in self.overlay_windows:
                try:
                    overlay.configure(bg=adjusted_color)
                except Exception as e:
                    logger.warning(f"Failed to update density: {e}")

    def show(self, use_fade=None):
        """Show all overlay windows with optional fade animation."""
        if not self.overlay_windows:
            return
        
        if use_fade is None:
            use_fade = self.enable_fade
        
        if use_fade and self.current_opacity > 0:
            self.fade_in()
        else:
            try:
                for overlay in self.overlay_windows:
                    overlay.deiconify()
                    overlay.attributes('-alpha', self.current_opacity)
                self.is_active = True
                if not self.monitoring:
                    self._start_monitoring()
            except Exception as e:
                logger.warning(f"Failed to show overlay: {e}")

    def hide(self, use_fade=None):
        """Hide all overlay windows without destroying them, with optional fade."""
        if not self.overlay_windows:
            return
        
        if use_fade is None:
            use_fade = self.enable_fade
        
        if use_fade and self.is_active:
            self.fade_out()
        else:
            try:
                for overlay in self.overlay_windows:
                    overlay.withdraw()
                self.is_active = False
            except Exception as e:
                logger.warning(f"Failed to hide overlay: {e}")
    
    def fade_in(self, duration=0.3):
        """Fade in overlay smoothly."""
        if not self.overlay_windows:
            return
        
        # Cancel any existing animation
        if self.fade_animation_id:
            self.root.after_cancel(self.fade_animation_id)
        
        steps = max(1, int(duration * 30))  # 30 fps
        target_opacity = self.current_opacity
        
        def animate(step=0):
            if step > steps:
                # Ensure final opacity
                for overlay in self.overlay_windows:
                    try:
                        overlay.attributes('-alpha', target_opacity)
                        overlay.deiconify()
                    except Exception:
                        pass
                self.is_active = True
                if not self.monitoring:
                    self._start_monitoring()
                self.fade_animation_id = None
                return
            
            opacity = (target_opacity * step) / steps
            for overlay in self.overlay_windows:
                try:
                    overlay.attributes('-alpha', opacity)
                    if step == 1:  # Show window on first step
                        overlay.deiconify()
                except Exception:
                    pass
            
            self.fade_animation_id = self.root.after(33, lambda: animate(step + 1))
        
        animate()
    
    def fade_out(self, duration=0.3):
        """Fade out overlay smoothly."""
        if not self.overlay_windows:
            return
        
        # Cancel any existing animation
        if self.fade_animation_id:
            self.root.after_cancel(self.fade_animation_id)
        
        steps = max(1, int(duration * 30))  # 30 fps
        start_opacity = self.current_opacity
        
        def animate(step=0):
            if step > steps:
                # Hide windows
                for overlay in self.overlay_windows:
                    try:
                        overlay.withdraw()
                    except Exception:
                        pass
                self.is_active = False
                self.fade_animation_id = None
                return
            
            opacity = start_opacity * (1 - (step / steps))
            for overlay in self.overlay_windows:
                try:
                    overlay.attributes('-alpha', opacity)
                except Exception:
                    pass
            
            self.fade_animation_id = self.root.after(33, lambda: animate(step + 1))
        
        animate()

    def toggle(self):
        """Toggle overlay visibility."""
        if self.is_active:
            self.hide()
        elif self.overlay_windows:
            self.show()
        return self.is_active

    def destroy(self):
        """Destroy all overlay windows."""
        self._stop_monitoring()
        for overlay in self.overlay_windows:
            try:
                overlay.destroy()
            except Exception:
                pass
        self.overlay_windows = []
        self.is_active = False


# ============================================================================
# TRAY MANAGER
# ============================================================================
class TrayManager:
    """Manages system tray icon and menu."""

    def __init__(self, callbacks):
        self.callbacks = callbacks
        self.icon = None
        self._lock = threading.Lock()
        self._created = False

    def create(self, color=None):
        """Create system tray icon (thread-safe)."""
        with self._lock:
            if self._created:
                return
            self._created = True

        try:
            image = self._create_icon_image(color)
            menu = self._create_menu()

            self.icon = pystray.Icon("easeview", image, "EaseView", menu)

            thread = threading.Thread(target=self.icon.run, daemon=True)
            thread.start()
            logger.info("Tray icon created")

        except Exception as e:
            logger.error(f"Failed to create tray icon: {e}")
            with self._lock:
                self._created = False

    def _create_icon_image(self, color=None):
        """Create tray icon image."""
        # Try loading from file first
        try:
            icon_path = self._get_resource_path('tray_icon.png')
            if os.path.exists(icon_path):
                return Image.open(icon_path)
        except Exception:
            pass

        # Fallback: generate simple icon
        fill_color = color or COLOURS['accent']
        image = Image.new('RGB', (64, 64), fill_color)
        draw = ImageDraw.Draw(image)
        draw.rectangle([4, 4, 60, 60], outline='white', width=3)
        return image

    def _get_resource_path(self, relative_path):
        """Get resource path for PyInstaller compatibility."""
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def _create_menu(self):
        """Create tray menu with quick access features."""
        menu_items = []
        
        # Main actions
        menu_items.append(pystray.MenuItem(
            "Show/Hide Overlay",
            lambda: self.callbacks.get('toggle_overlay', lambda: None)(),
            default=True))
        
        # Quick color switching
        if self.app and hasattr(self.app, 'PRESETS'):
            color_items = []
            for name, data in self.app.PRESETS.items():
                color_items.append(
                    pystray.MenuItem(
                        name,
                        lambda n=name, c=data['color']: self.callbacks.get('select_preset', lambda: None)(n, c)
                    )
                )
            
            if color_items:
                menu_items.append(pystray.MenuItem(
                    "Quick Color",
                    pystray.Menu(*color_items)
                ))
        
        # Quick profile switching
        if self.app and hasattr(self.app, 'settings'):
            profiles = self.app.settings.list_profiles()
            if profiles:
                profile_items = []
                for profile in profiles:
                    profile_items.append(
                        pystray.MenuItem(
                            profile,
                            lambda p=profile: self.callbacks.get('load_profile', lambda: None)(p)
                        )
                    )
                
                menu_items.append(pystray.MenuItem(
                    "Profiles",
                    pystray.Menu(*profile_items)
                ))
        
        menu_items.append(pystray.MenuItem(
            "Open Settings",
            lambda: self.callbacks.get('show_window', lambda: None)()))
        menu_items.append(pystray.Menu.SEPARATOR)
        menu_items.append(pystray.MenuItem(
            "Help",
            lambda: self.callbacks.get('show_help', lambda: None)()))
        menu_items.append(pystray.MenuItem(
            "About",
            lambda: self.callbacks.get('show_about', lambda: None)()))
        menu_items.append(pystray.Menu.SEPARATOR)
        menu_items.append(pystray.MenuItem(
            "Exit",
            lambda: self.callbacks.get('quit_app', lambda: None)()))
        
        return pystray.Menu(*menu_items)

    def stop(self):
        """Stop tray icon."""
        if self.icon:
            try:
                self.icon.stop()
            except Exception as e:
                logger.warning(f"Error stopping tray icon: {e}")


# ============================================================================
# ACCESSIBLE UI COMPONENTS
# ============================================================================
class AccessibleButton(tk.Frame):
    """Full-width clickable row with colour indicator and active state."""

    def __init__(self, parent, text, colour_hex, command, is_active=False, **kwargs):
        super().__init__(parent, bg=COLOURS['surface'], cursor="hand2")

        self.command = command
        self.colour_hex = colour_hex
        self.text = text
        self._is_active = is_active

        # Configure for keyboard navigation
        self.configure(takefocus=True, highlightthickness=2,
                      highlightcolor=COLOURS['focus'],
                      highlightbackground=COLOURS['border'])

        # Active indicator (left edge)
        self.active_indicator = tk.Frame(
            self,
            bg=COLOURS['accent'] if is_active else COLOURS['surface'],
            width=SPACING['active_indicator_width']
        )
        self.active_indicator.pack(side=tk.LEFT, fill=tk.Y)
        self.active_indicator.pack_propagate(False)

        # Colour indicator
        self.indicator = tk.Frame(
            self,
            bg=colour_hex,
            width=SPACING['colour_indicator_width']
        )
        self.indicator.pack(side=tk.LEFT, fill=tk.Y)
        self.indicator.pack_propagate(False)

        # Text label
        self.label = tk.Label(
            self,
            text=text,
            font=FONTS['button'],
            bg=COLOURS['surface'],
            fg=COLOURS['text_primary'],
            anchor='w',
            padx=SPACING['button_padding_x'],
            pady=SPACING['button_padding_y']
        )
        self.label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bind events
        for widget in [self, self.active_indicator, self.indicator, self.label]:
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self.bind("<Return>", self._on_click)
        self.bind("<space>", self._on_click)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)

        # Apply active styling
        if is_active:
            self._apply_active_style()

    def set_active(self, active):
        """Update active state."""
        self._is_active = active
        if active:
            self._apply_active_style()
        else:
            self._apply_inactive_style()

    def _apply_active_style(self):
        self.active_indicator.configure(bg=COLOURS['accent'])
        self.configure(bg=COLOURS['surface_active'])
        self.label.configure(bg=COLOURS['surface_active'])

    def _apply_inactive_style(self):
        self.active_indicator.configure(bg=COLOURS['surface'])
        self.configure(bg=COLOURS['surface'])
        self.label.configure(bg=COLOURS['surface'])

    def _on_click(self, event=None):
        if self.command:
            self.command()

    def _on_enter(self, event=None):
        if not self._is_active:
            self.configure(bg=COLOURS['surface_hover'])
            self.label.configure(bg=COLOURS['surface_hover'])

    def _on_leave(self, event=None):
        if not self._is_active:
            self.configure(bg=COLOURS['surface'])
            self.label.configure(bg=COLOURS['surface'])
        else:
            self._apply_active_style()

    def _on_focus_in(self, event=None):
        self.configure(highlightbackground=COLOURS['focus'])

    def _on_focus_out(self, event=None):
        self.configure(highlightbackground=COLOURS['border'])


class CustomColourButton(tk.Frame):
    """Custom colour picker button."""

    def __init__(self, parent, text, command, is_active=False, **kwargs):
        super().__init__(parent, bg=COLOURS['surface'], cursor="hand2")

        self.command = command
        self._is_active = is_active

        self.configure(takefocus=True, highlightthickness=2,
                      highlightcolor=COLOURS['focus'],
                      highlightbackground=COLOURS['border'])

        # Active indicator
        self.active_indicator = tk.Frame(
            self,
            bg=COLOURS['accent'] if is_active else COLOURS['surface'],
            width=SPACING['active_indicator_width']
        )
        self.active_indicator.pack(side=tk.LEFT, fill=tk.Y)
        self.active_indicator.pack_propagate(False)

        # Placeholder indicator
        self.indicator = tk.Frame(
            self,
            bg=COLOURS['background'],
            width=SPACING['colour_indicator_width']
        )
        self.indicator.pack(side=tk.LEFT, fill=tk.Y)
        self.indicator.pack_propagate(False)

        self.plus_label = tk.Label(
            self.indicator,
            text="+",
            font=('Segoe UI', 14, 'normal'),
            bg=COLOURS['background'],
            fg=COLOURS['text_secondary']
        )
        self.plus_label.place(relx=0.5, rely=0.5, anchor='center')

        self.label = tk.Label(
            self,
            text=text,
            font=FONTS['button'],
            bg=COLOURS['surface'],
            fg=COLOURS['text_primary'],
            anchor='w',
            padx=SPACING['button_padding_x'],
            pady=SPACING['button_padding_y']
        )
        self.label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for widget in [self, self.active_indicator, self.indicator, self.label, self.plus_label]:
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self.bind("<Return>", self._on_click)
        self.bind("<space>", self._on_click)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)

    def set_active(self, active, color=None):
        """Update active state and optionally update indicator colour."""
        self._is_active = active
        if active:
            self.active_indicator.configure(bg=COLOURS['accent'])
            self.configure(bg=COLOURS['surface_active'])
            self.label.configure(bg=COLOURS['surface_active'])
            if color:
                self.indicator.configure(bg=color)
                self.plus_label.configure(bg=color)
        else:
            self.active_indicator.configure(bg=COLOURS['surface'])
            self.configure(bg=COLOURS['surface'])
            self.label.configure(bg=COLOURS['surface'])
            self.indicator.configure(bg=COLOURS['background'])
            self.plus_label.configure(bg=COLOURS['background'])

    def _on_click(self, event=None):
        if self.command:
            self.command()

    def _on_enter(self, event=None):
        if not self._is_active:
            self.configure(bg=COLOURS['surface_hover'])
            self.label.configure(bg=COLOURS['surface_hover'])

    def _on_leave(self, event=None):
        if not self._is_active:
            self.configure(bg=COLOURS['surface'])
            self.label.configure(bg=COLOURS['surface'])

    def _on_focus_in(self, event=None):
        self.configure(highlightbackground=COLOURS['focus'])

    def _on_focus_out(self, event=None):
        self.configure(highlightbackground=COLOURS['border'])


class ToggleButton(tk.Frame):
    """Toggle button for overlay on/off state."""

    def __init__(self, parent, text_on, text_off, command, is_on=False, **kwargs):
        super().__init__(parent, bg=COLOURS['surface'], cursor="hand2")

        self.command = command
        self.text_on = text_on
        self.text_off = text_off
        self._is_on = is_on

        self.configure(takefocus=True, highlightthickness=2,
                      highlightcolor=COLOURS['focus'],
                      highlightbackground=COLOURS['border'])

        # Status indicator
        self.status_indicator = tk.Frame(
            self,
            bg=COLOURS['success'] if is_on else COLOURS['inactive'],
            width=8
        )
        self.status_indicator.pack(side=tk.LEFT, fill=tk.Y)
        self.status_indicator.pack_propagate(False)

        # Label
        self.label = tk.Label(
            self,
            text=text_on if is_on else text_off,
            font=FONTS['button'],
            bg=COLOURS['surface'],
            fg=COLOURS['text_primary'],
            anchor='w',
            padx=SPACING['button_padding_x'],
            pady=SPACING['button_padding_y']
        )
        self.label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for widget in [self, self.status_indicator, self.label]:
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self.bind("<Return>", self._on_click)
        self.bind("<space>", self._on_click)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)

    def set_state(self, is_on):
        """Update toggle state."""
        self._is_on = is_on
        self.status_indicator.configure(
            bg=COLOURS['success'] if is_on else COLOURS['inactive']
        )
        self.label.configure(text=self.text_on if is_on else self.text_off)

    def _on_click(self, event=None):
        if self.command:
            self.command()

    def _on_enter(self, event=None):
        self.configure(bg=COLOURS['surface_hover'])
        self.label.configure(bg=COLOURS['surface_hover'])

    def _on_leave(self, event=None):
        self.configure(bg=COLOURS['surface'])
        self.label.configure(bg=COLOURS['surface'])

    def _on_focus_in(self, event=None):
        self.configure(highlightbackground=COLOURS['focus'])

    def _on_focus_out(self, event=None):
        self.configure(highlightbackground=COLOURS['border'])


# ============================================================================
# MAIN APPLICATION
# ============================================================================
class EaseViewApp:
    """Main application controller."""

    # Preset colours
    PRESETS = {
        "Amber": {"color": "#FFD54F", "description": "Warm yellow tint"},
        "Blue": {"color": "#81D4FA", "description": "Cool blue tint"},
        "Green": {"color": "#A5D6A7", "description": "Soft green tint"},
        "Pink": {"color": "#F8BBD9", "description": "Light pink tint"},
        "Purple": {"color": "#CE93D8", "description": "Gentle purple tint"},
        "Grey": {"color": "#BDBDBD", "description": "Neutral grey tint"},
    }

    def __init__(self):
        # Check for single instance
        if not InstanceLocker.acquire_lock():
            messagebox.showwarning("EaseView", "Another instance of EaseView is already running.")
            sys.exit(0)
        
        # Initialize Tk
        self.root = tk.Tk()
        self.root.title("EaseView - R.Paxton 2026")

        # Detect Windows theme and update colors if needed
        self.current_colours = WindowsIntegration.get_windows_colors()
        
        # Initialize managers
        self.settings = SettingsManager()
        self.overlay = OverlayManager(self.root)
        self.tray = TrayManager({
            'toggle_overlay': self.toggle_overlay,
            'show_window': self.show_window,
            'show_help': self.show_help,
            'show_about': self.show_about,
            'quit_app': self.quit_app,
        })
        
        # Initialize hotkey manager
        self.hotkey_manager = HotkeyManager({
            'toggle': self.toggle_overlay,
            'increase_opacity': lambda: self.adjust_opacity(5),
            'decrease_opacity': lambda: self.adjust_opacity(-5),
            'increase_density': lambda: self.adjust_density(10),
            'decrease_density': lambda: self.adjust_density(-10),
        })
        
        # Initialize schedule manager
        self.schedule_manager = ScheduleManager(self)

        # UI state
        self.colour_buttons = {}
        self.custom_button = None
        self.toggle_button = None
        self.active_preset = self.settings.get('preset_name')
        self.custom_color = self.settings.get('custom_color')
        self.tooltips = {}  # Store tooltip widgets

        # Build UI
        self.set_window_icon()
        self.setup_window()
        self.create_menu_bar()
        self.bind_keyboard_shortcuts()

        # Restore active selection state
        self._update_selection_ui()

        # Setup window close/minimize behavior
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self.root.bind("<Unmap>", self._on_window_minimize)

        # Restore window geometry
        self._restore_window_geometry()
        
        # Start minimized if enabled
        if self.settings.get('start_minimized', False):
            self.root.withdraw()

        # Restore overlay state if enabled in settings
        self._restore_overlay_state()
        
        # Setup hotkeys from settings
        self._setup_hotkeys_from_settings()
        
        # Set fade preference
        self.overlay.enable_fade = self.settings.get('enable_fade', True)
        
        # Start schedule manager if enabled
        schedule = self.settings.get('schedule', {})
        if schedule.get('enabled', False):
            self.schedule_manager.start()
        
        # Check for startup
        if self.settings.get('auto_startup', False):
            WindowsIntegration.set_startup(True)

        logger.info("EaseView started")

    def get_resource_path(self, relative_path):
        """Get resource path for PyInstaller."""
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def set_window_icon(self):
        """Set application icon."""
        try:
            icon_path = self.get_resource_path('app_icon.ico')
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception as e:
            logger.warning(f"Could not set window icon: {e}")

    def bind_keyboard_shortcuts(self):
        """Set up global keyboard shortcuts."""
        # Toggle overlay: Ctrl+Shift+O
        self.root.bind_all("<Control-Shift-o>", lambda e: self.toggle_overlay())
        self.root.bind_all("<Control-Shift-O>", lambda e: self.toggle_overlay())

        # Emergency escape: Esc hides overlay
        self.root.bind_all("<Escape>", lambda e: self.hide_overlay())

        # Opacity controls: Ctrl+Shift+Up/Down
        self.root.bind_all("<Control-Shift-Up>", lambda e: self.adjust_opacity(5))
        self.root.bind_all("<Control-Shift-Down>", lambda e: self.adjust_opacity(-5))

        # Density controls: Ctrl+Shift+Left/Right
        self.root.bind_all("<Control-Shift-Left>", lambda e: self.adjust_density(-10))
        self.root.bind_all("<Control-Shift-Right>", lambda e: self.adjust_density(10))

    def adjust_opacity(self, delta):
        """Adjust opacity by delta percentage."""
        current = self.settings.get('opacity', 0.3) * 100
        new_value = max(10, min(60, current + delta))
        self.opacity_var.set(new_value)
        self.on_opacity_change(new_value)

    def adjust_density(self, delta):
        """Adjust density by delta percentage."""
        current = self.settings.get('density', 1.0) * 100
        new_value = max(50, min(150, current + delta))
        self.density_var.set(new_value)
        self.on_density_change(new_value)

    def create_menu_bar(self):
        """Create menu bar."""
        menubar = Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Toggle Overlay", command=self.toggle_overlay,
                            accelerator="Ctrl+Shift+O")
        file_menu.add_separator()
        
        # Profiles submenu
        profiles_menu = Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Profiles", menu=profiles_menu)
        profiles_menu.add_command(label="Save Current as Profile...", command=self._save_profile_dialog)
        profiles_menu.add_command(label="Load Profile...", command=self._load_profile_dialog)
        profiles_menu.add_separator()
        profiles_menu.add_command(label="Manage Profiles...", command=self._manage_profiles_dialog)
        
        file_menu.add_separator()
        file_menu.add_command(label="Export Settings...", command=self._export_settings)
        file_menu.add_command(label="Import Settings...", command=self._import_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit_app)

        settings_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="Startup Options...", command=self._startup_options)
        settings_menu.add_command(label="Hotkey Settings...", command=self._hotkey_settings)
        settings_menu.add_command(label="Schedule Overlay...", command=self._schedule_settings)
        settings_menu.add_command(label="Accessibility Options...", command=self._accessibility_settings)
        
        help_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Keyboard Shortcuts", command=self.show_shortcuts)
        help_menu.add_command(label="How to Use", command=self.show_help)
        help_menu.add_separator()
        help_menu.add_command(label="Check for Updates...", command=self._check_updates)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about)
    
    def _save_profile_dialog(self):
        """Dialog to save current settings as a profile."""
        name = tk.simpledialog.askstring("Save Profile", "Enter profile name:")
        if name:
            if self.settings.save_profile(name):
                messagebox.showinfo("Success", f"Profile '{name}' saved successfully.")
            else:
                messagebox.showerror("Error", f"Failed to save profile '{name}'.")
    
    def _load_profile_dialog(self):
        """Dialog to load a profile."""
        profiles = self.settings.list_profiles()
        if not profiles:
            messagebox.showinfo("No Profiles", "No saved profiles found.")
            return
        
        # Create dialog window
        dialog = tk.Toplevel(self.root)
        dialog.title("Load Profile")
        dialog.geometry("300x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="Select a profile to load:", font=FONTS['section']).pack(pady=10)
        
        listbox = tk.Listbox(dialog, height=15)
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        for profile in profiles:
            listbox.insert(tk.END, profile)
        
        def load_selected():
            selection = listbox.curselection()
            if selection:
                profile_name = listbox.get(selection[0])
                if self.settings.load_profile(profile_name):
                    messagebox.showinfo("Success", f"Profile '{profile_name}' loaded successfully.")
                    # Reload UI
                    self.active_preset = self.settings.get('preset_name')
                    self.custom_color = self.settings.get('custom_color')
                    self._update_selection_ui()
                    # Update sliders
                    if hasattr(self, 'opacity_var'):
                        self.opacity_var.set(self.settings.get('opacity', 0.3) * 100)
                    if hasattr(self, 'density_var'):
                        self.density_var.set(self.settings.get('density', 1.0) * 100)
                    dialog.destroy()
                else:
                    messagebox.showerror("Error", f"Failed to load profile '{profile_name}'.")
        
        tk.Button(dialog, text="Load", command=load_selected).pack(pady=5)
        tk.Button(dialog, text="Cancel", command=dialog.destroy).pack(pady=5)
    
    def _manage_profiles_dialog(self):
        """Dialog to manage profiles."""
        profiles = self.settings.list_profiles()
        dialog = tk.Toplevel(self.root)
        dialog.title("Manage Profiles")
        dialog.geometry("350x400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="Saved Profiles:", font=FONTS['section']).pack(pady=10)
        
        listbox = tk.Listbox(dialog, height=15)
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        for profile in profiles:
            listbox.insert(tk.END, profile)
        
        def delete_selected():
            selection = listbox.curselection()
            if selection:
                profile_name = listbox.get(selection[0])
                if messagebox.askyesno("Confirm", f"Delete profile '{profile_name}'?"):
                    if self.settings.delete_profile(profile_name):
                        listbox.delete(selection[0])
                        messagebox.showinfo("Success", f"Profile '{profile_name}' deleted.")
                    else:
                        messagebox.showerror("Error", f"Failed to delete profile '{profile_name}'.")
        
        tk.Button(dialog, text="Delete Selected", command=delete_selected).pack(pady=5)
        tk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=5)
    
    def _export_settings(self):
        """Export settings to a file."""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export Settings"
        )
        if filepath:
            if self.settings.export_settings(filepath):
                messagebox.showinfo("Success", f"Settings exported to {filepath}")
            else:
                messagebox.showerror("Error", "Failed to export settings")
    
    def _import_settings(self):
        """Import settings from a file."""
        if not messagebox.askyesno("Confirm", "This will replace your current settings. Continue?"):
            return
        
        filepath = filedialog.askopenfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Import Settings"
        )
        if filepath:
            if self.settings.import_settings(filepath):
                messagebox.showinfo("Success", "Settings imported successfully. Please restart the application.")
                # Reload UI
                self.active_preset = self.settings.get('preset_name')
                self.custom_color = self.settings.get('custom_color')
                self._update_selection_ui()
            else:
                messagebox.showerror("Error", "Failed to import settings")
    
    def _startup_options(self):
        """Dialog for startup options."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Startup Options")
        dialog.geometry("350x180")
        dialog.transient(self.root)
        dialog.grab_set()
        
        auto_startup_var = tk.BooleanVar(value=self.settings.get('auto_startup', False))
        start_minimized_var = tk.BooleanVar(value=self.settings.get('start_minimized', False))
        
        tk.Label(dialog, text="Windows Startup:", font=FONTS['section']).pack(pady=10)
        
        tk.Checkbutton(dialog, text="Start EaseView with Windows", variable=auto_startup_var,
                      font=FONTS['body']).pack(pady=5, anchor='w', padx=20)
        
        tk.Checkbutton(dialog, text="Start minimized to tray", variable=start_minimized_var,
                      font=FONTS['body']).pack(pady=5, anchor='w', padx=20)
        
        def save():
            self.settings.set('auto_startup', auto_startup_var.get())
            self.settings.set('start_minimized', start_minimized_var.get())
            WindowsIntegration.set_startup(auto_startup_var.get())
            messagebox.showinfo("Success", "Startup settings saved.")
            dialog.destroy()
        
        tk.Button(dialog, text="Save", command=save).pack(pady=10)
        tk.Button(dialog, text="Cancel", command=dialog.destroy).pack()
    
    def _hotkey_settings(self):
        """Dialog for hotkey customization."""
        messagebox.showinfo("Hotkey Settings", 
                          "Hotkey customization is available in future versions.\n"
                          "Currently using default hotkeys.")
    
    def _schedule_settings(self):
        """Dialog for schedule settings."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Schedule Overlay")
        dialog.geometry("380x350")
        dialog.transient(self.root)
        dialog.grab_set()
        
        schedule = self.settings.get('schedule', {})
        enabled_var = tk.BooleanVar(value=schedule.get('enabled', False))
        use_sunset_var = tk.BooleanVar(value=schedule.get('use_sunset', False))
        start_var = tk.StringVar(value=schedule.get('start_time', '09:00'))
        end_var = tk.StringVar(value=schedule.get('end_time', '17:00'))
        
        location = schedule.get('location', {})
        lat_var = tk.DoubleVar(value=location.get('latitude', 55.9533))
        lon_var = tk.DoubleVar(value=location.get('longitude', -3.1883))
        tz_var = tk.StringVar(value=location.get('timezone', 'Europe/London'))
        
        tk.Label(dialog, text="Schedule Overlay:", font=FONTS['section']).pack(pady=10)
        
        tk.Checkbutton(dialog, text="Enable scheduled overlay", variable=enabled_var,
                      font=FONTS['body']).pack(pady=5)
        
        tk.Checkbutton(dialog, text="Use sunset/sunrise (night mode)", variable=use_sunset_var,
                      font=FONTS['body']).pack(pady=5)
        
        # Fixed time settings
        time_frame = tk.Frame(dialog)
        time_frame.pack(pady=5)
        
        tk.Label(time_frame, text="Start time (HH:MM):", font=FONTS['body']).pack(side=tk.LEFT, padx=5)
        start_entry = tk.Entry(time_frame, textvariable=start_var, width=10)
        start_entry.pack(side=tk.LEFT, padx=5)
        
        tk.Label(time_frame, text="End time (HH:MM):", font=FONTS['body']).pack(side=tk.LEFT, padx=5)
        end_entry = tk.Entry(time_frame, textvariable=end_var, width=10)
        end_entry.pack(side=tk.LEFT, padx=5)
        
        # Location settings for sunset/sunrise
        if ASTRAL_AVAILABLE:
            loc_frame = tk.LabelFrame(dialog, text="Location (for sunset/sunrise)", font=FONTS['body'])
            loc_frame.pack(pady=10, padx=10, fill=tk.X)
            
            tk.Label(loc_frame, text="Latitude:", font=FONTS['body']).grid(row=0, column=0, padx=5, pady=2)
            tk.Entry(loc_frame, textvariable=lat_var, width=15).grid(row=0, column=1, padx=5, pady=2)
            
            tk.Label(loc_frame, text="Longitude:", font=FONTS['body']).grid(row=1, column=0, padx=5, pady=2)
            tk.Entry(loc_frame, textvariable=lon_var, width=15).grid(row=1, column=1, padx=5, pady=2)
            
            tk.Label(loc_frame, text="Timezone:", font=FONTS['body']).grid(row=2, column=0, padx=5, pady=2)
            tk.Entry(loc_frame, textvariable=tz_var, width=15).grid(row=2, column=1, padx=5, pady=2)
        
        def save():
            try:
                # Validate times if not using sunset
                if not use_sunset_var.get():
                    dt_time.fromisoformat(start_var.get())
                    dt_time.fromisoformat(end_var.get())
                
                schedule_data = {
                    'enabled': enabled_var.get(),
                    'use_sunset': use_sunset_var.get(),
                    'start_time': start_var.get(),
                    'end_time': end_var.get(),
                    'location': {
                        'latitude': lat_var.get(),
                        'longitude': lon_var.get(),
                        'timezone': tz_var.get()
                    }
                }
                
                self.settings.set('schedule', schedule_data)
                
                # Restart schedule manager
                self.schedule_manager.stop()
                if enabled_var.get():
                    self.schedule_manager.start()
                
                messagebox.showinfo("Success", "Schedule settings saved.")
                dialog.destroy()
            except ValueError:
                messagebox.showerror("Error", "Invalid time format. Use HH:MM (e.g., 09:00)")
        
        tk.Button(dialog, text="Save", command=save).pack(pady=10)
        tk.Button(dialog, text="Cancel", command=dialog.destroy).pack()
    
    def _accessibility_settings(self):
        """Dialog for accessibility settings."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Accessibility Options")
        dialog.geometry("350x280")
        dialog.transient(self.root)
        dialog.grab_set()
        
        accessibility = self.settings.get('accessibility', {})
        high_contrast_var = tk.BooleanVar(value=accessibility.get('high_contrast', False))
        font_scale_var = tk.DoubleVar(value=accessibility.get('font_scale', 1.0))
        enable_fade_var = tk.BooleanVar(value=self.settings.get('enable_fade', True))
        enable_notifications_var = tk.BooleanVar(value=self.settings.get('enable_notifications', True))
        auto_backup_var = tk.BooleanVar(value=self.settings.get('auto_backup', True))
        
        tk.Label(dialog, text="Accessibility Options:", font=FONTS['section']).pack(pady=10)
        
        tk.Checkbutton(dialog, text="High contrast mode", variable=high_contrast_var,
                      font=FONTS['body']).pack(pady=2, anchor='w', padx=20)
        
        scale_label = tk.Label(dialog, text=f"Font scale: {font_scale_var.get():.1f}x", font=FONTS['body'])
        scale_label.pack(pady=2)
        scale_widget = tk.Scale(dialog, from_=0.8, to=2.0, resolution=0.1,
                               orient=tk.HORIZONTAL, variable=font_scale_var,
                               command=lambda v: scale_label.config(
                                   text=f"Font scale: {float(v):.1f}x"))
        scale_widget.pack(pady=5)
        
        tk.Label(dialog, text="Preferences:", font=FONTS['section']).pack(pady=(10, 5))
        
        tk.Checkbutton(dialog, text="Enable fade animations", variable=enable_fade_var,
                      font=FONTS['body']).pack(pady=2, anchor='w', padx=20)
        
        tk.Checkbutton(dialog, text="Enable notifications", variable=enable_notifications_var,
                      font=FONTS['body']).pack(pady=2, anchor='w', padx=20)
        
        tk.Checkbutton(dialog, text="Auto-backup settings", variable=auto_backup_var,
                      font=FONTS['body']).pack(pady=2, anchor='w', padx=20)
        
        def save():
            self.settings.set('accessibility', {
                'high_contrast': high_contrast_var.get(),
                'font_scale': font_scale_var.get()
            })
            self.settings.set('enable_fade', enable_fade_var.get())
            self.settings.set('enable_notifications', enable_notifications_var.get())
            self.settings.set('auto_backup', auto_backup_var.get())
            
            # Apply fade setting immediately
            self.overlay.enable_fade = enable_fade_var.get()
            
            messagebox.showinfo("Success", "Settings saved. Restart required for font scaling.")
            dialog.destroy()
        
        tk.Button(dialog, text="Save", command=save).pack(pady=10)
        tk.Button(dialog, text="Cancel", command=dialog.destroy).pack()
    
    def _check_updates(self):
        """Check for application updates."""
        try:
            update_info = UpdateChecker.check_for_updates()
            if update_info and update_info.get('available'):
                msg = (f"Update available!\n\n"
                      f"Current version: {update_info['current_version']}\n"
                      f"Latest version: {update_info['latest_version']}\n\n"
                      f"Visit: {update_info.get('url', 'GitHub')}")
                messagebox.showinfo("Update Available", msg)
            else:
                messagebox.showinfo("No Updates", f"You are running the latest version ({VERSION}).")
        except Exception as e:
            logger.error(f"Update check failed: {e}")
            messagebox.showerror("Error", "Failed to check for updates.")

    def show_about(self):
        """Show about dialog."""
        messagebox.showinfo("About EaseView",
            f"EaseView - Screen Colour Overlay\n\n"
            f"Version {VERSION}\n\n"
            f"A tool to make screen reading easier.\n\n"
            f"Contact: Ross.paxton@south-ayrshire.gov.uk")

    def show_help(self):
        """Show help dialog."""
        messagebox.showinfo("How to Use",
            "How to Use EaseView:\n\n"
            "1. Select a colour from the list\n"
            "2. Adjust the strength slider\n"
            "3. Use the toggle button or tray icon to show/hide\n"
            "4. Your settings are saved automatically\n\n"
            "Press Esc at any time to hide the overlay.")

    def show_shortcuts(self):
        """Show keyboard shortcuts dialog."""
        messagebox.showinfo("Keyboard Shortcuts",
            "Keyboard Shortcuts:\n\n"
            "Ctrl+Shift+O      Toggle overlay on/off\n"
            "Ctrl+Shift+Up     Increase strength\n"
            "Ctrl+Shift+Down   Decrease strength\n"
            "Ctrl+Shift+Right  Increase density\n"
            "Ctrl+Shift+Left   Decrease density\n"
            "Escape            Hide overlay (emergency)\n"
            "Tab               Navigate between controls\n"
            "Enter/Space       Activate focused button")

    def show_window(self):
        """Show main window."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.attributes('-topmost', True)
        # Remove topmost after window is shown so it doesn't stay on top
        self.root.after(100, lambda: self.root.attributes('-topmost', False))

    def _on_window_close(self):
        """Handle window close - hide to tray instead of closing."""
        self.root.withdraw()

    def _on_window_minimize(self, event=None):
        """Handle window minimize - ensure it's hidden."""
        if event and event.widget == self.root:
            self.root.withdraw()

    def _restore_overlay_state(self):
        """Restore overlay state from settings on startup."""
        try:
            overlay_enabled = self.settings.get('overlay_enabled', False)
            if not overlay_enabled:
                return

            # Get the color from settings
            color = None
            preset_name = self.settings.get('preset_name')
            
            if preset_name and preset_name in self.PRESETS:
                color = self.PRESETS[preset_name]['color']
            elif self.custom_color:
                color = self.custom_color

            if color:
                # Restore overlay with saved settings
                opacity = self.settings.get('opacity', 0.3)
                density = self.settings.get('density', 1.0)
                success = self.overlay.create(color, opacity, density)
                
                if success:
                    self.toggle_button.set_state(True)
                    # Create tray icon with the color
                    self.tray.create(color)
                    logger.info("Overlay state restored on startup")
                else:
                    # If overlay creation failed, disable it in settings
                    self.settings.set('overlay_enabled', False, save_immediately=False)
                    logger.warning("Failed to restore overlay on startup")
        except Exception as e:
            logger.error(f"Error restoring overlay state: {e}")

    def setup_window(self):
        """Build main window UI."""
        self.root.geometry(f"{WINDOW['width']}x{WINDOW['height']}")
        self.root.configure(bg=COLOURS['background'])
        self.root.resizable(True, True)
        self.root.eval('tk::PlaceWindow . center')

        # ====================================================================
        # HEADER
        # ====================================================================
        header_frame = tk.Frame(self.root, bg=COLOURS['surface'])
        header_frame.pack(fill=tk.X)

        header_inner = tk.Frame(header_frame, bg=COLOURS['surface'])
        header_inner.pack(fill=tk.X, padx=SPACING['window_padding'], pady=16)

        tk.Label(
            header_inner,
            text="EaseView",
            font=FONTS['title'],
            bg=COLOURS['surface'],
            fg=COLOURS['text_primary'],
            anchor='w'
        ).pack(anchor='w')

        tk.Label(
            header_inner,
            text="Screen colour overlay for easier reading",
            font=FONTS['subtitle'],
            bg=COLOURS['surface'],
            fg=COLOURS['text_secondary'],
            anchor='w'
        ).pack(anchor='w', pady=(2, 0))

        tk.Frame(self.root, bg=COLOURS['divider'], height=1).pack(fill=tk.X)

        # ====================================================================
        # MAIN CONTENT
        # ====================================================================
        content_frame = tk.Frame(self.root, bg=COLOURS['background'])
        content_frame.pack(fill=tk.BOTH, expand=True,
                          padx=SPACING['window_padding'],
                          pady=SPACING['window_padding'])

        # Toggle button section
        toggle_section = tk.Frame(content_frame, bg=COLOURS['background'])
        toggle_section.pack(fill=tk.X, pady=(0, SPACING['section_gap']))

        self.toggle_button = ToggleButton(
            toggle_section,
            text_on="Overlay is ON (click to disable)",
            text_off="Overlay is OFF (click to enable)",
            command=self.toggle_overlay,
            is_on=self.overlay.is_active
        )
        self.toggle_button.pack(fill=tk.X)

        # Colour selection section
        tk.Label(
            content_frame,
            text="Overlay colour",
            font=FONTS['section'],
            bg=COLOURS['background'],
            fg=COLOURS['text_secondary'],
            anchor='w'
        ).pack(anchor='w', pady=(0, 8))

        colours_container = tk.Frame(content_frame, bg=COLOURS['background'])
        colours_container.pack(fill=tk.X)

        for name, data in self.PRESETS.items():
            is_active = (self.active_preset == name)
            btn = AccessibleButton(
                colours_container,
                text=name,
                colour_hex=data['color'],
                command=lambda n=name, c=data['color']: self.select_preset(n, c),
                is_active=is_active
            )
            btn.pack(fill=tk.X, pady=(0, SPACING['row_gap']))
            self.colour_buttons[name] = btn

        # Custom colour button
        is_custom_active = (self.active_preset is None and self.custom_color is not None)
        self.custom_button = CustomColourButton(
            colours_container,
            text="Choose custom colour",
            command=self.choose_custom_color,
            is_active=is_custom_active
        )
        self.custom_button.pack(fill=tk.X, pady=(0, SPACING['row_gap']))
        if is_custom_active and self.custom_color:
            self.custom_button.set_active(True, self.custom_color)

        # ====================================================================
        # OPACITY CONTROL
        # ====================================================================
        opacity_section = tk.Frame(content_frame, bg=COLOURS['background'])
        opacity_section.pack(fill=tk.X, pady=(SPACING['section_gap'], 0))

        opacity_header = tk.Frame(opacity_section, bg=COLOURS['background'])
        opacity_header.pack(fill=tk.X)

        tk.Label(
            opacity_header,
            text="Overlay strength",
            font=FONTS['section'],
            bg=COLOURS['background'],
            fg=COLOURS['text_secondary'],
            anchor='w'
        ).pack(side=tk.LEFT)

        self.opacity_value_label = tk.Label(
            opacity_header,
            text=f"{int(self.settings.get('opacity', 0.3) * 100)}%",
            font=FONTS['section'],
            bg=COLOURS['background'],
            fg=COLOURS['text_primary'],
            anchor='e'
        )
        self.opacity_value_label.pack(side=tk.RIGHT)

        slider_container = tk.Frame(opacity_section, bg=COLOURS['background'])
        slider_container.pack(fill=tk.X, pady=(12, 0))

        self.opacity_var = tk.DoubleVar(value=self.settings.get('opacity', 0.3) * 100)
        self.opacity_slider = tk.Scale(
            slider_container,
            from_=10,
            to=60,
            orient=tk.HORIZONTAL,
            variable=self.opacity_var,
            command=self.on_opacity_change,
            showvalue=False,
            bg=COLOURS['background'],
            fg=COLOURS['text_primary'],
            troughcolor=COLOURS['surface'],
            activebackground=COLOURS['accent'],
            highlightthickness=0,
            relief=tk.FLAT,
            bd=0,
            length=300,
            sliderlength=20
        )
        self.opacity_slider.pack(fill=tk.X)
        
        # Opacity quick presets
        opacity_presets_frame = tk.Frame(opacity_section, bg=COLOURS['background'])
        opacity_presets_frame.pack(fill=tk.X, pady=(8, 0))
        
        tk.Label(opacity_presets_frame, text="Quick:", font=FONTS['footer'],
                bg=COLOURS['background'], fg=COLOURS['text_secondary']).pack(side=tk.LEFT, padx=(0, 5))
        
        presets = [25, 30, 40, 50]
        for preset in presets:
            btn = tk.Button(opacity_presets_frame, text=f"{preset}%",
                          command=lambda p=preset: self.set_opacity_preset(p),
                          font=FONTS['footer'], width=5,
                          bg=COLOURS['surface'], fg=COLOURS['text_primary'],
                          relief=tk.FLAT, bd=1, cursor="hand2",
                          activebackground=COLOURS['surface_hover'])
            btn.pack(side=tk.LEFT, padx=2)

        # ====================================================================
        # DENSITY CONTROL
        # ====================================================================
        density_section = tk.Frame(content_frame, bg=COLOURS['background'])
        density_section.pack(fill=tk.X, pady=(SPACING['section_gap'], 0))

        density_header = tk.Frame(density_section, bg=COLOURS['background'])
        density_header.pack(fill=tk.X)

        tk.Label(
            density_header,
            text="Colour density",
            font=FONTS['section'],
            bg=COLOURS['background'],
            fg=COLOURS['text_secondary'],
            anchor='w'
        ).pack(side=tk.LEFT)

        self.density_value_label = tk.Label(
            density_header,
            text=f"{int(self.settings.get('density', 1.0) * 100)}%",
            font=FONTS['section'],
            bg=COLOURS['background'],
            fg=COLOURS['text_primary'],
            anchor='e'
        )
        self.density_value_label.pack(side=tk.RIGHT)

        density_slider_container = tk.Frame(density_section, bg=COLOURS['background'])
        density_slider_container.pack(fill=tk.X, pady=(12, 0))

        self.density_var = tk.DoubleVar(value=self.settings.get('density', 1.0) * 100)
        self.density_slider = tk.Scale(
            density_slider_container,
            from_=50,
            to=150,
            orient=tk.HORIZONTAL,
            variable=self.density_var,
            command=self.on_density_change,
            showvalue=False,
            bg=COLOURS['background'],
            fg=COLOURS['text_primary'],
            troughcolor=COLOURS['surface'],
            activebackground=COLOURS['accent'],
            highlightthickness=0,
            relief=tk.FLAT,
            bd=0,
            length=300,
            sliderlength=20
        )
        self.density_slider.pack(fill=tk.X)

        # Shortcut hint
        hint_label = tk.Label(
            content_frame,
            text="Tip: Press Ctrl+Shift+O to toggle, Esc to hide",
            font=FONTS['footer'],
            bg=COLOURS['background'],
            fg=COLOURS['text_secondary'],
            anchor='w'
        )
        hint_label.pack(anchor='w', pady=(SPACING['section_gap'], 0))

        # ====================================================================
        # FOOTER
        # ====================================================================
        footer_frame = tk.Frame(self.root, bg=COLOURS['surface'])
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM)

        tk.Frame(footer_frame, bg=COLOURS['divider'], height=1).pack(fill=tk.X)

        footer_inner = tk.Frame(footer_frame, bg=COLOURS['surface'])
        footer_inner.pack(fill=tk.X, padx=SPACING['window_padding'], pady=10)

        tk.Label(
            footer_inner,
            text=f"Version {VERSION}",
            font=FONTS['footer'],
            bg=COLOURS['surface'],
            fg=COLOURS['text_secondary'],
            anchor='w'
        ).pack(side=tk.LEFT)

        tk.Label(
            footer_inner,
            text="Ross.paxton@south-ayrshire.gov.uk",
            font=FONTS['footer'],
            bg=COLOURS['surface'],
            fg=COLOURS['text_secondary'],
            anchor='e'
        ).pack(side=tk.RIGHT)

    def _update_selection_ui(self):
        """Update UI to reflect current selection state."""
        # Clear all active states
        for name, btn in self.colour_buttons.items():
            btn.set_active(name == self.active_preset)

        # Update custom button
        is_custom = (self.active_preset is None and self.custom_color is not None)
        self.custom_button.set_active(is_custom, self.custom_color if is_custom else None)

    def select_preset(self, name, color):
        """Select a preset colour."""
        if not name or not color:
            logger.warning(f"Invalid preset selection: name={name}, color={color}")
            return
        
        self.active_preset = name
        self.settings.set('preset_name', name, save_immediately=False)
        self.settings.set('custom_color', color, save_immediately=False)
        self.settings.save_pending()
        self._update_selection_ui()
        self.apply_overlay(color)

    def choose_custom_color(self):
        """Open colour picker."""
        initial = self.custom_color if self.custom_color else "#FFD54F"
        try:
            color = colorchooser.askcolor(title="Choose overlay colour", initialcolor=initial)
            if color and color[1]:
                # Validate hex color format
                if not color[1].startswith('#'):
                    messagebox.showerror("Error", "Invalid color format selected.")
                    return
                
                self.active_preset = None
                self.custom_color = color[1]
                
                # Add to recent colors
                recent = self.settings.get('recent_colors', [])
                if color[1] not in recent:
                    recent.insert(0, color[1])
                    recent = recent[:10]  # Keep last 10
                    self.settings.set('recent_colors', recent, save_immediately=False)
                
                self.settings.set('preset_name', None, save_immediately=False)
                self.settings.set('custom_color', color[1], save_immediately=False)
                self.settings.save_pending()
                self._update_selection_ui()
                self.apply_overlay(color[1])
        except Exception as e:
            logger.error(f"Error in color picker: {e}")
            messagebox.showerror("Error", f"Failed to open color picker: {e}")

    def apply_overlay(self, color):
        """Apply overlay with given colour."""
        if not color:
            logger.warning("Attempted to apply overlay with no color")
            return
        
        opacity = self.settings.get('opacity', 0.3)
        density = self.settings.get('density', 1.0)
        
        # Set fade preference
        self.overlay.enable_fade = self.settings.get('enable_fade', True)
        
        success = self.overlay.create(color, opacity, density)

        if success:
            self.settings.set('overlay_enabled', True, save_immediately=False)
            self.settings.save_pending()
            self.toggle_button.set_state(True)
            self.root.attributes('-topmost', True)
            self.root.lift()

            # Create tray icon if needed
            self.tray.create(color)
            
            # Show notification
            if self.settings.get('enable_notifications', True) and TOAST_AVAILABLE:
                try:
                    toast = ToastNotifier()
                    toast.show_toast("EaseView", "Overlay enabled", duration=2, threaded=True)
                except Exception:
                    pass
        else:
            error_msg = (
                "Failed to create overlay. The overlay may not work correctly on this system.\n\n"
                "Possible causes:\n"
                "- Insufficient permissions\n"
                "- Graphics driver issues\n"
                "- Another application is interfering\n\n"
                "Try restarting the application or your computer."
            )
            logger.error("Overlay creation failed")
            messagebox.showerror("Error", error_msg)

    def toggle_overlay(self):
        """Toggle overlay on/off."""
        if self.overlay.is_active:
            self.hide_overlay()
        elif self.overlay.current_color:
            self.overlay.show()
            self.settings.set('overlay_enabled', True, save_immediately=False)
            self.settings.save_pending()
            self.toggle_button.set_state(True)
        elif self.custom_color or self.active_preset:
            # Re-create overlay with last colour
            color = self.custom_color if self.active_preset is None else self.PRESETS.get(self.active_preset, {}).get('color')
            if color:
                self.apply_overlay(color)
            else:
                messagebox.showwarning("No Color Selected", 
                    "Please select a color before enabling the overlay.")

    def hide_overlay(self):
        """Hide overlay (emergency escape)."""
        self.overlay.hide()
        self.settings.set('overlay_enabled', False, save_immediately=False)
        self.settings.save_pending()
        self.toggle_button.set_state(False)

    def on_opacity_change(self, value):
        """Handle opacity slider change."""
        opacity = float(value) / 100
        self.settings.set('opacity', opacity, save_immediately=False)
        self.opacity_value_label.configure(text=f"{int(float(value))}%")
        self.overlay.update_opacity(opacity)
        # Debounce saves for slider changes
        if hasattr(self, '_opacity_save_timer'):
            self.root.after_cancel(self._opacity_save_timer)
        self._opacity_save_timer = self.root.after(500, self.settings.save_pending)

    def on_density_change(self, value):
        """Handle density slider change."""
        density = float(value) / 100
        self.settings.set('density', density, save_immediately=False)
        self.density_value_label.configure(text=f"{int(float(value))}%")
        self.overlay.update_density(density)
        # Debounce saves for slider changes
        if hasattr(self, '_density_save_timer'):
            self.root.after_cancel(self._density_save_timer)
        self._density_save_timer = self.root.after(500, self.settings.save_pending)

    def _restore_window_geometry(self):
        """Restore window position and size from settings."""
        try:
            geometry = self.settings.get('window_geometry', {})
            if geometry and geometry.get('x') is not None and geometry.get('y') is not None:
                width = geometry.get('width', WINDOW['width'])
                height = geometry.get('height', WINDOW['height'])
                x = geometry.get('x')
                y = geometry.get('y')
                self.root.geometry(f"{width}x{height}+{x}+{y}")
            
            # Save geometry on window move/resize
            self.root.bind('<Configure>', self._on_window_configure)
        except Exception as e:
            logger.warning(f"Failed to restore window geometry: {e}")
    
    def _on_window_configure(self, event=None):
        """Save window geometry when moved or resized."""
        if event and event.widget == self.root:
            try:
                geometry = self.root.geometry()
                # Parse: "widthxheight+x+y"
                parts = geometry.split('+')
                if len(parts) == 3:
                    size_part = parts[0].split('x')
                    if len(size_part) == 2:
                        width = int(size_part[0])
                        height = int(size_part[1])
                        x = int(parts[1])
                        y = int(parts[2])
                        
                        self.settings.set('window_geometry', {
                            'x': x, 'y': y,
                            'width': width, 'height': height
                        }, save_immediately=False)
                        # Debounce saves
                        if hasattr(self, '_geometry_save_timer'):
                            self.root.after_cancel(self._geometry_save_timer)
                        self._geometry_save_timer = self.root.after(1000, self.settings.save_pending)
            except Exception:
                pass
    
    def _setup_hotkeys_from_settings(self):
        """Setup hotkeys from settings."""
        try:
            hotkeys = self.settings.get('hotkeys', {})
            if hotkeys and KEYBOARD_AVAILABLE:
                # Convert to keyboard format
                keyboard_map = {}
                for name, key in hotkeys.items():
                    if name == 'toggle':
                        keyboard_map['toggle'] = key
                    elif name == 'increase_opacity':
                        keyboard_map['increase_opacity'] = key
                    elif name == 'decrease_opacity':
                        keyboard_map['decrease_opacity'] = key
                    elif name == 'increase_density':
                        keyboard_map['increase_density'] = key
                    elif name == 'decrease_density':
                        keyboard_map['decrease_density'] = key
                
                self.hotkey_manager.register_all(keyboard_map)
        except Exception as e:
            logger.warning(f"Failed to setup hotkeys from settings: {e}")
    
    def _create_tooltip(self, widget, text):
        """Create a tooltip for a widget."""
        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            label = tk.Label(tooltip, text=text, bg="#FFFFE0", fg="black",
                           font=FONTS['footer'], relief="solid", borderwidth=1)
            label.pack()
            widget.tooltip = tooltip
        
        def on_leave(event):
            if hasattr(widget, 'tooltip'):
                widget.tooltip.destroy()
                del widget.tooltip
        
        widget.bind('<Enter>', on_enter)
        widget.bind('<Leave>', on_leave)
        return widget
    
    def quit_app(self):
        """Clean shutdown."""
        logger.info("EaseView shutting down")

        # Stop hotkey manager
        if hasattr(self, 'hotkey_manager'):
            self.hotkey_manager.stop()

        # Stop schedule manager
        if hasattr(self, 'schedule_manager'):
            self.schedule_manager.stop()

        # Stop tray first
        self.tray.stop()

        # Destroy overlay
        self.overlay.destroy()

        # Save final settings (including any pending changes)
        self.settings.save_pending()
        self.settings.save()
        
        # Save window geometry
        try:
            geometry = self.root.geometry()
            parts = geometry.split('+')
            if len(parts) == 3:
                size_part = parts[0].split('x')
                if len(size_part) == 2:
                    width = int(size_part[0])
                    height = int(size_part[1])
                    x = int(parts[1])
                    y = int(parts[2])
                    self.settings.set('window_geometry', {
                        'x': x, 'y': y,
                        'width': width, 'height': height
                    }, save_immediately=False)
                    self.settings.save()
        except Exception:
            pass

        # Release instance lock
        InstanceLocker.release_lock()

        # Quit Tk
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

        sys.exit(0)

    def run(self):
        """Start application."""
        self.root.mainloop()


if __name__ == "__main__":
    try:
        app = EaseViewApp()
        app.run()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        try:
            messagebox.showerror("Fatal Error", f"Application encountered an error:\n{e}")
        except:
            print(f"Fatal error: {e}")
        sys.exit(1)
