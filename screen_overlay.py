# ============================================================================
# EaseView - Screen Colour Overlay Tool
# R.Paxton 2025
# ============================================================================

import tkinter as tk
from tkinter import colorchooser, Menu, messagebox
import pystray
from PIL import Image, ImageDraw
import threading
import sys
import ctypes
import os
import json
from datetime import datetime

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
SETTINGS_FILE = os.path.join(os.path.expanduser('~'), '.easeview_settings.json')
LOG_FILE = os.path.join(os.path.expanduser('~'), '.easeview.log')
SETTINGS_VERSION = 3
VERSION = "2.3"


# ============================================================================
# LOGGER
# ============================================================================
class Logger:
    """Simple file logger for debugging production issues."""

    def __init__(self, log_file=LOG_FILE, max_lines=500):
        self.log_file = log_file
        self.max_lines = max_lines

    def log(self, level, message):
        """Write timestamped log entry."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = f"[{timestamp}] [{level}] {message}\n"

            # Append to log
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(entry)

            # Trim if too large
            self._trim_log()
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


# Global logger instance
logger = Logger()


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
    }

    def __init__(self, settings_file=SETTINGS_FILE):
        self.settings_file = settings_file
        self.settings = self.DEFAULT_SETTINGS.copy()
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
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value
        self.save()


# ============================================================================
# OVERLAY MANAGER
# ============================================================================
class OverlayManager:
    """Manages the fullscreen overlay window lifecycle."""

    def __init__(self, root):
        self.root = root
        self.overlay_window = None
        self.is_active = False
        self.current_color = None
        self.current_opacity = 0.3
        self.current_density = 1.0

    def create(self, color, opacity, density=1.0):
        """Create or update the overlay window."""
        self.current_color = color
        self.current_opacity = opacity
        self.current_density = density

        # Destroy existing overlay
        if self.overlay_window:
            try:
                self.overlay_window.destroy()
            except Exception as e:
                logger.warning(f"Error destroying old overlay: {e}")
            self.overlay_window = None

        try:
            # Create overlay window
            self.overlay_window = tk.Toplevel(self.root)
            self.overlay_window.attributes('-fullscreen', True)
            self.overlay_window.attributes('-topmost', True)
            self.overlay_window.attributes('-alpha', opacity)

            # Apply density-adjusted color
            adjusted_color = self._apply_density(color, density)
            self.overlay_window.configure(bg=adjusted_color)
            self.overlay_window.overrideredirect(True)

            # Make click-through
            self.overlay_window.update()
            success = self._make_click_through()

            if not success:
                logger.error("Failed to make overlay click-through, destroying")
                self.destroy()
                return False

            self.is_active = True
            logger.info(f"Overlay created: color={color}, opacity={opacity}, density={density}")
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

    def _make_click_through(self):
        """Make overlay window click-through using Windows API."""
        if not self.overlay_window:
            return False

        try:
            # Get window handle
            hwnd = self.overlay_window.winfo_id()
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

            style = ctypes.windll.user32.GetWindowLongW(target_hwnd, GWL_EXSTYLE)
            new_style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            result = ctypes.windll.user32.SetWindowLongW(target_hwnd, GWL_EXSTYLE, new_style)

            if result == 0:
                # Check for error
                error = ctypes.get_last_error()
                if error:
                    logger.error(f"SetWindowLongW failed with error: {error}")
                    return False

            logger.info("Click-through enabled successfully")
            return True

        except Exception as e:
            logger.error(f"Click-through setup failed: {e}")
            return False

    def update_opacity(self, opacity):
        """Update overlay opacity."""
        self.current_opacity = opacity
        if self.overlay_window and self.is_active:
            try:
                self.overlay_window.attributes('-alpha', opacity)
            except Exception as e:
                logger.warning(f"Failed to update opacity: {e}")

    def update_density(self, density):
        """Update overlay density (color intensity)."""
        self.current_density = density
        if self.overlay_window and self.is_active and self.current_color:
            try:
                adjusted_color = self._apply_density(self.current_color, density)
                self.overlay_window.configure(bg=adjusted_color)
            except Exception as e:
                logger.warning(f"Failed to update density: {e}")

    def show(self):
        """Show the overlay."""
        if self.overlay_window:
            try:
                self.overlay_window.deiconify()
                self.is_active = True
            except Exception as e:
                logger.warning(f"Failed to show overlay: {e}")

    def hide(self):
        """Hide the overlay without destroying it."""
        if self.overlay_window:
            try:
                self.overlay_window.withdraw()
                self.is_active = False
            except Exception as e:
                logger.warning(f"Failed to hide overlay: {e}")

    def toggle(self):
        """Toggle overlay visibility."""
        if self.is_active:
            self.hide()
        elif self.overlay_window:
            self.show()
        return self.is_active

    def destroy(self):
        """Destroy the overlay window."""
        if self.overlay_window:
            try:
                self.overlay_window.destroy()
            except Exception:
                pass
            self.overlay_window = None
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
        """Create tray menu."""
        return pystray.Menu(
            pystray.MenuItem("Show/Hide Overlay",
                           lambda: self.callbacks.get('toggle_overlay', lambda: None)(),
                           default=True),
            pystray.MenuItem("Open Settings",
                           lambda: self.callbacks.get('show_window', lambda: None)()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Help",
                           lambda: self.callbacks.get('show_help', lambda: None)()),
            pystray.MenuItem("About",
                           lambda: self.callbacks.get('show_about', lambda: None)()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit",
                           lambda: self.callbacks.get('quit_app', lambda: None)())
        )

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
        # Initialize Tk
        self.root = tk.Tk()
        self.root.title("EaseView - R.Paxton 2026")

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

        # UI state
        self.colour_buttons = {}
        self.custom_button = None
        self.toggle_button = None
        self.active_preset = self.settings.get('preset_name')
        self.custom_color = self.settings.get('custom_color')

        # Build UI
        self.set_window_icon()
        self.setup_window()
        self.create_menu_bar()
        self.bind_keyboard_shortcuts()

        # Restore active selection state
        self._update_selection_ui()

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
        file_menu.add_command(label="Exit", command=self.quit_app)

        help_menu = Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Keyboard Shortcuts", command=self.show_shortcuts)
        help_menu.add_command(label="How to Use", command=self.show_help)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about)

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
        self.active_preset = name
        self.settings.set('preset_name', name)
        self.settings.set('custom_color', color)
        self._update_selection_ui()
        self.apply_overlay(color)

    def choose_custom_color(self):
        """Open colour picker."""
        initial = self.custom_color if self.custom_color else "#FFD54F"
        color = colorchooser.askcolor(title="Choose overlay colour", initialcolor=initial)
        if color[1]:
            self.active_preset = None
            self.custom_color = color[1]
            self.settings.set('preset_name', None)
            self.settings.set('custom_color', color[1])
            self._update_selection_ui()
            self.apply_overlay(color[1])

    def apply_overlay(self, color):
        """Apply overlay with given colour."""
        opacity = self.settings.get('opacity', 0.3)
        density = self.settings.get('density', 1.0)
        success = self.overlay.create(color, opacity, density)

        if success:
            self.settings.set('overlay_enabled', True)
            self.toggle_button.set_state(True)
            self.root.attributes('-topmost', True)
            self.root.lift()

            # Create tray icon if needed
            self.tray.create(color)
        else:
            messagebox.showerror("Error",
                "Failed to create overlay. The overlay may not work correctly on this system.")

    def toggle_overlay(self):
        """Toggle overlay on/off."""
        if self.overlay.is_active:
            self.hide_overlay()
        elif self.overlay.current_color:
            self.overlay.show()
            self.settings.set('overlay_enabled', True)
            self.toggle_button.set_state(True)
        elif self.custom_color or self.active_preset:
            # Re-create overlay with last colour
            color = self.custom_color if self.active_preset is None else self.PRESETS.get(self.active_preset, {}).get('color')
            if color:
                self.apply_overlay(color)

    def hide_overlay(self):
        """Hide overlay (emergency escape)."""
        self.overlay.hide()
        self.settings.set('overlay_enabled', False)
        self.toggle_button.set_state(False)

    def on_opacity_change(self, value):
        """Handle opacity slider change."""
        opacity = float(value) / 100
        self.settings.set('opacity', opacity)
        self.opacity_value_label.configure(text=f"{int(float(value))}%")
        self.overlay.update_opacity(opacity)

    def on_density_change(self, value):
        """Handle density slider change."""
        density = float(value) / 100
        self.settings.set('density', density)
        self.density_value_label.configure(text=f"{int(float(value))}%")
        self.overlay.update_density(density)

    def quit_app(self):
        """Clean shutdown."""
        logger.info("EaseView shutting down")

        # Stop tray first
        self.tray.stop()

        # Destroy overlay
        self.overlay.destroy()

        # Save final settings
        self.settings.save()

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
    app = EaseViewApp()
    app.run()
