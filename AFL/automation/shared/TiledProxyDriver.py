"""An AFL API server backed by an existing Tiled HTTP service."""

import argparse
import json
import signal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from AFL.automation.APIServer.Driver import Driver


def load_profile(filename):
    import yaml

    profile = yaml.safe_load(Path(filename).read_text())
    if not isinstance(profile, dict) or profile.get('trees') is not None:
        raise ValueError('The AFL Tiled proxy requires a client profile, not a local catalog configuration.')
    uri = profile.get('uri')
    if not uri and profile.get('management', {}).get('host'):
        uri = f"http://{profile['management']['host']}:{profile.get('uvicorn', {}).get('port', 8000)}"
    parsed = urlsplit(str(uri or '').strip())
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('The Tiled profile must provide an HTTP or HTTPS uri.')
    key = str(profile.get('api_key') or profile.get('authentication', {}).get('single_user_api_key') or '').strip()
    if not key:
        authorization = str(profile.get('headers', {}).get('Authorization', ''))
        key = (authorization[7:] if authorization.lower().startswith('apikey ') else authorization).strip()
    return {
        'uri': urlunsplit((parsed.scheme, parsed.netloc, '/', '', '')),
        'api_key': key,
        'structure_clients': profile.get('structure_clients', 'dask'),
    }


class TiledProxyDriver(Driver):
    defaults = {'uri': '', 'structure_clients': 'dask', 'timeout': 10.0}

    def __init__(self, uri, api_key='', structure_clients='dask', *, http_client=None, afl_home=None):
        super().__init__('TiledProxyDriver', self.gather_defaults(),
                         {'uri': uri, 'structure_clients': structure_clients}, afl_home=afl_home)
        # Credentials belong to the private YAML, not persistent driver config.
        self._api_key = api_key
        self._http_client = http_client

    def connect(self):
        if self._http_client is None:
            import httpx

            self._http_client = httpx.Client(
                base_url=self.config['uri'], timeout=self.config['timeout'],
                headers={'Authorization': f'Apikey {self._api_key}'} if self._api_key else {},
                follow_redirects=False,
            )

    def close(self):
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None
        if self._tiled_client is not None:
            self._tiled_client.context.close()
            self._tiled_client = None

    def status(self):
        return [f"Tiled backend: {self.config['uri']}"]

    def _read_tiled_config(self):
        # The inherited AFL browser reads this connection, independently of
        # whichever other Tiled service is active in global AFL configuration.
        return {'status': 'success', 'tiled_server': self.config['uri'], 'tiled_api_key': self._api_key}

    def upstream_request(self, method, path, query=b'', body=b'', headers=None):
        self.connect()
        forwarded_headers = dict(headers or {})
        if self._api_key:
            forwarded_headers['Authorization'] = f'Apikey {self._api_key}'
        return self._http_client.request(
            method, '/' + path.lstrip('/') + (('?' + query.decode('ascii')) if query else ''),
            content=body, headers=forwarded_headers,
        )


def rewrite_links(value, upstream, local):
    """Keep Tiled pagination and data links on the local proxy origin."""
    if isinstance(value, list):
        return [rewrite_links(item, upstream, local) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == 'links' and isinstance(item, dict):
            result[key] = {name: local + link[len(upstream):]
                           if isinstance(link, str) and link.startswith(upstream) else link
                           for name, link in item.items()}
        else:
            result[key] = rewrite_links(item, upstream, local)
    return result


def create_server(profile, *, afl_home=None, http_client=None):
    from AFL.automation.APIServer.APIServer import APIServer
    from flask import Response, jsonify, request

    driver = TiledProxyDriver(profile['uri'], profile.get('api_key', ''),
                             profile.get('structure_clients', 'dask'), http_client=http_client, afl_home=afl_home)
    api = APIServer('TiledProxy', afl_home=afl_home)
    api.add_standard_routes()
    api.create_queue(driver)

    def proxy(path=''):
        # Tiled's native REST routes also serve Andon's existing bundled browser.
        forwarded_headers = {name: request.headers[name] for name in ('Accept', 'Content-Type', 'Range')
                             if name in request.headers}
        try:
            response = driver.upstream_request(request.method, 'api/v1/' + path, request.query_string,
                                               request.get_data(), forwarded_headers)
        except Exception:
            api.app.logger.exception('Could not reach the configured Tiled backend')
            return jsonify(detail='The configured Tiled backend is unreachable.'), 502
        content = response.content
        content_type = response.headers.get('content-type', 'application/octet-stream')
        if 'json' in content_type:
            try:
                payload = rewrite_links(response.json(), profile['uri'], request.url_root)
                content = json.dumps(payload).encode()
            except (ValueError, TypeError):
                pass
        headers = {name: value for name, value in response.headers.items()
                   if name.lower() in ('content-type', 'content-disposition', 'content-range', 'accept-ranges', 'etag', 'last-modified')}
        return Response(content, status=response.status_code, headers=headers)

    methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']
    api.app.add_url_rule('/api/v1/', 'tiled_api_root', proxy, methods=methods)
    api.app.add_url_rule('/api/v1/<path:path>', 'tiled_api', proxy, methods=methods)

    @api.app.get('/healthz')
    def health():
        try:
            response = driver.upstream_request('GET', 'api/v1/metadata/')
        except Exception:
            return jsonify(status='unavailable'), 502
        return jsonify(status='ready' if response.is_success else 'unavailable'), response.status_code

    return api


def main():
    from werkzeug.serving import make_server

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    profile = load_profile(args.config)
    api = create_server(profile)
    api.driver.connect()
    http_server = make_server(args.host, args.port, api.app, threaded=True)
    # AFL queue_state and all existing browser routes are provided by APIServer.
    api.init()

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(f'AFL Tiled proxy at http://{args.host}:{args.port}, backend {profile["uri"]}', flush=True)
    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http_server.server_close()
        api.queue_daemon.stop = True
        api.driver.close()


if __name__ == '__main__':
    main()
