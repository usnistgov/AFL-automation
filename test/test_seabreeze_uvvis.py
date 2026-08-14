import types

import numpy as np

from AFL.automation.instrument.SeabreezeUVVis import SeabreezeUVVis


class _Array:
    def __init__(self, value):
        self.value = value

    def __getitem__(self, key):
        assert key == ()
        return self.value


class _LazyArray:
    """Minimal dask-like array that materializes through NumPy conversion."""

    def __init__(self, value):
        self.value = value
        self.converted = False

    def __array__(self, dtype=None):
        self.converted = True
        return np.asarray(self.value, dtype=dtype)


class _TiledClient:
    def __init__(self, entries):
        self.entries = entries

    def __getitem__(self, key):
        if key == "run_documents":
            return self.entries
        raise KeyError(key)


def test_load_tiled_reference_uses_saved_entry_id():
    raw = np.array([1.0, 2.0])
    raw_std = np.array([0.1, 0.2])
    lazy_raw = _LazyArray(raw)
    lazy_raw_std = _LazyArray(raw_std)
    client = _TiledClient({
        "entry-123": {
            "spectrum_raw": _Array(lazy_raw),
            "spectrum_raw_std": _Array(lazy_raw_std),
        }
    })
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {"air_tiled_entry_id": "entry-123"}
    driver.data = types.SimpleNamespace(tiled_client=client)

    spectrum, spectrum_std = driver._load_tiled_reference("air")

    np.testing.assert_array_equal(spectrum, raw)
    np.testing.assert_array_equal(spectrum_std, raw_std)
    assert isinstance(spectrum, np.ndarray)
    assert isinstance(spectrum_std, np.ndarray)
    assert lazy_raw.converted
    assert lazy_raw_std.converted


def test_post_tiled_finalize_saves_reference_entry_id():
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {}

    driver.post_tiled_finalize(
        {"task_name": "save_reference", "reference_name": "air"},
        "entry-123",
    )

    assert driver.config["air_tiled_entry_id"] == "entry-123"
