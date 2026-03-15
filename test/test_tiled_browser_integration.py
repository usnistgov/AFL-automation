import io
import json
from types import SimpleNamespace

import pytest
import werkzeug

tiled = pytest.importorskip("tiled")
xr = pytest.importorskip("xarray")

from tiled.catalog import in_memory
from tiled.client import Context, from_context
from tiled.client.xarray import write_xarray_dataset
from tiled.server.app import build_app

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.DummyDriver import DummyDriver


@pytest.fixture
def seeded_tiled_client(tmp_path):
    tree = in_memory(writable_storage=str(tmp_path / "tiled-data"))
    app = build_app(tree)
    with Context.from_app(app) as context:
        client = from_context(context)
        client.create_container(key="run_documents", metadata={"type": "run_documents"})
        run_documents = client["run_documents"]

        datasets = [
            (
                "entry-old",
                xr.Dataset(
                    {"I": (("q",), [1.0, 2.0, 3.0])},
                    coords={"q": [0.01, 0.02, 0.03]},
                    attrs={
                        "task_name": "scan",
                        "driver_name": "driver-a",
                        "sample_name": "alpha",
                        "sample_uuid": "sam-001",
                        "AL_campaign_name": "campaign-1",
                        "AL_uuid": "al-001",
                        "meta": {"ended": "12/06/25 15:37:52-000000 "},
                    },
                ),
            ),
            (
                "entry-mid",
                xr.Dataset(
                    {"I": (("q",), [4.0, 5.0, 6.0])},
                    coords={"q": [0.04, 0.05, 0.06]},
                    attrs={
                        "task_name": "scan",
                        "driver_name": "driver-b",
                        "sample_name": "beta",
                        "sample_uuid": "sam-002",
                        "AL_campaign_name": "campaign-2",
                        "AL_uuid": "al-002",
                        "meta": {"ended": "12/07/25 10:32:34-000000 "},
                    },
                ),
            ),
            (
                "entry-new",
                xr.Dataset(
                    {"I": (("q",), [7.0, 8.0, 9.0])},
                    coords={"q": [0.07, 0.08, 0.09]},
                    attrs={
                        "task_name": "predict",
                        "driver_name": "driver-c",
                        "sample_name": "gamma",
                        "sample_uuid": "sam-003",
                        "AL_campaign_name": "campaign-3",
                        "AL_uuid": "al-003",
                        "meta": {"ended": "03/01/26 21:58:51-000000 "},
                    },
                ),
            ),
        ]

        for key, ds in datasets:
            write_xarray_dataset(run_documents, ds, key=key)

        yield client


@pytest.fixture
def server_client(seeded_tiled_client):
    if not hasattr(werkzeug, "__version__"):
        werkzeug.__version__ = "3"

    server = APIServer(name="TestServer")
    server.add_standard_routes()

    driver = DummyDriver(name="TestDriver")
    driver._tiled_client = seeded_tiled_client
    driver.config.write = False

    server.create_queue(driver, add_unqueued=True)

    flask_client = server.app.test_client()
    return SimpleNamespace(server=server, driver=driver, client=flask_client)


def test_tiled_search_total_count_and_default_sort(server_client):
    response = server_client.client.get(
        "/tiled_search",
        query_string={"queries": "[]", "filters": "{}", "sort": "[]", "offset": 0, "limit": 10},
    )
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["status"] == "success"
    assert payload["total_count"] == 3
    assert [row["id"] for row in payload["data"]] == ["entry-old", "entry-mid", "entry-new"]


def test_tiled_search_filter_and_temporal_sort(server_client):
    response = server_client.client.get(
        "/tiled_search",
        query_string={
            "queries": json.dumps([{"field": "sample_name", "value": "a"}]),
            "filters": "{}",
            "sort": json.dumps([{"colId": "meta_ended", "sort": "desc"}]),
            "offset": 0,
            "limit": 10,
        },
    )
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["status"] == "success"
    assert payload["total_count"] == 3
    assert [row["id"] for row in payload["data"]] == ["entry-new", "entry-mid", "entry-old"]


def test_tiled_get_metadata_returns_expected_values(server_client):
    response = server_client.client.get("/tiled_get_metadata", query_string={"entry_id": "entry-mid"})
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["status"] == "success"
    assert payload["metadata"]["attrs"]["sample_name"] == "beta"
    assert payload["metadata"]["attrs"]["driver_name"] == "driver-b"
    assert payload["metadata"]["attrs"]["meta"]["ended"] == "12/07/25 10:32:34-000000 "


def test_tiled_get_full_json_returns_data_values(server_client):
    response = server_client.client.get("/tiled_get_full_json", query_string={"entry_id": "entry-new"})
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["status"] == "success"
    assert payload["data"]["q"] == [0.07, 0.08, 0.09]
    assert payload["data"]["I"] == [7.0, 8.0, 9.0]


def test_tiled_upload_data_happy_path(server_client):
    csv_bytes = b"time,signal,label\n0.0,1.2,a\n1.0,3.4,b\n"
    form = {
        "file": (io.BytesIO(csv_bytes), "uploaded.csv"),
        "metadata": json.dumps(
            {
                "sample_name": "upload-sample",
                "sample_uuid": "upload-uuid",
                "driver_name": "manual_upload",
                "task_name": "manual_upload",
            }
        ),
        "coordinate_column": "time",
        "file_format": "csv",
    }

    upload_response = server_client.client.post(
        "/tiled_upload_data",
        data=form,
        content_type="multipart/form-data",
    )
    assert upload_response.status_code == 200
    upload_payload = upload_response.get_json()
    assert upload_payload["status"] == "success"
    assert upload_payload["entry_id"]
    assert upload_payload["dataset_summary"]["dims"]["time"] == 2

    search_response = server_client.client.get(
        "/tiled_search",
        query_string={
            "queries": json.dumps([{"field": "sample_name", "value": "upload-sample"}]),
            "filters": "{}",
            "sort": "[]",
            "offset": 0,
            "limit": 10,
        },
    )
    assert search_response.status_code == 200
    search_payload = search_response.get_json()
    assert search_payload["status"] == "success"
    assert search_payload["total_count"] == 1
    assert search_payload["data"][0]["id"] == upload_payload["entry_id"]


def test_tiled_upload_data_rejects_unknown_coordinate(server_client):
    csv_bytes = b"x,y\n1,2\n3,4\n"
    form = {
        "file": (io.BytesIO(csv_bytes), "bad_coord.csv"),
        "coordinate_column": "missing",
    }
    response = server_client.client.post(
        "/tiled_upload_data",
        data=form,
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "error"
    assert "Coordinate column" in payload["message"]


def test_tiled_upload_data_rejects_unsupported_extension(server_client):
    text_bytes = b"plain text payload\n"
    form = {
        "file": (io.BytesIO(text_bytes), "unsupported.txt"),
    }
    response = server_client.client.post(
        "/tiled_upload_data",
        data=form,
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "error"
    assert "infer upload format" in payload["message"] or "Unsupported file format" in payload["message"]
