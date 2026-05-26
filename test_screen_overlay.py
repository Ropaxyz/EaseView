"""Tests for EaseView. Run with: python -m unittest test_screen_overlay -v"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import screen_overlay as so


class TestUpdateChecker(unittest.TestCase):

    def test_parse_version(self):
        self.assertEqual(so.UpdateChecker.parse_version("3.0"),    ((3, 0, 0), ""))
        self.assertEqual(so.UpdateChecker.parse_version("v3.1.0"), ((3, 1, 0), ""))
        self.assertEqual(so.UpdateChecker.parse_version("V3.1"),   ((3, 1, 0), ""))
        self.assertEqual(so.UpdateChecker.parse_version("3.2.0-rc1"),
                         ((3, 2, 0), "rc1"))
        self.assertIsNone(so.UpdateChecker.parse_version("notaversion"))
        self.assertIsNone(so.UpdateChecker.parse_version(""))

    def test_is_newer(self):
        self.assertTrue(so.UpdateChecker.is_newer("V3.1",   "3.0"))
        self.assertTrue(so.UpdateChecker.is_newer("v3.1.0", "3.0.9"))
        self.assertTrue(so.UpdateChecker.is_newer("4.0.0",  "3.99.99"))
        self.assertFalse(so.UpdateChecker.is_newer("3.0",    "3.0"))
        self.assertFalse(so.UpdateChecker.is_newer("2.9",    "3.0"))
        self.assertFalse(so.UpdateChecker.is_newer("bogus",  "3.0"))
        # pre-release sorts older than release at the same numeric version
        self.assertTrue(so.UpdateChecker.is_newer("3.0.0",  "3.0.0-rc1"))
        self.assertFalse(so.UpdateChecker.is_newer("3.0.0-rc1", "3.0.0"))

    def test_check_no_network(self):
        with mock.patch.object(so.UpdateChecker, "fetch_latest", return_value=None):
            self.assertIsNone(so.UpdateChecker.check("3.0"))

    def test_check_returns_available(self):
        with mock.patch.object(
                so.UpdateChecker, "fetch_latest",
                return_value={"tag_name": "V9.9", "html_url": "http://example",
                              "body": "notes", "prerelease": False, "assets": []}):
            result = so.UpdateChecker.check("3.0")
            self.assertTrue(result["available"])
            self.assertEqual(result["latest_version"], "9.9")
            self.assertEqual(result["current_version"], "3.0")


class TestHotkeyManager(unittest.TestCase):

    def test_tk_to_keyboard(self):
        self.assertEqual(so.HotkeyManager.tk_to_keyboard("Control+Shift+O"),
                         "ctrl+shift+o")
        self.assertEqual(so.HotkeyManager.tk_to_keyboard("ctrl+alt+up"),
                         "ctrl+alt+up")
        self.assertEqual(so.HotkeyManager.tk_to_keyboard("Super+Space"),
                         "windows+space")
        self.assertEqual(so.HotkeyManager.tk_to_keyboard("ESC"), "esc")
        self.assertEqual(so.HotkeyManager.tk_to_keyboard(""), "")

    def test_dispatcher_runs_callback(self):
        # The wrapped callback must always go through the dispatcher,
        # otherwise the keyboard library would call Tk from its own thread.
        dispatched = []
        ran = []
        hm = so.HotkeyManager(
            callbacks={"toggle": lambda: ran.append("ran")},
            dispatch=lambda fn: (dispatched.append("d"), fn()))
        hm._wrap_for_main_thread("toggle", lambda: ran.append("ran"))()
        self.assertEqual(dispatched, ["d"])
        self.assertEqual(ran, ["ran"])

    def test_dispatcher_swallows_exceptions(self):
        def boom():
            raise RuntimeError("kaboom")
        hm = so.HotkeyManager(callbacks={"x": boom}, dispatch=lambda fn: fn())
        hm._wrap_for_main_thread("x", boom)()  # must not raise


class TestScheduleRange(unittest.TestCase):

    def test_normal_range(self):
        from datetime import time as t
        self.assertTrue (so.ScheduleManager._in_range(t(10, 0), t(9, 0),  t(17, 0)))
        self.assertFalse(so.ScheduleManager._in_range(t(8, 0),  t(9, 0),  t(17, 0)))
        self.assertFalse(so.ScheduleManager._in_range(t(18, 0), t(9, 0),  t(17, 0)))

    def test_overnight_range(self):
        from datetime import time as t
        self.assertTrue (so.ScheduleManager._in_range(t(23, 0), t(22, 0), t(6, 0)))
        self.assertTrue (so.ScheduleManager._in_range(t(2, 0),  t(22, 0), t(6, 0)))
        self.assertFalse(so.ScheduleManager._in_range(t(12, 0), t(22, 0), t(6, 0)))

    def test_zero_range(self):
        from datetime import time as t
        self.assertFalse(so.ScheduleManager._in_range(t(12, 0), t(12, 0), t(12, 0)))


class TestSettingsManager(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="easeview_test_")
        self.path = os.path.join(self.tmp, "settings.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults(self):
        m = so.SettingsManager(settings_file=self.path)
        self.assertGreaterEqual(m.get("opacity"), 0.1)
        self.assertLessEqual(m.get("opacity"), 0.6)
        self.assertGreaterEqual(m.get("density"), 0.5)
        self.assertLessEqual(m.get("density"), 1.5)

    def test_validation_clamps(self):
        with open(self.path, "w") as fh:
            json.dump({"opacity": 99.0, "density": -5.0,
                       "custom_color": "not_a_hex"}, fh)
        m = so.SettingsManager(settings_file=self.path)
        self.assertLessEqual(m.get("opacity"), 0.6)
        self.assertGreaterEqual(m.get("density"), 0.5)
        self.assertIsNone(m.get("custom_color"))

    def test_save_and_reload(self):
        m = so.SettingsManager(settings_file=self.path)
        m.set("opacity", 0.42)
        m.set("custom_color", "#abcdef")
        m2 = so.SettingsManager(settings_file=self.path)
        self.assertAlmostEqual(m2.get("opacity"), 0.42, places=3)
        self.assertEqual(m2.get("custom_color"), "#abcdef")

    def test_corrupt_file_is_recovered(self):
        with open(self.path, "w") as fh:
            fh.write("this is not json {{{")
        m = so.SettingsManager(settings_file=self.path)
        self.assertIsNotNone(m.get("opacity"))
        backups = [f for f in os.listdir(self.tmp)
                   if f.startswith("settings.json.corrupt")]
        self.assertTrue(backups)

    def test_save_writes_valid_json(self):
        m = so.SettingsManager(settings_file=self.path)
        m.set("opacity", 0.5)
        with open(self.path, "rb") as fh:
            data = fh.read()
        self.assertGreater(len(data), 10)
        json.loads(data.decode("utf-8"))

    def test_hotkey_migration_normalises_format(self):
        with open(self.path, "w") as fh:
            json.dump({"version": 4,
                       "hotkeys": {"toggle": "Control+Shift+O"}}, fh)
        m = so.SettingsManager(settings_file=self.path)
        self.assertEqual(m.get("hotkeys")["toggle"], "ctrl+shift+o")

    def test_profile_save_and_list(self):
        m = so.SettingsManager(settings_file=self.path)
        original = so.PROFILES_DIR
        so.PROFILES_DIR = os.path.join(self.tmp, "profiles")
        os.makedirs(so.PROFILES_DIR, exist_ok=True)
        try:
            self.assertTrue(m.save_profile("test profile"))
            self.assertIn("test profile", m.list_profiles())
            self.assertTrue(m.delete_profile("test profile"))
            self.assertNotIn("test profile", m.list_profiles())
        finally:
            so.PROFILES_DIR = original

    def test_invalid_profile_name_rejected(self):
        m = so.SettingsManager(settings_file=self.path)
        self.assertFalse(m.save_profile(""))
        self.assertFalse(m.save_profile("../escape"))

    def test_global_hotkeys_default_off(self):
        self.assertFalse(
            so.SettingsManager.DEFAULT_SETTINGS["enable_global_hotkeys"])


class TestAsyncLogger(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="easeview_log_")
        self.log = os.path.join(self.tmp, "log.txt")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_logs_and_stops_cleanly(self):
        lg = so.AsyncLogger(log_file=self.log)
        lg.info("hello")
        lg.warning("warn")
        lg.error("err")
        lg.stop()
        self.assertTrue(os.path.exists(self.log))
        with open(self.log, "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("hello", content)
        self.assertIn("warn",  content)
        self.assertIn("err",   content)


class TestMonitorDetector(unittest.TestCase):

    def test_returns_at_least_one(self):
        ms = so.MonitorDetector.get_monitors()
        self.assertGreaterEqual(len(ms), 1)
        for k in ("x", "y", "width", "height", "work_x", "work_y",
                  "work_width", "work_height"):
            self.assertIn(k, ms[0])

    def test_primary_returns_a_monitor(self):
        self.assertIn("width", so.MonitorDetector.primary())


class TestOverlayDensity(unittest.TestCase):

    def test_unchanged_at_1(self):
        self.assertEqual(
            so.OverlayManager._apply_density("#FFD54F", 1.0).lower(),
            "#ffd54f")

    def test_lightens_below_1(self):
        out = so.OverlayManager._apply_density("#000000", 0.5)
        self.assertGreater(int(out[1:3], 16), 100)

    def test_invalid_hex_returns_original(self):
        self.assertEqual(so.OverlayManager._apply_density("garbage", 1.2),
                         "garbage")


if __name__ == "__main__":
    unittest.main()
