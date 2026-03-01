import pytest

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
