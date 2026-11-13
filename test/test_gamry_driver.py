import importlib
import pathlib
import tempfile
from types import SimpleNamespace

import numpy as np
import pytest

from AFL.automation.instrument.Gamry.GamryDriver import GamryDriver
from AFL.automation.instrument.Gamry.gamry_worker import (
    _build_measurement_result_from_data,
    _calculate_dpv_differential_current,
    _derive_dpv_trace,
    _predict_dpv_point_count,
    _summarize_dpv_timing,
    _validate_voltage_limit,
    collect_dpv,
)
from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.data import DataTiled
from AFL.automation.APIServer.data.DataPacket import DataPacket


class FakeBridgeRoot:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def ping(self):
        self.calls.append(('ping',))
        return self.responses.get('ping', {'status': 'ok', 'result': {}})

    def list_instruments(self):
        self.calls.append(('list_instruments',))
        return self.responses.get('list_instruments', {'status': 'ok', 'result': {'instruments': []}})

    def validate_connection(self, instrument_name):
        self.calls.append(('validate_connection', instrument_name))
        return self.responses.get('validate_connection', {'status': 'ok', 'result': {'instrument_name': instrument_name}})

    def release_connection(self):
        self.calls.append(('release_connection',))
        return self.responses.get('release_connection', {'status': 'ok', 'result': {'released': True}})

    def collect_cv(self, instrument_name, process_name, initial_voltage, apex1_voltage, apex2_voltage, final_voltage, apex1_hold, apex2_hold, final_hold, scan_rate, step_size, cycles, scan_delay, current_range_mode):
        self.calls.append(
            (
                'collect_cv',
                instrument_name,
                process_name,
                initial_voltage,
                apex1_voltage,
                apex2_voltage,
                final_voltage,
                apex1_hold,
                apex2_hold,
                final_hold,
                scan_rate,
                step_size,
                cycles,
                scan_delay,
                current_range_mode,
            )
        )
        return self.responses['collect_cv']

    def run_measurement(self, instrument_name, process_name, measurement_mode, parameters):
        self.calls.append(('run_measurement', instrument_name, process_name, measurement_mode, parameters))
        return self.responses['run_measurement']


class FakeBridgeConnection:
    def __init__(self, root):
        self.root = root
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def driver(tmp_path, monkeypatch):
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    worker_path = tmp_path / 'gamry_worker.py'
    worker_path.write_text('# worker placeholder\n', encoding='utf-8')
    env_path = tmp_path / '.venv'
    scripts_path = env_path / 'Scripts'
    scripts_path.mkdir(parents=True)
    python_path = scripts_path / 'python.exe'
    python_path.write_text('', encoding='utf-8')
    driver = GamryDriver(
        gamry_env_path=str(env_path),
        overrides={
            'worker_path': str(worker_path),
            'subprocess_timeout': 5.0,
            'service_startup_timeout': 1.0,
            'service_port': 5069,
        },
    )
    yield driver
    driver.shutdownService()


def test_run_cv_builds_dataset(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'run_measurement': {
                'status': 'ok',
                'result': {
                    'mode': 'run_measurement',
                    'measurement_type': 'cyclic_voltammetry',
                    'x_key': 'potential',
                    'y_key': 'current',
                    'x_source': 'vf',
                    'y_source': 'im',
                    'instrument_name': 'PSTAT',
                    'process_name': 'AFL_GamryDriver',
                    'timestamp': '2026-04-15T12:00:00',
                    'parameters': {'scan_rate': 0.1, 'step_size': 0.001},
                    'data': {
                        'vf': [0.1, 0.2, 0.3],
                        'im': [1.0, 2.0, 3.0],
                        'time': [0.0, 0.5, 1.0],
                    },
                },
            }
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)

    dataset = driver.runCV(scan_rate=0.2, step_size=0.002)

    assert dataset.attrs['measurement_type'] == 'cyclic_voltammetry'
    assert dataset.attrs['instrument_name'] == 'PSTAT'
    assert np.allclose(dataset['potential'].values, [0.1, 0.2, 0.3])
    assert np.allclose(dataset['current'].values, [1.0, 2.0, 3.0])
    assert np.allclose(dataset['time'].values, [0.0, 0.5, 1.0])
    assert int(dataset.attrs['point_count']) == 3
    assert root.calls[0][0] == 'run_measurement'


def test_run_cv_raises_bridge_error(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'run_measurement': {
                'status': 'error',
                'error': {
                    'code': 'ConnectionError',
                    'message': 'No instrument found',
                },
            }
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)

    with pytest.raises(RuntimeError, match='No instrument found'):
        driver.runCV()


def test_run_measurement_builds_dpv_dataset(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'run_measurement': {
                'status': 'ok',
                'result': {
                    'mode': 'run_measurement',
                    'measurement_type': 'differential_pulse_voltammetry',
                    'x_key': 'potential',
                    'y_key': 'current',
                    'x_source': 'potential',
                    'y_source': 'current',
                    'instrument_name': 'PSTAT',
                    'process_name': 'AFL_GamryDriver',
                    'timestamp': '2026-04-15T12:00:00',
                    'parameters': {'step_size': 0.005, 'pulse_size': 0.025, 'sample_period': 0.5},
                    'data': {
                        'potential': [0.025, 0.03],
                        'current': [0.06, 0.08],
                    },
                },
            }
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)

    dataset = driver.runMeasurement(measurement_mode='dpv', return_data=True)

    assert dataset.attrs['measurement_type'] == 'differential_pulse_voltammetry'
    assert np.allclose(dataset['potential'].values, [0.025, 0.03])
    assert np.allclose(dataset['current'].values, [0.06, 0.08])
    assert set(dataset.data_vars) == {'potential', 'current'}
    assert root.calls[0][0] == 'run_measurement'
    assert root.calls[0][3] == 'dpv'
    assert root.calls[0][4]['pulse_size'] == driver.config['dpv_pulse_size']
    assert root.calls[0][4]['sample_period'] == driver.config['dpv_sample_period']


def test_derive_dpv_trace_samples_pre_pulse_and_pulse_end():
    data = {
        'time': [0.00, 0.20, 0.39, 0.49, 0.50, 0.70, 0.89, 0.99],
        'vf': [-1.000, -1.000, -1.000, -1.000, -0.975, -0.995, -0.995, -0.970],
        'im': [0.10, 0.11, 0.12, 0.13, 0.18, 0.14, 0.15, 0.22],
        'vu': [-1.000, -1.000, -1.000, -1.000, -0.975, -0.995, -0.995, -0.970],
    }

    derived = _derive_dpv_trace(data, sample_period=0.5, pulse_time=0.1)

    assert derived is not None
    assert np.allclose(derived['base_time'], [0.49, 0.89])
    assert np.allclose(derived['time'], [0.50, 0.99])
    assert np.allclose(derived['base_current'], [0.13, 0.15])
    assert np.allclose(derived['pulse_current'], [0.18, 0.22])
    assert np.allclose(derived['current'], [0.05, 0.07])
    assert np.allclose(derived['potential'], [-0.975, -0.97])
    assert np.allclose(derived['applied_signal'], [-0.975, -0.97])


def test_derive_dpv_trace_handles_monotonic_time_stream():
    data = {
        'time': [0.02, 0.18, 0.39, 0.48, 0.53, 0.68, 0.88, 0.98],
        'vf': [-1.000, -1.000, -1.000, -1.000, -0.975, -0.995, -0.995, -0.970],
        'im': [0.10, 0.11, 0.12, 0.13, 0.18, 0.14, 0.15, 0.22],
    }

    derived = _derive_dpv_trace(data, sample_period=0.5, pulse_time=0.1)

    assert derived is not None
    assert np.allclose(derived['base_current'], [0.13, 0.15])
    assert np.allclose(derived['pulse_current'], [0.18, 0.22])
    assert np.allclose(derived['current'], [0.05, 0.07])
    assert np.allclose(derived['potential'], [-0.975, -0.97])


def test_collect_dpv_allocates_curve_with_small_buffer_margin(monkeypatch):
    captured = {}

    class FakeCurve:
        def __init__(self, pstat, max_size):
            captured['max_size'] = max_size

        def run(self, block):
            captured['run_block'] = block

        def running(self):
            return False

        def acq_data(self):
            return np.array([], dtype=[('time', np.float32), ('vf', np.float32), ('im', np.float32)])

        def stop(self):
            captured['curve_stopped'] = True

        def free(self):
            captured['curve_freed'] = True

    class FakeSignal:
        def free(self):
            captured['signal_freed'] = True

    class FakePstat:
        def __init__(self, instrument_name):
            captured['instrument_name'] = instrument_name

        def set_ctrl_mode(self, mode):
            captured['ctrl_mode'] = mode

        def signal_pv_new(self, *args):
            captured['signal_args'] = args
            return FakeSignal()

        def set_signal_pv(self, signal):
            captured['signal_set'] = signal is not None

        def init_signal(self):
            captured['signal_initialized'] = True

        def set_cell(self, enabled):
            captured.setdefault('cell_states', []).append(enabled)

        def close(self):
            captured['pstat_closed'] = True

    fake_tkp = SimpleNamespace(
        PSTATMODE='PSTATMODE',
        Pstat=FakePstat,
        CpivCurve=FakeCurve,
        pstat_is_valid=lambda pstat: True,
    )

    monkeypatch.setattr('AFL.automation.instrument.Gamry.gamry_worker.initialize_pstat', lambda *args, **kwargs: None)
    monkeypatch.setattr('AFL.automation.instrument.Gamry.gamry_worker._curve_data_to_lists', lambda data: {'time': [], 'vf': [], 'im': []})
    monkeypatch.setattr('AFL.automation.instrument.Gamry.gamry_worker._derive_dpv_trace', lambda *args, **kwargs: None)
    monkeypatch.setattr('AFL.automation.instrument.Gamry.gamry_worker.time.sleep', lambda *_args, **_kwargs: None)

    result = collect_dpv(
        fake_tkp,
        'PSTAT',
        'test-process',
        {
            'initial_voltage': -1.0,
            'final_voltage': 0.0,
            'step_size': 0.005,
            'pulse_size': 0.025,
            'sample_period': 0.5,
            'pulse_time': 0.1,
            'noise_rejection': True,
            'irange_mode': 'fixed',
            'max_current': 0.0003,
            'current_range_mode': 'auto',
        },
    )

    assert result['measurement_type'] == 'differential_pulse_voltammetry'
    assert captured['max_size'] == 101000


def test_gamry_driver_defaults_use_amp_units(driver):
    quickbar = driver._quickbar_params_from_config(driver.config, 'dpv')

    assert driver.config['dpv_max_current'] == pytest.approx(0.0003)
    assert quickbar['max_current']['label'] == 'Max Current (A)'


def test_start_service_launches_worker(monkeypatch, driver):
    captured = {}
    process = SimpleNamespace(
        poll=lambda: None,
        terminate=lambda: None,
        wait=lambda timeout=None: None,
        stdout=None,
        stderr=None,
    )

    monkeypatch.setattr(driver, '_bridge_ready', lambda: False)
    monkeypatch.setattr(driver, '_wait_for_service_ready', lambda: None)
    monkeypatch.setattr(driver, '_is_port_in_use', lambda host, port: False)

    def fake_popen(command, **kwargs):
        captured['command'] = command
        captured['kwargs'] = kwargs
        return process

    monkeypatch.setattr('AFL.automation.instrument.Gamry.GamryDriver.subprocess.Popen', fake_popen)

    result = driver.startService()

    assert result['status'] == 'ok'
    assert captured['command'][2] == 'serve'
    assert captured['command'][3] == '127.0.0.1'
    assert captured['command'][4] == '5069'


def test_validate_connection_invokes_bridge(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'validate_connection': {
                'status': 'ok',
                'result': {
                    'instrument_name': 'PSTAT',
                    'serial_number': '12345',
                },
            }
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)

    result = driver.validateConnection()

    assert result['result']['serial_number'] == '12345'
    assert root.calls[0] == ('validate_connection', 'PSTAT')


def test_connect_instrument_releases_existing_bridge_handle(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'list_instruments': {'status': 'ok', 'result': {'instruments': ['PSTAT']}},
            'validate_connection': {
                'status': 'ok',
                'result': {
                    'instrument_name': 'PSTAT',
                    'serial_number': '12345',
                },
            },
            'release_connection': {'status': 'ok', 'result': {'released': True}},
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)
    monkeypatch.setattr(driver, '_bridge_ready', lambda: True)
    monkeypatch.setattr(driver, '_is_port_in_use', lambda host, port: True)

    result = driver.connectInstrument('PSTAT')

    assert result['connection']['release']['result']['released'] is True
    assert root.calls[0] == ('release_connection',)
    assert ('validate_connection', 'PSTAT') in root.calls


def test_shutdown_service_releases_bridge_handle_before_close(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'release_connection': {'status': 'ok', 'result': {'released': True}},
        }
    )
    connection = FakeBridgeConnection(root)
    driver._bridge_connection = connection

    result = driver.shutdownService()

    assert result['released'] is True
    assert connection.closed is True
    assert root.calls[0] == ('release_connection',)


def test_missing_persisted_worker_path_resets_to_repo_worker(tmp_path, monkeypatch):
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    stale_worker_path = tmp_path / 'missing_worker.py'
    env_path = tmp_path / '.venv'
    scripts_path = env_path / 'Scripts'
    scripts_path.mkdir(parents=True)
    (scripts_path / 'python.exe').write_text('', encoding='utf-8')

    driver = GamryDriver(
        gamry_env_path=str(env_path),
        overrides={
            'worker_path': str(stale_worker_path),
        },
    )

    expected_worker = pathlib.Path(__file__).resolve().parents[1] / 'AFL' / 'automation' / 'instrument' / 'Gamry' / 'gamry_worker.py'
    assert pathlib.Path(driver.getWorkerPath()) == expected_worker


def test_run_cv_quickbar_uses_live_config_defaults(driver):
    driver.config['initial_voltage'] = 0.25
    driver.config['apex1_voltage'] = 0.5
    driver.config['apex2_voltage'] = 0.25
    driver.config['final_voltage'] = 0.5
    driver.config['apex1_hold'] = 1.5
    driver.config['apex2_hold'] = 2.5
    driver.config['final_hold'] = 3.5
    driver.config['scan_rate'] = 0.2
    driver.config['step_size'] = 0.002
    driver.config['cycles'] = 4
    driver.config['scan_delay'] = 0.75
    driver.config['current_range_mode'] = 'manual'
    driver.refresh_quickbar()

    params = driver.quickbar.function_info['runCV']['qb']['params']

    assert params['initial_voltage']['default'] == 0.25
    assert params['apex1_voltage']['default'] == 0.5
    assert params['apex2_voltage']['default'] == 0.25
    assert params['final_voltage']['default'] == 0.5
    assert params['apex1_hold']['default'] == 1.5
    assert params['apex2_hold']['default'] == 2.5
    assert params['final_hold']['default'] == 3.5
    assert params['scan_rate']['default'] == 0.2
    assert params['step_size']['default'] == 0.002
    assert params['cycles']['default'] == 4
    assert params['scan_delay']['default'] == 0.75
    assert params['current_range_mode']['default'] == 'manual'


def test_apiserver_get_quickbar_returns_live_gamry_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path)
    worker_path = tmp_path / 'gamry_worker.py'
    worker_path.write_text('# worker placeholder\n', encoding='utf-8')
    env_path = tmp_path / '.venv'
    scripts_path = env_path / 'Scripts'
    scripts_path.mkdir(parents=True)
    (scripts_path / 'python.exe').write_text('', encoding='utf-8')

    driver = GamryDriver(
        gamry_env_path=str(env_path),
        overrides={
            'worker_path': str(worker_path),
            'initial_voltage': 0.25,
            'apex1_voltage': 0.5,
            'apex2_voltage': 0.25,
            'final_voltage': 0.5,
            'scan_rate': 0.1,
            'step_size': 0.001,
            'cycles': 1,
            'scan_delay': 0.0,
            'current_range_mode': 'auto',
        },
    )
    server = APIServer('gamry_demo_test')
    server.create_queue(driver, add_unqueued=False)

    with server.app.app_context():
        response, status = server.get_quickbar()
        payload = response.get_json()

    assert status == 200
    params = payload['runCV']['qb']['params']
    assert params['initial_voltage']['default'] == 0.25
    assert params['apex1_voltage']['default'] == 0.5
    assert params['apex2_voltage']['default'] == 0.25
    assert params['final_voltage']['default'] == 0.5
    assert params['scan_rate']['default'] == 0.1
    assert params['step_size']['default'] == 0.001
    assert params['cycles']['default'] == 1
    assert params['scan_delay']['default'] == 0.0
    assert params['current_range_mode']['default'] == 'auto'


def test_run_measurement_builds_chrono_dataset(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'run_measurement': {
                'status': 'ok',
                'result': {
                    'mode': 'run_measurement',
                    'measurement_type': 'chronoamperometry',
                    'x_key': 'time',
                    'y_key': 'current',
                    'x_source': 'time',
                    'y_source': 'current',
                    'instrument_name': 'PSTAT',
                    'process_name': 'AFL_GamryDriver',
                    'timestamp': '2026-04-22T12:00:00',
                    'parameters': {'initial_time': 1.0},
                    'data': {
                        'time': [0.0, 0.5, 1.0],
                        'potential': [0.5, 0.5, 0.0],
                        'current': [1.0, 0.8, 0.6],
                    },
                },
            }
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)

    dataset = driver.runMeasurement(measurement_mode='ca', ca_initial_time=1.0, ca_step1_time=2.0, ca_step2_time=2.0)

    assert dataset.attrs['measurement_type'] == 'chronoamperometry'
    assert dataset.attrs['x_key'] == 'time'
    assert dataset.attrs['y_key'] == 'current'
    assert dataset.attrs['parameters']['initial_time'] == 1.0
    assert np.allclose(dataset['time'].values, [0.0, 0.5, 1.0])
    assert np.allclose(dataset['potential'].values, [0.5, 0.5, 0.0])
    assert np.allclose(dataset['current'].values, [1.0, 0.8, 0.6])
    assert root.calls[0][0] == 'run_measurement'
    assert root.calls[0][3] == 'ca'


def test_build_measurement_result_from_data_uses_in_memory_values():
    result = _build_measurement_result_from_data(
        measurement_type='cyclic_voltammetry',
        instrument_name='PSTAT',
        process_name='AFL_GamryDriver',
        timestamp='2026-04-22T12:00:00',
        parameters={'scan_rate': 0.1},
        data={
            'time': [0.0, 1.0, 2.0],
            'vf': [0.1, 0.2, 0.3],
            'im': [1.0, 1.5, 1.2],
        },
    )

    assert result['x_source'] == 'potential'
    assert result['y_source'] == 'current'
    assert result['parameters']['scan_rate'] == 0.1
    assert result['data']['time'] == [0.0, 1.0, 2.0]
    assert result['data']['potential'] == [0.1, 0.2, 0.3]
    assert result['data']['current'] == [1.0, 1.5, 1.2]


def test_queued_gamry_wrappers_stamp_task_metadata(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'run_measurement': {
                'status': 'ok',
                'result': {
                    'mode': 'run_measurement',
                    'measurement_type': 'chronoamperometry',
                    'x_key': 'time',
                    'y_key': 'current',
                    'x_source': 'time',
                    'y_source': 'im',
                    'instrument_name': 'PSTAT',
                    'process_name': 'AFL_GamryDriver',
                    'timestamp': '2026-04-22T12:00:00',
                    'parameters': {'initial_time': 1.0},
                    'data': {
                        'time': [0.0, 0.5, 1.0],
                        'im': [1.0, 0.8, 0.6],
                    },
                },
            }
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)
    driver.data = DataPacket()

    driver.set_sample('electrode-sample', sample_uuid='SAM-ECHEM-001')

    deposition = driver.runCA()
    analyte = driver.runCA()

    assert deposition.attrs['task_name'] == 'runCA'
    assert deposition.attrs['step_name'] == 'ca'
    assert deposition.attrs['sample_uuid'] == 'SAM-ECHEM-001'
    assert deposition.attrs['sample_name'] == 'electrode-sample'
    assert analyte.attrs['task_name'] == 'runCA'
    assert analyte.attrs['step_name'] == 'ca'
    assert root.calls[0][3] == 'ca'
    assert root.calls[1][3] == 'ca'


def test_run_stripping_dpv_stamps_task_metadata(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'run_measurement': {
                'status': 'ok',
                'result': {
                    'mode': 'run_measurement',
                    'measurement_type': 'differential_pulse_voltammetry',
                    'x_key': 'potential',
                    'y_key': 'current',
                    'x_source': 'potential',
                    'y_source': 'current',
                    'instrument_name': 'PSTAT',
                    'process_name': 'AFL_GamryDriver',
                    'timestamp': '2026-04-22T12:00:00',
                    'parameters': {'step_size': 0.005},
                    'data': {
                        'potential': [0.025, 0.03],
                        'current': [0.06, 0.08],
                        'time': [0.50, 1.00],
                    },
                },
            }
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)
    driver.data = DataPacket()

    driver.set_sample('electrode-sample', sample_uuid='SAM-ECHEM-002')
    dataset = driver.runDPV()

    assert dataset.attrs['task_name'] == 'runDPV'
    assert dataset.attrs['step_name'] == 'dpv'
    assert dataset.attrs['measurement_type'] == 'differential_pulse_voltammetry'
    assert dataset.attrs['sample_uuid'] == 'SAM-ECHEM-002'
    assert root.calls[0][3] == 'dpv'


def test_enqueue_panel_measurement_stamps_mode_specific_metadata(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'run_measurement': {
                'status': 'ok',
                'result': {
                    'mode': 'run_measurement',
                    'measurement_type': 'sine_wave',
                    'x_key': 'time',
                    'y_key': 'current',
                    'x_source': 'time',
                    'y_source': 'current',
                    'instrument_name': 'PSTAT',
                    'process_name': 'AFL_GamryDriver',
                    'timestamp': '2026-04-22T12:00:00',
                    'parameters': {'signal_frequency': 10.0},
                    'data': {
                        'time': [0.0, 0.1, 0.2],
                        'current': [0.01, 0.02, 0.01],
                        'potential': [0.0, 0.05, 0.0],
                    },
                },
            }
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)
    driver.data = DataPacket()

    dataset = driver.enqueuePanelMeasurement(measurement_mode='sine')

    assert dataset.attrs['task_name'] == 'enqueuePanelMeasurement'
    assert dataset.attrs['step_name'] == 'panel_sine'
    assert dataset.attrs['measurement_type'] == 'sine_wave'
    assert root.calls[0][3] == 'sine'


def test_gamry_dataset_can_be_written_to_tiled(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'run_measurement': {
                'status': 'ok',
                'result': {
                    'mode': 'run_measurement',
                    'measurement_type': 'differential_pulse_voltammetry',
                    'x_key': 'potential',
                    'y_key': 'current',
                    'x_source': 'potential',
                    'y_source': 'current',
                    'instrument_name': 'PSTAT',
                    'process_name': 'AFL_GamryDriver',
                    'timestamp': '2026-04-22T12:00:00',
                    'parameters': {
                        'step_size': 0.005,
                        'dpv_diff_point_count': 2,
                        'cycle_completion_ratio': 1.0,
                    },
                    'data': {
                        'potential': [0.025, 0.03],
                        'current': [0.06, 0.08],
                    },
                },
            }
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)
    driver.data = DataPacket()
    driver.set_sample('electrode-sample', sample_uuid='SAM-ECHEM-003')
    dataset = driver.runDPV()

    class MockTiledContainer:
        def __init__(self, key, metadata=None):
            self.key = key
            self.metadata = metadata or {}

    class MockTiledClient:
        def __init__(self):
            self.containers = {}

        def __getitem__(self, key):
            return self.containers[key]

        def create_container(self, key, metadata=None):
            container = MockTiledContainer(key, metadata=metadata)
            self.containers[key] = container
            return container

    mock_client = MockTiledClient()
    monkeypatch.setattr('tiled.client.from_uri', lambda *args, **kwargs: mock_client)

    captured = {}

    def fake_write_xarray_dataset(client, written_dataset, key=None):
        captured['client'] = client
        captured['dataset'] = written_dataset
        captured['key'] = key

    tiled_mod = importlib.import_module('AFL.automation.APIServer.data.DataTiled')
    monkeypatch.setattr(tiled_mod, 'write_xarray_dataset', fake_write_xarray_dataset)

    with tempfile.TemporaryDirectory() as tmpdir:
        packet = DataTiled('http://localhost:8000', 'test-api-key', tmpdir)
        packet['uuid'] = 'QD-GAMRY-001'
        packet['task'] = {'task_name': 'runStrippingDPV'}
        packet['meta'] = {'return_val': 'xarray.Dataset'}
        packet['main_dataset'] = dataset
        packet.finalize()

    assert captured['client'] is mock_client.containers['run_documents']
    assert captured['key'] == 'QD-GAMRY-001'
    assert captured['dataset'].attrs['measurement_type'] == 'differential_pulse_voltammetry'
    assert captured['dataset'].attrs['sample_uuid'] == 'SAM-ECHEM-003'
    assert captured['dataset'].attrs['parameters']['dpv_diff_point_count'] == 2
    assert captured['dataset'].attrs['meta']['return_val'] == 'xarray.Dataset'


def test_run_measurement_now_serializes_non_cv_result(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'run_measurement': {
                'status': 'ok',
                'result': {
                    'mode': 'run_measurement',
                    'measurement_type': 'sine_wave',
                    'x_key': 'time',
                    'y_key': 'current',
                    'x_source': 'time',
                    'y_source': 'im',
                    'instrument_name': 'PSTAT',
                    'process_name': 'AFL_GamryDriver',
                    'timestamp': '2026-04-22T12:00:00',
                    'parameters': {'signal_frequency': 10.0},
                    'data': {
                        'time': [0.0, 0.1, 0.2],
                        'im': [0.0, 1.0, 0.0],
                        'vu': [0.0, 0.05, 0.0],
                    },
                },
            }
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)

    result = driver.runMeasurement(measurement_mode='sine', return_data=True, sine_frequency=10.0)

    assert result.attrs['measurement_type'] == 'sine_wave'
    assert result['time'].values.tolist() == [0.0, 0.1, 0.2]
    assert result['current'].values.tolist() == [0.0, 1.0, 0.0]
    assert result['applied_signal'].values.tolist() == [0.0, 0.05, 0.0]


def test_run_measurement_builds_sine_dataset_with_total_time(monkeypatch, driver):
    root = FakeBridgeRoot(
        responses={
            'run_measurement': {
                'status': 'ok',
                'result': {
                    'mode': 'run_measurement',
                    'measurement_type': 'sine_wave',
                    'x_key': 'time',
                    'y_key': 'current',
                    'x_source': 'time',
                    'y_source': 'im',
                    'instrument_name': 'PSTAT',
                    'process_name': 'AFL_GamryDriver',
                    'timestamp': '2026-04-15T12:00:00',
                    'parameters': {'total_time': 2.5, 'signal_frequency': 10.0},
                    'data': {
                        'time': [0.0, 0.1, 0.2],
                        'im': [0.01, 0.02, 0.03],
                    },
                },
            }
        }
    )
    connection = FakeBridgeConnection(root)

    monkeypatch.setattr(driver, '_ensure_service', lambda: None)
    monkeypatch.setattr(driver, '_get_bridge_connection', lambda: connection)

    dataset = driver.runMeasurement(measurement_mode='sine', return_data=True, sine_total_time=2.5)

    assert dataset.attrs['measurement_type'] == 'sine_wave'
    assert root.calls[0][0] == 'run_measurement'
    assert root.calls[0][3] == 'sine'
    assert root.calls[0][4]['total_time'] == 2.5
    assert 'cycles' not in root.calls[0][4]


def test_predict_dpv_point_count_rejects_oversized_run():
    prediction = _predict_dpv_point_count(
        initial_voltage=-1.0,
        final_voltage=0.0,
        step_size=0.001,
        sample_period=0.5,
        pulse_time=0.1,
        timer_resolution=0.01,
    )

    assert prediction['cycle_count'] == 1000
    assert prediction['samples_per_cycle'] == 50
    assert prediction['predicted_raw_points'] == 50000


def test_validate_voltage_limit_rejects_out_of_range_values():
    with pytest.raises(ValueError, match='hard limit'):
        _validate_voltage_limit(2.1)


def test_derive_dpv_trace_uses_native_cpivcurve_columns():
    data = {
        'T': [0.4, 0.9],
        'Vfwd': [-0.975221, -0.970204],
        'Vrev': [-1.00024, -0.995211],
        'Vstep': [-164.951, -164.112],
        'Ifwd': [-1.09226e-3, -7.72114e-4],
        'Irev': [-1.09226e-3, -1.09226e-3],
        'Idif': [0.0, 3.20145e-4],
        'Sig': [-0.975006, -0.970007],
    }

    derived = _derive_dpv_trace(data, sample_period=0.5, pulse_time=0.1)

    assert derived is not None
    assert np.allclose(derived['time'], [0.4, 0.9])
    assert np.allclose(derived['potential'], [-0.975221, -0.970204])
    assert np.allclose(derived['base_potential'], [-1.00024, -0.995211])
    assert np.allclose(derived['pulse_current'], [-1.09226e-3, -7.72114e-4])
    assert np.allclose(derived['base_current'], [-1.09226e-3, -1.09226e-3])
    assert np.allclose(derived['current'], [0.0, 3.20145e-4])
    assert np.allclose(derived['applied_signal'], [-0.975006, -0.970007])


def test_collect_dpv_uses_restored_signal_order_and_voltage_guard():
    class FakeCurve:
        def __init__(self, pstat, point_count):
            self.point_count = point_count

        def run(self, block):
            return None

        def running(self):
            return False

        def acq_data(self):
            return {
                'time': [0.00, 0.20, 0.39, 0.49, 0.50, 0.70, 0.89, 0.99],
                'vf': [-1.000, -1.000, -1.000, -1.000, -0.975, -0.995, -0.995, -0.970],
                'im': [0.10, 0.11, 0.12, 0.13, 0.18, 0.14, 0.15, 0.22],
                'vu': [-1.000, -1.000, -1.000, -1.000, -0.975, -0.995, -0.995, -0.970],
            }

    class FakePstat:
        def __init__(self, instrument_name):
            self.instrument_name = instrument_name
            self.signal_args = None

        def set_ach_select(self, value):
            self.ach_select = value

        def set_ie_stability(self, value):
            self.ie_stability = value

        def set_ca_speed(self, value):
            self.ca_speed = value

        def set_ground(self, value):
            self.ground = value

        def set_ich_range(self, value):
            self.ich_range = value

        def set_ich_range_mode(self, value):
            self.ich_range_mode = value

        def set_ich_offset_enable(self, value):
            self.ich_offset_enable = value

        def set_vch_range(self, value):
            self.vch_range = value

        def set_vch_range_mode(self, value):
            self.vch_range_mode = value

        def set_vch_offset_enable(self, value):
            self.vch_offset_enable = value

        def set_ach_range(self, value):
            self.ach_range = value

        def set_ie_range_lower_limit(self, value):
            self.ie_range_lower_limit = value

        def set_pos_feed_enable(self, value):
            self.pos_feed_enable = value

        def set_analog_out(self, value):
            self.analog_out = value

        def set_voltage(self, value):
            self.voltage = value

        def set_pos_feed_resistance(self, value):
            self.pos_feed_resistance = value

        def set_ierange_mode(self, value):
            self.ierange_mode = value

        def set_ie_range(self, value):
            self.ie_range = value

        def set_ctrl_mode(self, mode):
            self.ctrl_mode = mode

        def signal_pv_new(self, *args):
            self.signal_args = args
            return object()

        def set_signal_pv(self, signal):
            self.signal = signal

        def init_signal(self):
            return None

        def set_cell(self, enabled):
            self.cell_enabled = enabled

        def close(self):
            return None

    class FakeToolkit:
        PSTATMODE = 1
        ACHSELECT_GND = 0
        STABILITY_NORM = 0
        CASPEED_NORM = 0
        FLOAT = 0

        def __init__(self, pstat):
            self._pstat = pstat

        def Pstat(self, instrument_name):
            return self._pstat

        def CpivCurve(self, pstat, point_count):
            return FakeCurve(pstat, point_count)

        def pstat_is_valid(self, pstat):
            return True

    auto_pstat = FakePstat('PSTAT')
    auto_result = collect_dpv(
        FakeToolkit(auto_pstat),
        'PSTAT',
        'AFL_GamryDriver',
        {
            'initial_voltage': -1.0,
            'final_voltage': 0.0,
            'step_size': 0.005,
            'pulse_size': 0.025,
            'sample_period': 0.5,
            'pulse_time': 0.1,
            'noise_rejection': True,
            'irange_mode': 'fixed',
            'max_current': 0.3,
            'current_range_mode': 'auto',
        },
    )

    assert auto_pstat.signal_args is not None
    assert auto_pstat.signal_args[0] == -1.0
    assert auto_pstat.signal_args[1] == 0.005
    assert auto_pstat.signal_args[2] == 0.025
    assert auto_pstat.signal_args[3] is False
    assert auto_pstat.signal_args[4] == 0.0
    assert auto_pstat.signal_args[5] is False
    assert auto_pstat.signal_args[6] == 0.0
    assert auto_pstat.signal_args[8] == 0.001
    assert auto_pstat.signal_args[11] == 0.05
    assert auto_pstat.signal_args[12] is False
    assert auto_pstat.signal_args[13] == 0.0
    assert auto_pstat.signal_args[14] is False
    assert auto_pstat.ierange_mode is False
    assert auto_pstat.ie_range == pytest.approx(0.3)
    assert auto_result['parameters']['predicted_raw_points'] == 100000

    fixed_pstat = FakePstat('PSTAT')
    fixed_result = collect_dpv(
        FakeToolkit(fixed_pstat),
        'PSTAT',
        'AFL_GamryDriver',
        {
            'initial_voltage': -1.0,
            'final_voltage': 0.0,
            'step_size': 0.005,
            'pulse_size': 0.025,
            'sample_period': 0.5,
            'pulse_time': 0.1,
            'noise_rejection': False,
            'irange_mode': 'auto',
            'max_current': 0.45,
            'current_range_mode': 'fixed',
        },
    )

    assert fixed_pstat.signal_args is not None
    assert fixed_pstat.ierange_mode is True
    assert fixed_result['parameters']['noise_rejection'] is False
    assert fixed_result['parameters']['irange_mode'] == 'auto'
    assert fixed_result['parameters']['max_current'] == pytest.approx(0.45)
    assert fixed_result['parameters']['drop_knock_enabled'] is True

    manual_pstat = FakePstat('PSTAT')
    manual_result = collect_dpv(
        FakeToolkit(manual_pstat),
        'PSTAT',
        'AFL_GamryDriver',
        {
            'initial_voltage': -1.0,
            'final_voltage': 0.0,
            'step_size': 0.005,
            'pulse_size': 0.025,
            'sample_period': 0.5,
            'pulse_time': 0.1,
            'noise_rejection': True,
            'irange_mode': 'fixed',
            'max_current': 0.45,
            'current_range_mode': 'auto',
        },
    )

    assert manual_pstat.ierange_mode is False
    assert manual_pstat.ie_range == pytest.approx(0.45)
    assert manual_result['parameters']['drop_knock_enabled'] is False

    with pytest.raises(ValueError, match='hard limit'):
        collect_dpv(
            FakeToolkit(FakePstat('PSTAT')),
            'PSTAT',
            'AFL_GamryDriver',
            {
                'initial_voltage': 2.1,
                'final_voltage': 0.0,
                'step_size': 0.005,
                'pulse_size': 0.025,
                'sample_period': 0.5,
                'pulse_time': 0.1,
                'noise_rejection': True,
                'irange_mode': 'fixed',
                'max_current': 0.3,
                'current_range_mode': 'auto',
            },
        )


def test_collect_dpv_returns_derived_trace_without_text_exports(monkeypatch):
    class FakeCurve:
        def __init__(self, pstat, max_size):
            self.max_size = max_size

        def run(self, block):
            return None

        def running(self):
            return False

        def acq_data(self):
            return np.array([], dtype=[('time', np.float32), ('vf', np.float32), ('im', np.float32)])

    class FakeSignal:
        pass

    class FakePstat:
        def __init__(self, instrument_name):
            self.instrument_name = instrument_name

        def set_ctrl_mode(self, mode):
            self.ctrl_mode = mode

        def signal_pv_new(self, *args):
            self.signal_args = args
            return FakeSignal()

        def set_signal_pv(self, signal):
            self.signal = signal

        def init_signal(self):
            return None

        def set_cell(self, enabled):
            self.cell_enabled = enabled

        def close(self):
            return None

    fake_tkp = SimpleNamespace(
        PSTATMODE='PSTATMODE',
        Pstat=FakePstat,
        CpivCurve=FakeCurve,
        pstat_is_valid=lambda pstat: True,
    )

    monkeypatch.setattr('AFL.automation.instrument.Gamry.gamry_worker.initialize_pstat', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        'AFL.automation.instrument.Gamry.gamry_worker._curve_data_to_lists',
        lambda data: {'time': [0.0, 0.1], 'vf': [-1.0, -0.975], 'im': [0.1, 0.2]},
    )
    monkeypatch.setattr(
        'AFL.automation.instrument.Gamry.gamry_worker._derive_dpv_trace',
        lambda *args, **kwargs: {
            'time': [0.5, 1.0, 1.5],
            'potential': [-0.975, -0.970, -0.965],
            'current': [0.05, 0.06, 0.07],
        },
    )
    monkeypatch.setattr(
        'AFL.automation.instrument.Gamry.gamry_worker._curve_data_to_lists',
        lambda data: {
            'time': [0.00, 0.20, 0.39, 0.41, 0.45, 0.49, 0.50, 0.70, 0.89, 0.91, 0.95, 0.99],
            'vf': [-1.0, -1.0, -1.0, -0.975, -0.975, -0.975, -0.995, -0.995, -0.995, -0.97, -0.97, -0.97],
            'im': [0.10, 0.11, 0.12, 0.16, 0.17, 0.18, 0.14, 0.15, 0.16, 0.21, 0.22, 0.23],
        },
    )
    monkeypatch.setattr('AFL.automation.instrument.Gamry.gamry_worker._summarize_dpv_timing', lambda *args, **kwargs: {})
    monkeypatch.setattr('AFL.automation.instrument.Gamry.gamry_worker.time.sleep', lambda *_args, **_kwargs: None)

    result = collect_dpv(
        fake_tkp,
        'PSTAT',
        'test-process',
        {
            'initial_voltage': -1.0,
            'final_voltage': 0.0,
            'step_size': 0.005,
            'pulse_size': 0.025,
            'sample_period': 0.5,
            'pulse_time': 0.1,
            'noise_rejection': True,
            'irange_mode': 'fixed',
            'max_current': 0.0003,
            'current_range_mode': 'auto',
        },
    )

    assert result['measurement_type'] == 'differential_pulse_voltammetry'
    assert result['data'] == {
        'potential': [-1.0, -0.995],
        'current': pytest.approx([0.05333333333333333, 0.07]),
    }
    assert result['parameters']['dpv_diff_point_count'] == 2
    assert 'text_export_path' not in result['parameters']


def test_calculate_dpv_differential_current_uses_in_memory_raw_data():
    differential = _calculate_dpv_differential_current(
        {
            'time': [0.00, 0.20, 0.39, 0.41, 0.45, 0.49, 0.50, 0.70, 0.89, 0.91, 0.95, 0.99],
            'vf': [-1.0, -1.0, -1.0, -0.975, -0.975, -0.975, -0.995, -0.995, -0.995, -0.97, -0.97, -0.97],
            'im': [0.10, 0.11, 0.12, 0.16, 0.17, 0.18, 0.14, 0.15, 0.16, 0.21, 0.22, 0.23],
        },
        cycle_time=0.5,
        pulse_time=0.1,
    )

    assert differential['point_count'] == 2
    assert differential['skipped_cycles'] == 0
    assert differential['cycle_index'] == [0, 1]
    assert differential['voltage_v'] == [-1.0, -0.995]
    assert differential['diff_current_a'] == pytest.approx([0.05333333333333333, 0.07])


def test_summarize_dpv_timing_reports_observed_cycle_rate():
    summary = _summarize_dpv_timing(
        data={'time': [0.5, 1.9, 3.3]},
        expected_cycle_count=200,
        expected_cycle_time=0.5,
    )

    assert summary['expected_cycle_count'] == 200
    assert summary['observed_cycle_count'] == 3
    assert summary['observed_duration'] == pytest.approx(2.8)
    assert summary['observed_cycle_time'] == pytest.approx(1.4)
    assert summary['observed_cycles_per_second'] == pytest.approx(1.0 / 1.4)
    assert summary['cycle_completion_ratio'] == pytest.approx(3.0 / 200.0)
