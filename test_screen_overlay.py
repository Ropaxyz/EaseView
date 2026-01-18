"""
Unit tests for EaseView screen overlay application.
"""

import unittest
import json
import os
import tempfile
import shutil
from screen_overlay import SettingsManager, AsyncLogger, MonitorDetector, InstanceLocker

class TestSettingsManager(unittest.TestCase):
    """Test SettingsManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_settings_file = os.path.join(self.temp_dir, 'test_settings.json')
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)
    
    def test_default_settings(self):
        """Test default settings are correct."""
        from screen_overlay import SettingsManager, SETTINGS_FILE
        manager = SettingsManager()
        self.assertIsNotNone(manager.get('opacity'))
        self.assertIsNotNone(manager.get('density'))
    
    def test_settings_validation(self):
        """Test settings validation."""
        from screen_overlay import SettingsManager
        manager = SettingsManager()
        
        # Test opacity clamping
        manager.set('opacity', 2.0)  # Should clamp to 0.6
        self.assertLessEqual(manager.get('opacity'), 0.6)
        
        manager.set('opacity', -1.0)  # Should clamp to 0.1
        self.assertGreaterEqual(manager.get('opacity'), 0.1)
        
        # Test density clamping
        manager.set('density', 2.0)  # Should clamp to 1.5
        self.assertLessEqual(manager.get('density'), 1.5)
        
        manager.set('density', 0.1)  # Should clamp to 0.5
        self.assertGreaterEqual(manager.get('density'), 0.5)
    
    def test_settings_save_load(self):
        """Test settings save and load."""
        from screen_overlay import SettingsManager
        manager = SettingsManager()
        manager.settings_file = self.test_settings_file
        
        # Save settings
        manager.set('opacity', 0.4)
        manager.save()
        
        # Load settings
        manager2 = SettingsManager()
        manager2.settings_file = self.test_settings_file
        manager2.load()
        
        self.assertEqual(manager2.get('opacity'), 0.4)
    
    def test_profile_operations(self):
        """Test profile save, load, list, and delete."""
        from screen_overlay import SettingsManager, PROFILES_DIR
        manager = SettingsManager()
        
        # Create test profile
        profile_name = "test_profile"
        test_data = {'opacity': 0.5, 'density': 1.2}
        
        # Save profile
        result = manager.save_profile(profile_name, test_data)
        self.assertTrue(result)
        
        # List profiles
        profiles = manager.list_profiles()
        self.assertIn(profile_name, profiles)
        
        # Load profile
        manager2 = SettingsManager()
        result = manager2.load_profile(profile_name)
        self.assertTrue(result)
        
        # Delete profile
        result = manager.delete_profile(profile_name)
        self.assertTrue(result)
        
        # Verify deleted
        profiles = manager.list_profiles()
        self.assertNotIn(profile_name, profiles)


class TestLogger(unittest.TestCase):
    """Test AsyncLogger class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_log_file = os.path.join(self.temp_dir, 'test.log')
    
    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.test_log_file):
            os.remove(self.test_log_file)
        shutil.rmtree(self.temp_dir)
    
    def test_logger_creation(self):
        """Test logger can be created."""
        logger = AsyncLogger(log_file=self.test_log_file)
        self.assertIsNotNone(logger)
        logger.stop()
    
    def test_logging_operations(self):
        """Test logging operations."""
        logger = AsyncLogger(log_file=self.test_log_file)
        
        logger.info("Test info message")
        logger.warning("Test warning message")
        logger.error("Test error message")
        
        logger.stop()
        logger.queue.join()  # Wait for queue to empty
        
        # Verify log file was created
        self.assertTrue(os.path.exists(self.test_log_file))


class TestMonitorDetector(unittest.TestCase):
    """Test MonitorDetector class."""
    
    def test_get_monitors(self):
        """Test monitor detection returns at least one monitor."""
        monitors = MonitorDetector.get_monitors()
        self.assertGreater(len(monitors), 0)
        self.assertIn('width', monitors[0])
        self.assertIn('height', monitors[0])
        self.assertIn('x', monitors[0])
        self.assertIn('y', monitors[0])


class TestInstanceLocker(unittest.TestCase):
    """Test InstanceLocker class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        from screen_overlay import LOCK_FILE
        self.original_lock_file = LOCK_FILE
    
    def tearDown(self):
        """Clean up test fixtures."""
        InstanceLocker.release_lock()
        shutil.rmtree(self.temp_dir)
    
    def test_lock_acquire_release(self):
        """Test lock acquisition and release."""
        # Should be able to acquire lock
        result = InstanceLocker.acquire_lock()
        self.assertTrue(result)
        
        # Release lock
        InstanceLocker.release_lock()


if __name__ == '__main__':
    unittest.main()
