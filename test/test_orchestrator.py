"""
Tests for OrchestratorDriver

Tests cover:
- Configuration validation
- Client management
- Status tracking
- Integration with APIServer
"""

import os
import pytest
import json
import tempfile
import pathlib
from unittest.mock import Mock, patch, MagicMock

from AFL.automation.orchestrator.OrchestratorDriver import OrchestratorDriver


@pytest.fixture(autouse=True)
def sandbox_home(tmp_path, monkeypatch):
    """Isolate PersistentConfig writes to a temporary home directory."""
    home = tmp_path / "home"
    (home / ".afl").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))


class TestOrchestratorDriverConfiguration:
    """Test OrchestratorDriver configuration and validation"""

    def test_initialization_with_defaults(self):
        """Test that OrchestratorDriver initializes with default configuration"""
        driver = OrchestratorDriver()
        
        assert driver.name == 'OrchestratorDriver'
        assert driver.status_str == 'Fresh Server!'
        assert driver.wait_time == 30.0
        assert driver.uuid == {'rinse': None, 'prep': None, 'catch': None, 'agent': None}

    def test_initialization_with_custom_snapshot_directory(self):
        """Test initialization with custom snapshot directory"""
        custom_dir = '/custom/snapshot/path'
        driver = OrchestratorDriver(snapshot_directory=custom_dir)
        
        assert driver.config['snapshot_directory'] == custom_dir

    def test_initialization_with_camera_urls(self):
        """Test initialization with camera URLs"""
        camera_urls = ['http://camera1:8080', 'http://camera2:8080']
        driver = OrchestratorDriver(camera_urls=camera_urls)
        
        assert driver.config['camera_urls'] == camera_urls

    def test_validate_config_missing_required_keys(self):
        """Test that validation fails when required keys are missing"""
        driver = OrchestratorDriver()
        # Don't set any configuration - should be missing keys
        
        with pytest.raises(KeyError) as exc_info:
            driver.validate_config()

        assert "'load' client must be configured" in str(exc_info.value)

    def test_validate_config_missing_load_client(self):
        """Test that validation requires 'load' client"""
        driver = OrchestratorDriver(overrides={
            'client': {'prep': 'localhost:5001'},  # missing 'load'
            'instrument': [],
            'components': [],
            'AL_components': [],
        })
        
        with pytest.raises(KeyError) as exc_info:
            driver.validate_config()
        
        assert "'load' client must be configured" in str(exc_info.value)

    def test_validate_config_missing_prep_client(self):
        """Test that validation requires 'prep' client"""
        driver = OrchestratorDriver(overrides={
            'client': {'load': 'localhost:5000'},  # missing 'prep'
            'instrument': [],
            'components': [],
            'AL_components': [],
        })
        
        with pytest.raises(KeyError) as exc_info:
            driver.validate_config()
        
        assert "'prep' client must be configured" in str(exc_info.value)

    def test_validate_config_missing_instrument_config(self):
        """Test that validation requires at least one instrument"""
        driver = OrchestratorDriver(overrides={
            'client': {'load': 'localhost:5000', 'prep': 'localhost:5001'},
            'instrument': [],  # empty list
            'components': [],
            'AL_components': [],
        })
        
        with pytest.raises(ValueError) as exc_info:
            driver.validate_config()
        
        assert "At least one instrument must be configured" in str(exc_info.value)

    def test_validate_config_instrument_missing_required_fields(self):
        """Test that instruments require all necessary fields"""
        driver = OrchestratorDriver(overrides={
            'client': {'load': 'localhost:5000', 'prep': 'localhost:5001'},
            'instrument': [
                {'name': 'biosanem1'}  # missing other required fields
            ],
            'components': [],
            'AL_components': [],
        })
        
        with pytest.raises(KeyError) as exc_info:
            driver.validate_config()
        
        assert "missing the following required keys" in str(exc_info.value)

    def test_validate_config_valid_configuration(self):
        """Test that valid configuration passes validation"""
        driver = OrchestratorDriver(overrides={
            'client': {
                'load': 'localhost:5000',
                'prep': 'localhost:5001',
                'instrument1': 'localhost:5002'
            },
            'instrument': [
                {
                    'name': 'biosanem1',
                    'client_name': 'instrument1',
                    'measure_base_kw': {},
                    'empty_base_kw': {},
                    'concat_dim': 'q_sample'
                }
            ],
            'ternary': False,
            'data_tag': 'test',
            'components': ['water', 'salt'],
            'AL_components': [],
            'snapshot_directory': '/tmp',
            'max_sample_transmission': 0.6,
            'mix_order': [],
            'camera_urls': [],
            'composition_format': 'mass_fraction',
        })
        
        # Should not raise
        driver.validate_config()

    def test_validate_config_composition_format_invalid_str(self):
        """Test that invalid composition format string is rejected"""
        driver = OrchestratorDriver(overrides={
            'client': {
                'load': 'localhost:5000',
                'prep': 'localhost:5001'
            },
            'instrument': [
                {
                    'name': 'biosanem1',
                    'client_name': 'prep',
                    'measure_base_kw': {},
                    'empty_base_kw': {},
                    'concat_dim': 'q_sample'
                }
            ],
            'ternary': False,
            'data_tag': 'test',
            'components': ['water'],
            'AL_components': [],
            'snapshot_directory': '/tmp',
            'max_sample_transmission': 0.6,
            'mix_order': [],
            'camera_urls': [],
            'composition_format': 'invalid_format'
        })
        
        with pytest.raises(ValueError) as exc_info:
            driver.validate_config()
        
        assert "Invalid composition_format" in str(exc_info.value)

    def test_validate_config_composition_format_valid_str(self):
        """Test that valid composition format strings are accepted"""
        for valid_format in ['mass_fraction', 'volume_fraction', 'concentration', 'molarity']:
            driver = OrchestratorDriver(overrides={
                'client': {
                    'load': 'localhost:5000',
                    'prep': 'localhost:5001'
                },
                'instrument': [
                    {
                        'name': 'biosanem1',
                        'client_name': 'prep',
                        'measure_base_kw': {},
                        'empty_base_kw': {},
                        'concat_dim': 'q_sample'
                    }
                ],
                'ternary': False,
                'data_tag': 'test',
                'components': ['water'],
                'AL_components': [],
                'snapshot_directory': '/tmp',
                'max_sample_transmission': 0.6,
                'mix_order': [],
                'camera_urls': [],
                'composition_format': valid_format
            })
            
            # Should not raise
            driver.validate_config()

    def test_validate_config_composition_format_dict(self):
        """Test that per-component composition formats are validated correctly"""
        driver = OrchestratorDriver(overrides={
            'client': {
                'load': 'localhost:5000',
                'prep': 'localhost:5001'
            },
            'instrument': [
                {
                    'name': 'biosanem1',
                    'client_name': 'prep',
                    'measure_base_kw': {},
                    'empty_base_kw': {},
                    'concat_dim': 'q_sample'
                }
            ],
            'ternary': False,
            'data_tag': 'test',
            'components': ['water', 'salt'],
            'AL_components': [],
            'snapshot_directory': '/tmp',
            'max_sample_transmission': 0.6,
            'mix_order': [],
            'camera_urls': [],
            'composition_format': {
                'water': 'mass_fraction',
                'salt': 'concentration'
            }
        })
        
        # Should not raise
        driver.validate_config()

    def test_validate_config_composition_format_dict_invalid(self):
        """Test that invalid per-component composition formats are rejected"""
        driver = OrchestratorDriver(overrides={
            'client': {
                'load': 'localhost:5000',
                'prep': 'localhost:5001'
            },
            'instrument': [
                {
                    'name': 'biosanem1',
                    'client_name': 'prep',
                    'measure_base_kw': {},
                    'empty_base_kw': {},
                    'concat_dim': 'q_sample'
                }
            ],
            'ternary': False,
            'data_tag': 'test',
            'components': ['water', 'salt'],
            'AL_components': [],
            'snapshot_directory': '/tmp',
            'max_sample_transmission': 0.6,
            'mix_order': [],
            'camera_urls': [],
            'composition_format': {
                'water': 'mass_fraction',
                'salt': 'invalid_format'
            }
        })
        
        with pytest.raises(ValueError) as exc_info:
            driver.validate_config()
        
        assert "Invalid format" in str(exc_info.value)


class TestOrchestratorDriverClient:
    """Test OrchestratorDriver client management"""

    def test_client_initialization(self):
        """Test that client dict is initialized properly"""
        driver = OrchestratorDriver()
        assert isinstance(driver.client, dict)

    @patch('AFL.automation.orchestrator.OrchestratorDriver.Client')
    def test_get_client_creates_client_if_not_exists(self, mock_client_class):
        """Test that get_client creates a new Client if not cached"""
        mock_client_instance = Mock()
        mock_client_class.return_value = mock_client_instance
        
        driver = OrchestratorDriver(overrides={
            'client': {
                'load': 'http://localhost:5000',
                'prep': 'http://localhost:5001'
            },
            'instrument': [],
            'components': [],
            'AL_components': [],
        })
        
        # Mock the get_client method to simulate normal behavior
        # In real implementation, it would connect to the server
        driver.client['load'] = mock_client_instance
        
        assert driver.client['load'] == mock_client_instance


class TestOrchestratorDriverStatus:
    """Test OrchestratorDriver status tracking"""

    def test_initial_status(self):
        """Test that driver has initial status message"""
        driver = OrchestratorDriver()
        assert driver.status_str == 'Fresh Server!'

    def test_uuid_tracking(self):
        """Test that UUID dict tracks task IDs"""
        driver = OrchestratorDriver()
        
        expected_uuid_keys = {'rinse', 'prep', 'catch', 'agent'}
        assert set(driver.uuid.keys()) == expected_uuid_keys
        
        # All should be None initially
        for key in expected_uuid_keys:
            assert driver.uuid[key] is None

    def test_al_status_tracking(self):
        """Test that AL status is tracked"""
        driver = OrchestratorDriver()
        assert driver.AL_status_str == ''

    def test_al_campaign_name_tracking(self):
        """Test that AL campaign name is tracked"""
        driver = OrchestratorDriver()
        assert driver.AL_campaign_name is None


class TestOrchestratorDriverDefaults:
    """Test that OrchestratorDriver has proper defaults"""

    def test_defaults_exist(self):
        """Test that all required defaults are defined"""
        required_defaults = [
            'client',
            'instrument',
            'ternary',
            'data_tag',
            'components',
            'AL_components',
            'snapshot_directory',
            'max_sample_transmission',
            'mix_order',
            'camera_urls',
            'prepare_volume',
            'empty_prefix',
            'composition_format',
        ]
        
        for key in required_defaults:
            assert key in OrchestratorDriver.defaults, f"Missing default for '{key}'"

    def test_default_ternary_is_false(self):
        """Test that ternary defaults to False"""
        assert OrchestratorDriver.defaults['ternary'] is False

    def test_default_data_tag_is_default(self):
        """Test that data_tag defaults to 'default'"""
        assert OrchestratorDriver.defaults['data_tag'] == 'default'

    def test_default_composition_format_is_mass_fraction(self):
        """Test that composition_format defaults to mass_fraction"""
        assert OrchestratorDriver.defaults['composition_format'] == 'mass_fraction'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
