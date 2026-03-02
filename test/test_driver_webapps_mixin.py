import pytest
import logging
from types import SimpleNamespace
import re

pytest.importorskip("tiled.client")
xr = pytest.importorskip("xarray")

from AFL.automation.APIServer.DriverWebAppsMixin import DriverWebAppsMixin


class _DummyDriverWebApps(DriverWebAppsMixin):
    def __init__(self, dataset):
        self._dataset = dataset

    def _fetch_single_tiled_entry(self, entry_id):
        return self._dataset.copy(), {
            "sample_name": "",
            "sample_uuid": "",
            "entry_id": entry_id,
            "sample_composition": None,
        }


def test_detect_sample_dimension_single_dataset_no_guess():
    dataset = xr.Dataset({"I": (("q",), [1.0, 2.0, 3.0])})
    driver = _DummyDriverWebApps(dataset)

    sample_dim = driver._detect_sample_dimension(dataset, allow_size_fallback=False)

    assert sample_dim is None


def test_tiled_concat_single_entry_preserves_no_sample_dim():
    dataset = xr.Dataset(
        {"I": (("q",), [1.0, 2.0, 3.0]), "aux": (("angle",), [10.0, 20.0])}
    )
    driver = _DummyDriverWebApps(dataset)

    result = driver.tiled_concat_datasets(entry_ids=["entry-1"])

    assert result.attrs["_detected_sample_dim"] == "index"
    assert "index" in result.dims
    assert int(result.sizes["index"]) == 1
    assert "sample_name" in result.coords
    assert "sample_uuid" in result.coords
    assert "entry_id" in result.coords


def test_read_tiled_item_uses_optimize_wide_table_false():
    class _FakeItem:
        def __init__(self):
            self.kwargs_seen = None

        def read(self, **kwargs):
            self.kwargs_seen = kwargs
            return "ok"

    driver = _DummyDriverWebApps(xr.Dataset())
    item = _FakeItem()

    result = driver._read_tiled_item(item)

    assert result == "ok"
    assert item.kwargs_seen == {"optimize_wide_table": False}


def test_read_tiled_item_falls_back_when_keyword_unsupported():
    class _FakeItem:
        def __init__(self):
            self.calls = 0

        def read(self, **kwargs):
            self.calls += 1
            if kwargs:
                raise TypeError("read() got an unexpected keyword argument 'optimize_wide_table'")
            return "fallback-ok"

    driver = _DummyDriverWebApps(xr.Dataset())
    item = _FakeItem()

    result = driver._read_tiled_item(item)

    assert result == "fallback-ok"
    assert item.calls == 2


class _DummyUploadDriver(DriverWebAppsMixin):
    def __init__(self):
        self._client = object()
        self.app = SimpleNamespace(logger=logging.getLogger("test_upload_driver"))

    def _get_tiled_client(self):
        return self._client


def test_tiled_upload_dataset_csv_all_columns_as_vars_and_coord(monkeypatch):
    driver = _DummyUploadDriver()
    captured = {}

    def _fake_write(client, dataset):
        captured["client"] = client
        captured["dataset"] = dataset
        return object()

    monkeypatch.setattr("tiled.client.xarray.write_xarray_dataset", _fake_write)

    csv_bytes = b"time,signal,label\n0.0,1.2,a\n1.0,3.4,b\n"
    result = driver.tiled_upload_dataset(
        upload_bytes=csv_bytes,
        filename="example.csv",
        coordinate_column="time",
        metadata={"sample_name": "manual-data"},
    )

    assert result["status"] == "success"
    dataset = captured["dataset"]
    assert set(dataset.data_vars.keys()) == {"signal", "label"}
    assert "time" in dataset.coords
    assert "sample" not in dataset.coords
    assert list(dataset.dims.keys()) == ["time"]
    assert dataset.attrs["sample_name"] == "manual-data"
    assert dataset.sizes["time"] == 2
    assert dataset["label"].dtype.kind != "O"
    assert dataset.coords["time"].dtype.kind != "O"


def test_tiled_upload_dataset_rejects_unknown_coordinate(monkeypatch):
    driver = _DummyUploadDriver()

    def _fake_write(client, dataset):
        return object()

    monkeypatch.setattr("tiled.client.xarray.write_xarray_dataset", _fake_write)

    csv_bytes = b"x,y\n1,2\n3,4\n"
    result = driver.tiled_upload_dataset(
        upload_bytes=csv_bytes,
        filename="example.csv",
        coordinate_column="missing_column",
    )

    assert result["status"] == "error"
    assert "Coordinate column" in result["message"]


def test_tiled_upload_dataset_tsv_coordinate_q_not_all_nan(monkeypatch):
    driver = _DummyUploadDriver()
    captured = {}

    def _fake_write(client, dataset):
        captured["dataset"] = dataset
        return object()

    monkeypatch.setattr("tiled.client.xarray.write_xarray_dataset", _fake_write)

    tsv_bytes = b"Q\tI\n0.010\t100\n0.020\t200\n0.030\t300\n"
    result = driver.tiled_upload_dataset(
        upload_bytes=tsv_bytes,
        filename="example.tsv",
        coordinate_column="Q",
    )

    assert result["status"] == "success"
    dataset = captured["dataset"]
    assert "Q" in dataset.coords
    q_values = dataset.coords["Q"].values
    assert len(q_values) == 3
    assert not all(str(v).lower() == "nan" for v in q_values)


def test_tiled_upload_dataset_whitespace_delimited_tsv(monkeypatch):
    driver = _DummyUploadDriver()
    captured = {}

    def _fake_write(client, dataset):
        captured["dataset"] = dataset
        return object()

    monkeypatch.setattr("tiled.client.xarray.write_xarray_dataset", _fake_write)

    ws_tsv_bytes = b"Q I\n0.010 100\n0.020 200\n0.030 300\n"
    result = driver.tiled_upload_dataset(
        upload_bytes=ws_tsv_bytes,
        filename="example.tsv",
        coordinate_column="Q",
    )

    assert result["status"] == "success"
    dataset = captured["dataset"]
    assert "Q" in dataset.coords
    assert "I" in dataset.data_vars
    assert dataset.sizes["Q"] == 3
    assert float(dataset.coords["Q"].values[0]) == 0.01
    assert float(dataset["I"].values[2]) == 300.0


def test_tiled_upload_dataset_mixed_header_tab_data_whitespace(monkeypatch):
    driver = _DummyUploadDriver()
    captured = {}

    def _fake_write(client, dataset):
        captured["dataset"] = dataset
        return object()

    monkeypatch.setattr("tiled.client.xarray.write_xarray_dataset", _fake_write)

    mixed_bytes = (
        b"\tQ\tI\tdI\n"
        b"0.010 100 1.0\n"
        b"0.020 200 2.0\n"
        b"0.030 300 3.0\n"
    )
    result = driver.tiled_upload_dataset(
        upload_bytes=mixed_bytes,
        filename="example.tsv",
        coordinate_column="Q",
    )

    assert result["status"] == "success"
    dataset = captured["dataset"]
    assert "Q" in dataset.coords
    assert "I" in dataset.data_vars
    assert "dI" in dataset.data_vars
    q_values = dataset.coords["Q"].values
    assert len(q_values) == 3
    assert float(q_values[0]) == 0.01
    assert float(q_values[2]) == 0.03


def test_tiled_upload_dataset_direct_dataset_merges_kwargs(monkeypatch):
    driver = _DummyUploadDriver()
    captured = {}

    def _fake_write(client, dataset):
        captured["dataset"] = dataset
        return object()

    monkeypatch.setattr("tiled.client.xarray.write_xarray_dataset", _fake_write)

    ds = xr.Dataset({"I": (("q",), [1.0, 2.0, 3.0])})
    result = driver.tiled_upload_dataset(
        dataset=ds,
        sample_name="manual",
        driver_name="manual_upload",
    )

    assert result["status"] == "success"
    assert captured["dataset"].attrs["sample_name"] == "manual"
    assert captured["dataset"].attrs["driver_name"] == "manual_upload"
    meta = captured["dataset"].attrs["meta"]
    assert meta["exit_state"] == "Success!"
    assert meta["return_val"] == "xarray.Dataset"
    assert "run_time_seconds" in meta
    assert "run_time_minutes" in meta
    timestamp_pattern = r"^\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}-\d{6}( .*)?$"
    assert re.match(timestamp_pattern, meta["queued"])
    assert re.match(timestamp_pattern, meta["started"])
    assert re.match(timestamp_pattern, meta["ended"])
