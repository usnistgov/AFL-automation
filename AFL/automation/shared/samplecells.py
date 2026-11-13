"""Geometry and diagnostic plotting for shared sample-cell image pipelines."""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np

from AFL.automation.vision.ImageProcessing import ImageProcessing


class SampleCell(ImageProcessing):
    """Base interface for sample-cell image geometry.

    Sample-cell configuration deliberately lives on the cell instead of on a
    camera or instrument driver.  Subclasses should implement
    :meth:`extract_sample_image`; they may reuse the image-processing helpers
    inherited from :class:`ImageProcessing`.
    """

    defaults = {}

    def __init__(self, overrides=None, **config):
        self.config = {}
        for parent in reversed(type(self).__mro__):
            self.config.update(copy.deepcopy(getattr(parent, "defaults", {})))
        if overrides is not None:
            self.config.update(copy.deepcopy(overrides))
        self.config.update(copy.deepcopy(config))

    def extract_sample_image(self, image, **kwargs):
        """Return the image and mask for the sample region."""
        raise NotImplementedError

    @staticmethod
    def _display_image(image, color_order):
        image = np.asarray(image)
        if image.ndim == 3 and str(color_order).upper() == "BGR":
            return image[..., ::-1]
        return image

    def save_geometry_plot(
        self,
        raw_image,
        sample_image,
        *,
        save_path,
        filename,
        title="Detected sample-cell region",
        color_order="RGB",
        overlay_mask=None,
        show_full_image_axes=True,
        full_image_x_label="px",
        full_image_y_label="py",
    ):
        """Save a reusable full-frame and extracted-region diagnostic plot.

        A crop rectangle and circular outline are drawn when the corresponding
        metadata is present, so subclasses with non-circular geometry can use
        this routine without supplying neutron-cell-specific fields.
        """
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle, Rectangle

        raw_image = np.asarray(raw_image)
        row_crop = sample_image.get("row_crop", [0, raw_image.shape[0]])
        col_crop = sample_image.get("col_crop", [0, raw_image.shape[1]])
        fig, axes = plt.subplots(1, 2, figsize=(12, 6))
        axes[0].imshow(self._display_image(raw_image, color_order))
        axes[0].add_patch(
            Rectangle(
                (col_crop[0], row_crop[0]),
                col_crop[1] - col_crop[0],
                row_crop[1] - row_crop[0],
                edgecolor="red",
                facecolor="none",
                linewidth=2,
            )
        )
        axes[0].set_title("Captured image with cell crop")
        if show_full_image_axes:
            axes[0].set_xlabel(full_image_x_label)
            axes[0].set_ylabel(full_image_y_label)
        else:
            axes[0].axis("off")

        axes[1].imshow(self._display_image(sample_image["cropped_img"], color_order))
        if overlay_mask is not None:
            axes[1].imshow(np.where(overlay_mask, 1.0, np.nan), alpha=0.35, cmap="magma")
        if sample_image.get("geometry", "circular") == "circular" and all(
            key in sample_image for key in ("cx", "cy", "radius")
        ):
            axes[1].add_patch(
                Circle(
                    (sample_image["cx"], sample_image["cy"]),
                    sample_image["radius"],
                    edgecolor="red",
                    facecolor="none",
                    linewidth=2,
                )
            )
        if "body_bbox" in sample_image:
            left, top, right, bottom = sample_image["body_bbox"]
            axes[1].add_patch(
                Rectangle(
                    (left, top),
                    right - left,
                    bottom - top,
                    edgecolor="red",
                    facecolor="none",
                    linewidth=2,
                )
            )
        axes[1].set_title(title)
        axes[1].axis("off")
        fig.tight_layout()

        output_path = Path(save_path) / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        return output_path

    def save_mask_comparison_plot(
        self,
        reference_image,
        measurement_image,
        mask,
        *,
        save_path,
        filename,
        title,
        invert_mask=False,
    ):
        """Save a reference/measurement mask diagnostic plot."""
        import matplotlib.pyplot as plt

        mask = ~np.asarray(mask, dtype=bool) if invert_mask else np.asarray(mask, dtype=bool)
        fig, axes = plt.subplots(1, 2)
        for axis, image, label in zip(
            axes, (reference_image, measurement_image), ("Reference", "Measurement")
        ):
            axis.imshow(image)
            axis.imshow(np.where(mask, 0.0, np.nan))
            axis.set_title(label)
            axis.axis("off")
        fig.suptitle(title)
        output_path = Path(save_path) / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path)
        plt.close(fig)
        return output_path


class NeutronSampleCell(SampleCell):
    """Describe the circular optical region of a neutron sample cell.

    This is deliberately not a :class:`Driver`. Instrument drivers hold a
    sample-cell instance so its crop, circular ROI, and geometry configuration
    remain independent of camera acquisition and measurement settings.
    """

    geometry_defaults = {
        "row_crop": [0, 479],
        "col_crop": [0, 479],
        "hough_radii": 98,
    }
    defaults = geometry_defaults

    def extract_sample_image(
        self,
        image,
        *,
        row_crop=None,
        col_crop=None,
        hough_radii=None,
        color_order="RGB",
    ):
        """Crop ``image`` to the cell and locate its circular sample region."""
        config = getattr(self, "config", {})
        row_crop = row_crop if row_crop is not None else config.get("row_crop")
        col_crop = col_crop if col_crop is not None else config.get("col_crop")
        hough_radii = (
            hough_radii if hough_radii is not None else config.get("hough_radii")
        )
        if hough_radii is None:
            raise ValueError("hough_radii must be configured for neutron sample-cell geometry")

        cropped_image = self.crop_image(image, row_crop=row_crop, col_crop=col_crop)
        circle = self.crop_to_circle(cropped_image, hough_radii=hough_radii)
        cx, cy = (int(value) for value in circle["center"])
        radius = int(circle["radius"])
        return {
            "cropped_img": cropped_image,
            "gray_img": self.to_grayscale(cropped_image, color_order=color_order),
            "mask": circle["mask"],
            "cx": cx,
            "cy": cy,
            "radius": radius,
            "row_crop": list(row_crop) if row_crop is not None else [0, image.shape[0]],
            "col_crop": list(col_crop) if col_crop is not None else [0, image.shape[1]],
        }


class ScrewCapVial(SampleCell):
    """Describe the rectangular body of an upright cylindrical screw-cap vial.

    The configured row and column bounds first isolate the complete vial.  A
    band at the top of that crop is then excluded from the sample mask so the
    screw cap does not contribute to image measurements.  ``cap_height`` may
    be supplied in pixels for a calibrated camera; otherwise
    ``cap_height_fraction`` is used relative to the cropped image height.
    """

    geometry_defaults = {
        "row_crop": [0, 479],
        "col_crop": [0, 479],
        "cap_height": None,
        "cap_height_fraction": 0.2,
    }
    defaults = geometry_defaults

    def extract_sample_image(
        self,
        image,
        *,
        row_crop=None,
        col_crop=None,
        cap_height=None,
        cap_height_fraction=None,
        color_order="RGB",
    ):
        """Crop ``image`` to the vial and mask out its screw cap."""
        image = np.asarray(image)
        config = getattr(self, "config", {})
        row_crop = row_crop if row_crop is not None else config.get("row_crop")
        col_crop = col_crop if col_crop is not None else config.get("col_crop")
        if cap_height is None:
            cap_height = config.get("cap_height")
        if cap_height_fraction is None:
            cap_height_fraction = config.get("cap_height_fraction", 0.2)

        cropped_image = self.crop_image(image, row_crop=row_crop, col_crop=col_crop)
        height, width = cropped_image.shape[:2]

        if cap_height is None:
            cap_height_fraction = float(cap_height_fraction)
            if not 0 <= cap_height_fraction < 1:
                raise ValueError("cap_height_fraction must satisfy 0 <= value < 1")
            cap_height = int(np.ceil(height * cap_height_fraction))
        else:
            cap_height = int(cap_height)
            if not 0 <= cap_height < height:
                raise ValueError(
                    f"cap_height must satisfy 0 <= cap_height < cropped height ({height})"
                )

        mask = np.zeros((height, width), dtype=bool)
        mask[cap_height:, :] = True
        body_height = height - cap_height
        return {
            "cropped_img": cropped_image,
            "gray_img": self.to_grayscale(cropped_image, color_order=color_order),
            "mask": mask,
            "geometry": "cylindrical_vial",
            "body_bbox": [0, cap_height, width, height],
            "cap_height": cap_height,
            "cx": width // 2,
            "cy": cap_height + body_height // 2,
            "radius": width // 2,
            "row_crop": list(row_crop) if row_crop is not None else [0, image.shape[0]],
            "col_crop": list(col_crop) if col_crop is not None else [0, image.shape[1]],
        }
