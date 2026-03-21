"""
Tests for BioSANS instrument driver

These tests verify basic functionality without requiring hardware access.
They focus on configuration, initialization, and API structure.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path


@pytest.fixture
def epics_stub(tmp_path):
    with patch('AFL.automation.instrument.BioSANS.caget', return_value=0), \
         patch('AFL.automation.instrument.BioSANS.caput', return_value=True), \
         patch('AFL.automation.instrument.BioSANS.cainfo', return_value={}), \
         patch('AFL.automation.APIServer.Driver.pathlib.Path.home', return_value=tmp_path):
        yield


class TestBioSANSConfiguration:
    """Test BioSANS driver configuration and defaults"""
    
    def test_defaults_exist(self):
        """Test that BioSANS has required default config keys"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        assert hasattr(BioSANS, 'defaults')
        assert isinstance(BioSANS.defaults, dict)
        assert 'eic_token' in BioSANS.defaults
        assert 'ipts_number' in BioSANS.defaults
        assert 'beamline' in BioSANS.defaults
        
    def test_default_values(self):
        """Test specific default values"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        assert BioSANS.defaults['beamline'] == 'CG3'
        
    def test_initialization_without_hardware(self, epics_stub):
        """Test that driver can be instantiated without EPICS/EIC"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        # Should not fail during __init__ even without hardware
        # The client property is lazy-loaded
        driver = BioSANS(overrides={'write_to_disk': False})
        
        assert driver.name == 'BioSANS'
        assert driver.config['beamline'] == 'CG3'
        assert driver._client is None  # Not instantiated yet


class TestBioSANSClientManagement:
    """Test EIC client lazy loading and management"""
    
    @patch('AFL.automation.instrument.BioSANS.EICClient')
    def test_client_lazy_instantiation(self, mock_eic_client, epics_stub):
        """Test that EIC client is created on first access"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        # Reset to clear any state from previous tests
        driver = BioSANS(overrides={
            'write_to_disk': False,
            'eic_token': '1',
            'ipts_number': '1234',
            'beamline': 'CG3'
        })
        assert driver._client is None
        
        # Access client property
        _ = driver.client
        
        # Should have created client
        mock_eic_client.assert_called_with(
            ipts_number='1234',
            eic_token='1',
            beamline='CG3'
        )
        
    @patch('AFL.automation.instrument.BioSANS.EICClient')
    def test_client_uses_config_values(self, mock_eic_client, epics_stub):
        """Test that client is created with custom config"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        driver = BioSANS(overrides={
            'write_to_disk': False,
            'eic_token': 'custom_token',
            'ipts_number': '9999',
            'beamline': 'CustomBeamline'
        })
        
        _ = driver.client
        
        mock_eic_client.assert_called_once_with(
            ipts_number='9999',
            eic_token='custom_token',
            beamline='CustomBeamline'
        )
        
    @patch('AFL.automation.instrument.BioSANS.EICClient')
    def test_reset_client(self, mock_eic_client, epics_stub):
        """Test that reset_client clears the client instance"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        driver = BioSANS(overrides={'write_to_disk': False})
        _ = driver.client  # Create client
        
        driver.reset_client()
        assert driver._client is None


class TestBioSANSFilePathGeneration:
    """Test file path generation for data files"""

    def test_get_last_reduction_log_file_path_matches_default_template(self, epics_stub):
        """Test reduction log path matches the default template exactly"""
        from AFL.automation.instrument.BioSANS import BioSANS

        with patch('AFL.automation.instrument.BioSANS.caget', return_value=24680):
            driver = BioSANS(overrides={
                'write_to_disk': False,
                'ipts_number': '1234',
                'beamline': 'CG3',
                'run_cycle': 'RC511',
                'config': 'Config0'
            })

            filepath = driver.getLastReductionLogFilePath()

            assert filepath == str(Path(
                '/HFIR/CG3/IPTS-1234/shared/autoreduce/RC511/Config0/'
                'r24680_24680_reduction_log.hdf'
            ))
    
    def test_get_last_reduction_log_file_path(self, epics_stub):
        """Test reduction log file path generation"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        with patch('AFL.automation.instrument.BioSANS.caget', return_value=12345):
            driver = BioSANS(overrides={
                'write_to_disk': False,
                'ipts_number': '1234',
                'beamline': 'CG3',
                'run_cycle': 'RC511',
                'config': 'Config0'
            })
            
            filepath = driver.getLastReductionLogFilePath()
            
            assert isinstance(filepath, str)
            assert 'HFIR' in str(filepath)
            assert 'CG3' in str(filepath)
            assert 'IPTS-1234' in str(filepath)
            assert 'RC511' in str(filepath)
            assert 'Config0' in str(filepath)
            assert 'r12345_12345_reduction_log.hdf' in str(filepath)
            
    def test_get_last_file_path(self, epics_stub):
        """Test 1D reduced data file path generation"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        with patch('AFL.automation.instrument.BioSANS.caget', return_value=67890):
            driver = BioSANS(overrides={
                'write_to_disk': False,
                'ipts_number': '5678',
                'beamline': 'CG3',
                'run_cycle': 'RC512',
                'config': 'Config1'
            })
            
            filepath = driver.getLastFilePath()
            
            assert isinstance(filepath, str)
            assert '1D' in str(filepath)
            assert 'r67890_67890_1D_main.txt' in str(filepath)

    def test_get_last_file_path_matches_default_template(self, epics_stub):
        """Test reduced 1D path matches the default template exactly"""
        from AFL.automation.instrument.BioSANS import BioSANS

        with patch('AFL.automation.instrument.BioSANS.caget', return_value=24680):
            driver = BioSANS(overrides={
                'write_to_disk': False,
                'ipts_number': '1234',
                'beamline': 'CG3',
                'run_cycle': 'RC511',
                'config': 'Config0'
            })

            filepath = driver.getLastFilePath()

            assert filepath == str(Path(
                '/HFIR/CG3/IPTS-1234/shared/autoreduce/RC511/Config0/1D/'
                'r24680_24680_1D_main.txt'
            ))

    def test_get_last_reduction_log_file_path_uses_configured_data_path(self, epics_stub):
        """Test reduction log path template can be overridden via config"""
        from AFL.automation.instrument.BioSANS import BioSANS

        with patch('AFL.automation.instrument.BioSANS.caget', return_value=13579):
            driver = BioSANS(overrides={
                'write_to_disk': False,
                'ipts_number': '9876',
                'beamline': 'CG3',
                'run_cycle': 'RC999',
                'config': 'ConfigX',
                'reduction_log_data_path': '/tmp/custom/{INST}/IPTS-{IPTS}/{RUN_CYCLE}/{CONFIG}'
            })

            filepath = driver.getLastReductionLogFilePath()

            assert filepath == str(Path(
                '/tmp/custom/CG3/IPTS-9876/RC999/ConfigX/'
                'r13579_13579_reduction_log.hdf'
            ))

    def test_get_last_file_path_uses_configured_data_path(self, epics_stub):
        """Test reduced 1D path template can be overridden via config"""
        from AFL.automation.instrument.BioSANS import BioSANS

        with patch('AFL.automation.instrument.BioSANS.caget', return_value=13579):
            driver = BioSANS(overrides={
                'write_to_disk': False,
                'ipts_number': '9876',
                'beamline': 'CG3',
                'run_cycle': 'RC999',
                'config': 'ConfigX',
                'reduced_file_data_path': '/tmp/custom/{INST}/IPTS-{IPTS}/{RUN_CYCLE}/{CONFIG}/reduced'
            })

            filepath = driver.getLastFilePath()

            assert filepath == str(Path(
                '/tmp/custom/CG3/IPTS-9876/RC999/ConfigX/reduced/'
                'r13579_13579_1D_main.txt'
            ))

    @patch('AFL.automation.instrument.BioSANS.MockEICClient')
    def test_fallback_run_number_from_latest_files(self, mock_client, tmp_path, epics_stub):
        """If EPICS returns 0, driver falls back to latest run number on disk."""
        from AFL.automation.instrument.BioSANS import BioSANS

        data_dir = tmp_path / 'intersect-data'
        data_dir.mkdir(parents=True, exist_ok=True)

        (data_dir / 'r30503_30503_reduction_log.hdf').write_bytes(b'log')
        (data_dir / 'S_r30504_30504_1D_combined.txt').write_text('#Q\n0.1 1 0.1 0.01\n')
        (data_dir / 'r30500_30500_reduction_log.hdf').write_bytes(b'log')

        with patch('AFL.automation.instrument.BioSANS.caget', return_value=0):
            driver = BioSANS(overrides={
                'write_to_disk': False,
                'mock_mode': True,
                'reduction_log_data_path': str(data_dir),
                'reduced_file_data_path': str(data_dir),
            })

            _ = driver.client
            log_path = driver.getLastReductionLogFilePath()

        assert mock_client.called
        assert log_path.endswith('r30504_30504_reduction_log.hdf')

    @patch('AFL.automation.instrument.BioSANS.MockEICClient')
    def test_reduced_file_prefers_existing_combined_file_when_main_missing(self, mock_client, tmp_path, epics_stub):
        """Driver selects S_r..._1D_combined.txt when _1D_main.txt is absent."""
        from AFL.automation.instrument.BioSANS import BioSANS

        data_dir = tmp_path / 'intersect-data'
        data_dir.mkdir(parents=True, exist_ok=True)

        (data_dir / 'S_r30504_30504_1D_combined.txt').write_text('#Q\n0.1 1 0.1 0.01\n')

        with patch('AFL.automation.instrument.BioSANS.caget', return_value=30504):
            driver = BioSANS(overrides={
                'write_to_disk': False,
                'mock_mode': True,
                'reduced_file_data_path': str(data_dir),
            })

            _ = driver.client
            reduced_path = driver.getLastFilePath()

        assert mock_client.called
        assert reduced_path.endswith('S_r30504_30504_1D_combined.txt')


class TestBioSANSStatus:
    """Test status reporting"""
    
    def test_initial_status(self, epics_stub):
        """Test initial status values"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        driver = BioSANS(overrides={'write_to_disk': False})
        
        assert driver.status_txt == 'Just started...'
        assert driver.last_measured_transmission == [0, 0, 0, 0]
        
    def test_status_method(self, epics_stub):
        """Test status() method returns list of strings"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        driver = BioSANS(overrides={'write_to_disk': False})
        status = driver.status()
        
        assert isinstance(status, list)
        assert len(status) == 2
        assert all(isinstance(s, str) for s in status)
        assert 'Last Measured Transmission' in status[0]
        assert 'Status' in status[1]


class TestBioSANSExposureValidation:
    """Test exposure type validation"""
    
    def test_validate_exposure_type_valid(self, epics_stub):
        """Test that 'time' is a valid exposure type"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        driver = BioSANS(overrides={'write_to_disk': False})
        
        # Should not raise
        driver._validateExposureType('time')
        
    def test_validate_exposure_type_invalid(self, epics_stub):
        """Test that invalid exposure types raise ValueError"""
        from AFL.automation.instrument.BioSANS import BioSANS
        
        driver = BioSANS(overrides={'write_to_disk': False})
        
        with pytest.raises(ValueError, match='Exposure type must be one of "time"'):
            driver._validateExposureType('detector')
            
        with pytest.raises(ValueError, match='Exposure type must be one of "time"'):
            driver._validateExposureType('invalid')


class TestBioSANSDefaultPort:
    """Test default port configuration"""
    
    def test_default_port_exists(self):
        """Test that _DEFAULT_PORT is defined"""
        from AFL.automation.instrument import BioSANS as biosans_module
        
        assert hasattr(biosans_module, '_DEFAULT_PORT')
        assert biosans_module._DEFAULT_PORT == 5001
