"""Proxy APIServer driver for a remotely hosted :class:`GamryDriver`."""

from typing import Any, Dict, Optional

import xarray as xr

from AFL.automation.APIServer.Client import Client
from AFL.automation.APIServer.Driver import Driver, ProxyConnectionError, ProxyDriver


class GamryProxyDriver(ProxyDriver):
    """Proxy measurement requests to the APIServer that owns a Gamry instrument.

    Use this driver on a control or analysis machine when ``GamryDriver`` runs
    on the Windows instrument host.  ``server_ip`` and ``server_port`` name
    that *remote APIServer*, not the potentiostat's network address.  An SSH
    tunnel may be used as the transport; configure the local tunnel endpoint
    in ``server_ip``/``server_port``.

    The proxy has no direct instrument transport.  It forwards queued
    ``runCV``, ``runCA``, ``runSine``, and ``runDPV`` commands to the owner
    server, waits for the owner task, and retrieves its xarray dataset.

    Example
    -------
    With an SSH tunnel forwarding local port 9090 to the Windows APIServer's
    port 5051::

        proxy = GamryProxyDriver(overrides={
            'server_ip': '127.0.0.1',
            'server_port': '9090',
            'instrument_name': 'PSTAT',
        })
        dataset = proxy.runCV(
            apex1_voltage=-0.2,
            apex2_voltage=0.5,
            scan_rate=0.1,
            step_size=0.01,
        )

    When hosted by an APIServer, queue the same ``runCV`` task against the
    proxy server.  The returned task result is the owner-side dataset.
    """
    defaults = {}
    # Remote APIServer / SSH-tunnel endpoint.
    defaults['server_ip'] = '127.0.0.1'
    defaults['server_port'] = '9090'
    defaults['server_username'] = 'GamryProxyDriver'
    defaults['measurement_mode'] = 'cv'
    defaults['instrument_name'] = 'PSTAT'
    # Cyclic voltammetry (CV) settings.
    defaults['initial_voltage'] = 0.0
    defaults['apex1_voltage'] = -0.2
    defaults['apex2_voltage'] = 0.5
    defaults['final_voltage'] = 0.0
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

    @staticmethod
    def _quickbar_param(label: str, param_type: str, default: Any) -> Dict[str, Any]:
        return {'label': label, 'type': param_type, 'default': default}

    @classmethod
    def _quickbar_params_from_config(cls, config, mode: str) -> Dict[str, Dict[str, Any]]:
        """Return ordered, unit-labeled inputs for one measurement type."""
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
                'ca_initial_voltage': cls._quickbar_param('Initial Voltage (V)', 'float', config['ca_initial_voltage']),
                'ca_step1_voltage': cls._quickbar_param('Step 1 Voltage (V)', 'float', config['ca_step1_voltage']),
                'ca_step2_voltage': cls._quickbar_param('Step 2 Voltage (V)', 'float', config['ca_step2_voltage']),
                'ca_initial_time': cls._quickbar_param('Initial Time (s)', 'float', config['ca_initial_time']),
                'ca_step1_time': cls._quickbar_param('Step 1 Time (s)', 'float', config['ca_step1_time']),
                'ca_step2_time': cls._quickbar_param('Step 2 Time (s)', 'float', config['ca_step2_time']),
                'ca_sample_time': cls._quickbar_param('Sample Time (s)', 'float', config['ca_sample_time']),
                'ca_expected_max_v': cls._quickbar_param('Expected Maximum Voltage (V)', 'float', config['ca_expected_max_v']),
                'current_range_mode': cls._quickbar_param('Current Range Mode', 'text', config['current_range_mode']),
            }
        if mode == 'sine':
            return {
                'sine_dc_offset': cls._quickbar_param('DC Offset (V)', 'float', config['sine_dc_offset']),
                'sine_amplitude': cls._quickbar_param('Amplitude (V)', 'float', config['sine_amplitude']),
                'sine_frequency': cls._quickbar_param('Signal Frequency (Hz)', 'float', config['sine_frequency']),
                'sine_acq_frequency': cls._quickbar_param('Acquisition Frequency (Hz)', 'float', config['sine_acq_frequency']),
                'sine_total_time': cls._quickbar_param('Total Time (s)', 'float', config['sine_total_time']),
                'sine_phase_offset': cls._quickbar_param('Phase Offset (rad)', 'float', config['sine_phase_offset']),
                'current_range_mode': cls._quickbar_param('Current Range Mode', 'text', config['current_range_mode']),
            }
        if mode == 'dpv':
            return {
                'dpv_initial_voltage': cls._quickbar_param('Initial Voltage (V)', 'float', config['dpv_initial_voltage']),
                'dpv_final_voltage': cls._quickbar_param('Final Voltage (V)', 'float', config['dpv_final_voltage']),
                'dpv_step_size': cls._quickbar_param('Step Size (V)', 'float', config['dpv_step_size']),
                'dpv_pulse_size': cls._quickbar_param('Pulse Size (V)', 'float', config['dpv_pulse_size']),
                'dpv_sample_period': cls._quickbar_param('Sample Period (s)', 'float', config['dpv_sample_period']),
                'dpv_pulse_time': cls._quickbar_param('Pulse Time (s)', 'float', config['dpv_pulse_time']),
                'dpv_noise_rejection': cls._quickbar_param('Noise Rejection', 'bool', config['dpv_noise_rejection']),
                'dpv_irange_mode': cls._quickbar_param('Current Range Mode', 'text', config['dpv_irange_mode']),
                'dpv_max_current': cls._quickbar_param('Maximum Current (A)', 'float', config['dpv_max_current']),
                'current_range_mode': cls._quickbar_param('Current Range Mode', 'text', config['current_range_mode']),
            }
        raise ValueError(f'Unsupported quickbar mode: {mode}')

    def __init__(
        self,
        overrides=None,
        server_ip=None,
        server_port=None,
        proxy_clients=None,
    ):
        overrides = dict(overrides or {})
        if server_ip is not None:
            overrides['server_ip'] = server_ip
        if server_port is not None:
            overrides['server_port'] = str(server_port)
        super().__init__(
            name='GamryProxyDriver',
            defaults=self.gather_defaults(),
            overrides=overrides,
            proxy_clients=proxy_clients,
        )
        self.useful_links['Remote Gamry Driver'] = self._server_url()
        self.refresh_quickbar()

    def status(self):
        return [
            f"server_url={self._server_url()}",
            f"instrument_name={self.config['instrument_name']}",
            f"measurement_mode={self.config['measurement_mode']}",
        ]

    def _server_url(self) -> str:
        return f"http://{self.config['server_ip']}:{self.config['server_port']}"

    def _get_gamry_client(self) -> Client:
        """Return the lazily constructed client for the owner APIServer."""
        username = str(self.config.get('server_username', '')).strip() or None
        return self.get_proxy_client(
            'gamry',
            ip=str(self.config['server_ip']),
            port=str(self.config['server_port']),
            username=username,
            client_factory=Client,
        )

    def _coerce_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {'1', 'true', 'yes', 'on'}
        return bool(value)

    def refresh_quickbar(self) -> None:
        for function_name, mode in (
            ('runCV', 'cv'),
            ('runCA', 'ca'),
            ('runSine', 'sine'),
            ('runDPV', 'dpv'),
        ):
            function_info = self.quickbar.function_info.get(function_name)
            if function_info is not None:
                function_info.setdefault('qb', {})['params'] = self._quickbar_params_from_config(
                    self.config, mode
                )

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
                'ca_initial_voltage': float(self.config['ca_initial_voltage'] if overrides.get('ca_initial_voltage') is None else overrides['ca_initial_voltage']),
                'ca_step1_voltage': float(self.config['ca_step1_voltage'] if overrides.get('ca_step1_voltage') is None else overrides['ca_step1_voltage']),
                'ca_step2_voltage': float(self.config['ca_step2_voltage'] if overrides.get('ca_step2_voltage') is None else overrides['ca_step2_voltage']),
                'ca_initial_time': float(self.config['ca_initial_time'] if overrides.get('ca_initial_time') is None else overrides['ca_initial_time']),
                'ca_step1_time': float(self.config['ca_step1_time'] if overrides.get('ca_step1_time') is None else overrides['ca_step1_time']),
                'ca_step2_time': float(self.config['ca_step2_time'] if overrides.get('ca_step2_time') is None else overrides['ca_step2_time']),
                'ca_sample_time': float(self.config['ca_sample_time'] if overrides.get('ca_sample_time') is None else overrides['ca_sample_time']),
                'ca_expected_max_v': float(self.config['ca_expected_max_v'] if overrides.get('ca_expected_max_v') is None else overrides['ca_expected_max_v']),
                'current_range_mode': str(self.config['current_range_mode'] if overrides.get('current_range_mode') is None else overrides['current_range_mode']),
            }
        if mode == 'sine':
            return {
                'sine_dc_offset': float(self.config['sine_dc_offset'] if overrides.get('sine_dc_offset') is None else overrides['sine_dc_offset']),
                'sine_amplitude': float(self.config['sine_amplitude'] if overrides.get('sine_amplitude') is None else overrides['sine_amplitude']),
                'sine_frequency': float(self.config['sine_frequency'] if overrides.get('sine_frequency') is None else overrides['sine_frequency']),
                'sine_acq_frequency': float(self.config['sine_acq_frequency'] if overrides.get('sine_acq_frequency') is None else overrides['sine_acq_frequency']),
                'sine_total_time': float(self.config['sine_total_time'] if overrides.get('sine_total_time') is None else overrides['sine_total_time']),
                'sine_phase_offset': float(self.config['sine_phase_offset'] if overrides.get('sine_phase_offset') is None else overrides['sine_phase_offset']),
                'current_range_mode': str(self.config['current_range_mode'] if overrides.get('current_range_mode') is None else overrides['current_range_mode']),
            }
        if mode == 'dpv':
            return {
                'dpv_initial_voltage': float(self.config['dpv_initial_voltage'] if overrides.get('dpv_initial_voltage') is None else overrides['dpv_initial_voltage']),
                'dpv_final_voltage': float(self.config['dpv_final_voltage'] if overrides.get('dpv_final_voltage') is None else overrides['dpv_final_voltage']),
                'dpv_step_size': float(self.config['dpv_step_size'] if overrides.get('dpv_step_size') is None else overrides['dpv_step_size']),
                'dpv_pulse_size': float(self.config['dpv_pulse_size'] if overrides.get('dpv_pulse_size') is None else overrides['dpv_pulse_size']),
                'dpv_sample_period': float(self.config['dpv_sample_period'] if overrides.get('dpv_sample_period') is None else overrides['dpv_sample_period']),
                'dpv_pulse_time': float(self.config['dpv_pulse_time'] if overrides.get('dpv_pulse_time') is None else overrides['dpv_pulse_time']),
                'dpv_noise_rejection': self._coerce_bool(self.config['dpv_noise_rejection'] if overrides.get('dpv_noise_rejection') is None else overrides['dpv_noise_rejection']),
                'dpv_irange_mode': str(self.config['dpv_irange_mode'] if overrides.get('dpv_irange_mode') is None else overrides['dpv_irange_mode']),
                'dpv_max_current': float(self.config['dpv_max_current'] if overrides.get('dpv_max_current') is None else overrides['dpv_max_current']),
                'current_range_mode': str(self.config['current_range_mode'] if overrides.get('current_range_mode') is None else overrides['current_range_mode']),
            }
        raise ValueError(f'Unsupported measurement mode: {mode}')

    def _remote_dataset(self, task_name: str, measurement_mode: str, instrument_name: Optional[str] = None, **kwargs) -> xr.Dataset:
        payload = self._measurement_parameters(measurement_mode, kwargs)
        payload['instrument_name'] = self.config['instrument_name'] if instrument_name is None else str(instrument_name)
        client = self._get_gamry_client()
        remote_task_uuid = self.enqueue_proxy('gamry', task_name, **payload)
        try:
            meta = client.wait(target_uuid=remote_task_uuid, first_check_delay=0.5)
        except Exception as exc:
            raise ProxyConnectionError(
                f"Unable to wait for {task_name!r} through gamry proxy. "
                "The remote AFL APIServer may be unavailable."
            ) from exc
        if meta.get('exit_state') == 'Error!':
            raise RuntimeError(meta.get('return_val'))
        return_val = meta.get('return_val')
        if isinstance(return_val, dict):
            dataset_payload = return_val.get('dataset')
            if isinstance(dataset_payload, dict):
                return self._dataset_from_payload(dataset_payload)
        if return_val == 'xarray.Dataset':
            try:
                dataset = client.retrieve_obj(remote_task_uuid)
            except Exception as exc:
                raise ProxyConnectionError(
                    f"Unable to retrieve {task_name!r} results through gamry proxy. "
                    "The remote AFL APIServer may be unavailable."
                ) from exc
            if isinstance(dataset, xr.Dataset):
                return dataset
            raise TypeError(
                f"Remote task {task_name} for uuid={remote_task_uuid} stored a non-dataset object: "
                f"type={type(dataset).__name__}, value={dataset!r}"
            )
        raise TypeError(
            f"Remote task {task_name} for uuid={remote_task_uuid} returned unsupported payload: "
            f"type={type(return_val).__name__}, value={return_val!r}"
        )

    @staticmethod
    def _dataset_from_payload(payload: Dict[str, Any]) -> xr.Dataset:
        """Reconstruct a dataset returned inline by a compatible owner driver."""
        try:
            return xr.Dataset.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise TypeError('Remote Gamry driver returned an invalid dataset payload') from exc

    @Driver.unqueued()
    def ping(self):
        client = self._get_gamry_client()
        try:
            driver_status = client.driver_status()
        except Exception as exc:
            raise ProxyConnectionError(
                'Unable to query Gamry driver status through proxy. '
                'The remote AFL APIServer may be unavailable.'
            ) from exc
        return {
            'status': 'ok',
            'server_url': self._server_url(),
            'driver_status': driver_status,
        }

    @Driver.unqueued()
    def startBridge(self):
        self._get_gamry_client()
        return self.query_proxy('gamry', 'startService')

    @Driver.unqueued()
    def connectInstrument(self, instrument_name: Optional[str] = None):
        self._get_gamry_client()
        target = self.config['instrument_name'] if instrument_name is None else str(instrument_name)
        result = self.query_proxy('gamry', 'connectInstrument', instrument_name=target)
        self.config['instrument_name'] = target
        return result

    @Driver.quickbar(qb={'button_text': 'Run cyclic voltammetry', 'params': {}})
    @Driver.queued()
    def runCV(self, instrument_name: Optional[str] = None, **kwargs):
        return self._remote_dataset('runCV', 'cv', instrument_name=instrument_name, **kwargs)

    @Driver.quickbar(qb={'button_text': 'Run chronoamperometry', 'params': {}})
    @Driver.queued()
    def runCA(self, instrument_name: Optional[str] = None, **kwargs):
        return self._remote_dataset('runCA', 'ca', instrument_name=instrument_name, **kwargs)

    @Driver.quickbar(qb={'button_text': 'Run sine wave', 'params': {}})
    @Driver.queued()
    def runSine(self, instrument_name: Optional[str] = None, **kwargs):
        return self._remote_dataset('runSine', 'sine', instrument_name=instrument_name, **kwargs)

    @Driver.quickbar(qb={'button_text': 'Run differential pulse voltammetry', 'params': {}})
    @Driver.queued()
    def runDPV(self, instrument_name: Optional[str] = None, **kwargs):
        return self._remote_dataset('runDPV', 'dpv', instrument_name=instrument_name, **kwargs)


_DEFAULT_CUSTOM_CONFIG = {
    '_classname': 'AFL.automation.instrument.Gamry.GamryProxyDriver.GamryProxyDriver',
}
_DEFAULT_PORT = 5052

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
