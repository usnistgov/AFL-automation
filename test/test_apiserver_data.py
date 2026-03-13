"""
Tests for AFL.automation.APIServer.data module
"""
import pytest
import json
import tempfile
import os
import numpy as np
import pandas as pd
from pathlib import Path
import importlib

from AFL.automation.APIServer.data import DataPacket, DataJSON, DataTiled, DataTrashcan


class TestDataPacket:
    """Test DataPacket base class functionality"""

    def test_init(self):
        """Test DataPacket initialization"""
        dp = DataTrashcan()
        assert len(dp) == 0
        assert list(dp.keys()) == []

    def test_set_get_transient_data(self):
        """Test setting and getting transient data"""
        dp = DataTrashcan()
        dp['test_key'] = 'test_value'
        assert dp['test_key'] == 'test_value'
        assert 'test_key' in dp.keys()

    def test_set_get_system_data(self):
        """Test setting and getting system data"""
        dp = DataTrashcan()
        dp['driver_name'] = 'TestDriver'
        dp['driver_config'] = {'key': 'value'}
        assert dp['driver_name'] == 'TestDriver'
        assert dp['driver_config'] == {'key': 'value'}

    def test_set_get_sample_data(self):
        """Test setting and getting sample data"""
        dp = DataTrashcan()
        dp['sample_name'] = 'Test Sample'
        dp['sample_uuid'] = '12345-abcde'
        assert dp['sample_name'] == 'Test Sample'
        assert dp['sample_uuid'] == '12345-abcde'

    def test_protected_system_keys(self):
        """Test that system keys are stored in system dict"""
        dp = DataTrashcan()
        for key in DataPacket.PROTECTED_SYSTEM_KEYS:
            dp[key] = f'value_{key}'
            assert dp[key] == f'value_{key}'
            assert key in dp._system_dict

    def test_protected_sample_keys(self):
        """Test that sample keys are stored in sample dict"""
        dp = DataTrashcan()
        for key in DataPacket.PROTECTED_SAMPLE_KEYS:
            dp[key] = f'value_{key}'
            assert dp[key] == f'value_{key}'
            assert key in dp._sample_dict

    def test_reset_clears_transient_only(self):
        """Test that reset clears only transient data"""
        dp = DataTrashcan()
        dp['transient_key'] = 'transient_value'
        dp['driver_name'] = 'TestDriver'
        dp['sample_name'] = 'TestSample'
        
        dp.reset()
        
        # Transient data should be cleared
        assert 'transient_key' not in dp.keys()
        # System and sample data should remain
        assert dp['driver_name'] == 'TestDriver'
        assert dp['sample_name'] == 'TestSample'

    def test_reset_sample(self):
        """Test that reset_sample clears only sample data"""
        dp = DataTrashcan()
        dp['transient_key'] = 'transient_value'
        dp['driver_name'] = 'TestDriver'
        dp['sample_name'] = 'TestSample'
        
        dp.reset_sample()
        
        # Sample data should be cleared
        assert 'sample_name' not in dp.keys()
        # Transient and system data should remain
        assert dp['transient_key'] == 'transient_value'
        assert dp['driver_name'] == 'TestDriver'

    def test_dict_method(self):
        """Test _dict() returns combined dictionary"""
        dp = DataTrashcan()
        dp['transient_key'] = 'transient_value'
        dp['driver_name'] = 'TestDriver'
        dp['sample_name'] = 'TestSample'
        
        result = dp._dict()
        assert result['transient_key'] == 'transient_value'
        assert result['driver_name'] == 'TestDriver'
        assert result['sample_name'] == 'TestSample'

    def test_dict_method_is_copy(self):
        """Test that _dict() returns a deep copy"""
        dp = DataTrashcan()
        dp['test_dict'] = {'nested': 'value'}
        
        result = dp._dict()
        result['test_dict']['nested'] = 'modified'
        
        # Original should not be modified
        assert dp['test_dict']['nested'] == 'value'

    def test_len(self):
        """Test __len__ method"""
        dp = DataTrashcan()
        assert len(dp) == 0
        
        dp['transient_key'] = 'value'
        assert len(dp) == 1
        
        dp['driver_name'] = 'TestDriver'
        assert len(dp) == 2
        
        dp['sample_name'] = 'TestSample'
        assert len(dp) == 3

    def test_iter(self):
        """Test __iter__ method"""
        dp = DataTrashcan()
        dp['transient_key'] = 'transient_value'
        dp['driver_name'] = 'TestDriver'
        dp['sample_name'] = 'TestSample'
        
        keys = list(dp)
        assert 'transient_key' in keys
        assert 'driver_name' in keys
        assert 'sample_name' in keys

    def test_delitem(self):
        """Test __delitem__ method"""
        dp = DataTrashcan()
        dp['transient_key'] = 'transient_value'
        dp['driver_name'] = 'TestDriver'
        dp['sample_name'] = 'TestSample'
        
        del dp['transient_key']
        assert 'transient_key' not in dp.keys()
        
        del dp['driver_name']
        assert 'driver_name' not in dp.keys()
        
        del dp['sample_name']
        assert 'sample_name' not in dp.keys()

    def test_sanitize_primitive_types(self):
        """Test _sanitize with primitive types"""
        dp = DataTrashcan()
        dp['int_val'] = 42
        dp['float_val'] = 3.14
        dp['str_val'] = 'hello'
        dp['bool_val'] = True
        
        dp._sanitize()
        
        assert dp['int_val'] == 42
        assert dp['float_val'] == 3.14
        assert dp['str_val'] == 'hello'
        assert dp['bool_val'] is True

    def test_sanitize_list(self):
        """Test _sanitize with lists"""
        dp = DataTrashcan()
        dp['short_list'] = [1, 2, 3]
        
        dp._sanitize()
        
        assert dp['short_list'] == [1, 2, 3]

    def test_sanitize_long_list(self):
        """Test _sanitize with long lists (should be summarized)"""
        dp = DataTrashcan()
        long_list = list(range(100))
        dp['long_list'] = long_list
        
        dp._sanitize()
        
        # Should be summarized as a string
        assert isinstance(dp['long_list'], str)
        assert '<list of 100 elements>' == dp['long_list']

    def test_sanitize_numpy_array(self):
        """Test _sanitize with numpy arrays"""
        dp = DataTrashcan()
        dp['small_array'] = np.array([1, 2, 3])
        
        dp._sanitize()
        
        assert dp['small_array'] == [1, 2, 3]

    def test_sanitize_large_numpy_array(self):
        """Test _sanitize with large numpy arrays (should be summarized)"""
        dp = DataTrashcan()
        large_array = np.arange(100)
        dp['large_array'] = large_array
        
        dp._sanitize()
        
        # Should be summarized as a string
        assert isinstance(dp['large_array'], str)
        assert 'ndarray of shape' in dp['large_array']

    def test_sanitize_dataframe(self):
        """Test _sanitize with pandas DataFrames"""
        dp = DataTrashcan()
        df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
        dp['dataframe'] = df
        
        dp._sanitize()
        
        # Should be converted to JSON string
        assert isinstance(dp['dataframe'], str)
        # Verify it's valid JSON (to_json is the correct method)
        json.loads(dp['dataframe'])

    def test_sanitize_nested_dict(self):
        """Test _sanitize with nested dictionaries"""
        dp = DataTrashcan()
        dp['nested'] = {
            'level1': {
                'level2': 'value'
            }
        }
        
        dp._sanitize()
        
        assert dp['nested']['level1']['level2'] == 'value'

    def test_sanitize_dict_with_numpy(self):
        """Test _sanitize with dict containing numpy arrays"""
        dp = DataTrashcan()
        dp['nested'] = {
            'array': np.array([1, 2, 3])
        }
        
        dp._sanitize()
        
        assert dp['nested']['array'] == [1, 2, 3]

    def test_finalize_calls_transmit_and_reset(self):
        """Test that finalize calls transmit and reset"""
        dp = DataTrashcan()
        dp['test_key'] = 'test_value'
        dp['driver_name'] = 'TestDriver'
        
        dp.finalize()
        
        # Transient data should be cleared
        assert 'test_key' not in dp.keys()
        # System data should remain
        assert dp['driver_name'] == 'TestDriver'


class TestDataTrashcan:
    """Test DataTrashcan implementation"""

    def test_transmit_does_nothing(self):
        """Test that transmit does nothing"""
        dp = DataTrashcan()
        dp['test_key'] = 'test_value'
        dp.transmit()  # Should not raise any errors
        # Data should still be there
        assert dp['test_key'] == 'test_value'

    def test_add_array_does_nothing(self):
        """Test that add_array does nothing"""
        dp = DataTrashcan()
        dp.add_array('test', np.array([1, 2, 3]))  # Should not raise any errors


class TestDataJSON:
    """Test DataJSON implementation"""

    def test_init(self):
        """Test DataJSON initialization"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = DataJSON(tmpdir)
            assert dp.path == tmpdir

    def test_add_array(self):
        """Test adding an array"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = DataJSON(tmpdir)
            arr = np.array([1, 2, 3])
            dp.add_array('test_array', arr)
            
            # Array should be stored as a key
            assert 'test_array' in dp.keys()

    def test_transmit_creates_json_file(self):
        """Test that transmit creates a JSON file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = DataJSON(tmpdir)
            dp['test_key'] = 'test_value'
            dp['int_val'] = 42
            
            dp.transmit()
            
            # Check that a JSON file was created
            files = os.listdir(tmpdir)
            assert len(files) == 1
            assert files[0].endswith('.json')

    def test_transmit_with_array(self):
        """Test transmit with array data"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = DataJSON(tmpdir)
            dp['test_key'] = 'test_value'
            dp.add_array('test_array', np.array([1, 2, 3]))
            
            dp.transmit()
            
            # Check that a JSON file was created
            files = os.listdir(tmpdir)
            assert len(files) == 1
            
            # Load and verify contents
            with open(os.path.join(tmpdir, files[0])) as f:
                data = json.load(f)
            
            assert data['test_key'] == 'test_value'
            assert data['test_array'] == [1, 2, 3]

    def test_finalize_creates_file_and_resets(self):
        """Test that finalize creates file and resets data"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = DataJSON(tmpdir)
            dp['test_key'] = 'test_value'
            dp['driver_name'] = 'TestDriver'
            
            dp.finalize()
            
            # File should be created
            files = os.listdir(tmpdir)
            assert len(files) == 1
            
            # Transient data should be cleared
            assert 'test_key' not in dp.keys()
            # System data should remain
            assert dp['driver_name'] == 'TestDriver'

    def test_json_file_naming(self):
        """Test that JSON files are named with timestamps"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = DataJSON(tmpdir)
            dp['test_key'] = 'test_value'
            
            dp.transmit()
            
            files = os.listdir(tmpdir)
            # File should have timestamp format (YYYY-MM-DD-HH:MM:SS.ffffff.json)
            assert files[0].endswith('.json')
            # Should contain date components (at least YYYY-MM-DD format)
            assert files[0].count('-') >= 2  # Year-Month-Day gives at least 2 dashes


class TestDataTiled:
    """Test DataTiled implementation (requires tiled server)"""

    @pytest.fixture
    def mock_tiled_server(self, monkeypatch):
        """Mock tiled client for testing without actual server"""
        class MockTiledClient:
            def __init__(self, *args, **kwargs):
                self.data = []
            
            def new(self, key=None, structure=None, metadata=None):
                self.data.append({
                    'key': key,
                    'structure': structure,
                    'metadata': metadata
                })
                return self
            
            def write(self, data):
                self.data[-1]['data'] = data
        
        mock_client = MockTiledClient()
        
        def mock_from_uri(*args, **kwargs):
            return mock_client
        
        monkeypatch.setattr('tiled.client.from_uri', mock_from_uri)
        return mock_client

    def test_init_with_backup(self, mock_tiled_server):
        """Test DataTiled initialization"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = DataTiled('http://localhost:8000', 'test-api-key', tmpdir)
            assert dp.backup_path == tmpdir
            assert hasattr(dp, 'tiled_client')
            assert hasattr(dp, 'arrays')

    def test_add_array(self, mock_tiled_server):
        """Test adding an array"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = DataTiled('http://localhost:8000', 'test-api-key', tmpdir)
            arr = np.array([1, 2, 3])
            dp.add_array('test_array', arr)
            
            assert 'test_array' in dp.arrays
            np.testing.assert_array_equal(dp.arrays['test_array'], arr)

    def test_subtransmit_array(self, mock_tiled_server):
        """Test subtransmit_array functionality"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dp = DataTiled('http://localhost:8000', 'test-api-key', tmpdir)
            arr = np.array([1, 2, 3, 4, 5])
            dp['test_key'] = 'test_value'
            
            dp.subtransmit_array('test_array', arr)
            
            # Array should have been transmitted and removed from transient dict
            assert 'main_array' not in dp.keys()
            assert 'array_name' not in dp.keys()
            # Other data should remain
            assert dp['test_key'] == 'test_value'

    def test_tiled_writes_use_run_document_prefix(self, mock_tiled_server, monkeypatch):
        """Test that DataTiled writes are keyed under run_document/<uuid>."""
        captured = {}

        def fake_write_xarray_dataset(client, dataset, key=None):
            captured['key'] = key

        tiled_mod = importlib.import_module('AFL.automation.APIServer.data.DataTiled')
        monkeypatch.setattr(tiled_mod, 'write_xarray_dataset', fake_write_xarray_dataset)

        with tempfile.TemporaryDirectory() as tmpdir:
            dp = DataTiled('http://localhost:8000', 'test-api-key', tmpdir)
            dp['uuid'] = 'QD-123'
            dp.subtransmit_array('test_array', np.array([1, 2, 3]))
            assert captured['key'] == 'run_document/QD-123'


# Integration test to verify import works
# Added these since having issues with AFL-agent finding / importing data module
def test_import_data_module():
    """Test that the data module can be imported"""
    from AFL.automation.APIServer import data
    assert hasattr(data, 'DataPacket')
    assert hasattr(data, 'DataJSON')
    assert hasattr(data, 'DataTiled')
    assert hasattr(data, 'DataTrashcan')


def test_import_data_classes():
    """Test that data classes can be imported directly"""
    from AFL.automation.APIServer.data import DataPacket, DataJSON, DataTiled, DataTrashcan
    
    assert DataPacket is not None
    assert DataJSON is not None
    assert DataTiled is not None
    assert DataTrashcan is not None
