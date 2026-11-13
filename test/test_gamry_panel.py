import xarray as xr

from AFL.automation.instrument.Gamry.GamryDriver import GamryDriver


class _PanelTestGamryDriver(GamryDriver):
    def __init__(self):
        self._test_instruments = ['PSTAT', 'PSTAT-2']
        super().__init__(
            gamry_env_path=r"C:\\fake\\env",
            instrument_name="PSTAT",
            overrides={
                'worker_path': r"C:\\fake\\worker.py",
                'service_host': '127.0.0.1',
                'service_port': 5059,
            },
        )

    def _is_port_in_use(self, host, port):
        return False

    def _bridge_ready(self):
        return False

    def listInstruments(self):
        return {'status': 'ok', 'result': {'instruments': list(self._test_instruments)}}

    def validateConnection(self):
        return {
            'status': 'ok',
            'result': {
                'instrument_name': self.config['instrument_name'],
                'serial_number': 'TEST-123',
            },
        }

    def collectCV(self, **kwargs):
        dataset = xr.Dataset(
            data_vars={
                'potential': ('point', [0.1, 0.2, 0.3]),
                'current': ('point', [1.0, 1.5, 1.2]),
                'time': ('point', [0.0, 1.0, 2.0]),
            },
            coords={'point': [0, 1, 2]},
        )
        dataset.attrs['instrument_name'] = self.config['instrument_name']
        dataset.attrs['point_count'] = 3
        dataset.attrs['parameters'] = {'scan_rate': kwargs.get('scan_rate', self.config['scan_rate'])}
        dataset.attrs['measurement_type'] = 'cyclic_voltammetry'
        dataset.attrs['x_key'] = 'potential'
        dataset.attrs['y_key'] = 'current'
        return dataset

    def runMeasurement(self, measurement_mode=None, instrument_name=None, return_data=False, **kwargs):
        mode = measurement_mode or self.config['measurement_mode']
        if instrument_name is not None:
            self.config['instrument_name'] = instrument_name
        if mode == 'ca':
            dataset = xr.Dataset(
                data_vars={
                    'time': ('point', [0.0, 0.5, 1.0]),
                    'current': ('point', [1.0, 0.8, 0.6]),
                    'potential': ('point', [0.5, 0.5, 0.0]),
                },
                coords={'point': [0, 1, 2]},
            )
            dataset.attrs['measurement_type'] = 'chronoamperometry'
            dataset.attrs['x_key'] = 'time'
            dataset.attrs['y_key'] = 'current'
            dataset.attrs['parameters'] = {'initial_time': 1.0}
        elif mode == 'dpv':
            dataset = xr.Dataset(
                data_vars={
                    'potential': ('point', [-1.0, -0.995]),
                    'current': ('point', [0.05, 0.07]),
                },
                coords={'point': [0, 1]},
            )
            dataset.attrs['measurement_type'] = 'differential_pulse_voltammetry'
            dataset.attrs['x_key'] = 'potential'
            dataset.attrs['y_key'] = 'current'
            dataset.attrs['parameters'] = {'dpv_step_size': 0.005}
        elif mode == 'sine':
            dataset = xr.Dataset(
                data_vars={
                    'time': ('point', [0.0, 0.1, 0.2]),
                    'current': ('point', [0.01, 0.02, 0.01]),
                    'potential': ('point', [0.0, 0.05, 0.0]),
                },
                coords={'point': [0, 1, 2]},
            )
            dataset.attrs['measurement_type'] = 'sine_wave'
            dataset.attrs['x_key'] = 'time'
            dataset.attrs['y_key'] = 'current'
            dataset.attrs['parameters'] = {'signal_frequency': 10.0}
        else:
            dataset = self.collectCV(**kwargs)
            dataset.attrs['parameters'] = {'scan_rate': kwargs.get('scan_rate', self.config['scan_rate'])}
        dataset.attrs['instrument_name'] = self.config['instrument_name']
        dataset.attrs['point_count'] = int(dataset.sizes['point'])
        self._last_cv_dataset = dataset
        return dataset


def test_get_panel_state_returns_config_and_service_snapshot():
    driver = _PanelTestGamryDriver()

    state = driver.getPanelState()

    assert state['status'] == 'ok'
    assert state['config']['instrument_name'] == 'PSTAT'
    assert state['service']['bridge_ready'] is False
    assert state['last_result'] is None
    assert 'runCV' in state['quickbar']
    assert 'initial_voltage' in state['quickbar']['runCV']


def test_update_panel_config_persists_numeric_values():
    driver = _PanelTestGamryDriver()

    result = driver.updatePanelConfig(
        instrument_name='PSTAT-2',
        initial_voltage=0.25,
        scan_rate=0.5,
        cycles=3,
        current_range_mode='manual',
    )

    assert result['status'] == 'ok'
    assert driver.config['instrument_name'] == 'PSTAT-2'
    assert driver.config['initial_voltage'] == 0.25
    assert driver.config['scan_rate'] == 0.5
    assert driver.config['cycles'] == 3
    assert driver.config['current_range_mode'] == 'manual'


def test_update_panel_config_persists_mode_specific_values():
    driver = _PanelTestGamryDriver()

    result = driver.updatePanelConfig(
        measurement_mode='sine',
        sine_dc_offset=0.1,
        sine_amplitude=0.02,
        sine_frequency=25.0,
        sine_acq_frequency=1000.0,
        sine_total_time=4.0,
    )

    assert result['status'] == 'ok'
    assert driver.config['measurement_mode'] == 'sine'
    assert driver.config['sine_dc_offset'] == 0.1
    assert driver.config['sine_amplitude'] == 0.02
    assert driver.config['sine_frequency'] == 25.0
    assert driver.config['sine_acq_frequency'] == 1000.0
    assert driver.config['sine_total_time'] == 4.0


def test_update_panel_config_persists_dpv_values():
    driver = _PanelTestGamryDriver()

    result = driver.updatePanelConfig(
        measurement_mode='dpv',
        dpv_initial_voltage=-1.0,
        dpv_final_voltage=0.0,
        dpv_step_size=0.005,
        dpv_pulse_size=0.025,
        dpv_sample_period=0.5,
        dpv_pulse_time=0.1,
        dpv_noise_rejection=True,
        dpv_irange_mode='fixed',
        dpv_max_current=0.3,
    )

    assert result['status'] == 'ok'
    assert driver.config['measurement_mode'] == 'dpv'
    assert driver.config['dpv_initial_voltage'] == -1.0
    assert driver.config['dpv_final_voltage'] == 0.0
    assert driver.config['dpv_step_size'] == 0.005
    assert driver.config['dpv_pulse_size'] == 0.025
    assert driver.config['dpv_sample_period'] == 0.5
    assert driver.config['dpv_noise_rejection'] is True
    assert driver.config['dpv_irange_mode'] == 'fixed'
    assert driver.config['dpv_max_current'] == 0.3


def test_connect_instrument_updates_selected_potentiostat():
    driver = _PanelTestGamryDriver()

    result = driver.connectInstrument('PSTAT-2')

    assert result['status'] == 'ok'
    assert driver.config['instrument_name'] == 'PSTAT-2'
    assert result['connection']['instrument_name'] == 'PSTAT-2'
    assert result['connection']['validation']['result']['serial_number'] == 'TEST-123'
    assert result['available_instruments']['instruments'] == ['PSTAT', 'PSTAT-2']
    assert result['service']['bridge_ready'] is False
    assert result['service']['bridge_usable'] is True


def test_run_cv_now_serializes_dataset_and_caches_last_result():
    driver = _PanelTestGamryDriver()

    dataset = driver.runMeasurement(measurement_mode='cv', return_data=True, scan_rate=0.75)
    panel_result = driver._build_panel_result(dataset)
    driver._last_panel_result = panel_result

    assert panel_result['attrs']['instrument_name'] == 'PSTAT'
    assert panel_result['attrs']['point_count'] == 3
    assert panel_result['attrs']['plot_source'] == 'dataset'
    assert panel_result['plot_data']['voltage_v'] == [0.1, 0.2, 0.3]
    assert panel_result['plot_data']['current_a'] == [1.0, 1.5, 1.2]
    assert driver.getPanelState()['last_result']['plot_data']['time_s'] == [0.0, 1.0, 2.0]


def test_run_measurement_serializes_generic_result():
    driver = _PanelTestGamryDriver()

    dataset = driver.runMeasurement(measurement_mode='ca', return_data=True)
    result = driver._build_panel_result(dataset)

    assert result['attrs']['measurement_type'] == 'chronoamperometry'
    assert result['attrs']['plot_source'] == 'dataset'
    assert result['plot_data']['time_s'] == [0.0, 0.5, 1.0]
    assert result['plot_data']['voltage_v'] == [0.5, 0.5, 0.0]
    assert result['plot_data']['current_a'] == [1.0, 0.8, 0.6]


def test_run_measurement_serializes_dpv_result_from_dataset():
    driver = _PanelTestGamryDriver()

    dataset = driver.runMeasurement(measurement_mode='dpv', return_data=True)
    result = driver._build_panel_result(dataset)
    driver._last_panel_result = result

    assert result['attrs']['measurement_type'] == 'differential_pulse_voltammetry'
    assert result['attrs']['plot_source'] == 'dataset'
    assert result['attrs']['plot_variant'] == 'dpv_differential'
    assert result['plot_data']['voltage_v'] == [-1.0, -0.995]
    assert result['plot_data']['diff_current_a'] == [0.05, 0.07]
    assert 'current_a' not in result['plot_data']
    assert 'time_s' not in result['plot_data']
    assert result['data']['potential'] == [-1.0, -0.995]
    assert driver.getPanelState()['last_result']['plot_data']['voltage_v'] == [-1.0, -0.995]


def test_run_measurement_serializes_sine_result_from_dataset():
    driver = _PanelTestGamryDriver()

    dataset = driver.runMeasurement(measurement_mode='sine', return_data=True)
    result = driver._build_panel_result(dataset)

    assert result['attrs']['measurement_type'] == 'sine_wave'
    assert result['attrs']['plot_source'] == 'dataset'
    assert result['plot_data']['time_s'] == [0.0, 0.1, 0.2]
    assert result['plot_data']['voltage_v'] == [0.0, 0.05, 0.0]
    assert result['plot_data']['current_a'] == [0.01, 0.02, 0.01]


def test_run_measurement_persists_dataset_to_data_backend():
    driver = _PanelTestGamryDriver()

    class _RecordingData:
        def __init__(self):
            self.values = {}
            self.finalize_calls = 0

        def __setitem__(self, key, value):
            self.values[key] = value

        def finalize(self):
            self.finalize_calls += 1

    driver.data = _RecordingData()

    dataset = driver.runMeasurement(measurement_mode='ca', return_data=True)
    driver.data['main_dataset'] = dataset
    driver.data.finalize()

    assert 'main_dataset' in driver.data.values
    assert driver.data.values['main_dataset'].attrs['measurement_type'] == 'chronoamperometry'
    assert driver.data.finalize_calls == 1
