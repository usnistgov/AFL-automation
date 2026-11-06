Connect an AFL server to an existing Tiled service
================================================

``AFL.automation.shared.TiledProxyDriver`` starts an AFL API server backed by a
remote Tiled HTTP service. It provides the standard AFL queue and browser routes
and forwards Tiled REST requests through ``/api/v1/``. Pagination and data links
are rewritten to the local proxy origin, so existing Andon browser and plot
clients can use the local server.

Keep deployment settings in a private client YAML, such as one in
``afl-configs``. The upstream Tiled API key is separate from SSH authentication::

    uri: "http://<tiled-host>:<tiled-port>"
    authentication:
      single_user_api_key: "<tiled-api-key>"
    structure_clients: "dask"
    management:
      type: "afl_proxy"

Start the proxy in the environment containing AFL-automation::

    python -m AFL.automation.shared.TiledProxyDriver \
        --config <private-client-profile.yml> --host 127.0.0.1 --port <local-port>

The existing NAS YAML with ``management.host``, ``uvicorn.port``, and
``authentication.single_user_api_key`` can also be passed directly to this
command. Andon's proxy launcher uses a client YAML containing ``uri`` to
distinguish the local AFL proxy from a Docker-managed NAS deployment.

``/healthz`` checks authenticated upstream metadata access. An invalid key
returns the upstream authentication failure, and an unreachable backend returns
HTTP 502. The local server may be reachable while its backend is unavailable.
Its ordinary server logs describe the local proxy; NAS container logs and
container lifecycle operations remain on the NAS.

Run the read-only integration probe with the same Python environment::

    python scripts/probe-tiled-proxy.py <private-nas-profile.yml>

The probe creates an isolated temporary server, checks health, the AFL browser,
catalog search, metadata, data, and filters, then shuts it down. It does not
create, change, or delete NAS catalog entries.
