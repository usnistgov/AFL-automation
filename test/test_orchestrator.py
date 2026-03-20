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
import xarray as xr

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
            'composition_format': 'masses',
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
        for valid_format in ['masses', 'mass_fraction', 'volume_fraction', 'concentration', 'molarity']:
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
                'water': 'masses',
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

    def test_default_composition_format_is_masses(self):
        """Test that composition_format defaults to masses"""
        assert OrchestratorDriver.defaults['composition_format'] == 'masses'

    def test_default_next_samples_variable(self):
        """Test that next_samples_variable defaults to next_samples"""
        assert OrchestratorDriver.defaults['next_samples_variable'] == 'next_samples'


class _FakeTiledContainer:
    def __init__(self, entries):
        self._entries = entries

    def items(self):
        return list(self._entries.items())

    def __getitem__(self, key):
        return self._entries[key]


class _FakeTiledClient:
    def __init__(self, run_documents):
        self._run_documents = run_documents

    def __getitem__(self, key):
        if key != 'run_documents':
            raise KeyError(key)
        return self._run_documents


class _FakeTiledEntry:
    def __init__(self, metadata, dataset):
        self.metadata = metadata
        self._dataset = dataset

    def read(self):
        return self._dataset


class TestOrchestratorDriverPredictFromTiled:
    def _driver_with_minimal_config(self):
        driver = OrchestratorDriver(overrides={
            'client': {
                'load': 'localhost:5000',
                'prep': 'localhost:5001',
                'agent': 'localhost:5002',
            },
            'instrument': [
                {
                    'name': 'inst1',
                    'client_name': 'inst_client',
                    'measure_base_kw': {},
                    'empty_base_kw': {},
                    'concat_dim': 'sample',
                }
            ],
            'ternary': False,
            'data_tag': 'test',
            'components': [],
            'AL_components': [],
            'snapshot_directory': '/tmp',
            'max_sample_transmission': 0.6,
            'mix_order': [],
            'camera_urls': [],
            'composition_format': 'masses',
            'next_samples_variable': 'next_samples',
        })
        driver.app = Mock()
        driver.app.logger = Mock()
        return driver

    def test_get_latest_predict_entry_matches_sample_uuid(self):
        driver = self._driver_with_minimal_config()
        ds = xr.Dataset({'next_samples': ('component', [1.0])}, coords={'component': ['A']})
        entry = _FakeTiledEntry(
            metadata={
                'sample_uuid': 'SAM-123',
                'task_name': 'predict',
                'meta': {'ended': '2026-02-28T01:00:00'},
            },
            dataset=ds,
        )
        driver.data = Mock()
        driver.data.tiled_client = _FakeTiledClient(_FakeTiledContainer({'entry-1': entry}))

        entry_id, returned_entry = driver._get_latest_predict_tiled_entry(sample_uuid='SAM-123')
        assert entry_id == 'entry-1'
        assert returned_entry is entry

    def test_get_latest_predict_entry_matches_nested_run_documents_attrs_sample_uuid(self):
        driver = self._driver_with_minimal_config()
        ds = xr.Dataset({'next_samples': ('component', [2.0])}, coords={'component': ['B']})
        entry = _FakeTiledEntry(
            metadata={
                'attrs': {
                    'sample_uuid': 'SAM-456',
                    'task_name': 'predict',
                    'meta': {'ended': '03/20/26 11:20:50-348049'},
                }
            },
            dataset=ds,
        )
        driver.data = Mock()
        driver.data.tiled_client = _FakeTiledClient(
            _FakeTiledContainer(
                {'batch-1': _FakeTiledContainer({'entry-2': entry})}
            )
        )

        entry_id, returned_entry = driver._get_latest_predict_tiled_entry(sample_uuid='SAM-456')
        assert entry_id == 'batch-1/entry-2'
        assert returned_entry is entry

    def test_process_sample_enqueue_next_uses_configured_masses_and_not_retrieve_obj(self):
        driver = self._driver_with_minimal_config()
        driver.data = Mock()
        ds = xr.Dataset(
            {'next_samples': ('component', [1.2, 3.4])},
            coords={'component': ['comp_a', 'comp_b']}
        )
        entry = _FakeTiledEntry(
            metadata={
                'sample_uuid': 'SAM-XYZ',
                'task_name': 'predict',
                'meta': {'ended': '2026-02-28T01:02:00'},
            },
            dataset=ds,
        )
        driver.data.tiled_client = _FakeTiledClient(_FakeTiledContainer({'entry-3': entry}))

        agent_client = Mock()
        agent_client.enqueue.return_value = {'return_val': 'AGENT-UUID'}
        agent_client.retrieve_obj.side_effect = AssertionError("retrieve_obj should not be called")

        driver.get_client = Mock(return_value=agent_client)
        driver.make_and_measure = Mock()
        driver.validate_config = Mock()
        driver._queue = Mock()
        driver._queue.qsize.return_value = 0

        driver.process_sample(
            sample={},
            predict_next=True,
            enqueue_next=True,
            sample_uuid='SAM-XYZ',
            AL_uuid='AL-XYZ',
            AL_campaign_name='camp',
        )

        assert driver._queue.put.call_count == 1
        queued_package, _ = driver._queue.put.call_args[0]
        assert queued_package['task']['task_name'] == 'process_sample'
        masses = queued_package['task']['sample']['masses']
        assert masses['comp_a'] == '1.2 mg'
        assert masses['comp_b'] == '3.4 mg'

    def test_process_sample_enqueue_next_groups_components_by_mixed_composition_format(self):
        driver = self._driver_with_minimal_config()
        driver.config['composition_format'] = {
            'comp_mass': 'masses',
            'comp_conc': 'concentration',
            'comp_fraction': 'mass_fraction',
            'comp_molarity': 'molarity',
        }
        driver.data = Mock()
        ds = xr.Dataset(
            {'next_samples': ('component', [1.2, 3.4, 0.25, 0.01])},
            coords={'component': ['comp_mass', 'comp_conc', 'comp_fraction', 'comp_molarity']}
        )
        entry = _FakeTiledEntry(
            metadata={
                'sample_uuid': 'SAM-MIXED',
                'task_name': 'predict',
                'meta': {'ended': '2026-02-28T01:03:00'},
            },
            dataset=ds,
        )
        driver.data.tiled_client = _FakeTiledClient(_FakeTiledContainer({'entry-mixed': entry}))

        agent_client = Mock()
        agent_client.enqueue.return_value = {'return_val': 'AGENT-UUID'}
        agent_client.retrieve_obj.side_effect = AssertionError("retrieve_obj should not be called")

        driver.get_client = Mock(return_value=agent_client)
        driver.make_and_measure = Mock()
        driver.validate_config = Mock()
        driver._queue = Mock()
        driver._queue.qsize.return_value = 0

        driver.process_sample(
            sample={},
            predict_next=True,
            enqueue_next=True,
            sample_uuid='SAM-MIXED',
            AL_uuid='AL-XYZ',
            AL_campaign_name='camp',
        )

        queued_package, _ = driver._queue.put.call_args[0]
        queued_sample = queued_package['task']['sample']
        assert queued_sample['masses']['comp_mass'] == '1.2 mg'
        assert queued_sample['concentrations']['comp_conc'] == '3.4 mg/ml'
        assert queued_sample['mass_fractions']['comp_fraction'] == 0.25
        assert queued_sample['molarities']['comp_molarity'] == '0.01 mol/L'

    def test_process_sample_enqueue_next_uses_first_prediction_row_when_multiple_rows_exist(self):
        driver = self._driver_with_minimal_config()
        driver.data = Mock()
        ds = xr.Dataset(
            {'next_samples': (('candidate', 'component'), [[1.2, 3.4], [9.9, 8.8]])},
            coords={'candidate': [0, 1], 'component': ['comp_a', 'comp_b']}
        )
        entry = _FakeTiledEntry(
            metadata={
                'sample_uuid': 'SAM-MULTI',
                'task_name': 'predict',
                'meta': {'ended': '2026-02-28T01:04:00'},
            },
            dataset=ds,
        )
        driver.data.tiled_client = _FakeTiledClient(_FakeTiledContainer({'entry-multi': entry}))

        agent_client = Mock()
        agent_client.enqueue.return_value = {'return_val': 'AGENT-UUID'}
        agent_client.retrieve_obj.side_effect = AssertionError("retrieve_obj should not be called")

        driver.get_client = Mock(return_value=agent_client)
        driver.make_and_measure = Mock()
        driver.validate_config = Mock()
        driver._queue = Mock()
        driver._queue.qsize.return_value = 0

        driver.process_sample(
            sample={},
            predict_next=True,
            enqueue_next=True,
            sample_uuid='SAM-MULTI',
            AL_uuid='AL-XYZ',
            AL_campaign_name='camp',
        )

        queued_package, _ = driver._queue.put.call_args[0]
        masses = queued_package['task']['sample']['masses']
        assert masses['comp_a'] == '1.2 mg'
        assert masses['comp_b'] == '3.4 mg'

    def test_process_sample_enqueue_next_raises_when_tiled_entry_missing(self):
        driver = self._driver_with_minimal_config()
        driver.data = Mock()
        driver.data.tiled_client = _FakeTiledClient(_FakeTiledContainer({}))

        agent_client = Mock()
        agent_client.enqueue.return_value = {'return_val': 'AGENT-UUID'}

        driver.get_client = Mock(return_value=agent_client)
        driver.make_and_measure = Mock()
        driver.validate_config = Mock()
        driver._queue = Mock()
        driver._queue.qsize.return_value = 0

        with pytest.raises(ValueError):
            driver.process_sample(
                sample={},
                predict_next=True,
                enqueue_next=True,
                sample_uuid='SAM-MISSING',
                AL_uuid='AL-XYZ',
                AL_campaign_name='camp',
            )

    def test_process_sample_enqueue_next_raises_when_variable_missing(self):
        driver = self._driver_with_minimal_config()
        driver.data = Mock()
        ds = xr.Dataset({'not_next_samples': ('component', [5.0])}, coords={'component': ['comp_a']})
        entry = _FakeTiledEntry(
            metadata={
                'sample_uuid': 'SAM-ABC',
                'task_name': 'predict',
                'meta': {'ended': '2026-02-28T01:05:00'},
            },
            dataset=ds,
        )
        driver.data.tiled_client = _FakeTiledClient(_FakeTiledContainer({'entry-4': entry}))

        agent_client = Mock()
        agent_client.enqueue.return_value = {'return_val': 'AGENT-UUID'}

        driver.get_client = Mock(return_value=agent_client)
        driver.make_and_measure = Mock()
        driver.validate_config = Mock()
        driver._queue = Mock()
        driver._queue.qsize.return_value = 0

        with pytest.raises(ValueError):
            driver.process_sample(
                sample={},
                predict_next=True,
                enqueue_next=True,
                sample_uuid='SAM-ABC',
                AL_uuid='AL-XYZ',
                AL_campaign_name='camp',
            )

    def test_get_last_measurement_entry_prefers_newest_queue_style_timestamp(self):
        driver = self._driver_with_minimal_config()
        driver.data = Mock()
        older_entry = _FakeTiledEntry(
            metadata={
                'attrs': {
                    'sample_uuid': 'SAM-MEASURE',
                    'task_name': 'expose',
                    'meta': {'ended': '03/20/26 11:20:45-486705'},
                }
            },
            dataset=xr.Dataset(),
        )
        newer_entry = _FakeTiledEntry(
            metadata={
                'attrs': {
                    'sample_uuid': 'SAM-MEASURE',
                    'task_name': 'expose',
                    'meta': {'ended': '03/20/26 11:20:50-348049'},
                }
            },
            dataset=xr.Dataset(),
        )
        driver.data.tiled_client = _FakeTiledClient(
            _FakeTiledContainer(
                {
                    'batch-1': _FakeTiledContainer({'entry-old': older_entry}),
                    'batch-2': _FakeTiledContainer({'entry-new': newer_entry}),
                }
            )
        )

        entry_id = driver._get_last_tiled_entry_for_measurement(
            sample_uuid='SAM-MEASURE',
            task_name='expose',
        )

        assert entry_id == 'batch-2/entry-new'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
