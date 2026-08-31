from AFL.automation.instrument.Gamry.GamryProxyDriver import GamryProxyDriver
from AFL.automation.APIServer.Driver import ProxyDriver


class FakeClient:
    def __init__(self, ip=None, port='5000', username=None, interactive=False):
        self.ip = ip
        self.port = port
        self.interactive = interactive
        self.logged_in_username = None
        self.calls = []
        if username is not None:
            self.login(username)

    def login(self, username, populate_commands=True):
        self.logged_in_username = username

    def driver_status(self):
        self.calls.append(('driver_status', {}, None))
        return {'status': 'ok', 'driver': 'remote-gamry'}

    def query_driver(self, **kwargs):
        self.calls.append(('query_driver', kwargs, None))
        route = kwargs.get('r')
        if route == 'validateConnection':
            return {'status': 'ok', 'validated': True}
        if route == 'connectInstrument':
            return {'status': 'ok', 'instrument_name': kwargs.get('instrument_name', 'PSTAT')}
        if route == 'startService':
            return {'status': 'ok'}
        raise AssertionError(f'Unexpected query_driver route: {route}')

    def enqueue(self, **kwargs):
        self.calls.append(('enqueue', kwargs, None))
        return 'remote-task-1'

    def wait(self, target_uuid, first_check_delay=0.5):
        self.calls.append(('wait', {'target_uuid': target_uuid, 'first_check_delay': first_check_delay}, None))
        return {
            'exit_state': 'Completed',
            'return_val': 'xarray.Dataset',
        }

    def retrieve_obj(self, uuid):
        import xarray as xr

        self.calls.append(('retrieve_obj', {'uuid': uuid}, None))
        return xr.Dataset(
            data_vars={
                'current': ('point', [1.0, 0.8]),
                'time': ('point', [0.0, 0.5]),
            },
            coords={'point': [0, 1]},
            attrs={'measurement_mode': 'ca'},
        )


def test_status_reports_remote_endpoint(monkeypatch):
    monkeypatch.setattr('AFL.automation.instrument.Gamry.GamryProxyDriver.Client', FakeClient)
    driver = GamryProxyDriver(overrides={'server_ip': 'gamry-win', 'server_port': '5051'})

    status = driver.status()

    assert 'server_url=http://gamry-win:5051' in status


def test_is_proxy_driver():
    assert isinstance(GamryProxyDriver(), ProxyDriver)


def test_quickbar_parameters_are_grouped_and_labeled_with_units():
    driver = GamryProxyDriver()

    cv_params = driver.quickbar.function_info['runCV']['qb']['params']
    ca_params = driver.quickbar.function_info['runCA']['qb']['params']

    assert list(cv_params)[:7] == [
        'initial_voltage',
        'apex1_voltage',
        'apex2_voltage',
        'final_voltage',
        'apex1_hold',
        'apex2_hold',
        'final_hold',
    ]
    assert cv_params['apex1_hold']['label'] == 'Apex 1 Hold (s)'
    assert cv_params['scan_rate']['label'] == 'Scan Rate (V/s)'
    assert list(ca_params)[:3] == [
        'ca_initial_voltage',
        'ca_step1_voltage',
        'ca_step2_voltage',
    ]
    assert ca_params['ca_sample_time']['label'] == 'Sample Time (s)'


def test_ping_uses_client_and_login(monkeypatch):
    monkeypatch.setattr('AFL.automation.instrument.Gamry.GamryProxyDriver.Client', FakeClient)
    driver = GamryProxyDriver(
        overrides={
            'server_ip': 'gamry-win',
            'server_port': '5051',
            'server_username': 'afl',
        }
    )

    result = driver.ping()

    assert result == {
        'status': 'ok',
        'server_url': 'http://gamry-win:5051',
        'driver_status': {'status': 'ok', 'driver': 'remote-gamry'},
    }


def test_unqueued_methods_forward_to_remote_client(monkeypatch):
    monkeypatch.setattr('AFL.automation.instrument.Gamry.GamryProxyDriver.Client', FakeClient)
    driver = GamryProxyDriver(overrides={'server_ip': 'gamry-win', 'server_port': '5051'})

    status = driver.ping()
    connection = driver.connectInstrument(instrument_name='PSTAT-1')

    assert status['driver_status']['driver'] == 'remote-gamry'
    assert connection['instrument_name'] == 'PSTAT-1'


def test_queued_methods_forward_task_name_and_kwargs(monkeypatch):
    monkeypatch.setattr('AFL.automation.instrument.Gamry.GamryProxyDriver.Client', FakeClient)
    driver = GamryProxyDriver(overrides={'server_ip': 'gamry-win', 'server_port': '5051'})

    result = driver.runCA(instrument_name='PSTAT-1', ca_step1_time=2.0)

    assert result.attrs['measurement_mode'] == 'ca'
    assert driver._proxy_clients['gamry'].calls[0] == (
        'enqueue',
        {
            'task_name': 'runCA',
            'interactive': False,
            'ca_initial_voltage': 0.0,
            'ca_step1_voltage': 0.5,
            'ca_step2_voltage': 0.0,
            'ca_initial_time': 1.0,
            'ca_step1_time': 2.0,
            'ca_step2_time': 2.0,
            'ca_sample_time': 0.05,
            'ca_expected_max_v': 10.0,
            'current_range_mode': 'auto',
            'instrument_name': 'PSTAT-1',
        },
        None,
    )


def test_client_login_is_skipped_without_username(monkeypatch):
    monkeypatch.setattr('AFL.automation.instrument.Gamry.GamryProxyDriver.Client', FakeClient)
    driver = GamryProxyDriver(overrides={'server_ip': 'gamry-win'})

    result = driver.ping()

    assert result['driver_status']['driver'] == 'remote-gamry'
    assert driver._proxy_clients['gamry'].logged_in_username == 'GamryProxyDriver'
