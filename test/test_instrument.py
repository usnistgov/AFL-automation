"""
Tests for BioSANS instrument driver

These tests verify basic functionality without requiring hardware access.
They focus on configuration, initialization, and API structure.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path


@pytest.fixture
def epics_stub():
    with patch('AFL.automation.instrument.BioSANS.caget', return_value=0), \
         patch('AFL.automation.instrument.BioSANS.caput', return_value=True), \
         patch('AFL.automation.instrument.BioSANS.cainfo', return_value={}):
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
        assert BioSANS.defaults['use_subtracted_data'] is True
        
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
            
            assert isinstance(filepath, Path)
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
            
            assert isinstance(filepath, Path)
            assert '1D' in str(filepath)
            assert 'r67890_67890_1D_main.txt' in str(filepath)


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
