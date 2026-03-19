from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TILED_APP_ROOT = REPO_ROOT / "AFL" / "automation" / "apps" / "tiled_browser"
JS_ROOT = TILED_APP_ROOT / "js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_html_pages_load_shared_tiled_http_client():
    browser_html = _read(TILED_APP_ROOT / "tiled_browser.html")
    plot_html = _read(TILED_APP_ROOT / "tiled_plot.html")
    gantt_html = _read(TILED_APP_ROOT / "tiled_gantt.html")

    expected_tag = '/static/apps/tiled_browser/js/tiled_http_client.js'
    assert expected_tag in browser_html
    assert expected_tag in plot_html
    assert expected_tag in gantt_html


def test_shared_client_defines_direct_tiled_http_contract_helpers():
    shared_client = _read(JS_ROOT / "tiled_http_client.js")

    assert "api/v1/search/" in shared_client
    assert "api/v1/distinct/" in shared_client
    assert "api/v1/metadata/" in shared_client

    assert "buildSearchParams" in shared_client
    assert "buildDistinctParams" in shared_client
    assert "resolveMetadataValue" in shared_client
    assert "probeDirectMode" in shared_client
    assert "mode: useProxy ? 'proxy' : 'direct'" in shared_client
    assert "toEntryRef" in shared_client
    assert "entryRefFromItem" in shared_client

    # Dual-path mapping requirement for key fields
    assert "task_name: ['task_name', 'attrs.task_name']" in shared_client
    assert "meta_ended: ['meta.ended', 'attrs.meta.ended']" in shared_client
    assert "run_time_minutes: ['meta.run_time_minutes', 'attrs.meta.run_time_minutes']" in shared_client


def test_browser_uses_config_and_upload_backend_routes_only():
    browser_js = _read(JS_ROOT / "tiled_browser.js")
    shared_client = _read(JS_ROOT / "tiled_http_client.js")

    # Kept backend routes (config now centralized in shared client module)
    assert "/tiled_config" in shared_client
    assert "/tiled_upload_data" in browser_js
    assert "window.TiledHttpClient.loadConfig()" in browser_js
    assert "/tiled_search" in shared_client
    assert "/tiled_get_metadata" in shared_client
    assert "/tiled_get_data" in shared_client
    assert "/tiled_get_full_json" in shared_client

    # Legacy read-proxy routes should not be used
    assert "/tiled_search" not in browser_js
    assert "/tiled_get_data" not in browser_js
    assert "/tiled_get_metadata" not in browser_js
    assert "/tiled_get_distinct_values" not in browser_js


def test_plot_and_gantt_remove_legacy_read_proxy_routes():
    plot_js = _read(JS_ROOT / "tiled_plot.js")
    gantt_js = _read(JS_ROOT / "tiled_gantt.js")

    removed_plot_routes = [
        "/tiled_get_plot_manifest",
        "/tiled_get_plot_variable_data",
        "/tiled_download_combined_dataset",
    ]
    for route in removed_plot_routes:
        assert route not in plot_js

    assert "/tiled_get_gantt_metadata" not in gantt_js

    # Direct config/bootstrap usage retained
    assert "window.TiledHttpClient.loadConfig()" in plot_js
    assert "window.TiledHttpClient.loadConfig()" in gantt_js
    assert "window.TiledHttpClient.toEntryRef(entry)" in plot_js
    assert "window.TiledHttpClient.toEntryRef(entry)" in gantt_js


def test_browser_selection_preserves_entry_references():
    browser_js = _read(JS_ROOT / "tiled_browser.js")

    assert "window.TiledHttpClient.entryRefFromItem(item)" in browser_js
    assert "selectedRows.map(row => row.entryRef || row.id)" in browser_js


def test_html_pages_use_apps_static_layout():
    browser_html = _read(TILED_APP_ROOT / "tiled_browser.html")
    plot_html = _read(TILED_APP_ROOT / "tiled_plot.html")
    gantt_html = _read(TILED_APP_ROOT / "tiled_gantt.html")

    assert "/static/apps/common/ag-grid-community/styles/ag-grid.css" in browser_html
    assert "/static/apps/common/ag-grid-community/dist/ag-grid-community.min.js" in browser_html
    assert "/static/apps/common/plotly/plotly.min.js" in plot_html
    assert "/static/apps/common/plotly/plotly.min.js" in gantt_html


def test_selection_caps_are_enforced_in_frontend():
    browser_js = _read(JS_ROOT / "tiled_browser.js")
    plot_js = _read(JS_ROOT / "tiled_plot.js")
    gantt_js = _read(JS_ROOT / "tiled_gantt.js")

    assert "selectedRows.length > 25" in browser_js
    assert "selectedRows.length > 200" in browser_js

    assert "entryIds.length > 25" in plot_js
    assert "entryIds.length > 200" in gantt_js


def test_stale_response_suppression_present_for_browser_grid():
    browser_js = _read(JS_ROOT / "tiled_browser.js")

    assert "AbortController" in browser_js
    assert "searchRequestState.sequence" in browser_js
    assert "status === 'aborted'" in browser_js
