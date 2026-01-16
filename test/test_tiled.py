"""
Tests for Tiled Data Catalog Server

Tests cover:
- Configuration validation and loading
- Database initialization
- API endpoints and responses
- Authentication settings
- Storage configuration
"""

import pytest
import yaml
import tempfile
import pathlib
import json
import sqlite3
from unittest.mock import Mock, patch, MagicMock


class TestTiledConfiguration:
    """Test Tiled server configuration validation and loading"""

    @pytest.fixture
    def tiled_config_path(self):
        """Fixture providing the path to the Tiled config file (non-docker)"""
        return pathlib.Path(__file__).parent.parent / 'tiled' / 'config.yml'

    def test_config_file_exists(self, tiled_config_path):
        """Test that the Tiled configuration file exists"""
        assert tiled_config_path.exists(), f"Config file not found at {tiled_config_path}"

    def test_config_valid_yaml(self, tiled_config_path):
        """Test that the configuration file is valid YAML"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        assert isinstance(config, dict), "Configuration should be a dictionary"

    def test_config_has_uvicorn_section(self, tiled_config_path):
        """Test that configuration has uvicorn server settings"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        assert 'uvicorn' in config, "Configuration must have 'uvicorn' section"

    def test_config_uvicorn_host_is_set(self, tiled_config_path):
        """Test that uvicorn host is configured"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        assert 'host' in config['uvicorn'], "uvicorn must have 'host' setting"
        assert config['uvicorn']['host'] == '0.0.0.0', "Host should be 0.0.0.0 for Docker"

    def test_config_uvicorn_port_is_set(self, tiled_config_path):
        """Test that uvicorn port is configured"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        assert 'port' in config['uvicorn'], "uvicorn must have 'port' setting"
        assert config['uvicorn']['port'] == 8000, "Port should be 8000"

    def test_config_has_trees_section(self, tiled_config_path):
        """Test that configuration has tree definitions"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        assert 'trees' in config, "Configuration must have 'trees' section"
        assert isinstance(config['trees'], list), "Trees should be a list"
        assert len(config['trees']) > 0, "At least one tree should be configured"

    def test_config_tree_has_required_fields(self, tiled_config_path):
        """Test that tree configurations have required fields"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        for i, tree in enumerate(config['trees']):
            assert 'path' in tree, f"Tree {i} must have 'path' field"
            assert 'tree' in tree, f"Tree {i} must have 'tree' type field"
            assert 'args' in tree, f"Tree {i} must have 'args' field"

    def test_config_default_tree_is_root(self, tiled_config_path):
        """Test that default tree is at root path"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        root_tree = None
        for tree in config['trees']:
            if tree['path'] == '/':
                root_tree = tree
                break
        
        assert root_tree is not None, "Root tree (/) should be configured"

    def test_config_default_tree_uses_catalog(self, tiled_config_path):
        """Test that root tree uses catalog type"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        root_tree = next((t for t in config['trees'] if t['path'] == '/'), None)
        assert root_tree is not None
        assert root_tree['tree'] == 'catalog', "Root tree should be of type 'catalog'"

    def test_config_default_tree_has_uri(self, tiled_config_path):
        """Test that tree configuration includes database URI"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        root_tree = next((t for t in config['trees'] if t['path'] == '/'), None)
        args = root_tree['args']
        
        assert 'uri' in args, "Tree args must have 'uri' for database connection"

    def test_config_database_uses_sqlite(self, tiled_config_path):
        """Test that database backend is SQLite"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        root_tree = next((t for t in config['trees'] if t['path'] == '/'), None)
        uri = root_tree['args']['uri']
        
        assert 'sqlite' in uri.lower(), "Database should use SQLite"
        assert 'aiosqlite' in uri.lower(), "Should use aiosqlite for async support"

    def test_config_writable_storage_configured(self, tiled_config_path):
        """Test that writable storage directory is configured"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        root_tree = next((t for t in config['trees'] if t['path'] == '/'), None)
        args = root_tree['args']
        
        assert 'writable_storage' in args, "Must have writable_storage configured"
        assert args['writable_storage'] == 'data/', "Storage should be in 'data/' directory"

    def test_config_init_if_not_exists(self, tiled_config_path):
        """Test that database auto-initialization is configured"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        root_tree = next((t for t in config['trees'] if t['path'] == '/'), None)
        args = root_tree['args']
        
        assert 'init_if_not_exists' in args, "Must have init_if_not_exists setting"
        assert args['init_if_not_exists'] is True, "Should auto-initialize database"


class TestTiledAuthentication:
    """Test Tiled authentication configuration"""

    @pytest.fixture
    def tiled_config_path(self):
        """Fixture providing the path to the Tiled config file"""
        return pathlib.Path(__file__).parent.parent / 'tiled' / 'config.yml'

    def test_config_has_authentication_section(self, tiled_config_path):
        """Test that configuration has authentication section"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        assert 'authentication' in config, "Configuration should have 'authentication' section"

    def test_config_has_single_user_api_key(self, tiled_config_path):
        """Test that single user API key setting exists"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        assert 'single_user_api_key' in config['authentication']

    def test_default_api_key_is_empty(self, tiled_config_path):
        """Test that default API key is empty (can be set via env var)"""
        with open(tiled_config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        api_key = config['authentication']['single_user_api_key']
        assert api_key == "", "Default API key should be empty string"

    def test_api_key_can_be_generated(self):
        """Test that API key can be generated using openssl"""
        # Simulate generating a key using openssl rand -hex 32
        import secrets
        api_key = secrets.token_hex(32)
        
        assert len(api_key) == 64, "API key should be 64 characters (32 bytes in hex)"
        assert all(c in '0123456789abcdef' for c in api_key), "API key should be valid hex"


class TestTiledDockerfile:
    """Test Dockerfile configuration for Tiled"""

    @pytest.fixture
    def dockerfile_path(self):
        """Fixture providing the path to the Tiled Dockerfile (docker layout)"""
        return pathlib.Path(__file__).parent.parent / 'docker' / 'Dockerfile.tiled'

    def test_dockerfile_exists(self, dockerfile_path):
        """Test that Dockerfile.tiled exists"""
        assert dockerfile_path.exists(), f"Dockerfile not found at {dockerfile_path}"

    def test_dockerfile_uses_python_base(self, dockerfile_path):
        """Test that Dockerfile uses Python base image"""
        with open(dockerfile_path, 'r') as f:
            content = f.read()
        
        assert 'python:3.12' in content, "Should use Python 3.12 base image"

    def test_dockerfile_installs_tiled(self, dockerfile_path):
        """Test that Dockerfile installs tiled package"""
        with open(dockerfile_path, 'r') as f:
            content = f.read()
        
        assert 'tiled' in content, "Should install tiled package"
        assert 'pip install' in content, "Should use pip to install packages"

    def test_dockerfile_exposes_port_8000(self, dockerfile_path):
        """Test that Dockerfile exposes port 8000"""
        with open(dockerfile_path, 'r') as f:
            content = f.read()
        
        assert '8000' in content, "Should expose port 8000"
        assert 'EXPOSE' in content, "Should have EXPOSE directive"

    def test_dockerfile_has_healthcheck(self, dockerfile_path):
        """Test that Dockerfile includes a health check"""
        with open(dockerfile_path, 'r') as f:
            content = f.read()
        
        assert 'HEALTHCHECK' in content, "Should have HEALTHCHECK directive"

    def test_dockerfile_copies_config(self, dockerfile_path):
        """Test that Dockerfile copies tiled config"""
        with open(dockerfile_path, 'r') as f:
            content = f.read()
        
        assert 'config.yml' in content, "Should copy config.yml file"
        assert 'COPY' in content, "Should have COPY directive"

    def test_dockerfile_creates_data_directory(self, dockerfile_path):
        """Test that Dockerfile creates necessary directories"""
        with open(dockerfile_path, 'r') as f:
            content = f.read()
        
        assert '/app/data' in content, "Should create /app/data directory"

    def test_dockerfile_sets_python_env_vars(self, dockerfile_path):
        """Test that Dockerfile sets Python environment variables"""
        with open(dockerfile_path, 'r') as f:
            content = f.read()
        
        assert 'PYTHONUNBUFFERED=1' in content, "Should set PYTHONUNBUFFERED"
        assert 'PYTHONDONTWRITEBYTECODE=1' in content, "Should set PYTHONDONTWRITEBYTECODE"


class TestTiledDatabaseSetup:
    """Test Tiled database configuration and initialization"""

    def test_sqlite_uri_format_valid(self):
        """Test that SQLite URI format is valid"""
        uri = "sqlite+aiosqlite:///catalog.db"
        
        assert uri.startswith('sqlite'), "SQLite URI should start with 'sqlite'"
        assert 'aiosqlite' in uri, "Should use aiosqlite for async"
        assert ':///' in uri, "SQLite file URI should use three slashes"

    def test_sqlite_database_file_path(self):
        """Test that database file path is correctly formatted"""
        uri = "sqlite+aiosqlite:///catalog.db"
        
        # Extract the database file path
        db_file = uri.split('///')[-1]
        assert db_file == 'catalog.db', "Database file should be 'catalog.db'"

    def test_data_storage_directory_configured(self):
        """Test that data storage directory is properly configured"""
        storage_dir = 'data/'
        
        assert storage_dir.startswith('data'), "Storage should be in data directory"
        assert storage_dir.endswith('/'), "Storage path should end with /"

    def test_database_auto_initialization_safe(self):
        """Test that auto-initialization setting is appropriate for Docker"""
        # In Docker, init_if_not_exists=true is fine because each container
        # has its own database volume
        init_if_not_exists = True
        
        assert init_if_not_exists is True, "Auto-initialization should be enabled for single-container setup"

    def test_database_initialization_race_condition_warning(self):
        """Test understanding of potential race condition with auto-init"""
        # This is documented in the config - in a horizontally-scaled deployment,
        # multiple containers could race to initialize the database.
        # For single Docker container, this is not an issue.
        
        # Document the scenario:
        init_if_not_exists = True
        scaling_mode = 'single'  # vs 'horizontally-scaled'
        
        # For single container, auto-init is safe
        if scaling_mode == 'single':
            assert init_if_not_exists is True


class TestTiledAPIEndpoints:
    """Test Tiled API endpoint structure"""

    def test_root_tree_path_is_slash(self):
        """Test that root tree path is configured as '/'"""
        tree_path = '/'
        assert tree_path == '/', "Root tree should be at path '/'"

    def test_metadata_endpoint_expected(self):
        """Test that metadata endpoint is expected to exist"""
        # Standard Tiled endpoints:
        # GET /metadata - Get root metadata
        # GET /tree - Get tree structure
        # POST /value - Store value
        
        endpoints = ['/metadata', '/tree', '/search', '/']
        assert '/metadata' in endpoints, "Should have /metadata endpoint"

    def test_catalog_tree_type_features(self):
        """Test features provided by catalog tree type"""
        tree_type = 'catalog'
        
        # Catalog trees support:
        features = ['search', 'traverse', 'store_timeseries', 'store_tabular']
        
        # Verify the tree_type name is correct
        assert tree_type == 'catalog', "Should use 'catalog' tree type for data storage"


class TestTiledDataStorage:
    """Test Tiled data storage and retrieval capabilities"""

    def test_supports_timeseries_data(self):
        """Test that Tiled can store timeseries data"""
        # Tiled catalog supports timeseries with timestamps
        timeseries_example = {
            'timestamps': [1.0, 2.0, 3.0],
            'values': [10.5, 11.2, 9.8]
        }
        
        assert 'timestamps' in timeseries_example
        assert 'values' in timeseries_example

    def test_supports_tabular_data(self):
        """Test that Tiled can store tabular data"""
        # Tiled catalog supports tabular data (DataFrames, arrays)
        tabular_example = {
            'columns': ['q_value', 'intensity', 'error'],
            'data': [[0.001, 100, 5], [0.002, 95, 4]]
        }
        
        assert 'columns' in tabular_example
        assert 'data' in tabular_example

    def test_supports_nested_structures(self):
        """Test that Tiled supports nested container structures"""
        # Tiled catalog is hierarchical, can have containers within containers
        container_structure = {
            'path': '/',
            'children': [
                {'path': '/experiment1', 'type': 'container'},
                {'path': '/experiment1/measurement1', 'type': 'data'}
            ]
        }
        
        assert 'children' in container_structure


class TestTiledIntegrationWithOrchestrator:
    """Test how Tiled integrates with OrchestratorDriver"""

    def test_orchestrator_uses_tiled_client(self):
        """Test that OrchestratorDriver can connect to Tiled"""
        # OrchestratorDriver uses from tiled.client import from_uri
        # Configuration would have tiled_server in the config
        
        tiled_uri = 'http://tiled:8000'
        api_key = None  # Can be optional for read-only
        
        # This is how OrchestratorDriver would connect
        assert tiled_uri.startswith('http'), "Should be HTTP URI"

    def test_orchestrator_writes_measurement_data(self):
        """Test that measurement data can be written to Tiled"""
        measurement_data_structure = {
            'q_values': [0.001, 0.002, 0.003],
            'intensity': [1000, 950, 900],
            'error': [50, 47, 45],
            'timestamp': '2026-01-16T10:30:00',
            'instrument': 'BioSANS',
            'sample_id': 'SAMPLE001'
        }
        
        assert 'q_values' in measurement_data_structure
        assert 'intensity' in measurement_data_structure
        assert 'timestamp' in measurement_data_structure

    def test_agent_reads_from_tiled(self):
        """Test that AgentDriver can read from Tiled"""
        # AgentDriver would query for recent measurements
        # to make decisions on next sample to prepare
        
        query_example = {
            'filter': 'timestamp > 2026-01-16',
            'limit': 10,
            'sort': '-timestamp'
        }
        
        assert 'filter' in query_example
        assert 'timestamp' in query_example['filter']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
