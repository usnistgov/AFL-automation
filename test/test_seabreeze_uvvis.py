import sys
import types

import numpy as np
import pytest

from AFL.automation.instrument.SeabreezeUVVis import SeabreezeUVVis


def test_init_raises_actionable_error_when_seabreeze_cannot_load(monkeypatch):
    class _MissingSeaBreeze:
        @staticmethod
        def use(backend):
            raise ModuleNotFoundError("No module named 'seabreeze'")

    module = sys.modules[SeabreezeUVVis.__module__]
    monkeypatch.setattr(module, "seabreeze", _MissingSeaBreeze())

    with pytest.raises(RuntimeError, match="SeaBreeze could not be loaded") as error:
        SeabreezeUVVis()

    assert "AFL-automation[seabreeze]" in str(error.value)


def test_init_raises_actionable_error_when_no_spectrometer_is_detected(monkeypatch):
    class _SeaBreeze:
        @staticmethod
        def use(backend):
            assert backend == "cseabreeze"

    class _Spectrometer:
        @staticmethod
        def from_first_available():
            raise AssertionError("must not connect when no devices are listed")

    spectrometers = types.ModuleType("seabreeze.spectrometers")
    spectrometers.Spectrometer = _Spectrometer
    spectrometers.list_devices = lambda: []
    module = sys.modules[SeabreezeUVVis.__module__]
    monkeypatch.setattr(module, "seabreeze", _SeaBreeze())
    monkeypatch.setitem(sys.modules, "seabreeze.spectrometers", spectrometers)

    with pytest.raises(RuntimeError, match="did not detect any spectrometers"):
        SeabreezeUVVis()


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


def test_load_tiled_reference_uses_configured_tiled_locator():
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
    driver.config = {"air": "entry-123"}
    driver.data = types.SimpleNamespace(tiled_client=client)

    spectrum, spectrum_std = driver._load_tiled_reference("air")

    np.testing.assert_array_equal(spectrum, raw)
    np.testing.assert_array_equal(spectrum_std, raw_std)
    assert isinstance(spectrum, np.ndarray)
    assert isinstance(spectrum_std, np.ndarray)
    assert lazy_raw.converted
    assert lazy_raw_std.converted


def test_load_local_reference_uses_npz_locator(tmp_path):
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {"reference": "reference.npz"}
    driver._reference_cache = {}
    driver._reference_directory = tmp_path
    driver.wavelengths = np.array([0.0, 400.0, 500.0])
    saved_path = driver._save_reference(
        np.array([12.0, 15.0]),
        np.array([0.2, 0.3]),
        "reference",
    )
    driver._reference_cache = {}

    spectrum, spectrum_std = driver._load_reference("reference")

    assert driver._reference_source("reference") == "local"
    assert saved_path == tmp_path / "reference.npz"
    np.testing.assert_array_equal(spectrum, [12.0, 15.0])
    np.testing.assert_array_equal(spectrum_std, [0.2, 0.3])


def test_tiled_locator_requires_tiled_connection():
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {"dark": "QD-reference"}

    with pytest.raises(ValueError, match="requires an initialized Tiled connection"):
        driver._load_reference("dark")


def test_reference_locator_must_be_nonempty():
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {"reference": ""}

    with pytest.raises(ValueError, match="must be a non-empty string"):
        driver._reference_source("reference")


def test_measure_uses_measure_mode_and_only_raw_spectrum_names(tmp_path):
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {
        "reference": "reference.npz",
        "air": "air.npz",
        "dark": "dark.npz",
        "save_single_scan": False,
    }
    driver._reference_cache = {}
    driver._reference_directory = tmp_path
    driver.wavelengths = np.array([0.0, 400.0, 500.0])
    driver._acquire_spectra = lambda n_frames: np.array(
        [[10.0, 20.0], [14.0, 24.0]]
    )

    dataset = driver.measure(n_frames=2)

    assert dataset.attrs["mode"] == "measure"
    assert "spectrum_raw" in dataset
    assert "spectrum_raw_std" in dataset
    assert "spectrum" not in dataset
    assert "spectrum_std" not in dataset


def test_measure_attaches_reduction_results_from_reduce(tmp_path):
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {
        "reference": "reference.npz",
        "air": "air.npz",
        "dark": "dark.npz",
        "save_single_scan": False,
    }
    driver._reference_cache = {}
    driver._reference_directory = tmp_path
    driver.wavelengths = np.array([0.0, 400.0, 500.0])
    driver._acquire_spectra = lambda n_frames: np.array(
        [[10.0, 20.0], [14.0, 24.0]]
    )
    driver.reduce = lambda *args, **kwargs: {
        "transmission": np.array([0.5, 0.6]),
        "transmission_std": np.array([0.01, 0.02]),
        "extinction": np.array([0.3, 0.2]),
        "extinction_std": np.array([0.01, 0.02]),
    }

    dataset = driver.measure(n_frames=2, reduced=True)

    np.testing.assert_array_equal(dataset["transmission"], [0.5, 0.6])
    np.testing.assert_array_equal(dataset["extinction"], [0.3, 0.2])


def test_measure_limits_dataset_and_reduction_to_requested_wavelengths(tmp_path):
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {
        "reference": "reference.npz",
        "air": "air.npz",
        "dark": "dark.npz",
        "save_single_scan": False,
    }
    driver._reference_cache = {}
    driver._reference_directory = tmp_path
    driver.wavelengths = np.array([0.0, 400.0, 500.0, 600.0])
    driver._acquire_spectra = lambda n_frames: np.array(
        [[10.0, 20.0, 30.0], [14.0, 24.0, 34.0]]
    )
    captured = {}

    def reduce(data_mean, data_std, **kwargs):
        captured["mean"] = data_mean
        captured["mask"] = kwargs["wavelength_mask"]
        return {
            "transmission": np.array([0.5, 0.6]),
            "transmission_std": np.array([0.01, 0.02]),
            "extinction": np.array([0.3, 0.2]),
            "extinction_std": np.array([0.01, 0.02]),
        }

    driver.reduce = reduce

    dataset = driver.measure(n_frames=2, reduced=True, wavelengths=[450, 650])

    np.testing.assert_array_equal(dataset["wavelength"], [500.0, 600.0])
    np.testing.assert_array_equal(dataset["all_spectra"], [[20.0, 30.0], [24.0, 34.0]])
    np.testing.assert_array_equal(captured["mean"], [22.0, 32.0])
    np.testing.assert_array_equal(captured["mask"], [False, True, True])


@pytest.mark.parametrize(
    "wavelengths",
    ([500], [500, 500], [600, 500], (400, 500), ["400", 500], [1200, 1300]),
)
def test_measure_rejects_invalid_wavelength_ranges(tmp_path, wavelengths):
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {
        "reference": "reference.npz",
        "air": "air.npz",
        "dark": "dark.npz",
        "save_single_scan": False,
    }
    driver._reference_cache = {}
    driver._reference_directory = tmp_path
    driver.wavelengths = np.array([0.0, 400.0, 500.0])
    driver._acquire_spectra = lambda n_frames: np.array([[10.0, 20.0]])

    with pytest.raises(ValueError, match="wavelengths"):
        driver.measure(n_frames=1, wavelengths=wavelengths)


def test_post_tiled_finalize_updates_tiled_locator():
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {"air": "old-entry"}

    driver.post_tiled_finalize(
        {"task_name": "save_reference", "reference_name": "air"},
        "entry-123",
    )

    assert driver.config["air"] == "entry-123"


def test_post_tiled_finalize_saves_dark_entry_id():
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {"dark": "old-dark-entry"}

    driver.post_tiled_finalize(
        {"task_name": "measure", "set_dark": True},
        "dark-entry-123",
    )

    assert driver.config["dark"] == "dark-entry-123"


def test_post_tiled_finalize_preserves_local_locator():
    driver = object.__new__(SeabreezeUVVis)
    driver.config = {"reference": "reference.npz"}

    driver.post_tiled_finalize(
        {"task_name": "save_reference", "reference_name": "reference"},
        "entry-123",
    )

    assert driver.config["reference"] == "reference.npz"


def test_reduce_subtracts_dark_from_sample_and_reference():
    driver = object.__new__(SeabreezeUVVis)
    sample = np.array([50.0, 30.0])
    sample_std = np.array([2.0, 3.0])
    reference = np.array([90.0, 50.0])
    reference_std = np.array([4.0, 5.0])
    dark = np.array([10.0, 10.0])
    dark_std = np.array([1.0, 2.0])
    driver._load_reference = lambda name: {
        "reference": (reference, reference_std),
        "dark": (dark, dark_std),
    }[name]

    result = driver.reduce(sample, sample_std)

    numerator = sample - dark
    denominator = reference - dark
    expected_transmission = numerator / denominator
    expected_std = np.sqrt(
        (sample_std / denominator) ** 2
        + (numerator * reference_std / denominator**2) ** 2
        + ((sample - reference) * dark_std / denominator**2) ** 2
    )
    np.testing.assert_allclose(result["transmission"], expected_transmission)
    np.testing.assert_allclose(result["transmission_std"], expected_std)
    np.testing.assert_allclose(result["extinction"], -np.log10(expected_transmission))
    np.testing.assert_allclose(result["transmission"], [0.5, 0.5])

    transmission_only = driver.reduce(sample, sample_std, absorbance=False)

    assert set(transmission_only) == {"transmission", "transmission_std"}

    absorbance_only = driver.reduce(sample, sample_std, transmission=False)

    assert set(absorbance_only) == {"extinction", "extinction_std"}
    with pytest.raises(ValueError, match="At least one"):
        driver.reduce(
            sample,
            sample_std,
            transmission=False,
            absorbance=False,
        )
