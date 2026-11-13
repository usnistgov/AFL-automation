"""
Tests for AFL.automation.APIServer core functionality
"""
import pytest
import tempfile
import json
import logging
from pathlib import Path
from types import SimpleNamespace

from AFL.automation.APIServer import APIServer
from AFL.automation.APIServer.Client import Client
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.APIServer.DummyDriver import DummyDriver
from AFL.automation.APIServer.QueueDaemon import QueueDaemon


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

    def test_init_logging_does_not_duplicate_file_handlers(self, tmp_path):
        server = APIServer(name='LoggingServer', afl_home=tmp_path)
        logfile = (tmp_path / 'LoggingServer.log').resolve()

        server.init_logging()

        handlers = [
            handler for handler in server.app.logger.handlers
            if isinstance(handler, logging.FileHandler)
            and Path(handler.baseFilename).resolve() == logfile
        ]
        assert len(handlers) == 1
        assert handlers[0] in logging.getLogger('werkzeug').handlers
        assert server.app.logger.propagate is False

    def test_apiserver_log_records_do_not_reach_root_handlers(self, tmp_path):
        server = APIServer(name='NonPropagatingServer', afl_home=tmp_path)
        root_records = []

        class RecordingHandler(logging.Handler):
            def emit(self, record):
                root_records.append(record)

        root_handler = RecordingHandler()
        root_logger = logging.getLogger()
        root_logger.addHandler(root_handler)
        try:
            server.app.logger.warning('single server log record')
        finally:
            root_logger.removeHandler(root_handler)

        assert root_records == []

    def test_apiserver_create_queue(self, dummy_driver):
        """Test that APIServer can create a queue with a driver"""
        server = APIServer(name='TestServer')
        server.create_queue(dummy_driver, add_unqueued=False)
        
        assert server.driver == dummy_driver
        assert dummy_driver.app is not None
        assert dummy_driver.app == server.app

    def test_driver_log_level_configures_attached_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv('AFL_HOME', str(tmp_path))
        driver = DummyDriver(
            name='ConfiguredLoggingDriver',
            overrides={'log_level': 'WARNING'},
        )
        server = APIServer(name='ConfiguredLoggingServer', afl_home=tmp_path)

        server.create_queue(driver, add_unqueued=False)

        assert driver.config['log_level'] == 'WARNING'
        assert server.app.logger.level == logging.WARNING

        driver.set_config(log_level='ERROR')
        assert server.app.logger.level == logging.ERROR

    def test_apiserver_apps_static_route(self):
        server = APIServer(name='TestServer')
        client = server.app.test_client()

        response = client.get('/static/apps/server_page/css/style.css')

        assert response.status_code == 200
        assert b'body' in response.data

    def test_apiserver_static_app_alias_routes(self):
        server = APIServer(name='TestServer')
        server.add_standard_routes()
        client = server.app.test_client()

        for route in (
            '/static/config.html',
            '/static/config-retro.html',
            '/static/status.html',
        ):
            response = client.get(route)
            assert response.status_code == 200

    def test_apiserver_main_pages_render_from_apps(self, dummy_driver):
        server = APIServer(name='TestServer')
        server.create_queue(dummy_driver, add_unqueued=False)
        server.add_standard_routes()
        client = server.app.test_client()

        root_response = client.get('/')
        app_response = client.get('/app')

        assert root_response.status_code == 200
        assert b'Quick Links' in root_response.data
        assert app_response.status_code == 200
        assert b'Autonomous Formulations Lab' in app_response.data

    def test_apiserver_nested_driver_static_dirs(self, tmp_path):
        class NestedStaticDriver(DummyDriver):
            static_dirs = {
                'apps/example/js': tmp_path / 'js',
            }

        asset_dir = tmp_path / 'js'
        asset_dir.mkdir()
        asset_path = asset_dir / 'example.js'
        asset_path.write_text('console.log("nested");', encoding='utf-8')

        driver = NestedStaticDriver(name='NestedDriver')
        server = APIServer(name='TestServer')
        server.create_queue(driver, add_unqueued=False)
        client = server.app.test_client()

        response = client.get('/static/apps/example/js/example.js')

        assert response.status_code == 200
        assert b'nested' in response.data


@pytest.mark.parametrize(
    ("entry_id", "has_tiled_backend", "expected_status"),
    [
        ("QD-123", True, "written"),
        (None, True, "fallback"),
        (None, False, "not_configured"),
    ],
)
def test_queue_metadata_reports_tiled_write_outcome(
    entry_id, has_tiled_backend, expected_status
):
    daemon = object.__new__(QueueDaemon)
    daemon.data = SimpleNamespace(last_tiled_entry_id=entry_id)
    if has_tiled_backend:
        daemon.data.last_tiled_error = None
    package = {"meta": {}}

    daemon._attach_tiled_result_metadata(package)

    assert package["meta"]["tiled_entry_id"] == entry_id
    assert package["meta"]["tiled_status"] == expected_status


def test_client_wait_returns_requested_task_tiled_entry_id(monkeypatch):
    client = object.__new__(Client)
    client.url = "http://afl.test"
    client.headers = {}
    queue_history = [
        {"uuid": "QD-earlier", "meta": {"tiled_entry_id": "QD-earlier"}},
        {"uuid": "QD-requested", "meta": {"tiled_entry_id": "QD-requested"}},
        {"uuid": "QD-later", "meta": {"tiled_entry_id": "QD-later"}},
    ]

    class Response:
        def json(self):
            return [queue_history, [], []]

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: Response())

    result = client.wait(target_uuid="QD-requested", first_check_delay=0)

    assert result["tiled_entry_id"] == "QD-requested"


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
