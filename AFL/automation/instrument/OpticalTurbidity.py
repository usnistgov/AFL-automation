import copy
import datetime
import time
import warnings

import lazy_loader as lazy
import numpy as np
import xarray as xr

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.samplecells import NeutronSampleCell, SampleCell

try:
    from tiled.queries import Eq
except ImportError:
    Eq = None
    warnings.warn("Cannot import from tiled...empty UUID lookup will not work", stacklevel=2)


class OpticalTurbidity(Driver):
    defaults = {
        "save_path": "/home/afl642/2305_SINQ_TurbidityImages/",
        "camera_interface": "http",
        "camera_url": "http://afl-video:8081/103/current",
        "camera_index": 0,
        "empty_uuid": "",
    }

    def __init__(self, camera=None, overrides=None, sample_cell=None):
        """
        Initialize OpticalTurbidity calculator driver.

        Parameters
        ----------
        camera : object, optional
            Camera object (for example, a NetworkCamera instance). If None, one
            will be created when using the HTTP interface.
        overrides : dict, optional
            Configuration overrides for PersistentConfig.
        sample_cell : SampleCell, optional
            Geometry and image-processing strategy. Defaults to a
            ``NeutronSampleCell``.
        """
        if sample_cell is None:
            sample_cell = NeutronSampleCell()
        if not isinstance(sample_cell, SampleCell):
            raise TypeError("sample_cell must be an instance of SampleCell")
        self.sample_cell = sample_cell
        self.camera = camera
        self.empty_img = None
        self._opencv_capture = None
        Driver.__init__(
            self,
            name="OpticalTurbidity",
            defaults=self.gather_defaults(),
            overrides=overrides,
        )

        if self.camera is None and self.config["camera_interface"] == "http":
            from AFL.automation.instrument.NetworkCamera import NetworkCamera

            self.camera = NetworkCamera(self.config["camera_url"])

    def _collect_image(self, **kwargs):
        """
        Collect an image based on the configured camera interface.

        Returns
        -------
        tuple
            `(collected, img)` where `collected` indicates success.
        """
        interface = self.config["camera_interface"]

        if interface == "http":
            if self.camera is None:
                from AFL.automation.instrument.NetworkCamera import NetworkCamera

                if "camera_url" not in self.config:
                    raise ValueError("camera_url must be set in config when camera_interface='http'")
                self.camera = NetworkCamera(self.config["camera_url"])
            return self.camera.collect(**kwargs)

        if interface == "opencv":
            try:
                cv2_module = lazy.load("cv2", require="AFL-automation[vision]")
            except Exception as exc:
                raise ImportError(
                    "opencv-python is required for camera_interface='opencv'. "
                    f"Install with: pip install AFL-automation[vision]. Error: {exc}"
                )

            if "camera_index" not in self.config:
                raise ValueError("camera_index must be set in config when camera_interface='opencv'")

            camera_index = self.config["camera_index"]
            if self._opencv_capture is None:
                self._opencv_capture = cv2_module.VideoCapture(camera_index)

            return self._opencv_capture.read()

        raise ValueError(
            f"Unsupported camera_interface: '{interface}'. "
            "Supported values are: 'http', 'opencv'"
        )

    def _reset_camera(self):
        """Reset the configured camera connection."""
        interface = self.config["camera_interface"]

        if interface == "http":
            if self.camera is not None:
                self.camera.camera_reset()
            return

        if interface == "opencv":
            if self._opencv_capture is not None:
                self._opencv_capture.release()
            try:
                cv2_module = lazy.load("cv2", require="AFL-automation[vision]")
            except Exception as exc:
                raise ImportError(
                    "opencv-python is required for camera_interface='opencv'. "
                    f"Install with: pip install AFL-automation[vision]. Error: {exc}"
                )
            camera_index = self.config.get("camera_index", 0)
            self._opencv_capture = cv2_module.VideoCapture(camera_index)

    def _build_dataset(
        self,
        *,
        name,
        turbidity_metric,
        measurement_img,
        empty_img,
        mask,
        cx,
        cy,
        empty_from_measurement=False,
        is_empty_reference=False,
    ):
        ds = xr.Dataset()
        ds.attrs["located_center"] = [cx, cy]
        ds.attrs["name"] = name
        ds.attrs["turbidity_metric"] = turbidity_metric
        ds.attrs["empty_uuid"] = self.config.get("empty_uuid", "")
        ds.attrs["empty_available"] = not empty_from_measurement
        ds.attrs["is_empty_reference"] = is_empty_reference
        ds["turbidity"] = turbidity_metric
        ds["img"] = (("px", "py"), measurement_img)
        ds["img_MT"] = (("px", "py"), empty_img)
        ds["mask"] = (("px", "py"), mask)
        return ds

    def measure(self, set_empty=False, plotting=False, **kwargs):
        """
        This is an optical turbidity measurement observing the SANS cell.

        Parameters
        ----------
        set_empty : bool, optional
            If True, set the current image as the empty reference image.
        plotting : bool, optional
            If True, save diagnostic plots.
        **kwargs : dict
            Additional arguments passed to image collection.

        Returns
        -------
        xarray.Dataset
            Dataset with turbidity measurements and images. When
            `set_empty=True`, the dataset contains the captured empty image.
        """
        name = kwargs.pop("name", "")

        print("attempting to collect camera image")
        self._reset_camera()
        time.sleep(0.2)
        collected, img = self._collect_image(**kwargs)
        print(collected, img)

        if collected:
            print("collected image")
            measurement_img = self.sample_cell.to_grayscale(img, color_order="RGB")
        else:
            self._reset_camera()
            print("trying to reset camera connection")
            collected, img = self._collect_image(**kwargs)
            if collected:
                measurement_img = self.sample_cell.to_grayscale(img, color_order="RGB")
                print("success on retry")
            else:
                raise RuntimeError(
                    "Failed to collect camera image after two attempts. "
                    "Check that the camera is connected and the "
                    f"camera_interface ('{self.config['camera_interface']}') "
                    "settings are correct."
                )

        if set_empty:
            self.empty_img = measurement_img
            print("setting empty image", measurement_img)
            if self.data is not None and "sample_uuid" in self.data:
                self.config["empty_uuid"] = copy.deepcopy(self.data["sample_uuid"])
            return self._build_dataset(
                name=name,
                turbidity_metric=1.0,
                measurement_img=measurement_img,
                empty_img=measurement_img,
                mask=np.ones_like(measurement_img, dtype=bool),
                cx=0,
                cy=0,
                empty_from_measurement=False,
                is_empty_reference=True,
            )

        print("measuring turbidity")

        empty_img = None
        empty_from_measurement = False
        if self.empty_img is not None:
            empty_img = self.empty_img
        elif self.config.get("empty_uuid"):
            if Eq is None:
                self.log_warning("Cannot load empty image without tiled. Using measurement image for mask.")
            elif self.data is None or not hasattr(self.data, "tiled_client") or self.data.tiled_client is None:
                self.log_warning("No tiled client available. Using measurement image for mask.")
            else:
                tiled_result = self.data.tiled_client.search(Eq("sample_uuid", self.config["empty_uuid"]))
                result_items = list(tiled_result.items())
                if not result_items:
                    self.log_warning(
                        f"No tiled entry found for empty_uuid={self.config['empty_uuid']}. "
                        "Using measurement image for mask."
                    )
                else:
                    item = result_items[-1][-1]
                    try:
                        ds = item.read(optimize_wide_table=False)
                    except TypeError:
                        ds = item.read()
                    if "img_MT" in ds:
                        empty_img = ds["img_MT"].values
                    elif "img" in ds:
                        empty_img = ds["img"].values

        if empty_img is None:
            self.log_warning("No empty image available. Using measurement image for mask and normalization.")
            empty_img = measurement_img
            empty_from_measurement = True

        reference_sample = self.sample_cell.extract_sample_image(empty_img, color_order="RGB")
        measurement_img = self.sample_cell.crop_image(
            measurement_img,
            row_crop=reference_sample["row_crop"],
            col_crop=reference_sample["col_crop"],
        )
        empty_img = reference_sample["cropped_img"]
        mask = reference_sample["mask"]
        cx = reference_sample["cx"]
        cy = reference_sample["cy"]
        turbidity_metric = self.sample_cell.turbidity_measurement(
            measurement_img, empty_img, mask, color_order="RGB"
        )["turbidity_metric"]

        if plotting:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            title = f"Turbidity metric {np.round(turbidity_metric, 2)}"
            self.sample_cell.save_mask_comparison_plot(
                empty_img,
                measurement_img,
                mask,
                save_path=self.config["save_path"],
                filename=f"{timestamp}-turbidity0.png",
                title=title,
            )
            self.sample_cell.save_mask_comparison_plot(
                empty_img,
                measurement_img,
                mask,
                save_path=self.config["save_path"],
                filename=f"{timestamp}-turbidity1.png",
                title=title,
                invert_mask=True,
            )

        return self._build_dataset(
            name=name,
            turbidity_metric=turbidity_metric,
            measurement_img=measurement_img,
            empty_img=empty_img,
            mask=mask,
            cx=cx,
            cy=cy,
            empty_from_measurement=empty_from_measurement,
            is_empty_reference=False,
        )


_DEFAULT_CUSTOM_CONFIG = {
    "_classname": "AFL.automation.instrument.OpticalTurbidity.OpticalTurbidity",
    "_args": [
        {
            "_classname": "AFL.automation.instrument.NetworkCamera.NetworkCamera",
            "_args": ["http://afl-video:8081/103/current"],
        }
    ],
    "sample_cell": {
        "_classname": "AFL.automation.shared.samplecells.NeutronSampleCell",
    },
}
_DEFAULT_CUSTOM_PORT = 5001
if __name__ == "__main__":
    from AFL.automation.shared.launcher import *
