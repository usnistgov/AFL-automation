"""Driver for Ocean Optics UV-Vis spectrometers supported by SeaBreeze."""

import datetime
from pathlib import Path
from typing import List, Optional
import time
import uuid
import warnings

import h5py
import lazy_loader as lazy
import numpy as np
import xarray as xr

from AFL.automation.APIServer.Driver import Driver

seabreeze = lazy.load("seabreeze", require="AFL-automation[seabreeze]")


class SeabreezeUVVis(Driver):
    """Collect spectra from a SeaBreeze-compatible UV-Vis spectrometer.

    Other Parameters
    ----------------
    correct_dark_counts : bool, default=False
        Pass SeaBreeze's device-specific dark-count correction option to each
        acquired spectrum. This is separate from the stored ``dark`` spectrum
        used for transmission reduction.
    correct_nonlinearity : bool, default=False
        Pass SeaBreeze's detector nonlinearity correction option to each
        acquired spectrum when supported by the device.
    exposure : float, default=0.010
        Spectrometer integration time in seconds.
    exposure_delay : float, default=0
        Additional delay in seconds between consecutively acquired frames.
    save_single_scan : bool, default=False
        Whether acquired spectra are also written to the configured HDF5 file.
    file_name : str, default="test.h5"
        HDF5 file name used when ``save_single_scan`` is enabled.
    file_path : str or pathlib.Path, default="."
        Directory containing the HDF5 file written when ``save_single_scan``
        is enabled.
    reference : str, default="reference_spectrum.npz"
        Illuminated reference locator. A value ending in ``.npz`` is a local
        filename below the driver's ``uvvis`` directory; any other non-empty
        value is a Tiled ``run_documents`` entry ID.
    air : str, default="air_reference_spectrum.npz"
        Optional air-reference locator used to report the ``mean_air``
        diagnostic. Local and Tiled values are selected as for ``reference``.
    dark : str, default="dark_spectrum.npz"
        Dark-spectrum locator subtracted from sample and reference spectra
        during transmission reduction. Local and Tiled values are selected as
        for ``reference``.
    """

    defaults = {
        "correct_dark_counts": False,
        "correct_nonlinearity": False,
        "exposure": 0.010,
        "exposure_delay": 0,
        "save_single_scan": False,
        "file_name": "test.h5",
        "file_path": ".",
        "reference": "reference_spectrum.npz",
        "air": "air_reference_spectrum.npz",
        "dark": "dark_spectrum.npz",
    }

    _LEGACY_CONFIG_KEYS = {
        "correctDarkCounts": "correct_dark_counts",
        "correctNonlinearity": "correct_nonlinearity",
        "saveSingleScan": "save_single_scan",
        "filename": "file_name",
        "filepath": "file_path",
    }

    def __init__(
        self,
        backend: str = "cseabreeze",
        device_serial: Optional[str] = None,
        overrides: Optional[dict] = None,
    ) -> None:
        """Initialize the spectrometer driver.

        Parameters
        ----------
        backend : str, default="cseabreeze"
            SeaBreeze backend to use.
        device_serial : str, optional
            Serial number of the spectrometer to connect to. The first
            available spectrometer is used when omitted.
        overrides : dict, optional
            Configuration values that override the driver defaults.
        """
        super().__init__(
            name="SeabreezeUVVis",
            defaults=self.gather_defaults(),
            overrides=overrides,
        )
        self._reference_cache = {}
        self._reference_directory = self.path / "uvvis"
        migrated_keys = []
        for legacy_key, current_key in self._LEGACY_CONFIG_KEYS.items():
            if legacy_key in self.config:
                self.config[current_key] = self.config[legacy_key]
                del self.config[legacy_key]
                migrated_keys.append(legacy_key)
        if migrated_keys:
            warnings.warn(
                "Deprecated configuration keys were migrated to PEP 8 names: "
                f"{', '.join(migrated_keys)}.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.log_info("Configuring SeaBreeze using backend %s" % backend)
        try:
            # ``seabreeze`` is a lazy proxy so importing this driver remains
            # possible on systems without the optional hardware dependency.
            # Accessing it here resolves the proxy at the first point the SDK
            # is actually required.
            seabreeze.use(backend)
            from seabreeze.spectrometers import Spectrometer, list_devices
        except ImportError as error:
            raise RuntimeError(
                "SeaBreeze could not be loaded. Install the optional dependency "
                "with 'pip install AFL-automation[seabreeze]' and verify its "
                "native dependencies are available."
            ) from error

        self.log_info("Attempting to list spectrometers.")
        devices = list_devices()
        self.log_info("SeaBreeze sees devices: %s" % devices)
        if not devices:
            raise RuntimeError(
                "SeaBreeze did not detect any spectrometers. Check that the "
                "instrument is connected, powered, and accessible to this process."
            )
        if device_serial is None:
            self.log_info("Connecting to the first available spectrometer.")
            self.spectrometer = Spectrometer.from_first_available()
        else:
            self.log_info("Connecting to spectrometer serial number %s." % device_serial)
            self.spectrometer = Spectrometer.from_serial_number(device_serial)

        self.log_info("Connected successfully to %s." % self.spectrometer)
        self.wavelengths = self.spectrometer.wavelengths()
        self.set_exposure(self.config["exposure"])

    @Driver.unqueued()
    def get_exposure(self) -> float:
        """Return the integration time.

        Returns
        -------
        float
            Integration time in seconds.
        """
        return self.config["exposure"]

    @Driver.unqueued()
    def get_exposure_delay(self) -> float:
        """Return the delay between acquired frames.

        Returns
        -------
        float
            Delay in seconds.
        """
        return self.config["exposure_delay"]

    @Driver.unqueued()
    def get_file_name(self) -> str:
        """Return the individual-scan file name.

        Returns
        -------
        str
            Configured file name.
        """
        return self.config["file_name"]

    @Driver.unqueued()
    def get_save_single_scan(self) -> bool:
        """Return whether individual scans are written to disk.

        Returns
        -------
        bool
            ``True`` when acquired scans are saved.
        """
        return self.config["save_single_scan"]

    @Driver.unqueued()
    def get_file_path(self) -> str:
        """Return the individual-scan output directory.

        Returns
        -------
        str
            Configured output directory.
        """
        return str(self.config["file_path"])

    def set_file_path(self, file_path: str) -> None:
        """Set the individual-scan output directory.

        Parameters
        ----------
        file_path : str
            Directory for acquired scan files.
        """
        self.config["file_path"] = Path(file_path)

    def set_file_name(self, file_name: str) -> None:
        """Set the individual-scan file name.

        Parameters
        ----------
        file_name : str
            Name for acquired scan files.
        """
        self.config["file_name"] = file_name

    def set_save_single_scan(self, save_single_scan: bool) -> None:
        """Enable or disable writing individual scans to disk.

        Parameters
        ----------
        save_single_scan : bool
            Whether to write acquired scans to disk.
        """
        self.config["save_single_scan"] = save_single_scan

    def set_exposure_delay(self, delay: float) -> None:
        """Set the delay between acquired frames.

        Parameters
        ----------
        delay : float
            Delay in seconds.
        """
        self.config["exposure_delay"] = delay

    def set_exposure(self, exposure: float) -> None:
        """Set the spectrometer integration time.

        Parameters
        ----------
        exposure : float
            Integration time in seconds.
        """
        self.config["exposure"] = exposure
        self.spectrometer.integration_time_micros(1_000_000 * exposure)

    def _acquire_spectra(self, n_frames: int) -> np.ndarray:
        """Acquire spectra, excluding SeaBreeze's internal dark-reference pixel.

        Parameters
        ----------
        n_frames : int
            Number of spectra to acquire.

        Returns
        -------
        numpy.ndarray
            Array with shape ``(n_frames, n_wavelengths)``.

        Raises
        ------
        ValueError
            If ``n_frames`` is less than one.
        """
        if n_frames < 1:
            raise ValueError("n_frames must be at least 1.")

        spectra: List[np.ndarray] = []
        for _ in range(n_frames):
            intensities = self.spectrometer.intensities(
                correct_dark_counts=self.config["correct_dark_counts"],
                correct_nonlinearity=self.config["correct_nonlinearity"],
            )
            spectra.append(intensities[1:])
            delay = self.config["exposure_delay"]
            if delay:
                time.sleep(delay)
        return np.asarray(spectra)

    def _write_data(self, data: np.ndarray) -> None:
        """Write wavelength and intensity data to the configured HDF5 file.

        Parameters
        ----------
        data : numpy.ndarray
            Intensity data to store alongside the wavelength grid.
        """
        output_path = Path(self.config["file_path"]) / self.config["file_name"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(output_path, "w") as output_file:
            output_file.create_dataset("wavelength", data=self.wavelengths)
            output_file.create_dataset(str(uuid.uuid1()), data=data)

    def _reference_path(self, reference_name: str) -> Path:
        """Return the AFL-home path for a locally configured reference.

        Parameters
        ----------
        reference_name : {"reference", "air", "dark"}
            Reference to locate.

        Returns
        -------
        pathlib.Path
            Local reference file path.

        Raises
        ------
        ValueError
            If the slot is unsupported or is configured as a Tiled entry.
        """
        locator = self._reference_locator(reference_name)
        if self._reference_source(reference_name) != "local":
            raise ValueError(
                f"The {reference_name} locator {locator!r} is a Tiled entry, "
                "not a local .npz file."
            )
        return self._reference_directory / locator

    def _reference_locator(self, reference_name: str) -> str:
        """Return the configured local-file or Tiled-entry locator for a slot."""
        if reference_name not in {"reference", "air", "dark"}:
            raise ValueError(
                "reference_name must be one of 'reference', 'air', or 'dark'."
            )
        locator = self.config[reference_name]
        if not isinstance(locator, str) or not locator.strip():
            raise ValueError(
                f"The {reference_name} locator must be a non-empty string."
            )
        return locator.strip()

    def _reference_source(self, reference_name: str) -> str:
        """Classify a reference locator as a local file or Tiled entry."""
        locator = self._reference_locator(reference_name)
        return "local" if locator.lower().endswith(".npz") else "tiled"

    def _has_tiled_connection(self) -> bool:
        """Return whether the driver has an initialized Tiled client.

        Returns
        -------
        bool
            ``True`` when an APIServer supplied a usable Tiled data packet.
        """
        return getattr(getattr(self, "data", None), "tiled_client", None) is not None

    def _has_reference(self, reference_name: str) -> bool:
        """Return whether the requested reference is available from its active source.

        Parameters
        ----------
        reference_name : {"reference", "air", "dark"}
            Reference slot to check.

        Returns
        -------
        bool
            ``True`` if the configured local file exists or a Tiled connection
            is available for the configured entry ID.
        """
        if self._reference_source(reference_name) == "tiled":
            return self._has_tiled_connection()
        return (
            reference_name in self._reference_cache
            or self._reference_path(reference_name).is_file()
        )

    def _validate_reference_save_target(self, reference_name: str) -> None:
        """Ensure a configured reference save destination is usable."""
        if (
            self._reference_source(reference_name) == "tiled"
            and not self._has_tiled_connection()
        ):
            locator = self._reference_locator(reference_name)
            raise ValueError(
                f"The {reference_name} locator {locator!r} requires an "
                "initialized Tiled connection to save a reference."
            )

    def _reference_metadata(self, reference_name: str) -> dict:
        """Return provenance metadata for a configured reference slot."""
        locator = self._reference_locator(reference_name)
        source = self._reference_source(reference_name)
        metadata = {
            f"{reference_name}_locator": locator,
            f"{reference_name}_source": source,
        }
        if source == "local":
            path_key = (
                "reference_path"
                if reference_name == "reference"
                else f"{reference_name}_reference_path"
            )
            metadata[path_key] = str(self._reference_path(reference_name))
        return metadata

    def _save_reference(
        self,
        spectrum_mean: np.ndarray,
        spectrum_std: np.ndarray,
        reference_name: str,
    ) -> Path:
        """Cache and persist a reference spectrum at its local-file locator.

        Parameters
        ----------
        spectrum_mean : numpy.ndarray
            Mean intensity of the reference measurement.
        spectrum_std : numpy.ndarray
            Standard deviation of the reference measurement.
        reference_name : {"reference", "air", "dark"}
            Reference slot to update.

        Returns
        -------
        pathlib.Path
            Path of the persisted compressed NumPy archive.

        Raises
        ------
        ValueError
            If the configured locator is a Tiled entry.
        """
        if self._reference_source(reference_name) != "local":
            raise ValueError(
                f"The {reference_name} locator is a Tiled entry and cannot be "
                "saved as a local .npz file."
            )
        self._reference_cache[reference_name] = (
            np.array(spectrum_mean, copy=True),
            np.array(spectrum_std, copy=True),
        )
        reference_path = self._reference_path(reference_name)
        reference_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            reference_path,
            wavelength=self.wavelengths[1:],
            spectrum_mean=spectrum_mean,
            spectrum_std=spectrum_std,
        )
        return reference_path

    def _load_reference(self, reference_name: str) -> tuple:
        """Load a reference spectrum from its configured source.

        Parameters
        ----------
        reference_name : {"reference", "air", "dark"}
            Reference slot to load.

        Returns
        -------
        tuple of numpy.ndarray
            Reference mean intensity and standard deviation.

        Raises
        ------
        ValueError
            If the configured source is unavailable or incompatible.
        """
        if self._reference_source(reference_name) == "tiled":
            return self._load_tiled_reference(reference_name)
        return self._load_local_reference(reference_name)

    def _load_local_reference(self, reference_name: str) -> tuple:
        """Load a cached or persisted local ``.npz`` reference spectrum."""
        cached_reference = self._reference_cache.get(reference_name)
        if cached_reference is not None:
            return cached_reference

        reference_path = self._reference_path(reference_name)
        if not reference_path.is_file():
            raise ValueError(
                f"No local {reference_name} reference exists at {reference_path}. "
                "Acquire one with save_reference() or the matching "
                "measure(set_reference=True, set_air=True, or set_dark=True) option."
            )

        with np.load(reference_path) as reference_data:
            wavelength = reference_data["wavelength"]
            spectrum_mean = reference_data["spectrum_mean"]
            spectrum_std = reference_data["spectrum_std"]
        if not np.array_equal(wavelength, self.wavelengths[1:]):
            raise ValueError(
                f"The local {reference_name} reference wavelength grid does not "
                "match the connected spectrometer."
            )
        self._reference_cache[reference_name] = (spectrum_mean, spectrum_std)
        return spectrum_mean, spectrum_std

    def _load_tiled_reference(self, reference_name: str) -> tuple:
        """Load a reference spectrum from Tiled.

        Parameters
        ----------
        reference_name : {"reference", "air", "dark"}
            Reference slot to load.

        Returns
        -------
        tuple of numpy.ndarray
            Reference mean intensity and standard deviation.

        Raises
        ------
        ValueError
            If a Tiled connection is unavailable or the entry no longer exists.
        """
        reference_entry_id = self._reference_locator(reference_name)
        if self._reference_source(reference_name) != "tiled":
            raise ValueError(
                f"The {reference_name} locator is a local .npz file, not a "
                "Tiled entry."
            )
        if not self._has_tiled_connection():
            raise ValueError(
                f"The {reference_name} locator {reference_entry_id!r} requires "
                "an initialized Tiled connection."
            )
        try:
            reference_entry = self.data.tiled_client["run_documents"][
                reference_entry_id
            ]
        except KeyError as error:
            raise ValueError(
                f"The configured Tiled {reference_name} entry "
                f"{reference_entry_id!r} no longer exists."
            ) from error
        # Tiled clients configured with ``structure_clients="dask"`` return
        # lazy dask arrays here. Materialize them before reduction so the
        # resulting xarray Dataset is NumPy-backed and can be written to Tiled.
        reference_spectrum = np.asarray(reference_entry["spectrum_raw"][()])
        reference_std = np.asarray(reference_entry["spectrum_raw_std"][()])
        return reference_spectrum, reference_std

    def post_tiled_finalize(self, task, tiled_entry_id):
        """Persist a finalized Tiled ID for references configured as Tiled."""
        task_name = task.get("task_name")
        reference_names = []
        if task_name == "save_reference":
            reference_names.append(task.get("reference_name", "reference"))
        elif task_name == "measure":
            if task.get("set_reference"):
                reference_names.append("reference")
            if task.get("set_air"):
                reference_names.append("air")
            if task.get("set_dark"):
                reference_names.append("dark")
        for reference_name in reference_names:
            if self._reference_source(reference_name) == "tiled":
                self.config[reference_name] = tiled_entry_id

    @Driver.queued()
    def measure(
        self,
        n_frames: int,
        reduced: bool = False,
        absorbance: bool = True,
        set_reference: bool = False,
        set_air: bool = False,
        set_dark: bool = False,
        exposure: Optional[float] = None,
    ) -> xr.Dataset:
        """Acquire spectra and optionally reduce them against a reference.

        Parameters
        ----------
        n_frames : int
            Number of spectra to acquire.
        reduced : bool, default=False
            Whether to include transmission and extinction variables in
            addition to the measured intensity spectrum.
        absorbance : bool, default=True
            Whether to include extinction (absorbance) variables when
            ``reduced`` is ``True``. Transmission variables are always
            included for a reduced measurement.
        set_reference : bool, default=False
            Save this measurement as the reference source.
        set_air : bool, default=False
            Save this measurement as the air reference source.
        set_dark : bool, default=False
            Save this measurement as the dark reference source.
        exposure : float, optional
            Temporary integration time in seconds.

        Returns
        -------
        xarray.Dataset
            Raw spectra, summary statistics, and optionally reduced spectra.

        Raises
        ------
        ValueError
            If a requested reference is unavailable or incompatible.
        """
        if exposure is not None:
            self.set_exposure(exposure)
        for reference_name, should_save in (
            ("reference", set_reference),
            ("air", set_air),
            ("dark", set_dark),
        ):
            if should_save:
                self._validate_reference_save_target(reference_name)

        raw_spectra = self._acquire_spectra(n_frames)
        raw_mean = np.mean(raw_spectra, axis=0)
        raw_std = np.std(raw_spectra, axis=0)

        for reference_name, should_save in (
            ("reference", set_reference),
            ("air", set_air),
            ("dark", set_dark),
        ):
            if should_save and self._reference_source(reference_name) == "local":
                self._save_reference(raw_mean, raw_std, reference_name)

        if reduced:
            reduction = self.reduce(
                raw_mean,
                raw_std,
                transmission=True,
                absorbance=absorbance,
            )

        if not set_air and self._has_reference("air"):
            air_reduction = self.reduce(
                raw_mean,
                raw_std,
                absorbance=False,
                transmission=True,
                reference_name="air",
            )
            mean_air = np.mean(air_reduction["transmission"])
            std_air = np.mean(air_reduction["transmission_std"])
        else:
            mean_air = None
            std_air = None

        if self.config["save_single_scan"]:
            self._write_data(raw_spectra)

        dataset = xr.Dataset()
        dataset.attrs.update(
            mode="measure",
            reduced=reduced,
            absorbance=absorbance,
            mean_air=mean_air,
            std_air=std_air,
        )
        for reference_name in ("reference", "air", "dark"):
            dataset.attrs.update(self._reference_metadata(reference_name))
        dataset["wavelength"] = ("wavelength", self.wavelengths[1:])
        dataset["all_spectra"] = (("frame", "wavelength"), raw_spectra)
        dataset["spectrum_raw"] = ("wavelength", raw_mean)
        dataset["spectrum_raw_std"] = ("wavelength", raw_std)
        if reduced:
            for variable_name, values in reduction.items():
                dataset[variable_name] = ("wavelength", values)
        return dataset

    @Driver.queued()
    def save_reference(
        self,
        n_frames: int = 1,
        reference_name: str = "reference",
        exposure: Optional[float] = None,
    ) -> xr.Dataset:
        """Acquire and save a reference for later spectrum reduction.

        Parameters
        ----------
        n_frames : int, default=1
            Number of spectra to average into the reference.
        reference_name : {"reference", "air", "dark"}, default="reference"
            Reference slot to update. Its configured locator selects the local
            ``.npz`` or Tiled save destination.
        exposure : float, optional
            Temporary integration time in seconds.

        Returns
        -------
        xarray.Dataset
            Saved reference spectrum and its standard deviation.
        """
        if exposure is not None:
            self.set_exposure(exposure)
        self._validate_reference_save_target(reference_name)
        raw_spectra = self._acquire_spectra(n_frames)
        spectrum_mean = np.mean(raw_spectra, axis=0)
        spectrum_std = np.std(raw_spectra, axis=0)
        if self._reference_source(reference_name) == "local":
            self._save_reference(
                spectrum_mean, spectrum_std, reference_name
            )

        dataset = xr.Dataset()
        dataset.attrs.update(
            mode="reference",
            reference_name=reference_name,
        )
        dataset.attrs.update(self._reference_metadata(reference_name))
        dataset["wavelength"] = ("wavelength", self.wavelengths[1:])
        dataset["spectrum_raw"] = ("wavelength", spectrum_mean)
        dataset["spectrum_raw_std"] = ("wavelength", spectrum_std)
        return dataset

    @Driver.unqueued()
    def get_reference_path(self, reference_name: str = "reference") -> str:
        """Return the AFL-home path for a local reduction reference.

        Parameters
        ----------
        reference_name : {"reference", "air", "dark"}, default="reference"
            Local reference slot to inspect.

        Returns
        -------
        str
            Reference file path beneath ``AFL_HOME/uvvis``.

        Raises
        ------
        ValueError
            If the slot is configured as a Tiled entry.
        """
        return str(self._reference_path(reference_name))

    def reduce(
        self,
        data_raw_mean: np.ndarray,
        data_raw_std: np.ndarray,
        absorbance: bool = True,
        reference_name: str = "reference",
        transmission: bool = True,
    ) -> dict:
        r"""Reduce a raw spectrum against the active reference and dark source.

        Parameters
        ----------
        data_raw_mean : numpy.ndarray
            Mean raw sample intensity.
        data_raw_std : numpy.ndarray
            Standard deviation of the raw sample intensity.
        absorbance : bool, default=True
            Include extinction (absorbance) and propagated-uncertainty arrays.
        reference_name : {"reference", "air"}, default="reference"
            Reference slot to use. Its configured locator selects the local or
            Tiled source.
        transmission : bool, default=True
            Include transmission and propagated-uncertainty arrays.

        Returns
        -------
        dict of numpy.ndarray
            Mapping containing the requested arrays: ``transmission`` and
            ``transmission_std`` and/or ``extinction`` and ``extinction_std``.

        Raises
        ------
        ValueError
            If neither transmission nor absorbance is requested.

        Notes
        -----
        Let $S$, $R$, and $D$ be the mean sample, reference, and dark
        intensities, respectively. The dark-corrected transmission is:

        $$
        T = \frac{S - D}{R - D}
        $$

        Assuming independent sample, reference, and dark uncertainties
        $\sigma_S$, $\sigma_R$, and $\sigma_D$, its propagated uncertainty is:

        $$
        \sigma_T = \sqrt{
            \left(\frac{\sigma_S}{R - D}\right)^2
            + \left(\frac{(S - D)\sigma_R}{(R - D)^2}\right)^2
            + \left(\frac{(S - R)\sigma_D}{(R - D)^2}\right)^2
        }
        $$

        The returned ``extinction`` fields are absorbance values and use:

        $$
        A = -\log_{10}(T), \qquad
        \sigma_A = \frac{\sigma_T}{|T|\ln(10)}
        $$
        """
        if not transmission and not absorbance:
            raise ValueError("At least one of transmission or absorbance must be True.")
        reference_spectrum, reference_std = self._load_reference(reference_name)
        dark_spectrum, dark_std = self._load_reference("dark")
        with np.errstate(divide="ignore", invalid="ignore"):
            numerator = data_raw_mean - dark_spectrum
            denominator = reference_spectrum - dark_spectrum
            transmission_values = numerator / denominator
            # Propagate the independent sample, reference, and dark-spectrum
            # uncertainties through T = (sample - dark) / (reference - dark).
            transmission_std = np.sqrt(
                (data_raw_std / denominator) ** 2
                + (numerator * reference_std / denominator**2) ** 2
                + (
                    (data_raw_mean - reference_spectrum)
                    * dark_std
                    / denominator**2
                ) ** 2
            )
        result = {}
        if transmission:
            result["transmission"] = transmission_values
            result["transmission_std"] = transmission_std
        if absorbance:
            with np.errstate(divide="ignore", invalid="ignore"):
                extinction = -np.log10(transmission_values)
                extinction_std = transmission_std / (
                    np.abs(transmission_values) * np.log(10)
                )
            result["extinction"] = extinction
            result["extinction_std"] = extinction_std
        return result

    # Compatibility API: preserve existing server routes and Python callers while
    # directing new integrations to PEP 8 names.
    @Driver.unqueued()
    def getExposure(self):
        """Return the integration time through the deprecated API.

        Returns
        -------
        float
            Integration time in seconds.

        Warns
        -----
        DeprecationWarning
            Use :meth:`get_exposure` instead.
        """
        self._warn_deprecated("getExposure", "get_exposure")
        return self.get_exposure()

    @Driver.unqueued()
    def getExposureDelay(self):
        """Return the frame delay through the deprecated API.

        Returns
        -------
        float
            Delay in seconds.

        Warns
        -----
        DeprecationWarning
            Use :meth:`get_exposure_delay` instead.
        """
        self._warn_deprecated("getExposureDelay", "get_exposure_delay")
        return self.get_exposure_delay()

    @Driver.unqueued()
    def getFilename(self):
        """Return the scan file name through the deprecated API.

        Returns
        -------
        str
            Configured file name.

        Warns
        -----
        DeprecationWarning
            Use :meth:`get_file_name` instead.
        """
        self._warn_deprecated("getFilename", "get_file_name")
        return self.get_file_name()

    @Driver.unqueued()
    def getSaveSingleScan(self):
        """Return the scan-save setting through the deprecated API.

        Returns
        -------
        bool
            Scan-save setting.

        Warns
        -----
        DeprecationWarning
            Use :meth:`get_save_single_scan` instead.
        """
        self._warn_deprecated("getSaveSingleScan", "get_save_single_scan")
        return self.get_save_single_scan()

    @Driver.unqueued()
    def getFilepath(self):
        """Return the scan directory through the deprecated API.

        Returns
        -------
        str
            Configured output directory.

        Warns
        -----
        DeprecationWarning
            Use :meth:`get_file_path` instead.
        """
        self._warn_deprecated("getFilepath", "get_file_path")
        return self.get_file_path()

    def setFilepath(self, file_path):
        """Set the scan directory through the deprecated API.

        Parameters
        ----------
        file_path : str
            New output directory.

        Warns
        -----
        DeprecationWarning
            Use :meth:`set_file_path` instead.
        """
        self._warn_deprecated("setFilepath", "set_file_path")
        self.set_file_path(file_path)

    def setFilename(self, file_name):
        """Set the scan file name through the deprecated API.

        Parameters
        ----------
        file_name : str
            New output file name.

        Warns
        -----
        DeprecationWarning
            Use :meth:`set_file_name` instead.
        """
        self._warn_deprecated("setFilename", "set_file_name")
        self.set_file_name(file_name)

    def setSaveSingleScan(self, save_single_scan):
        """Set scan persistence through the deprecated API.

        Parameters
        ----------
        save_single_scan : bool
            Whether to save acquired scans.

        Warns
        -----
        DeprecationWarning
            Use :meth:`set_save_single_scan` instead.
        """
        self._warn_deprecated("setSaveSingleScan", "set_save_single_scan")
        self.set_save_single_scan(save_single_scan)

    def setExposureDelay(self, delay):
        """Set frame delay through the deprecated API.

        Parameters
        ----------
        delay : float
            Delay in seconds.

        Warns
        -----
        DeprecationWarning
            Use :meth:`set_exposure_delay` instead.
        """
        self._warn_deprecated("setExposureDelay", "set_exposure_delay")
        self.set_exposure_delay(delay)

    def setExposure(self, exposure):
        """Set integration time through the deprecated API.

        Parameters
        ----------
        exposure : float
            Integration time in seconds.

        Warns
        -----
        DeprecationWarning
            Use :meth:`set_exposure` instead.
        """
        self._warn_deprecated("setExposure", "set_exposure")
        self.set_exposure(exposure)

    def collect(self, *args, **kwargs):
        """Acquire spectra through the deprecated API.

        Parameters
        ----------
        *args
            Positional arguments forwarded to :meth:`measure`.
        **kwargs
            Keyword arguments forwarded to :meth:`measure`. The legacy
            ``nframes`` name is translated to ``n_frames``.

        Returns
        -------
        xarray.Dataset
            Measurement result.

        Warns
        -----
        DeprecationWarning
            Use :meth:`measure` instead.
        """
        self._warn_deprecated("collect", "measure")
        kwargs.pop("return_data", None)
        if "nframes" in kwargs:
            kwargs["n_frames"] = kwargs.pop("nframes")
        return self.measure(*args, **kwargs)

    @Driver.unqueued()
    def collectSingleSpectrum(self, set_reference=False, set_air=False, **kwargs):
        """Acquire one spectrum through the deprecated API.

        Parameters
        ----------
        set_reference : bool, default=False
            Save the spectrum as the local reference.
        set_air : bool, default=False
            Save the spectrum as the local air reference.
        **kwargs
            Ignored legacy keyword arguments.

        Returns
        -------
        xarray.Dataset
            Single raw spectrum.

        Warns
        -----
        DeprecationWarning
            Use :meth:`measure` with ``n_frames=1`` instead.
        """
        self._warn_deprecated("collectSingleSpectrum", "measure(n_frames=1)")
        del kwargs
        raw_spectrum = self._acquire_spectra(1)[0]
        if self.config["save_single_scan"]:
            self._write_data(raw_spectrum)
        if set_reference:
            self._save_reference(raw_spectrum, np.zeros_like(raw_spectrum), "reference")
        if set_air:
            self._save_reference(raw_spectrum, np.zeros_like(raw_spectrum), "air")

        dataset = xr.Dataset()
        dataset.attrs.update(mode="single", reduced=False)
        dataset["wavelength"] = ("wavelength", self.wavelengths[1:])
        dataset["spectrum_raw"] = ("wavelength", raw_spectrum)
        return dataset

    def collectContinuous(self, duration, start=None, return_data=False, **kwargs):
        """Acquire continuously through the deprecated API.

        Parameters
        ----------
        duration : float
            Acquisition duration in seconds.
        start : datetime.datetime, optional
            Time at which acquisition begins. Starts immediately when omitted.
        return_data : bool, default=False
            Retained for compatibility and ignored.
        **kwargs
            Ignored legacy keyword arguments.

        Returns
        -------
        xarray.Dataset
            First acquired spectrum and wavelength grid.

        Warns
        -----
        DeprecationWarning
            Use :meth:`measure` instead.
        """
        self._warn_deprecated("collectContinuous", "measure")
        del return_data, kwargs
        start_time = start or datetime.datetime.now()
        duration_delta = datetime.timedelta(seconds=duration)
        while datetime.datetime.now() < start_time:
            time.sleep(0.001)

        spectra = []
        while datetime.datetime.now() < start_time + duration_delta:
            spectra.append(self._acquire_spectra(1)[0])

        dataset = xr.Dataset()
        dataset.attrs["mode"] = "continuous"
        dataset["wavelength"] = ("wavelength", self.wavelengths[1:])
        dataset["spectra"] = ("wavelength", spectra[0])
        self._write_data(np.asarray(spectra))
        return dataset

    def reduced(self, *args, **kwargs):
        """Reduce a spectrum through the deprecated API.

        Parameters
        ----------
        *args
            Positional arguments forwarded to :meth:`reduce`.
        **kwargs
            Keyword arguments forwarded to :meth:`reduce`. The legacy
            ``reference_uuid`` key is translated to a local reference name.

        Returns
        -------
        tuple of numpy.ndarray
            Reduced spectrum and propagated uncertainty.

        Warns
        -----
        DeprecationWarning
            Use :meth:`reduce` instead.
        """
        self._warn_deprecated("reduced", "reduce")
        legacy_reference_key = kwargs.pop("reference_uuid", None)
        if legacy_reference_key is not None:
            kwargs["reference_name"] = (
                "air" if legacy_reference_key == "air_uuid" else "reference"
            )
        legacy_absorbance = kwargs.get(
            "absorbance", args[2] if len(args) > 2 else True
        )
        result = self.reduce(*args, **kwargs)
        if legacy_absorbance:
            return result["extinction"], result["extinction_std"]
        return result["transmission"], result["transmission_std"]

    @staticmethod
    def _warn_deprecated(old_name: str, new_name: str) -> None:
        """Emit a consistent warning for a deprecated compatibility method.

        Parameters
        ----------
        old_name : str
            Deprecated method name.
        new_name : str
            Preferred replacement method name.
        """
        warnings.warn(
            f"{old_name}() is deprecated and will be removed in a future release; "
            f"use {new_name}() instead.",
            DeprecationWarning,
            stacklevel=3,
        )


_DEFAULT_CUSTOM_CONFIG = {
    "_classname": "AFL.automation.instrument.SeabreezeUVVis.SeabreezeUVVis",
    "backend": "pyseabreeze",
}
_DEFAULT_PORT = 5051


if __name__ == "__main__":
    from AFL.automation.shared.launcher import *
