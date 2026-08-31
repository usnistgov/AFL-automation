"""APIServer driver that owns a locally connected Gamry potentiostat.

``GamryDriver`` runs on the Windows host with Gamry's ``toolkitpy`` package
and the physical potentiostat.  It launches :mod:`gamry_worker` in the
configured Gamry Python environment, communicates with that worker over a
local RPyC connection, and exposes queued measurement methods to APIServer.
"""

from AFL.automation.APIServer.Driver import Driver
import atexit
import datetime
import json
import os
import pathlib
import socket
import subprocess
import time
from typing import Any, Dict, Optional

import numpy as np
import xarray as xr
from jinja2 import Template

from AFL.automation.APIServer.data.DataPacket import DataPacket


class GamryDriver(Driver):
    """Control a Gamry potentiostat through the local worker process.

    Configure ``gamry_env_path`` to the Python environment that can import
    ``toolkitpy``.  The worker path normally needs no override: it defaults to
    the packaged ``gamry_worker.py`` file.  Start this driver on the Windows
    instrument host; clients on other machines should normally use
    :class:`GamryProxyDriver` instead of connecting to the instrument host
    directly.

    Example
    -------
    Start an APIServer using a configuration equivalent to::

        GamryDriver(overrides={
            'gamry_env_path': r'C:\\GamryPython\\.venv',
            'instrument_name': 'PSTAT',
        })

    Then queue a CV from an AFL client::

        from AFL.automation.APIServer.Client import Client

        client = Client(ip='gamry-windows-host', port='5051', username='operator')
        task_uuid = client.enqueue(
            task_name='runCV',
            initial_voltage=0.0,
            apex1_voltage=-0.2,
            apex2_voltage=0.5,
            final_voltage=0.0,
            scan_rate=0.1,
            step_size=0.01,
        )
        result = client.wait(target_uuid=task_uuid)
        dataset = client.retrieve_obj(task_uuid)

    ``runCV``, ``runCA``, ``runSine``, and ``runDPV`` are queued operations;
    use ``connectInstrument`` and status methods only for short setup checks.
    """
    defaults = {}
    # Worker and APIServer settings.
    defaults['gamry_env_path'] = ''
    defaults['worker_path'] = ''
    defaults['instrument_name'] = 'PSTAT'
    defaults['process_name'] = 'AFL_GamryDriver'
    defaults['subprocess_timeout'] = 300.0
    defaults['service_host'] = '127.0.0.1'
    defaults['service_port'] = 5059
    defaults['service_startup_timeout'] = 15.0
    defaults['measurement_mode'] = 'cv'
    # Cyclic voltammetry (CV) settings.
    defaults['initial_voltage'] = 0
    defaults['apex1_voltage'] = -0.2
    defaults['apex2_voltage'] = 0.5
    defaults['final_voltage'] = 0
    defaults['apex1_hold'] = 0.0
    defaults['apex2_hold'] = 0.0
    defaults['final_hold'] = 0.0
    defaults['scan_rate'] = 0.1
    defaults['step_size'] = 0.001
    defaults['cycles'] = 1
    defaults['scan_delay'] = 0.0
    defaults['current_range_mode'] = 'auto'
    # Chronoamperometry (CA) settings.
    defaults['ca_initial_voltage'] = 0.0
    defaults['ca_step1_voltage'] = 0.5
    defaults['ca_step2_voltage'] = 0.0
    defaults['ca_initial_time'] = 1.0
    defaults['ca_step1_time'] = 2.0
    defaults['ca_step2_time'] = 2.0
    defaults['ca_sample_time'] = 0.05
    defaults['ca_expected_max_v'] = 10.0
    # Sine-wave settings.
    defaults['sine_dc_offset'] = 0.0
    defaults['sine_amplitude'] = 0.05
    defaults['sine_frequency'] = 10.0
    defaults['sine_acq_frequency'] = 1000.0
    defaults['sine_total_time'] = 0.5
    defaults['sine_phase_offset'] = 0.0
    # Differential pulse voltammetry (DPV) settings.
    defaults['dpv_initial_voltage'] = -1.0
    defaults['dpv_final_voltage'] = 0.0
    defaults['dpv_step_size'] = 0.005
    defaults['dpv_pulse_size'] = 0.025
    defaults['dpv_sample_period'] = 0.5
    defaults['dpv_pulse_time'] = 0.1
    defaults['dpv_noise_rejection'] = True
    defaults['dpv_irange_mode'] = 'fixed'
    defaults['dpv_max_current'] = 0.0003
    static_dirs = {
        'gamry_panel_assets': pathlib.Path(__file__).parent.parent.parent / 'apps' / 'gamry_panel',
    }

    @staticmethod
    def _normalize_dpv_irange_mode(value: Any) -> str:
        normalized = str(value).strip().lower()
        if normalized not in {'auto', 'fixed'}:
            return 'fixed'
        return normalized

    @staticmethod
    def _quickbar_param(label: str, param_type: str, default: Any) -> Dict[str, Any]:
        return {'label': label, 'type': param_type, 'default': default}

    @classmethod
    def _quickbar_params_from_config(cls, config, mode: str) -> Dict[str, Dict[str, Any]]:
        if mode == 'cv':
            return {
                'initial_voltage': cls._quickbar_param('Initial Voltage (V)', 'float', config['initial_voltage']),
                'apex1_voltage': cls._quickbar_param('Apex 1 Voltage (V)', 'float', config['apex1_voltage']),
                'apex2_voltage': cls._quickbar_param('Apex 2 Voltage (V)', 'float', config['apex2_voltage']),
                'final_voltage': cls._quickbar_param('Final Voltage (V)', 'float', config['final_voltage']),
                'apex1_hold': cls._quickbar_param('Apex 1 Hold (s)', 'float', config['apex1_hold']),
                'apex2_hold': cls._quickbar_param('Apex 2 Hold (s)', 'float', config['apex2_hold']),
                'final_hold': cls._quickbar_param('Final Hold (s)', 'float', config['final_hold']),
                'scan_rate': cls._quickbar_param('Scan Rate (V/s)', 'float', config['scan_rate']),
                'step_size': cls._quickbar_param('Step Size (V)', 'float', config['step_size']),
                'cycles': cls._quickbar_param('Cycles', 'int', config['cycles']),
                'scan_delay': cls._quickbar_param('Scan Delay (s)', 'float', config['scan_delay']),
                'current_range_mode': cls._quickbar_param('Current Range Mode', 'text', config['current_range_mode']),
            }
        if mode == 'ca':
            return {
                'initial_voltage': cls._quickbar_param('Initial Voltage (V)', 'float', config['ca_initial_voltage']),
                'step1_voltage': cls._quickbar_param('Step 1 Voltage (V)', 'float', config['ca_step1_voltage']),
                'step2_voltage': cls._quickbar_param('Step 2 Voltage (V)', 'float', config['ca_step2_voltage']),
                'initial_time': cls._quickbar_param('Initial Time (s)', 'float', config['ca_initial_time']),
                'step1_time': cls._quickbar_param('Step 1 Time (s)', 'float', config['ca_step1_time']),
                'step2_time': cls._quickbar_param('Step 2 Time (s)', 'float', config['ca_step2_time']),
                'sample_time': cls._quickbar_param('Sample Time (s)', 'float', config['ca_sample_time']),
                'expected_max_v': cls._quickbar_param('Expected Max V', 'float', config['ca_expected_max_v']),
                'current_range_mode': cls._quickbar_param('Current Range Mode', 'text', config['current_range_mode']),
            }
        if mode == 'sine':
            return {
                'dc_offset': cls._quickbar_param('DC Offset (V)', 'float', config['sine_dc_offset']),
                'amplitude': cls._quickbar_param('Amplitude (V)', 'float', config['sine_amplitude']),
                'signal_frequency': cls._quickbar_param('Signal Frequency (Hz)', 'float', config['sine_frequency']),
                'acq_frequency': cls._quickbar_param('Acquisition Frequency (Hz)', 'float', config['sine_acq_frequency']),
                'total_time': cls._quickbar_param('Total Time (s)', 'float', config['sine_total_time']),
                'phase_offset': cls._quickbar_param('Phase Offset (rad)', 'float', config['sine_phase_offset']),
                'current_range_mode': cls._quickbar_param('Current Range Mode', 'text', config['current_range_mode']),
            }
        if mode == 'dpv':
            return {
                'initial_voltage': cls._quickbar_param('Initial E (V)', 'float', config['dpv_initial_voltage']),
                'final_voltage': cls._quickbar_param('Final E (V)', 'float', config['dpv_final_voltage']),
                'step_size': cls._quickbar_param('Step Size (V)', 'float', config['dpv_step_size']),
                'pulse_size': cls._quickbar_param('Pulse Size E (V)', 'float', config['dpv_pulse_size']),
                'sample_period': cls._quickbar_param('Sample Period (s)', 'float', config['dpv_sample_period']),
                'pulse_time': cls._quickbar_param('Pulse Time (s)', 'float', config['dpv_pulse_time']),
                'noise_rejection': cls._quickbar_param('Noise Rejection', 'bool', config['dpv_noise_rejection']),
                'irange_mode': cls._quickbar_param('I/E Range Mode', 'text', config['dpv_irange_mode']),
                'max_current': cls._quickbar_param('Max Current (A)', 'float', config['dpv_max_current']),
                'current_range_mode': cls._quickbar_param('Current Range Mode', 'text', config['current_range_mode']),
            }
        raise ValueError(f'Unsupported quickbar mode: {mode}')

    def __init__(self, gamry_env_path=None, instrument_name=None, overrides=None):
        self.app = None
        self._service_process = None
        self._bridge_connection = None
        self._last_cv_dataset = None
        self._last_panel_result = None
        self._last_connection_result = None
        Driver.__init__(self, name='GamryDriver', defaults=self.gather_defaults(), overrides=overrides)

        configured_env_path = str(self.config.get('gamry_env_path', '')).strip()
        if gamry_env_path is not None:
            self.config['gamry_env_path'] = str(pathlib.Path(gamry_env_path))
        elif configured_env_path:
            self.config['gamry_env_path'] = str(pathlib.Path(configured_env_path))
        else:
            self.config['gamry_env_path'] = ''

        if instrument_name is not None:
            self.config['instrument_name'] = instrument_name

        default_worker_path = pathlib.Path(__file__).with_name('gamry_worker.py')
        configured_worker_path = pathlib.Path(self.config['worker_path']) if self.config['worker_path'] else None
        if configured_worker_path is None or not configured_worker_path.exists():
            self.config['worker_path'] = str(default_worker_path)

        self.config['dpv_irange_mode'] = self._normalize_dpv_irange_mode(self.config.get('dpv_irange_mode', 'fixed'))
        self.refresh_quickbar()
        self.useful_links['Gamry Panel'] = '/gamry_panel'
        atexit.register(self.shutdownService)

    def status(self):
        return [
            f"instrument_name={self.config['instrument_name']}",
            f"gamry_env_path={self.config['gamry_env_path']}",
            f"worker_path={self.config['worker_path']}",
            f"bridge_endpoint={self.config['service_host']}:{int(self.config['service_port'])}",
        ]

    @Driver.unqueued()
    def getGamryEnvPath(self):
        return self.config['gamry_env_path']

    def setGamryEnvPath(self, gamry_env_path):
        self.config['gamry_env_path'] = gamry_env_path

    @Driver.unqueued()
    def getWorkerPath(self):
        return self.config['worker_path']

    def setWorkerPath(self, worker_path):
        self.config['worker_path'] = worker_path

    @Driver.unqueued()
    def getInstrumentName(self):
        return self.config['instrument_name']

    def setInstrumentName(self, instrument_name):
        self.config['instrument_name'] = instrument_name

    @Driver.unqueued()
    def getSubprocessTimeout(self):
        return self.config['subprocess_timeout']

    @Driver.unqueued()
    def getWorkerLogPath(self):
        return str(self._worker_log_path())

    def setSubprocessTimeout(self, timeout):
        self.config['subprocess_timeout'] = float(timeout)

    def _worker_log_path(self) -> pathlib.Path:
        return pathlib.Path.home() / '.afl' / 'gamry_worker.log'

    def _resolve_env_python_path(self, env_path: pathlib.Path) -> pathlib.Path:
        candidates = [
            env_path / 'Scripts' / 'python.exe',
            env_path / 'Scripts' / 'python',
            env_path / 'bin' / 'python',
            env_path / 'bin' / 'python3',
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _listener_pid(self, port: int) -> Optional[int]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                if probe.connect_ex((str(self.config['service_host']), int(port))) != 0:
                    return None
        except OSError:
            return None

        completed = subprocess.run(
            [
                'powershell',
                '-NoProfile',
                '-Command',
                f"(Get-NetTCPConnection -LocalPort {int(port)} -State Listen | Select-Object -First 1 -ExpandProperty OwningProcess)",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if completed.returncode != 0:
            return None
        stdout = completed.stdout.strip()
        if not stdout:
            return None
        try:
            return int(stdout.splitlines()[-1].strip())
        except ValueError:
            return None

    @Driver.unqueued()
    def startService(self):
        self._ensure_service()
        return {
            'status': 'ok',
            'bridge_endpoint': '{}:{}'.format(self.config['service_host'], int(self.config['service_port'])),
        }

    @Driver.unqueued()
    def shutdownService(self):
        released = False
        connection = self._bridge_connection
        if connection is not None:
            try:
                response = self._coerce_bridge_value(connection.root.release_connection())
                released = bool(response.get('result', {}).get('released', False))
            except Exception:
                pass
        self._bridge_connection = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

        stopped = False
        process = self._service_process
        self._service_process = None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                stopped = True
            else:
                stopped = True

        stale_pid = self._listener_pid(int(self.config['service_port']))
        if stale_pid is not None:
            try:
                os.kill(stale_pid, 15)
                stopped = True
                deadline = time.time() + 5.0
                while time.time() < deadline:
                    if self._listener_pid(int(self.config['service_port'])) is None:
                        break
                    time.sleep(0.1)
                remaining_pid = self._listener_pid(int(self.config['service_port']))
                if remaining_pid is not None:
                    os.kill(remaining_pid, 9)
            except OSError:
                pass

        return {'status': 'ok', 'stopped': stopped, 'released': released}

    @Driver.unqueued()
    def validateConnection(self):
        return self._invoke_bridge('validate_connection', {})

    @Driver.unqueued()
    def releaseConnection(self):
        try:
            return self._invoke_bridge('release_connection', {})
        except Exception:
            return {'status': 'ok', 'result': {'released': False}}

    @Driver.unqueued()
    def listInstruments(self):
        return self._invoke_bridge('list_instruments', {})

    @Driver.unqueued(render_hint='html')
    def gamry_panel(self, **kwargs):
        base = pathlib.Path(__file__).parent.parent.parent / 'apps' / 'gamry_panel'
        html = Template((base / 'gamry_panel.html').read_text(encoding='utf-8'))
        css = (base / 'gamry_panel.css').read_text(encoding='utf-8')
        js = (base / 'gamry_panel.js').read_text(encoding='utf-8')
        return html.render(inline_css=css, inline_js=js)

    @Driver.unqueued()
    def getPanelState(self):
        return {
            'status': 'ok',
            'service': self._service_status(),
            'config': self._panel_config_snapshot(),
            'quickbar': self._quickbar_snapshot(),
            'available_instruments': self._safe_list_instruments(),
            'last_connection': self._last_connection_snapshot(),
            'last_result': self._last_panel_result,
        }

    @Driver.unqueued()
    def diagnoseConnection(self, instrument_name: Optional[str] = None):
        return self._run_worker_diagnostic(instrument_name=instrument_name)

    @Driver.unqueued()
    def connectInstrument(self, instrument_name: Optional[str] = None):
        target_instrument = self.config['instrument_name'] if instrument_name is None else str(instrument_name)
        if not target_instrument:
            raise ValueError('instrument_name is required to connect to a Gamry potentiostat')
        self.setInstrumentName(target_instrument)
        release_result = self.releaseConnection()
        instruments = self._safe_list_instruments()
        validation = self.validateConnection()
        self._last_connection_result = {
            'instrument_name': target_instrument,
            'available_instruments': instruments,
            'release': release_result,
            'validation': validation,
            'connected_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        return {
            'status': 'ok',
            'service': self._service_status(),
            'config': self._panel_config_snapshot(),
            'available_instruments': instruments,
            'connection': self._last_connection_snapshot(),
        }

    @Driver.unqueued()
    def runMeasurement(
        self,
        measurement_mode: Optional[str] = None,
        instrument_name: Optional[str] = None,
        return_data: bool = False,
        task_name: Optional[str] = None,
        step_name: Optional[str] = None,
        **kwargs,
    ):
        mode = str(self.config['measurement_mode'] if measurement_mode is None else measurement_mode).lower()
        if instrument_name is not None:
            self.setInstrumentName(str(instrument_name))
        self.config['measurement_mode'] = mode
        parameters = self._measurement_parameters(mode, kwargs)
        response = self._invoke_bridge('run_measurement', {'measurement_mode': mode, 'parameters': parameters})
        dataset = self._dataset_from_measurement_response(
            response,
            task_name=task_name,
            step_name=step_name,
        )
        self._last_cv_dataset = dataset
        if return_data:
            return dataset
        return dataset

    @Driver.quickbar(qb={'button_text': 'Run cyclic voltammetry', 'params': {}})
    @Driver.queued()
    def runCV(
        self,
        instrument_name: Optional[str] = None,
        **kwargs,
    ):
        return self.runMeasurement(
            measurement_mode='cv',
            instrument_name=instrument_name,
            return_data=True,
            task_name='runCV',
            step_name='cv',
            **kwargs,
        )

    @Driver.quickbar(qb={'button_text': 'Run chronoamperometry', 'params': {}})
    @Driver.queued()
    def runCA(
        self,
        instrument_name: Optional[str] = None,
        **kwargs,
    ):
        return self.runMeasurement(
            measurement_mode='ca',
            instrument_name=instrument_name,
            return_data=True,
            task_name='runCA',
            step_name='ca',
            **kwargs,
        )

    @Driver.quickbar(qb={'button_text': 'Run sine wave', 'params': {}})
    @Driver.queued()
    def runSine(
        self,
        instrument_name: Optional[str] = None,
        **kwargs,
    ):
        return self.runMeasurement(
            measurement_mode='sine',
            instrument_name=instrument_name,
            return_data=True,
            task_name='runSine',
            step_name='sine',
            **kwargs,
        )

    @Driver.quickbar(qb={'button_text': 'Run differential pulse voltammetry', 'params': {}})
    @Driver.queued()
    def runDPV(
        self,
        instrument_name: Optional[str] = None,
        **kwargs,
    ):
        return self.runMeasurement(
            measurement_mode='dpv',
            instrument_name=instrument_name,
            return_data=True,
            task_name='runDPV',
            step_name='dpv',
            **kwargs,
        )

    @Driver.unqueued()
    def enqueuePanelMeasurement(
        self,
        measurement_mode: Optional[str] = None,
        instrument_name: Optional[str] = None,
        **kwargs,
    ):
        mode = str(self.config['measurement_mode'] if measurement_mode is None else measurement_mode).lower()
        task_name_by_mode = {
            'cv': 'enqueuePanelMeasurement',
            'ca': 'enqueuePanelMeasurement',
            'sine': 'enqueuePanelMeasurement',
            'dpv': 'enqueuePanelMeasurement',
        }
        step_name_by_mode = {
            'cv': 'panel_cv',
            'ca': 'panel_ca',
            'sine': 'panel_sine',
            'dpv': 'panel_dpv',
        }
        return self.runMeasurement(
            measurement_mode=mode,
            instrument_name=instrument_name,
            return_data=True,
            task_name=task_name_by_mode[mode],
            step_name=step_name_by_mode[mode],
            **kwargs,
        )


    @Driver.unqueued()
    def updatePanelConfig(
        self,
        instrument_name: Optional[str] = None,
        measurement_mode: Optional[str] = None,
        initial_voltage: Optional[float] = None,
        apex1_voltage: Optional[float] = None,
        apex2_voltage: Optional[float] = None,
        final_voltage: Optional[float] = None,
        apex1_hold: Optional[float] = None,
        apex2_hold: Optional[float] = None,
        final_hold: Optional[float] = None,
        scan_rate: Optional[float] = None,
        step_size: Optional[float] = None,
        cycles: Optional[int] = None,
        scan_delay: Optional[float] = None,
        current_range_mode: Optional[str] = None,
        ca_initial_voltage: Optional[float] = None,
        ca_step1_voltage: Optional[float] = None,
        ca_step2_voltage: Optional[float] = None,
        ca_initial_time: Optional[float] = None,
        ca_step1_time: Optional[float] = None,
        ca_step2_time: Optional[float] = None,
        ca_sample_time: Optional[float] = None,
        ca_expected_max_v: Optional[float] = None,
        sine_dc_offset: Optional[float] = None,
        sine_amplitude: Optional[float] = None,
        sine_frequency: Optional[float] = None,
        sine_acq_frequency: Optional[float] = None,
        sine_total_time: Optional[float] = None,
        sine_phase_offset: Optional[float] = None,
        dpv_initial_voltage: Optional[float] = None,
        dpv_final_voltage: Optional[float] = None,
        dpv_step_size: Optional[float] = None,
        dpv_pulse_size: Optional[float] = None,
        dpv_sample_period: Optional[float] = None,
        dpv_pulse_time: Optional[float] = None,
        dpv_noise_rejection: Optional[bool] = None,
        dpv_irange_mode: Optional[str] = None,
        dpv_max_current: Optional[float] = None,
        **kwargs,
    ):
        updates = {}
        if instrument_name is not None:
            updates['instrument_name'] = str(instrument_name)
        if measurement_mode is not None:
            updates['measurement_mode'] = str(measurement_mode).lower()
        numeric_fields = {
            'initial_voltage': initial_voltage,
            'apex1_voltage': apex1_voltage,
            'apex2_voltage': apex2_voltage,
            'final_voltage': final_voltage,
            'apex1_hold': apex1_hold,
            'apex2_hold': apex2_hold,
            'final_hold': final_hold,
            'scan_rate': scan_rate,
            'step_size': step_size,
            'scan_delay': scan_delay,
            'ca_initial_voltage': ca_initial_voltage,
            'ca_step1_voltage': ca_step1_voltage,
            'ca_step2_voltage': ca_step2_voltage,
            'ca_initial_time': ca_initial_time,
            'ca_step1_time': ca_step1_time,
            'ca_step2_time': ca_step2_time,
            'ca_sample_time': ca_sample_time,
            'ca_expected_max_v': ca_expected_max_v,
            'sine_dc_offset': sine_dc_offset,
            'sine_amplitude': sine_amplitude,
            'sine_frequency': sine_frequency,
            'sine_acq_frequency': sine_acq_frequency,
            'sine_total_time': sine_total_time,
            'sine_phase_offset': sine_phase_offset,
            'dpv_initial_voltage': dpv_initial_voltage,
            'dpv_final_voltage': dpv_final_voltage,
            'dpv_step_size': dpv_step_size,
            'dpv_pulse_size': dpv_pulse_size,
            'dpv_sample_period': dpv_sample_period,
            'dpv_pulse_time': dpv_pulse_time,
            'dpv_max_current': dpv_max_current,
        }
        for key, value in numeric_fields.items():
            if value is not None:
                updates[key] = float(value)
        integer_fields = {
            'cycles': cycles,
        }
        for key, value in integer_fields.items():
            if value is not None:
                updates[key] = int(value)
        if dpv_noise_rejection is not None:
            updates['dpv_noise_rejection'] = bool(dpv_noise_rejection)
        if current_range_mode is not None:
            updates['current_range_mode'] = str(current_range_mode)
        if dpv_irange_mode is not None:
            updates['dpv_irange_mode'] = self._normalize_dpv_irange_mode(dpv_irange_mode)
        if updates:
            self.set_config(**updates)
            if 'dpv_irange_mode' not in updates:
                self.config['dpv_irange_mode'] = self._normalize_dpv_irange_mode(self.config.get('dpv_irange_mode', 'fixed'))
            self.refresh_quickbar()
        return {
            'status': 'ok',
            'config': self._panel_config_snapshot(),
            'quickbar': self._quickbar_snapshot(),
        }

    def _ensure_service(self) -> None:
        env_path = pathlib.Path(self.config['gamry_env_path'])
        worker_path = pathlib.Path(self.config['worker_path'])
        python_path = self._resolve_env_python_path(env_path)
        if not env_path.exists():
            raise FileNotFoundError(f"Gamry virtual environment not found: {env_path}")
        if not python_path.exists():
            raise FileNotFoundError(f"Gamry virtual environment interpreter not found: {python_path}")
        if not worker_path.exists():
            raise FileNotFoundError(f"Gamry worker script not found: {worker_path}")

        if self._bridge_ready():
            return

        if self._service_process is not None and self._service_process.poll() is None:
            self._wait_for_service_ready()
            return

        if self._is_port_in_use(self.config['service_host'], int(self.config['service_port'])):
            self.shutdownService()

        command = [
            str(python_path),
            str(worker_path),
            'serve',
            self.config['service_host'],
            str(int(self.config['service_port'])),
            self.config['process_name'],
        ]
        launch_env = os.environ.copy()
        launch_env.pop('PYTHONHOME', None)
        launch_env.pop('PYTHONPATH', None)
        launch_env['AFL_GAMRY_WORKER_LOG'] = str(self._worker_log_path())
        print(f"Gamry bridge command: {command}")
        self._service_process = subprocess.Popen(
            command,
            cwd=str(env_path),
            env=launch_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._wait_for_service_ready()

    def _wait_for_service_ready(self) -> None:
        deadline = time.time() + float(self.config['service_startup_timeout'])
        while time.time() < deadline:
            process = self._service_process
            if process is not None and process.poll() is not None:
                stdout = process.stdout.read().strip() if process.stdout is not None else ''
                stderr = process.stderr.read().strip() if process.stderr is not None else ''
                raise RuntimeError(
                    f"Gamry bridge exited with code {process.returncode}. stderr={stderr or '<empty>'} stdout={stdout or '<empty>'}"
                )
            if self._bridge_ready():
                return
            time.sleep(0.2)
        raise RuntimeError(
            'Timed out waiting for Gamry bridge at {}:{}'.format(
                self.config['service_host'],
                int(self.config['service_port']),
            )
        )

    def _bridge_ready(self) -> bool:
        try:
            connection = self._get_bridge_connection()
            payload = connection.root.ping()
            return payload.get('status') == 'ok'
        except Exception:
            self._close_bridge_connection()
            return False

    def _close_bridge_connection(self) -> None:
        connection = self._bridge_connection
        self._bridge_connection = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def _get_bridge_connection(self):
        if self._bridge_connection is not None:
            return self._bridge_connection
        try:
            import rpyc
        except ImportError as exc:
            raise RuntimeError(
                'RPyC is required in the AFL Python environment to use the Gamry bridge client.'
            ) from exc
        self._bridge_connection = rpyc.connect(
            self.config['service_host'],
            int(self.config['service_port']),
            config={'sync_request_timeout': float(self.config['subprocess_timeout'])},
        )
        return self._bridge_connection

    def _is_port_in_use(self, host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex((host, port)) == 0

    def _run_worker_diagnostic(self, instrument_name: Optional[str] = None) -> Dict[str, Any]:
        env_path = pathlib.Path(self.config['gamry_env_path'])
        worker_path = pathlib.Path(self.config['worker_path'])
        python_path = self._resolve_env_python_path(env_path)
        if not env_path.exists():
            raise FileNotFoundError(f"Gamry virtual environment not found: {env_path}")
        if not python_path.exists():
            raise FileNotFoundError(f"Gamry virtual environment interpreter not found: {python_path}")
        if not worker_path.exists():
            raise FileNotFoundError(f"Gamry worker script not found: {worker_path}")

        command = [str(python_path), str(worker_path), 'diagnose']
        target_instrument = self.config['instrument_name'] if instrument_name is None else str(instrument_name)
        if target_instrument:
            command.append(target_instrument)
        command.append(self.config['process_name'])

        launch_env = os.environ.copy()
        launch_env.pop('PYTHONHOME', None)
        launch_env.pop('PYTHONPATH', None)
        print(f"Gamry diagnostic command: {command}")
        completed = subprocess.run(
            command,
            cwd=str(env_path),
            env=launch_env,
            capture_output=True,
            text=True,
            timeout=float(self.config['subprocess_timeout']),
            check=False,
        )
        stdout = completed.stdout.strip() if completed.stdout else ''
        stderr = completed.stderr.strip() if completed.stderr else ''
        if completed.returncode != 0:
            raise RuntimeError(
                f"Gamry diagnostic failed with code {completed.returncode}. stderr={stderr or '<empty>'} stdout={stdout or '<empty>'}"
            )
        if not stdout:
            raise RuntimeError('Gamry diagnostic produced no output')
        return json.loads(stdout)

    def _invoke_bridge(self, command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_service()
        try:
            connection = self._get_bridge_connection()
            if command == 'list_instruments':
                response = connection.root.list_instruments()
            elif command == 'validate_connection':
                response = connection.root.validate_connection(self.config['instrument_name'])
            elif command == 'release_connection':
                response = connection.root.release_connection()
            elif command == 'collect_cv':
                parameters = payload.get('parameters', {})
                response = connection.root.collect_cv(
                    self.config['instrument_name'],
                    self.config['process_name'],
                    float(parameters['initial_voltage']),
                    float(parameters['apex1_voltage']),
                    float(parameters['apex2_voltage']),
                    float(parameters['final_voltage']),
                    float(parameters['apex1_hold']),
                    float(parameters['apex2_hold']),
                    float(parameters['final_hold']),
                    float(parameters['scan_rate']),
                    float(parameters['step_size']),
                    int(parameters['cycles']),
                    float(parameters['scan_delay']),
                    str(parameters['current_range_mode']),
                )
            elif command == 'run_measurement':
                parameters = payload.get('parameters', {})
                try:
                    response = connection.root.run_measurement(
                        self.config['instrument_name'],
                        self.config['process_name'],
                        str(payload['measurement_mode']),
                        parameters,
                    )
                except Exception as exc:
                    if 'run_measurement' in str(exc):
                        self._restart_stale_bridge_service()
                        connection = self._get_bridge_connection()
                        response = connection.root.run_measurement(
                            self.config['instrument_name'],
                            self.config['process_name'],
                            str(payload['measurement_mode']),
                            parameters,
                        )
                    else:
                        raise
            else:
                raise ValueError(f'Unsupported bridge command: {command}')
            response = self._coerce_bridge_value(response)
        except Exception as exc:
            self._close_bridge_connection()
            raise RuntimeError(f'Gamry bridge request failed: {exc}') from exc

        if response.get('status') != 'ok':
            error = response.get('error', {})
            message = error.get('message', 'Unknown Gamry bridge error')
            code = error.get('code', 'bridge_error')
            raise RuntimeError(f"Gamry bridge error [{code}]: {message}")
        result = response.get('result', {})
        if isinstance(result, dict) and 'error' in result:
            error = result.get('error', {})
            message = error.get('message', 'Unknown Gamry measurement error')
            error_type = error.get('type', 'measurement_error')
            traceback_text = error.get('traceback')
            if traceback_text:
                raise RuntimeError(f"Gamry measurement error [{error_type}]: {message}\n{traceback_text}")
            raise RuntimeError(f"Gamry measurement error [{error_type}]: {message}")
        return response

    def _restart_stale_bridge_service(self) -> None:
        self._close_bridge_connection()
        self.shutdownService()
        self._ensure_service()

    def _sanitize_dataset_attrs(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        packet = DataPacket()
        return packet._core_sanitize(attrs)

    def _dataset_from_measurement_response(
        self,
        response: Dict[str, Any],
        task_name: Optional[str] = None,
        step_name: Optional[str] = None,
    ) -> xr.Dataset:
        payload = response.get('result', {})
        data = payload.get('data', {})
        measurement_type = payload.get('measurement_type', 'unknown')
        x_key = payload.get('x_key') or ('potential' if 'vf' in data else 'time')
        y_key = payload.get('y_key') or 'current'
        x_source = payload.get('x_source') or ('vf' if 'vf' in data else 'time')
        y_source = payload.get('y_source') or ('im' if 'im' in data else y_key)
        x_values = np.asarray(data.get(x_source, []), dtype=float)
        y_values = np.asarray(data.get(y_source, []), dtype=float)
        point_count = min(x_values.size, y_values.size) if x_values.size and y_values.size else max(x_values.size, y_values.size)
        point_index = np.arange(point_count, dtype=int)

        attrs = {
            'mode': payload.get('mode', 'run_measurement'),
            'measurement_type': measurement_type,
            'instrument_name': payload.get('instrument_name', self.config['instrument_name']),
            'process_name': payload.get('process_name', self.config['process_name']),
            'timestamp': payload.get('timestamp', datetime.datetime.now(datetime.timezone.utc).isoformat()),
            'parameters': payload.get('parameters', {}),
            'point_count': int(point_count),
            'x_key': x_key,
            'y_key': y_key,
            'measurement_mode': payload.get('measurement_mode', self.config['measurement_mode']),
        }
        if task_name is not None:
            attrs['task_name'] = task_name
        if step_name is not None:
            attrs['step_name'] = step_name
        if self.data is not None:
            sample_uuid = self.data.get('sample_uuid', None)
            sample_name = self.data.get('sample_name', None)
            if sample_uuid is not None:
                attrs['sample_uuid'] = sample_uuid
            if sample_name is not None:
                attrs['sample_name'] = sample_name

        ds = xr.Dataset(attrs=self._sanitize_dataset_attrs(attrs))
        ds['point'] = ('point', point_index)
        if x_values.size:
            ds[x_key] = ('point', x_values[:point_count])
        if y_values.size:
            ds[y_key] = ('point', y_values[:point_count])

        for source_name, target_name in (
            ('time', 'time'),
            ('vf', 'potential'),
            ('potential', 'potential'),
            ('vu', 'applied_signal'),
            ('applied_signal', 'applied_signal'),
            ('im', 'current'),
            ('current', 'current'),
        ):
            values = data.get(source_name)
            if values is None:
                continue
            array = np.asarray(values, dtype=float)
            if array.size == point_count:
                ds[target_name] = ('point', array[:point_count])

        reserved_names = {'point', x_key, y_key, 'time', 'potential', 'applied_signal', 'current'}
        for source_name, values in data.items():
            if source_name in reserved_names:
                continue
            try:
                array = np.asarray(values, dtype=float)
            except (TypeError, ValueError):
                continue
            if array.size == point_count:
                ds[source_name] = ('point', array[:point_count])

        return ds

    def _quickbar_snapshot(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        return {
            'runCV': self._quickbar_params_from_config(self.config, 'cv'),
            'runCA': self._quickbar_params_from_config(self.config, 'ca'),
            'runSine': self._quickbar_params_from_config(self.config, 'sine'),
            'runDPV': self._quickbar_params_from_config(self.config, 'dpv'),
        }

    def refresh_quickbar(self) -> None:
        for function_name, params in self._quickbar_snapshot().items():
            function_info = self.quickbar.function_info.get(function_name)
            if function_info is None:
                continue
            function_info.setdefault('qb', {})['params'] = params

    def _measurement_parameters(self, mode: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
        if mode == 'cv':
            return {
                'initial_voltage': float(self.config['initial_voltage'] if overrides.get('initial_voltage') is None else overrides['initial_voltage']),
                'apex1_voltage': float(self.config['apex1_voltage'] if overrides.get('apex1_voltage') is None else overrides['apex1_voltage']),
                'apex2_voltage': float(self.config['apex2_voltage'] if overrides.get('apex2_voltage') is None else overrides['apex2_voltage']),
                'final_voltage': float(self.config['final_voltage'] if overrides.get('final_voltage') is None else overrides['final_voltage']),
                'apex1_hold': float(self.config['apex1_hold'] if overrides.get('apex1_hold') is None else overrides['apex1_hold']),
                'apex2_hold': float(self.config['apex2_hold'] if overrides.get('apex2_hold') is None else overrides['apex2_hold']),
                'final_hold': float(self.config['final_hold'] if overrides.get('final_hold') is None else overrides['final_hold']),
                'scan_rate': float(self.config['scan_rate'] if overrides.get('scan_rate') is None else overrides['scan_rate']),
                'step_size': float(self.config['step_size'] if overrides.get('step_size') is None else overrides['step_size']),
                'cycles': int(self.config['cycles'] if overrides.get('cycles') is None else overrides['cycles']),
                'scan_delay': float(self.config['scan_delay'] if overrides.get('scan_delay') is None else overrides['scan_delay']),
                'current_range_mode': str(self.config['current_range_mode'] if overrides.get('current_range_mode') is None else overrides['current_range_mode']),
            }
        if mode == 'ca':
            return {
                'initial_voltage': float(self.config['ca_initial_voltage'] if overrides.get('ca_initial_voltage') is None else overrides['ca_initial_voltage']),
                'step1_voltage': float(self.config['ca_step1_voltage'] if overrides.get('ca_step1_voltage') is None else overrides['ca_step1_voltage']),
                'step2_voltage': float(self.config['ca_step2_voltage'] if overrides.get('ca_step2_voltage') is None else overrides['ca_step2_voltage']),
                'initial_time': float(self.config['ca_initial_time'] if overrides.get('ca_initial_time') is None else overrides['ca_initial_time']),
                'step1_time': float(self.config['ca_step1_time'] if overrides.get('ca_step1_time') is None else overrides['ca_step1_time']),
                'step2_time': float(self.config['ca_step2_time'] if overrides.get('ca_step2_time') is None else overrides['ca_step2_time']),
                'sample_time': float(self.config['ca_sample_time'] if overrides.get('ca_sample_time') is None else overrides['ca_sample_time']),
                'expected_max_v': float(self.config['ca_expected_max_v'] if overrides.get('ca_expected_max_v') is None else overrides['ca_expected_max_v']),
                'current_range_mode': str(self.config['current_range_mode'] if overrides.get('current_range_mode') is None else overrides['current_range_mode']),
            }
        if mode == 'sine':
            return {
                'dc_offset': float(self.config['sine_dc_offset'] if overrides.get('sine_dc_offset') is None else overrides['sine_dc_offset']),
                'amplitude': float(self.config['sine_amplitude'] if overrides.get('sine_amplitude') is None else overrides['sine_amplitude']),
                'signal_frequency': float(self.config['sine_frequency'] if overrides.get('sine_frequency') is None else overrides['sine_frequency']),
                'acq_frequency': float(self.config['sine_acq_frequency'] if overrides.get('sine_acq_frequency') is None else overrides['sine_acq_frequency']),
                'total_time': float(self.config['sine_total_time'] if overrides.get('sine_total_time') is None else overrides['sine_total_time']),
                'phase_offset': float(self.config['sine_phase_offset'] if overrides.get('sine_phase_offset') is None else overrides['sine_phase_offset']),
                'current_range_mode': str(self.config['current_range_mode'] if overrides.get('current_range_mode') is None else overrides['current_range_mode']),
            }
        if mode == 'dpv':
            irange_mode = self.config['dpv_irange_mode'] if overrides.get('dpv_irange_mode') is None else overrides['dpv_irange_mode']
            irange_mode = str(irange_mode).strip().lower()
            if irange_mode not in {'auto', 'fixed'}:
                irange_mode = 'fixed'
            return {
                'initial_voltage': float(self.config['dpv_initial_voltage'] if overrides.get('dpv_initial_voltage') is None else overrides['dpv_initial_voltage']),
                'final_voltage': float(self.config['dpv_final_voltage'] if overrides.get('dpv_final_voltage') is None else overrides['dpv_final_voltage']),
                'step_size': float(self.config['dpv_step_size'] if overrides.get('dpv_step_size') is None else overrides['dpv_step_size']),
                'pulse_size': float(self.config['dpv_pulse_size'] if overrides.get('dpv_pulse_size') is None else overrides['dpv_pulse_size']),
                'sample_period': float(self.config['dpv_sample_period'] if overrides.get('dpv_sample_period') is None else overrides['dpv_sample_period']),
                'pulse_time': float(self.config['dpv_pulse_time'] if overrides.get('dpv_pulse_time') is None else overrides['dpv_pulse_time']),
                'noise_rejection': bool(self.config['dpv_noise_rejection'] if overrides.get('dpv_noise_rejection') is None else overrides['dpv_noise_rejection']),
                'irange_mode': irange_mode,
                'max_current': float(self.config['dpv_max_current'] if overrides.get('dpv_max_current') is None else overrides['dpv_max_current']),
                'current_range_mode': str(self.config['current_range_mode'] if overrides.get('current_range_mode') is None else overrides['current_range_mode']),
            }
        raise ValueError(f'Unsupported measurement mode: {mode}')

    def _safe_list_instruments(self):
        try:
            response = self.listInstruments()
        except Exception as exc:
            return {
                'status': 'error',
                'message': str(exc),
                'instruments': [],
            }
        result = response.get('result', {}) if isinstance(response, dict) else {}
        instruments = result.get('instruments', []) if isinstance(result, dict) else []
        return {
            'status': 'ok',
            'instruments': self._coerce_bridge_value(instruments),
        }

    def _last_connection_snapshot(self):
        if self._last_connection_result is None:
            return None
        return self._coerce_bridge_value(self._last_connection_result)

    def _coerce_bridge_value(self, value):
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {self._coerce_bridge_value(key): self._coerce_bridge_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._coerce_bridge_value(item) for item in value]
        if hasattr(value, 'items'):
            try:
                return {
                    self._coerce_bridge_value(key): self._coerce_bridge_value(item)
                    for key, item in value.items()
                }
            except Exception:
                pass
        if hasattr(value, '__iter__') and not hasattr(value, 'dtype'):
            try:
                return [self._coerce_bridge_value(item) for item in list(value)]
            except Exception:
                pass
        return str(value)

    def _service_status(self) -> Dict[str, Any]:
        process = self._service_process
        process_running = process is not None and process.poll() is None
        port_open = self._is_port_in_use(self.config['service_host'], int(self.config['service_port']))
        bridge_ready = False
        try:
            bridge_ready = self._bridge_ready()
        except Exception:
            bridge_ready = False
        has_connection = self._last_connection_result is not None
        bridge_usable = bridge_ready or has_connection
        return {
            'process_running': process_running,
            'port_open': port_open,
            'bridge_ready': bridge_ready,
            'bridge_usable': bridge_usable,
            'host': self.config['service_host'],
            'port': int(self.config['service_port']),
            'instrument_name': self.config['instrument_name'],
            'has_connection': has_connection,
        }

    def _panel_config_snapshot(self) -> Dict[str, Any]:
        return {
            'gamry_env_path': self.config['gamry_env_path'],
            'worker_path': self.config['worker_path'],
            'instrument_name': self.config['instrument_name'],
            'process_name': self.config['process_name'],
            'subprocess_timeout': float(self.config['subprocess_timeout']),
            'service_host': self.config['service_host'],
            'service_port': int(self.config['service_port']),
            'service_startup_timeout': float(self.config['service_startup_timeout']),
            'measurement_mode': self.config['measurement_mode'],
            'initial_voltage': float(self.config['initial_voltage']),
            'apex1_voltage': float(self.config['apex1_voltage']),
            'apex2_voltage': float(self.config['apex2_voltage']),
            'final_voltage': float(self.config['final_voltage']),
            'apex1_hold': float(self.config['apex1_hold']),
            'apex2_hold': float(self.config['apex2_hold']),
            'final_hold': float(self.config['final_hold']),
            'scan_rate': float(self.config['scan_rate']),
            'step_size': float(self.config['step_size']),
            'cycles': int(self.config['cycles']),
            'scan_delay': float(self.config['scan_delay']),
            'current_range_mode': self.config['current_range_mode'],
            'ca_initial_voltage': float(self.config['ca_initial_voltage']),
            'ca_step1_voltage': float(self.config['ca_step1_voltage']),
            'ca_step2_voltage': float(self.config['ca_step2_voltage']),
            'ca_initial_time': float(self.config['ca_initial_time']),
            'ca_step1_time': float(self.config['ca_step1_time']),
            'ca_step2_time': float(self.config['ca_step2_time']),
            'ca_sample_time': float(self.config['ca_sample_time']),
            'ca_expected_max_v': float(self.config['ca_expected_max_v']),
            'sine_dc_offset': float(self.config['sine_dc_offset']),
            'sine_amplitude': float(self.config['sine_amplitude']),
            'sine_frequency': float(self.config['sine_frequency']),
            'sine_acq_frequency': float(self.config['sine_acq_frequency']),
            'sine_total_time': float(self.config['sine_total_time']),
            'sine_phase_offset': float(self.config['sine_phase_offset']),
            'dpv_initial_voltage': float(self.config['dpv_initial_voltage']),
            'dpv_final_voltage': float(self.config['dpv_final_voltage']),
            'dpv_step_size': float(self.config['dpv_step_size']),
            'dpv_pulse_size': float(self.config['dpv_pulse_size']),
            'dpv_sample_period': float(self.config['dpv_sample_period']),
            'dpv_pulse_time': float(self.config['dpv_pulse_time']),
            'dpv_noise_rejection': bool(self.config['dpv_noise_rejection']),
            'dpv_irange_mode': self.config['dpv_irange_mode'],
            'dpv_max_current': float(self.config['dpv_max_current']),
        }

    def _serialize_dataset(self, dataset: Optional[xr.Dataset]) -> Optional[Dict[str, Any]]:
        if dataset is None:
            return None
        payload = {
            'attrs': {},
            'data': {},
            'dims': {key: int(value) for key, value in dataset.sizes.items()},
        }
        for key, value in dataset.attrs.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload['attrs'][key] = value
            else:
                payload['attrs'][key] = str(value)
        for name in dataset.data_vars:
            payload['data'][name] = dataset[name].values.tolist()
        for name in dataset.coords:
            if name not in payload['data']:
                payload['data'][name] = dataset.coords[name].values.tolist()
        return payload

    def _build_panel_result(self, dataset: Optional[xr.Dataset]) -> Optional[Dict[str, Any]]:
        serialized = self._serialize_dataset(dataset)
        if serialized is None:
            return None

        attrs = dict(serialized.get('attrs', {}))
        data = serialized.get('data', {})
        measurement_type = str(attrs.get('measurement_type', 'measurement'))
        plot_data: Dict[str, Any] = {}

        if 'time' in data:
            plot_data['time_s'] = data['time']
        if 'potential' in data:
            plot_data['voltage_v'] = data['potential']
        if 'current' in data:
            if measurement_type == 'differential_pulse_voltammetry':
                plot_data['diff_current_a'] = data['current']
            else:
                plot_data['current_a'] = data['current']

        attrs['plot_source'] = 'dataset'
        if measurement_type == 'differential_pulse_voltammetry':
            attrs['plot_variant'] = 'dpv_differential'

        return {
            'attrs': attrs,
            'data': data,
            'plot_data': plot_data,
            'dims': serialized.get('dims', {}),
        }


# _OVERRIDE_MAIN_MODULE_NAME = 'GamryDriver'
_DEFAULT_CUSTOM_CONFIG = {
    '_classname': 'AFL.automation.instrument.Gamry.GamryDriver.GamryDriver',
}
_DEFAULT_PORT = 5051

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
