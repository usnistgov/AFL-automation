import pytest
import logging
from types import SimpleNamespace

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

    assert result.attrs["_detected_sample_dim"] is None


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
    assert set(dataset.data_vars.keys()) == {"time", "signal", "label"}
    assert "sample" in dataset.coords
    assert dataset.attrs["sample_name"] == "manual-data"
    assert dataset.sizes["sample"] == 2


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
