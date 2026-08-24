import datetime
import logging
import pathlib
import sys
import time

import lazy_loader as lazy
import numpy as np
import xarray as xr

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.samplecells import NeutronSampleCell


class RGBCamera(NeutronSampleCell, Driver):
    """
    Driver for capturing RGB images and computing average RGB values.
    
    This driver interfaces with a USB camera to capture images and extract
    the average RGB values along with image metadata.
    """
    
    defaults = {
        "camera_index": 0,
        "save_path": "/home/afl642/rgb_images/",
        "px_crop": [220, 350],
        "py_crop": [120, 250],
        "hough_radii": 40,
        "subtract_background": True,
        "show_background_pipeline": False,
        "background_threshold": 25,
        "background_capture_on_init": True,
        "background": "background.npz",
        "camera_warmup_delay": 0.2,
    }

    def __init__(self, overrides=None):
        """
        Initialize RGBCamera driver.

        Parameters
        ----------
        overrides : dict, optional
            Configuration overrides for PersistentConfig.
        """
        self._opencv_capture = None
        # ``bkg`` is deliberately a locator, never an image array.  A
        # background captured without Tiled is stored under AFL_HOME; after a
        # queued capture is persisted to Tiled, post_tiled_finalize replaces
        # this value with that entry ID.
        self.bkg = None
        self._background_meta = {}
        Driver.__init__(
            self,
            name="RGBCamera",
            defaults=self.gather_defaults(),
            overrides=overrides,
        )
        self._background_path = self.path / "RGBCamera" / "background.npz"
        configured_background = self.config.get("background", "background.npz")
        if (
            isinstance(configured_background, str)
            and not configured_background.lower().endswith(".npz")
        ):
            self.bkg = configured_background
        elif self._background_path.is_file():
            self.bkg = str(self._background_path)
        self._configure_direct_logging()
        try:
            self.open()
        except ImportError as exc:
            self.log_warning(
                "OpenCV is unavailable; RGB camera will remain closed until "
                f"the vision extra is installed. {exc}"
            )
        if self.config.get("background_capture_on_init", True):
            try:
                self.refresh_background()
            except Exception as exc:
                self.log_warning(f"Initial background capture failed: {exc}")

    def _configure_direct_logging(self):
        """
        Ensure driver logs are visible when the driver is used directly in Python/IPython.
        """
        if self.app is not None:
            return

        for handler in self.logger.handlers:
            if getattr(handler, "_afl_direct_driver_handler", False):
                return

        handler = logging.StreamHandler(sys.stdout)
        handler._afl_direct_driver_handler = True
        handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
        self.logger.addHandler(handler)
        self.logger.propagate = False

    def _collect_image(self, **kwargs):
        """
        Collect an image based on the configured camera interface.

        Returns
        -------
        tuple
            `(collected, img)` where `collected` indicates success.
        """
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
        if self._opencv_capture is None or not self._opencv_capture.isOpened():
            self.open()

        return self._opencv_capture.read()

    @Driver.queued()
    def open(self):
        """Open the configured OpenCV camera and retain its capture handle."""
        if self._opencv_capture is not None and self._opencv_capture.isOpened():
            return {
                "camera_index": self.config.get("camera_index", 0),
                "opened": True,
            }
        self.close()
        try:
            cv2_module = lazy.load("cv2", require="AFL-automation[vision]")
        except Exception as exc:
            raise ImportError(
                "opencv-python is required for camera_interface='opencv'. "
                f"Install with: pip install AFL-automation[vision]. Error: {exc}"
            )
        camera_index = self.config.get("camera_index", 0)
        self._opencv_capture = cv2_module.VideoCapture(camera_index)
        return {
            "camera_index": camera_index,
            "opened": bool(self._opencv_capture.isOpened()),
        }

    def _save_local_background(self, background, mask, metadata):
        """Persist a background reference beneath ``AFL_HOME/RGBCamera``."""
        self._background_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            self._background_path,
            background=np.asarray(background),
            mask=np.asarray(mask, dtype=bool),
            cx=metadata["cx"],
            cy=metadata["cy"],
            radius=metadata["radius"],
        )
        self.bkg = str(self._background_path)
        self.config["background"] = self.bkg

    def _load_background(self):
        """Load the background and ROI mask addressed by ``self.bkg``."""
        if self.bkg is None:
            raise ValueError("No background reference has been captured.")

        locator = str(self.bkg)
        if pathlib.Path(locator).suffix.lower() == ".npz":
            background_path = pathlib.Path(locator)
            if not background_path.is_file():
                raise ValueError(f"Local RGB background does not exist at {background_path}.")
            with np.load(background_path) as background_data:
                result = {
                    "background": np.array(background_data["background"], copy=True),
                    "mask": np.array(background_data["mask"], dtype=bool, copy=True),
                    "meta": {
                        "cx": int(background_data["cx"]),
                        "cy": int(background_data["cy"]),
                        "radius": int(background_data["radius"]),
                    },
                }
        else:
            tiled_client = getattr(getattr(self, "data", None), "tiled_client", None)
            if tiled_client is None:
                raise ValueError(
                    f"RGB background {locator!r} is a Tiled entry and requires an initialized Tiled connection."
                )
            try:
                entry = tiled_client["run_documents"][locator]
                result = {
                    # Tiled stores a display-ready RGB image. The OpenCV
                    # subtraction pipeline remains BGR internally.
                    "background": np.asarray(entry["background_rgb"][()])[..., ::-1],
                    "mask": np.asarray(entry["background_mask"][()], dtype=bool),
                    "meta": dict(getattr(entry, "metadata", {}).get("attrs", {})),
                }
            except KeyError as exc:
                raise ValueError(f"RGB background Tiled entry {locator!r} no longer exists.") from exc

        self._background_meta = result["meta"]
        return result

    @Driver.queued()
    def close(self):
        """Release the OpenCV camera handle so another process can use it."""
        if self._opencv_capture is not None:
            self._opencv_capture.release()
            self._opencv_capture = None
        return {"closed": True}

    def _reset_camera(self):
        """Reset the configured camera connection."""
        self.close()
        self.open()

    def _capture_processed_frame(self, **kwargs):
        """
        Capture an image and apply the standard crop/circle processing pipeline.

        Returns
        -------
        tuple
            `(img, processed)` where `img` is the raw BGR frame and `processed`
            is the payload returned by `_process_image`.
        """
        px_crop = self.config["px_crop"]
        py_crop = self.config["py_crop"]
        hough_radii = self.config["hough_radii"]
        warmup_delay = self.config.get("camera_warmup_delay", 0.2)

        self.log_info(
            "Capturing RGB image with circular ROI detection "
            f"(px_crop={px_crop}, py_crop={py_crop}, hough_radii={hough_radii})."
        )
        self.log_debug("Attempting to collect camera image.")

        # A number of still-image camera backends acquire only when the
        # VideoCapture session is opened.  Reusing the session opened during
        # driver startup therefore repeats the initial image on later calls.
        # Resetting it here makes every capture_rgb invocation initiate a new
        # hardware acquisition.
        self._reset_camera()
        time.sleep(warmup_delay)
        collected, img = self._collect_image(**kwargs)

        if collected:
            self.log_debug("Successfully collected camera image.")
        else:
            self._reset_camera()
            self.log_warning("Initial camera capture failed; resetting camera connection and retrying.")
            time.sleep(warmup_delay)
            collected, img = self._collect_image(**kwargs)
            if collected:
                self.log_info("Camera capture succeeded on retry.")
            else:
                raise RuntimeError(
                    "Failed to collect camera image after two attempts. "
                    "Check that the camera is connected and that "
                    f"camera_index ('{self.config.get('camera_index', 0)}') is correct."
                )

        processed = self._process_image(img)
        return img, processed

    def _log_rgb_measurement(self, avg_rgb, *, subtract_background, radius, changed_pixel_count=None):
        """
        Emit a concise log message describing how RGB values were obtained.
        """
        if subtract_background:
            threshold = self.config.get("background_threshold", 25)
            self.log_info(
                "Computed RGB using background-subtracted foreground extraction "
                f"inside the circular ROI (radius={radius}, threshold={threshold}, "
                f"changed_pixels={changed_pixel_count}). "
                f"RGB=({avg_rgb['R']:.2f}, {avg_rgb['G']:.2f}, {avg_rgb['B']:.2f})."
            )
        else:
            self.log_info(
                "Computed RGB using direct circular ROI averaging "
                f"(radius={radius}). "
                f"RGB=({avg_rgb['R']:.2f}, {avg_rgb['G']:.2f}, {avg_rgb['B']:.2f})."
            )

    def _process_image(self, img, px_crop=None, py_crop=None, hough_radii=None):
        """
        Crop the image, locate the circular sample region, and compute masked RGB averages.

        Parameters
        ----------
        img : np.ndarray
            Input image in BGR format (from OpenCV).
        px_crop : list, optional
            Pixel range [start, end] for cropping along the x-axis. Defaults to
            the driver's ``px_crop`` configuration.
        py_crop : list, optional
            Pixel range [start, end] for cropping along the y-axis. Defaults to
            the driver's ``py_crop`` configuration.
        hough_radii : int or list, optional
            Radius or radii to use for Hough circle detection.

        Returns
        -------
        dict
            Processed image payload including cropped image, mask, center, radius,
            and average RGB values computed inside the mask.
        """
        px_crop = self.config["px_crop"] if px_crop is None else px_crop
        py_crop = self.config["py_crop"] if py_crop is None else py_crop
        sample = self.extract_sample_image(
            img,
            row_crop=py_crop,
            col_crop=px_crop,
            hough_radii=hough_radii,
            color_order="BGR",
        )
        sample["avg_rgb"] = self.rgb_values(
            sample["cropped_img"], sample["mask"], color_order="BGR"
        )
        return sample

    def _process_image_with_background(self, background, image, show=False, threshold=None, roi_mask=None):
        """
        Compute a foreground mask from a stored background image and return RGB averages.

        Parameters
        ----------
        background : np.ndarray
            Cropped background image.
        image : np.ndarray
            Cropped image containing the object of interest.
        show : bool, optional
            If True, save a pyplot view of the subtraction pipeline.
        threshold : float, optional
            Difference threshold used to define the foreground mask.
        roi_mask : np.ndarray, optional
            Boolean mask restricting subtraction to the circular sample region.

        Returns
        -------
        dict
            Background-subtraction results including mask, extracted image, and avg_rgb.
        """
        I1 = np.asarray(background)
        I2 = np.asarray(image)

        if I1.shape != I2.shape:
            raise ValueError(
                "Background and measurement image shapes must match for subtraction. "
                f"Got {I1.shape} and {I2.shape}."
            )

        diff = np.abs(I2.astype(np.float32) - I1.astype(np.float32))
        if diff.ndim == 3:
            diff_map = diff.mean(axis=2)
        else:
            diff_map = diff

        if threshold is None:
            threshold = self.config.get("background_threshold", 25)

        mask = diff_map > threshold
        if roi_mask is not None:
            roi_mask = np.asarray(roi_mask, dtype=bool)
            if roi_mask.shape != diff_map.shape:
                raise ValueError(
                    "ROI mask shape must match the cropped image shape for background subtraction. "
                    f"Got {roi_mask.shape} and {diff_map.shape}."
                )
            mask = mask & roi_mask
        try:
            from scipy.ndimage import binary_closing, binary_fill_holes, binary_opening
        except ImportError as exc:
            raise ImportError(
                "Background subtraction requires scipy. Install AFL-automation[vision]."
            ) from exc
        mask = binary_opening(mask, structure=np.ones((3, 3)))
        mask = binary_closing(mask, structure=np.ones((5, 5)))
        mask = binary_fill_holes(mask)
        if roi_mask is not None:
            mask = mask & roi_mask
        changed_pixel_count = int(np.count_nonzero(mask))

        if changed_pixel_count < 10:
            self.log_warning(
                "Background subtraction detected fewer than 10 changed pixels "
                f"between the stored background and the captured image ({changed_pixel_count} pixels)."
            )

        if I2.ndim == 3:
            extracted = np.where(mask[..., None], I2, 0)
        else:
            extracted = np.where(mask, I2, 0)

        # An unchanged frame legitimately has no foreground pixels.  Report a
        # zero-valued foreground measurement instead of passing an empty mask
        # to rgb_values(), which would abort the queued capture.
        if changed_pixel_count:
            avg_rgb = self.rgb_values(extracted, mask, color_order="BGR")
        else:
            avg_rgb = {"R": 0.0, "G": 0.0, "B": 0.0}

        pipeline_plot_path = None
        if show:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(1, 4, figsize=(16, 4))
            ax[0].imshow(I1[:, :, ::-1] if I1.ndim == 3 else I1)
            ax[0].set_title("Background I1")
            ax[1].imshow(I2[:, :, ::-1] if I2.ndim == 3 else I2)
            ax[1].set_title("Image I2")
            ax[2].imshow(mask, cmap="gray")
            ax[2].set_title("Mask")
            ax[3].imshow(extracted[:, :, ::-1] if extracted.ndim == 3 else extracted)
            ax[3].set_title("Extracted object")

            for axis in ax:
                axis.axis("off")

            plt.tight_layout()
            save_path = pathlib.Path(self.config.get("save_path", "./"))
            save_path.mkdir(parents=True, exist_ok=True)
            pipeline_plot_path = (
                save_path
                / f"{datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}-rgb-background-pipeline.png"
            )
            plt.savefig(pipeline_plot_path, dpi=100, bbox_inches="tight")
            plt.close(fig)
            self.log_info(f"Saved background-subtraction pipeline plot to {pipeline_plot_path}.")

        return {
            "background": I1,
            "image": I2,
            "mask": mask,
            "changed_pixel_count": changed_pixel_count,
            "foreground_detected": bool(changed_pixel_count),
            "extracted": extracted,
            "pipeline_plot_path": None if pipeline_plot_path is None else str(pipeline_plot_path),
            "avg_rgb": avg_rgb,
        }

    @Driver.queued()
    def refresh_background(self, **kwargs):
        """
        Capture and persist a new cropped background reference image.

        The local archive is available immediately at
        ``AFL_HOME/RGBCamera/background.npz``.  When this queued result is
        written to Tiled, :meth:`post_tiled_finalize` switches ``self.bkg``
        to the resulting Tiled entry ID.
        """
        _, processed = self._capture_processed_frame(**kwargs)
        masked_background = np.where(
            processed["mask"][..., None],
            processed["cropped_img"],
            0,
        )
        self._background_meta = {
            "cx": processed["cx"],
            "cy": processed["cy"],
            "radius": processed["radius"],
            "shape": processed["cropped_img"].shape,
        }
        self._save_local_background(masked_background, processed["mask"], self._background_meta)
        self.log_info(
            "Stored new background reference for RGB subtraction "
            f"(center=({processed['cx']}, {processed['cy']}), radius={processed['radius']})."
        )
        dataset = xr.Dataset()
        dataset.attrs.update(
            mode="rgb_background",
            background_locator=str(self._background_path),
            located_center=[processed["cx"], processed["cy"]],
            mask_radius=processed["radius"],
        )
        dataset["background_rgb"] = (
            ("height", "width", "rgb_channel"),
            masked_background[..., ::-1],
        )
        dataset = dataset.assign_coords(rgb_channel=["R", "G", "B"])
        dataset["background_mask"] = (("height", "width"), processed["mask"])
        return dataset

    def post_tiled_finalize(self, task, tiled_entry_id):
        """Use the persisted Tiled background after a successful refresh."""
        if task.get("task_name") == "refresh_background":
            self.bkg = tiled_entry_id
            self.config["background"] = tiled_entry_id

    def _build_dataset(
        self,
        *,
        name,
        avg_rgb,
        measurement_img,
        mask,
        cx,
        cy,
        radius,
        img_metadata,
    ):
        """
        Build an xarray Dataset containing RGB measurements, an RGB image, mask, and metadata.
        """
        ds = xr.Dataset()
        ds.attrs["name"] = name
        ds.attrs["avg_R"] = avg_rgb["R"]
        ds.attrs["avg_G"] = avg_rgb["G"]
        ds.attrs["avg_B"] = avg_rgb["B"]
        ds.attrs["timestamp"] = img_metadata["timestamp"]
        ds.attrs["image_height"] = img_metadata["height"]
        ds.attrs["image_width"] = img_metadata["width"]
        ds.attrs["camera_index"] = self.config.get("camera_index", 0)
        ds.attrs["located_center"] = [cx, cy]
        ds.attrs["mask_radius"] = radius
        ds.attrs["background_subtracted"] = img_metadata.get("background_subtracted", False)
        ds.attrs["background_available"] = self.bkg is not None
        ds.attrs["background_threshold"] = img_metadata.get(
            "background_threshold",
            self.config.get("background_threshold", 25),
        )

        ds["avg_rgb"] = xr.DataArray(
            [avg_rgb["R"], avg_rgb["G"], avg_rgb["B"]],
            coords={"channel": ["R", "G", "B"]},
        )
        # Persist one display-ready image.  Keeping only RGB also matches the
        # background dataset format used by Tiled and avoids redundant image
        # arrays in every capture entry.
        ds["img_rgb"] = (
            ("height", "width", "rgb_channel"),
            measurement_img[..., ::-1],
        )
        ds = ds.assign_coords(rgb_channel=["R", "G", "B"])
        ds["mask"] = (("height", "width"), mask)

        return ds

    @Driver.queued(
        qb={
            "button_text": "Capture RGB",
            "params": {
                "name": {"label": "Measurement Name", "type": "text", "default": ""},
                "plotting": {"label": "Save diagnostic plots", "type": "bool", "default": False},
                "subtract_background": {
                    "label": "Subtract background",
                    "type": "bool",
                    "default": False,
                },
                "show_background_pipeline": {
                    "label": "Show background pipeline",
                    "type": "bool",
                    "default": False,
                },
            },
        }
    )
    def capture_rgb(
        self,
        name="",
        plotting=False,
        subtract_background=False,
        show_background_pipeline=False,
        **kwargs,
    ):
        """
        Capture an image and compute average RGB values.

        Parameters
        ----------
        name : str, optional
            Name/identifier for the measurement.
        plotting : bool, optional
            If True, save diagnostic plots of the captured image.
        subtract_background : bool, optional
            If True, use the stored background reference to compute the average RGB.
        show_background_pipeline : bool, optional
            If True, display the background subtraction diagnostic plot.
        **kwargs : dict
            Additional arguments passed to image collection.

        Returns
        -------
        xarray.Dataset
            Dataset with average RGB values, image, and metadata.
        """
        img, processed = self._capture_processed_frame(**kwargs)

        subtract_background = subtract_background or self.config.get("subtract_background", False)
        show_background_pipeline = show_background_pipeline or self.config.get(
            "show_background_pipeline", False
        )

        background_processed = None
        avg_rgb = processed["avg_rgb"]
        if subtract_background:
            if self.bkg is None:
                self.refresh_background(**kwargs)
            background = self._load_background()
            roi_mask = processed["mask"]
            if background["mask"].shape == processed["mask"].shape:
                roi_mask = roi_mask & background["mask"]
            background_processed = self._process_image_with_background(
                background["background"],
                np.where(processed["mask"][..., None], processed["cropped_img"], 0),
                show=show_background_pipeline,
                roi_mask=roi_mask,
            )
            avg_rgb = background_processed["avg_rgb"]
        self._log_rgb_measurement(
            avg_rgb,
            subtract_background=subtract_background,
            radius=processed["radius"],
            changed_pixel_count=(
                None if background_processed is None else background_processed["changed_pixel_count"]
            ),
        )

        img_metadata = {
            "timestamp": datetime.datetime.now().isoformat(),
            "height": processed["cropped_img"].shape[0],
            "width": processed["cropped_img"].shape[1],
            "background_subtracted": subtract_background,
            "background_threshold": self.config.get("background_threshold", 25),
        }

        ds = self._build_dataset(
            name=name,
            avg_rgb=avg_rgb,
            measurement_img=processed["cropped_img"],
            mask=processed["mask"],
            cx=processed["cx"],
            cy=processed["cy"],
            radius=processed["radius"],
            img_metadata=img_metadata,
        )
        if plotting:
            try:
                save_path = pathlib.Path(self.config.get("save_path", "./"))
                plot_file = self.save_geometry_plot(
                    img,
                    processed,
                    save_path=save_path,
                    filename=f"{datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}-rgb-capture.png",
                    title="Detected neutron sample cell",
                    color_order="BGR",
                    show_full_image_axes=True,
                    full_image_x_label="px",
                    full_image_y_label="py",
                    overlay_mask=(
                        None if background_processed is None else background_processed["mask"]
                    ),
                )
                self.log_info(f"Saved RGB capture diagnostic plot to {plot_file}.")
            except Exception as e:
                self.log_warning(f"Could not save RGB capture diagnostic plot: {e}")

        return ds

_DEFAULT_CUSTOM_CONFIG = {
    "_classname": "AFL.automation.vision.RGBCamera.RGBCamera",
    "overrides": {
        "camera_index": 0,
        "px_crop": [220, 350],
        "py_crop": [120, 250],
        "hough_radii": 40,
        "save_path": "/home/afl642/rgb_camera/",
        "subtract_background": True,
        "show_background_pipeline": False,
        "background_threshold": 25,
        "background_capture_on_init": True,
        "background": "background.npz",
        "camera_warmup_delay": 0.2,
    }
}
_DEFAULT_CUSTOM_PORT = 5095

if __name__ == "__main__":
    from AFL.automation.shared.launcher import *
