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


def test_distinct_fallback_collects_all_pages_with_filters_and_counts(tmp_path):
    requests = []
    filter_params = {
        'filter[in][condition][key]': 'attrs.AL_campaign_name',
        'filter[in][condition][value]': '["campaign-1"]',
    }

    def upstream(request):
        requests.append(request)
        assert request.headers['Authorization'] == 'Apikey test-key'
        if '/distinct/' in request.url.path:
            return httpx.Response(500, json={'detail': 'Internal server error'})
        assert request.url.path == '/api/v1/search/run_documents'
        for key, value in filter_params.items():
            assert request.url.params[key] == value
        if request.url.params.get('page[cursor]') == 'last-page':
            return httpx.Response(200, json={
                'data': [{'attributes': {
                    'metadata': {'attrs': {'driver_name': 'driver-later', 'labels': [1, 2]}},
                    'structure_family': 'array', 'specs': [{'name': 'xarray'}],
                }}],
                'links': {'next': None},
            })
        assert request.url.params.get_list('fields') == ['metadata', 'structure_family', 'specs']
        assert 'metadata' not in request.url.params
        # The backend may cap the requested limit. Always follow its next link.
        next_url = httpx.URL('http://nas:8000/api/v1/search/run_documents', params={
            **filter_params, 'page[cursor]': 'last-page',
        })
        return httpx.Response(200, json={
            'data': [{'attributes': {
                'metadata': {'attrs': {'driver_name': 'driver-first', 'labels': [1, 2]}},
                'structure_family': 'array', 'specs': [{'name': 'xarray'}],
            }}, {'attributes': {
                'metadata': {'driver_name': 'driver-flat'},
                'structure_family': 'container', 'specs': [],
            }}],
            'links': {'next': str(next_url)},
        })

    http_client = httpx.Client(base_url='http://nas:8000/', transport=httpx.MockTransport(upstream))
    api = proxy.create_server({'uri': 'http://nas:8000/', 'api_key': 'test-key'},
                              afl_home=tmp_path, http_client=http_client)
    try:
        response = api.app.test_client().get('/api/v1/distinct/run_documents', query_string=[
            ('metadata', 'attrs.driver_name'), ('metadata', 'driver_name'), ('metadata', 'attrs.labels'),
            ('counts', 'true'), ('structure_families', 'true'), ('specs', 'true'),
            *filter_params.items(),
        ])
        assert response.status_code == 200
        assert len(requests) == 3
        assert response.json == {
            'metadata': {
                'attrs.driver_name': [
                    {'value': 'driver-first', 'count': 1}, {'value': None, 'count': 1},
                    {'value': 'driver-later', 'count': 1},
                ],
                'driver_name': [{'value': None, 'count': 2}, {'value': 'driver-flat', 'count': 1}],
                'attrs.labels': [{'value': [1, 2], 'count': 2}, {'value': None, 'count': 1}],
            },
            'structure_families': [{'value': 'array', 'count': 2}, {'value': 'container', 'count': 1}],
            'specs': [{'value': [{'name': 'xarray'}], 'count': 2}, {'value': [], 'count': 1}],
        }
    finally:
        api.driver.close()


def test_distinct_fallback_preserves_response_and_json_value_types(tmp_path):
    def upstream(request):
        if '/distinct/' in request.url.path:
            return httpx.Response(500, json={'detail': 'distinct failed'})
        return httpx.Response(200, json={
            'data': [{'attributes': {'metadata': {'value': value}}} for value in (True, 1, True)],
            'links': {'next': None},
        })

    http_client = httpx.Client(base_url='http://nas:8000/', transport=httpx.MockTransport(upstream))
    driver = proxy.TiledProxyDriver(uri='http://nas:8000/', afl_home=tmp_path, http_client=http_client)
    try:
        response = driver.upstream_request('GET', 'api/v1/distinct/run_documents', b'metadata=value')
        response.raise_for_status()
        assert response.request.url.path == '/api/v1/distinct/run_documents'
        assert response.json() == {'metadata': {'value': [{'value': True}, {'value': 1}]}}
    finally:
        driver.close()


@pytest.mark.parametrize('status', [200, 400, 401, 403, 404])
def test_distinct_preserves_success_and_request_errors_without_fallback(tmp_path, status):
    requests = []
    payload = {'metadata': {'attrs.driver_name': [{'value': 'driver-native'}]}}

    def upstream(request):
        requests.append(request)
        return httpx.Response(status, json=payload)

    http_client = httpx.Client(base_url='http://nas:8000/', transport=httpx.MockTransport(upstream))
    driver = proxy.TiledProxyDriver(uri='http://nas:8000/', afl_home=tmp_path, http_client=http_client)
    try:
        response = driver.upstream_request('GET', 'api/v1/distinct/run_documents', b'metadata=attrs.driver_name')
        assert response.status_code == status
        assert response.json() == payload
        assert len(requests) == 1
    finally:
        driver.close()


@pytest.mark.parametrize('status', [405, 500, 501])
def test_distinct_fallback_propagates_search_failure(tmp_path, status):
    def upstream(request):
        if '/distinct/' in request.url.path:
            return httpx.Response(status, json={'detail': 'distinct failed'})
        return httpx.Response(503, json={'detail': 'search unavailable'})

    http_client = httpx.Client(base_url='http://nas:8000/', transport=httpx.MockTransport(upstream))
    driver = proxy.TiledProxyDriver(uri='http://nas:8000/', afl_home=tmp_path, http_client=http_client)
    try:
        response = driver.upstream_request('GET', 'api/v1/distinct/run_documents', b'metadata=attrs.driver_name')
        assert response.status_code == 503
        assert response.json() == {'detail': 'search unavailable'}
    finally:
        driver.close()


@pytest.mark.parametrize('next_link', [
    'http://other-host:8000/api/v1/search/run_documents?page[offset]=1',
    'http://nas:8000/api/v1/search/run_documents?metadata=attrs.driver_name',
])
def test_distinct_fallback_rejects_foreign_or_repeated_pagination(tmp_path, next_link):
    requests = []

    def upstream(request):
        requests.append(request)
        if '/distinct/' in request.url.path:
            return httpx.Response(500, json={'detail': 'distinct failed'})
        return httpx.Response(200, json={
            'data': [{'attributes': {'metadata': {'attrs': {'driver_name': 'first-page'}}}}],
            'links': {'next': next_link},
        })

    http_client = httpx.Client(base_url='http://nas:8000/', transport=httpx.MockTransport(upstream))
    driver = proxy.TiledProxyDriver(uri='http://nas:8000/', afl_home=tmp_path, http_client=http_client)
    try:
        with pytest.raises(ValueError, match='pagination link'):
            driver.upstream_request('GET', 'api/v1/distinct/run_documents', b'metadata=attrs.driver_name')
        assert len(requests) <= 3
    finally:
        driver.close()


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
