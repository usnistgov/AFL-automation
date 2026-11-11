"""An AFL API server backed by an existing Tiled HTTP service."""

import argparse
import json
import signal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from AFL.automation.APIServer.Driver import Driver


def load_profile(filename):
    """Read connection settings from a private Tiled client or NAS YAML."""
    import yaml

    profile = yaml.safe_load(Path(filename).read_text())
    if not isinstance(profile, dict) or profile.get("trees") is not None:
        raise ValueError(
            "The AFL Tiled proxy requires a client profile, "
            "not a local catalog configuration."
        )

    uri = profile.get("uri")
    management = profile.get("management", {})
    if not uri and management.get("host"):
        port = profile.get("uvicorn", {}).get("port", 8000)
        uri = f"http://{management['host']}:{port}"
    parsed = urlsplit(str(uri or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("The Tiled profile must provide an HTTP or HTTPS uri.")

    key = str(
        profile.get("api_key")
        or profile.get("authentication", {}).get("single_user_api_key")
        or ""
    ).strip()
    if not key:
        authorization = str(profile.get("headers", {}).get("Authorization", ""))
        if authorization.lower().startswith("apikey "):
            key = authorization[7:].strip()
        else:
            key = authorization.strip()

    return {
        "uri": urlunsplit((parsed.scheme, parsed.netloc, "/", "", "")),
        "api_key": key,
        "structure_clients": profile.get("structure_clients", "dask"),
    }


class TiledProxyDriver(Driver):
    """Forward Tiled HTTP requests and provide the standard AFL browser.

    Parameters
    ----------
    uri : str, optional
        Backend URL. When omitted, use the persistent driver configuration
        or the value supplied in overrides.
    api_key : str, optional
        Backend API key, kept outside the persistent driver configuration.
    structure_clients : str, optional
        Tiled structure client selection for the inherited AFL browser.
    overrides : dict, optional
        Configuration values that override the driver defaults.
    http_client : httpx.Client, optional
        HTTP client supplied by the caller, for example with a mock transport.
    afl_home : str or pathlib.Path, optional
        Directory containing the driver's persistent configuration.
    """

    defaults = {
        "uri": "",
        "structure_clients": "dask",
        "timeout": 10.0,
    }

    def __init__(
        self,
        uri=None,
        api_key="",
        structure_clients=None,
        overrides=None,
        *,
        http_client=None,
        afl_home=None,
    ):
        """Initialize configuration without opening a backend connection."""
        overrides = dict(overrides or {})
        if uri is not None:
            overrides["uri"] = uri
        if structure_clients is not None:
            overrides["structure_clients"] = structure_clients

        super().__init__(
            name="TiledProxyDriver",
            defaults=self.gather_defaults(),
            overrides=overrides,
            afl_home=afl_home,
        )
        # Credentials belong to the private YAML, not persistent driver config.
        self._api_key = api_key
        self._http_client = http_client

    def connect(self):
        """Create the backend HTTP client on first use."""
        if self._http_client is None:
            import httpx

            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Apikey {self._api_key}"
            self._http_client = httpx.Client(
                base_url=self.config["uri"],
                timeout=self.config["timeout"],
                headers=headers,
                follow_redirects=False,
            )

    def close(self):
        """Close cached HTTP and Tiled clients; safe to call more than once."""
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None
        if self._tiled_client is not None:
            self._tiled_client.context.close()
            self._tiled_client = None

    def status(self):
        """Return backend information without making a network request."""
        return [f"Tiled backend: {self.config['uri']}"]

    def _read_tiled_config(self):
        """Use this backend for the inherited AFL browser routes."""
        # The inherited AFL browser reads this connection, independently of
        # whichever other Tiled service is active in global AFL configuration.
        return {
            "status": "success",
            "tiled_server": self.config["uri"],
            "tiled_api_key": self._api_key,
        }

    def upstream_request(self, method, path, query=b"", body=b"", headers=None):
        """Forward one request using the configured backend credentials."""
        self.connect()
        forwarded_headers = dict(headers or {})
        if self._api_key:
            forwarded_headers["Authorization"] = f"Apikey {self._api_key}"

        request_path = "/" + path.lstrip("/")
        if query:
            request_path += "?" + query.decode("ascii")
        return self._http_client.request(
            method,
            request_path,
            content=body,
            headers=forwarded_headers,
        )


def rewrite_links(value, upstream, local):
    """Keep Tiled pagination and data links on the local proxy origin."""
    if isinstance(value, list):
        return [rewrite_links(item, upstream, local) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == "links" and isinstance(item, dict):
            links = {}
            for name, link in item.items():
                if isinstance(link, str) and link.startswith(upstream):
                    link = local + link[len(upstream):]
                links[name] = link
            result[key] = links
        else:
            result[key] = rewrite_links(item, upstream, local)
    return result


def create_server(profile, *, afl_home=None, http_client=None):
    """Create an APIServer with AFL routes and native Tiled REST forwarding."""
    from AFL.automation.APIServer.APIServer import APIServer
    from flask import Response, jsonify, request

    driver = TiledProxyDriver(
        api_key=profile.get("api_key", ""),
        overrides={
            "uri": profile["uri"],
            "structure_clients": profile.get("structure_clients", "dask"),
        },
        http_client=http_client,
        afl_home=afl_home,
    )
    api = APIServer("TiledProxy", afl_home=afl_home)
    api.add_standard_routes()
    api.create_queue(driver)

    def proxy(path=""):
        # Tiled's native REST routes also serve Andon's existing bundled browser.
        forwarded_headers = {
            name: request.headers[name]
            for name in ("Accept", "Content-Type", "Range")
            if name in request.headers
        }
        try:
            response = driver.upstream_request(
                method=request.method,
                path="api/v1/" + path,
                query=request.query_string,
                body=request.get_data(),
                headers=forwarded_headers,
            )
        except Exception:
            api.app.logger.exception("Could not reach the configured Tiled backend")
            return jsonify(detail="The configured Tiled backend is unreachable."), 502

        content = response.content
        content_type = response.headers.get("content-type", "application/octet-stream")
        if "json" in content_type:
            try:
                payload = rewrite_links(
                    response.json(), driver.config["uri"], request.url_root
                )
                content = json.dumps(payload).encode()
            except (ValueError, TypeError):
                pass

        response_header_names = (
            "content-type",
            "content-disposition",
            "content-range",
            "accept-ranges",
            "etag",
            "last-modified",
        )
        headers = {
            name: value
            for name, value in response.headers.items()
            if name.lower() in response_header_names
        }
        return Response(content, status=response.status_code, headers=headers)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    api.app.add_url_rule("/api/v1/", "tiled_api_root", proxy, methods=methods)
    api.app.add_url_rule("/api/v1/<path:path>", "tiled_api", proxy, methods=methods)

    @api.app.get("/healthz")
    def health():
        try:
            response = driver.upstream_request("GET", "api/v1/metadata/")
        except Exception:
            return jsonify(status="unavailable"), 502
        status = "ready" if response.is_success else "unavailable"
        return jsonify(status=status), response.status_code

    return api


def main():
    """Launch the proxy from a private Tiled connection profile."""
    from werkzeug.serving import make_server

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    profile = load_profile(args.config)
    api = create_server(profile)
    api.driver.connect()
    http_server = make_server(args.host, args.port, api.app, threaded=True)
    # AFL queue_state and all existing browser routes are provided by APIServer.
    api.init()

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(
        f"AFL Tiled proxy at http://{args.host}:{args.port}, backend {profile['uri']}",
        flush=True,
    )
    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http_server.server_close()
        api.queue_daemon.stop = True
        api.driver.close()


if __name__ == "__main__":
    main()
