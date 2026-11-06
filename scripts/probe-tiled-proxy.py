"""Read-only live smoke test of the AFL Tiled proxy using the current Python environment."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml

from AFL.automation.shared import TiledProxyDriver as proxy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('nas_profile', help='Existing private NAS YAML containing its URL and API key')
    parser.add_argument('--keep-profile', help='Save a private client YAML for the Andon card')
    args = parser.parse_args()
    profile = proxy.load_profile(args.nas_profile)
    key = profile['api_key']
    client_yaml = yaml.safe_dump({
        'uri': profile['uri'], 'authentication': {'single_user_api_key': key},
        'structure_clients': profile['structure_clients'], 'management': {'type': 'afl_proxy'}
    })
    if args.keep_profile:
        target = Path(args.keep_profile)
        with target.open('w') as output:
            os.chmod(target, 0o600)
            output.write(client_yaml)
        print(f'Private client profile saved to {target}', flush=True)

    def report(name, **values):
        text = json.dumps({'check': name, **values}, default=str)
        print(text.replace(key, '<redacted>') if key else text, flush=True)

    with tempfile.TemporaryDirectory(prefix='andon-proxy-smoke-') as directory:
        runtime = Path(directory)
        client_config = runtime / 'client.yml'
        client_config.write_text(client_yaml)
        client_config.chmod(0o600)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        logfile = runtime / 'proxy.log'
        environment = dict(os.environ, AFL_HOME=str(runtime / '.afl'))
        with logfile.open('w') as output:
            process = subprocess.Popen([sys.executable, '-u', '-m', 'AFL.automation.shared.TiledProxyDriver', '--config', str(client_config),
                                        '--host', '127.0.0.1', '--port', str(port)],
                                       stdout=output, stderr=subprocess.STDOUT, env=environment)
        base_url = f'http://127.0.0.1:{port}'
        try:
            with httpx.Client(base_url=base_url, timeout=15) as client:
                for _ in range(60):
                    if process.poll() is not None:
                        raise RuntimeError('Proxy exited during startup: ' + logfile.read_text())
                    try:
                        if client.get('/queue_state').status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.25)
                else:
                    raise RuntimeError('Proxy did not become ready')
                report('AFL proxy launched', python=sys.executable, address=base_url, backend=profile['uri'])
                for path in ['/healthz', '/queue_state', '/tiled_browser', '/api/v1/', '/api/v1/metadata/',
                             '/api/v1/search/run_documents?page[limit]=1', '/tiled_search?limit=1',
                             '/tiled_get_distinct_values?field=sample_name']:
                    response = client.get(path)
                    body = response.json() if 'json' in response.headers.get('content-type', '') else {}
                    report(path, http_status=response.status_code,
                           status=body.get('status') if isinstance(body, dict) else None,
                           rows=len(body['data']) if isinstance(body, dict) and isinstance(body.get('data'), list) else None)
                    assert response.status_code == 200, f'{path}: {response.text[:200]}'
                    assert not isinstance(body, dict) or body.get('status') != 'error', f'{path}: {body.get("message")}'
                    if path.startswith('/api/v1/search'):
                        for link in body.get('links', {}).values():
                            if isinstance(link, str) and link.startswith('http'):
                                assert link.startswith(base_url + '/'), f'Link escaped the proxy: {link}'
                        report('Tiled links stay on the local proxy', success=True)
                    if path.startswith('/tiled_search') and body.get('data'):
                        entry_id = body['data'][0]['id']
                        for entry_path in ['/tiled_get_metadata', '/tiled_get_full_json']:
                            response = client.get(entry_path, params={'entry_id': entry_id})
                            payload = response.json()
                            report(entry_path, http_status=response.status_code, status=payload.get('status'))
                            assert response.status_code == 200 and payload.get('status') == 'success'
        finally:
            process.send_signal(signal.SIGINT) if process.poll() is None else None
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            report('Proxy stopped', exit_code=process.returncode)
            if process.returncode != 0:
                report('Proxy output', output=logfile.read_text())
        assert process.returncode == 0


if __name__ == '__main__':
    main()
