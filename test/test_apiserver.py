"""
Tests for AFL.automation.APIServer core functionality
"""
import pytest
import tempfile
import json
from pathlib import Path

from AFL.automation.APIServer import APIServer
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.APIServer.DummyDriver import DummyDriver


class TestDriver:
    """Test Driver base class"""

    def test_driver_initialization(self):
        """Test that Driver can be initialized"""
        driver = DummyDriver(name='TestDriver')
        assert driver.name == 'TestDriver'
        assert hasattr(driver, 'config')
        assert hasattr(driver, 'logger')

    def test_driver_config_creation(self):
        """Test that config directory and file are created"""
        driver = DummyDriver(name='TestDriver')
        assert driver.path.exists()
        assert driver.filepath.exists() or driver.filepath.parent.exists()

    def test_driver_with_overrides(self):
        """Test driver initialization with override config values"""
        overrides = {'speed of light': 2.5e8}
        driver = DummyDriver(
            name='TestDriver',
            overrides=overrides
        )
        assert driver.config['speed of light'] == 2.5e8

    def test_driver_useful_links(self):
        """Test that useful_links are set correctly"""
        useful_links = {
            "Documentation": "/docs",
            "Dashboard": "/dashboard"
        }
        driver = DummyDriver(name='TestDriver', useful_links=useful_links)
        assert "Documentation" in driver.useful_links
        assert "Dashboard" in driver.useful_links
        # Tiled Browser should be added by default
        assert "Tiled Browser" in driver.useful_links

    def test_driver_static_dirs(self):
        """Test that static directories are configured"""
        driver = DummyDriver(name='TestDriver')
        assert hasattr(driver, 'static_dirs')
        assert isinstance(driver.static_dirs, dict)

    def test_queued_decorator_registration(self):
        """Test that @Driver.queued decorator registers methods"""
        # DummyDriver should have queued methods registered
        assert len(Driver.queued.functions) > 0
        assert 'test_command1' in Driver.queued.functions

    def test_unqueued_decorator_registration(self):
        """Test that @Driver.unqueued decorator registers methods"""
        # DummyDriver should have unqueued methods registered
        assert len(Driver.unqueued.functions) > 0
        assert 'how_many' in Driver.unqueued.functions


class TestDummyDriver:
    """Test DummyDriver implementation"""

    def test_dummy_driver_initialization(self):
        """Test DummyDriver initialization"""
        driver = DummyDriver(name='TestDummy')
        assert driver.name == 'TestDummy'

    def test_dummy_driver_status(self):
        """Test DummyDriver status method"""
        driver = DummyDriver(name='TestDummy')
        status = driver.status()
        assert isinstance(status, list)
        assert len(status) > 0

    def test_dummy_driver_how_many(self):
        """Test DummyDriver how_many method"""
        driver = DummyDriver(name='TestDummy')
        # Need to set up app for logging
        from flask import Flask
        driver.app = Flask('test')
        result = driver.how_many(count=5)
        assert isinstance(result, str)
        assert '5' in result


class TestAPIServer:
    """Test APIServer class"""

    @pytest.fixture
    def dummy_driver(self):
        """Create a DummyDriver instance for testing"""
        return DummyDriver(name='TestAPIServer')

    def test_apiserver_initialization(self):
        """Test APIServer initialization"""
        server = APIServer(
            name='TestServer',
            experiment='Test Experiment',
            contact='test@example.com'
        )
        assert server.name == 'TestServer'
        assert server.experiment == 'Test Experiment'
        assert server.contact == 'test@example.com'

    def test_apiserver_has_flask_app(self):
        """Test that APIServer creates a Flask app"""
        server = APIServer(name='TestServer')
        assert hasattr(server, 'app')
        assert server.app is not None

    def test_apiserver_create_queue(self, dummy_driver):
        """Test that APIServer can create a queue with a driver"""
        server = APIServer(name='TestServer')
        server.create_queue(dummy_driver, add_unqueued=False)
        
        assert server.driver == dummy_driver
        assert dummy_driver.app is not None
        assert dummy_driver.app == server.app


def test_import_apiserver():
    """Test that APIServer can be imported"""
    from AFL.automation.APIServer import APIServer
    assert APIServer is not None


def test_import_driver():
    """Test that Driver can be imported"""
    from AFL.automation.APIServer.Driver import Driver
    assert Driver is not None


def test_import_dummy_driver():
    """Test that DummyDriver can be imported"""
    from AFL.automation.APIServer.DummyDriver import DummyDriver
    assert DummyDriver is not None


def test_import_client():
    """Test that Client can be imported"""
    from AFL.automation.APIServer.Client import Client
    assert Client is not None


def test_apiserver_module_all():
    """Test that __all__ exports are correct"""
    import AFL.automation.APIServer as apiserver_module
    assert hasattr(apiserver_module, '__all__')
    assert 'APIServer' in apiserver_module.__all__
