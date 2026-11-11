import httpx
import pytest

from AFL.automation.shared import TiledProxyDriver as proxy


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv('AFL_HOME', str(tmp_path))
    requests = []

    def upstream(request):
        requests.append(request)
        assert request.headers['Authorization'] == 'Apikey test-key'
        if request.url.path.endswith('/array/full/entry'):
            return httpx.Response(200, content=b'\x01\x02\x03', headers={'content-type': 'application/octet-stream'})
        return httpx.Response(200, json={
            'data': [{'id': 'entry', 'links': {'full': 'http://nas:8000/api/v1/array/full/entry'}}],
            'links': {'next': 'http://nas:8000/api/v1/search/run_documents?page[offset]=1'},
        })

    http_client = httpx.Client(base_url='http://nas:8000/', transport=httpx.MockTransport(upstream))
    api = proxy.create_server({'uri': 'http://nas:8000/', 'api_key': 'test-key'},
                              afl_home=tmp_path, http_client=http_client)
    yield api, requests
    api.driver.close()


@pytest.mark.parametrize("connection_kwargs", [
    {
        "overrides": {
            "uri": "http://tiled:8000/",
            "structure_clients": "numpy",
            "timeout": 2.5,
        },
    },
    {
        "uri": "http://tiled:8000/",
        "structure_clients": "numpy",
        "overrides": {"timeout": 2.5},
    },
])
def test_driver_configuration_controls_lazy_backend_connection(
    tmp_path, monkeypatch, connection_kwargs
):
    requests = []

    def upstream(request):
        requests.append(request)
        return httpx.Response(200, json={"data": []})

    original_client = httpx.Client

    def create_http_client(**kwargs):
        return original_client(transport=httpx.MockTransport(upstream), **kwargs)

    monkeypatch.setattr(httpx, "Client", create_http_client)
    driver = proxy.TiledProxyDriver(
        api_key="test-key", afl_home=tmp_path, **connection_kwargs
    )
    try:
        assert driver._http_client is None
        assert driver.status() == ["Tiled backend: http://tiled:8000/"]
        assert driver._read_tiled_config()["tiled_server"] == "http://tiled:8000/"
        assert driver.config["structure_clients"] == "numpy"
        assert "test-key" not in driver.filepath.read_text()

        response = driver.upstream_request("GET", "api/v1/metadata/")
        assert response.status_code == 200
        assert str(requests[0].url) == "http://tiled:8000/api/v1/metadata/"
        assert requests[0].headers["Authorization"] == "Apikey test-key"
        assert all(value == 2.5 for value in requests[0].extensions["timeout"].values())
    finally:
        driver.close()


def test_browser_and_queue_routes_use_the_existing_afl_server(server):
    api, _ = server
    client = api.app.test_client()
    assert client.get('/queue_state').status_code == 200
    assert client.get('/tiled_browser').status_code == 200
    assert api.driver._read_tiled_config()['tiled_server'] == 'http://nas:8000/'
    assert 'test-key' not in api.driver.filepath.read_text()


def test_search_keeps_pagination_and_data_links_on_the_proxy(server):
    api, requests = server
    response = api.app.test_client().get('/api/v1/search/run_documents?page[limit]=1')
    assert response.status_code == 200
    assert str(requests[0].url) == 'http://nas:8000/api/v1/search/run_documents?page[limit]=1'
    assert response.json['links']['next'].startswith('http://localhost/api/v1/search/')
    assert response.json['data'][0]['links']['full'] == 'http://localhost/api/v1/array/full/entry'


def test_array_data_remains_binary(server):
    api, _ = server
    response = api.app.test_client().get('/api/v1/array/full/entry')
    assert response.data == b'\x01\x02\x03'
    assert response.content_type == 'application/octet-stream'


@pytest.mark.parametrize('status', [401, 403, 503])
def test_upstream_failures_reach_browser_and_health_check(server, status):
    api, _ = server
    api.driver._http_client.close()
    api.driver._http_client = httpx.Client(base_url='http://nas:8000/', transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json={'detail': 'Unavailable'})
    ))
    assert api.app.test_client().get('/api/v1/metadata/').status_code == status
    assert api.app.test_client().get('/healthz').status_code == status


def test_unreachable_upstream_returns_bad_gateway(server):
    api, _ = server
    api.driver._http_client.close()

    def unavailable(request):
        raise httpx.ConnectError('Connection refused', request=request)

    api.driver._http_client = httpx.Client(base_url='http://nas:8000/', transport=httpx.MockTransport(unavailable))
    assert api.app.test_client().get('/api/v1/metadata/').status_code == 502
    assert api.app.test_client().get('/healthz').status_code == 502


def test_loads_both_client_and_existing_nas_profiles(tmp_path):
    profile = tmp_path / 'profile.yml'
    profile.write_text('uri: http://nas:8000\nauthentication:\n  single_user_api_key: test-key\n')
    assert proxy.load_profile(profile)['api_key'] == 'test-key'
    profile.write_text('management:\n  host: nas\nuvicorn:\n  port: 8000\n')
    assert proxy.load_profile(profile)['uri'] == 'http://nas:8000/'
    profile.write_text('trees: []\n')
    with pytest.raises(ValueError, match='client profile'):
        proxy.load_profile(profile)
