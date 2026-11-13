import numpy as np
import pytest
import matplotlib.pyplot as plt

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.samplecells import NeutronSampleCell, SampleCell, ScrewCapVial
from AFL.automation.vision.ImageProcessing import ImageProcessing
from AFL.automation.vision.PiCameraDriver import PiCameraDriver
from AFL.automation.vision.RGBCamera import RGBCamera, _DEFAULT_CUSTOM_CONFIG


class FakeCamera:
    def capture_array(self, stream_name):
        return np.zeros((2, 3, 3), dtype=np.uint8)


class FakeOpenCVCapture:
    def __init__(self, camera_index):
        self.camera_index = camera_index
        self.released = False
        self.properties = []

    def isOpened(self):
        return not self.released

    def release(self):
        self.released = True

    def set(self, property_id, value):
        self.properties.append((property_id, value))
        return True


class FakeCV2:
    CAP_PROP_BUFFERSIZE = 38
    CAP_PROP_AUTOFOCUS = 39
    CAP_PROP_AUTO_EXPOSURE = 21

    def __init__(self):
        self.captures = []

    def VideoCapture(self, camera_index):
        capture = FakeOpenCVCapture(camera_index)
        self.captures.append(capture)
        return capture


def test_image_processing_crops_circular_region_and_calculates_rgb():
    processor = ImageProcessing()
    image = np.zeros((5, 5, 3), dtype=np.uint8)
    image[..., 0] = 10
    image[..., 1] = 20
    image[..., 2] = 30

    circle = processor.crop_to_circle(image, center=(2, 2), radius=2)

    assert circle["mask"].shape == (5, 5)
    assert not circle["mask"][0, 0]
    assert circle["mask"][2, 2]
    assert processor.rgb_values(image, circle["mask"]) == {"R": 10.0, "G": 20.0, "B": 30.0}


def test_image_processing_background_normalizes_turbidity():
    processor = ImageProcessing()
    background = np.full((2, 2), 100, dtype=np.uint8)
    image = np.full((2, 2), 50, dtype=np.uint8)

    result = processor.turbidity_measurement(image, background)

    assert result["turbidity_metric"] == pytest.approx(151 / 201)


def test_picamera_exposes_image_processing_operations():
    driver = PiCameraDriver(camera=FakeCamera())
    image = np.zeros((3, 3, 3), dtype=np.uint8)
    image[..., 0] = 10
    image[..., 1] = 20
    image[..., 2] = 30
    driver.dropbox = {"image": image, "background": image * 2}

    assert driver.measure_mean_rgb("image")["avg_rgb"] == {"R": 10.0, "G": 20.0, "B": 30.0}
    driver.set_background("background")
    # The legacy normalization uses a background-derived pedestal.
    assert driver.measure_turbidity("image")["turbidity_metric"] == pytest.approx(0.7533163536028865)
    assert "measure_mean_rgb" in driver.unqueued.functions
    assert "measure_turbidity" in driver.unqueued.functions
    assert "set_background" in driver.queued.functions


def test_picamera_measurements_apply_rectangular_crop_only_when_both_bounds_given():
    driver = PiCameraDriver(camera=FakeCamera())
    image = np.zeros((4, 4, 3), dtype=np.uint8)
    image[1:3, 1:3] = [10, 20, 30]
    background = np.full((4, 4, 3), 100, dtype=np.uint8)
    sample = background.copy()
    sample[1:3, 1:3] = 50
    driver.dropbox = {"image": image, "sample": sample, "background": background}

    assert driver.measure_mean_rgb(
        "image", row_crop=[1, 3], col_crop=[1, 3]
    )["avg_rgb"] == {"R": 10.0, "G": 20.0, "B": 30.0}
    assert driver.measure_mean_rgb("image", row_crop=[1, 3])["avg_rgb"] == {
        "R": 2.5,
        "G": 5.0,
        "B": 7.5,
    }

    cropped_turbidity = driver.measure_turbidity(
        "sample",
        background_uid="background",
        row_crop=[1, 3],
        col_crop=[1, 3],
    )
    assert cropped_turbidity["turbidity_metric"] == pytest.approx(151 / 201)


def test_rgb_camera_uses_image_processing_mixin_and_vision_loader(monkeypatch):
    sample_cell = NeutronSampleCell(
        row_crop=[1, 5], col_crop=[1, 5], hough_radii=2
    )
    driver = RGBCamera(
        overrides={"background_capture_on_init": False}, sample_cell=sample_cell
    )
    image = np.zeros((6, 6, 3), dtype=np.uint8)
    image[..., 0] = 30  # B
    image[..., 1] = 20  # G
    image[..., 2] = 10  # R

    monkeypatch.setattr(sample_cell, "find_circular_region", lambda image, radii: (3, 3, 2))
    processed = driver._process_image(image, px_crop=[1, 5], py_crop=[1, 5], hough_radii=2)
    configured_crop = driver._process_image(image, hough_radii=2)

    assert isinstance(driver, Driver)
    assert isinstance(driver.sample_cell, (NeutronSampleCell, ImageProcessing))
    assert processed["avg_rgb"] == {"R": 10.0, "G": 20.0, "B": 30.0}
    assert processed["mask"].shape == (4, 4)
    assert configured_crop["mask"].shape == (4, 4)
    assert "measure_mean_rgb" in driver.unqueued.functions
    assert "set_background" in driver.queued.functions
    assert RGBCamera.__module__ == "AFL.automation.vision.RGBCamera"
    assert _DEFAULT_CUSTOM_CONFIG["_classname"] == "AFL.automation.vision.RGBCamera.RGBCamera"
    assert "px_crop" not in driver.config
    assert "py_crop" not in driver.config
    assert "row_crop" not in driver.config
    assert "col_crop" not in driver.config
    assert "row_crop" not in _DEFAULT_CUSTOM_CONFIG["overrides"]
    assert "col_crop" not in _DEFAULT_CUSTOM_CONFIG["overrides"]


def test_rgb_camera_opens_on_initialization_and_can_be_closed(monkeypatch):
    fake_cv2 = FakeCV2()
    monkeypatch.setattr(
        "AFL.automation.vision.RGBCamera.lazy.load", lambda *args, **kwargs: fake_cv2
    )

    driver = RGBCamera(overrides={
        "background_capture_on_init": False,
        "camera_index": 4,
    })

    assert len(fake_cv2.captures) == 1
    assert driver._opencv_capture is fake_cv2.captures[0]
    assert driver._opencv_capture.camera_index == 4
    assert driver._opencv_capture.properties == [(38, 1), (39, 1), (21, 0.75)]
    assert "open" in driver.queued.functions
    assert "close" in driver.queued.functions
    assert driver.open() == {"camera_index": 4, "opened": True}
    assert len(fake_cv2.captures) == 1

    assert driver.close() == {"closed": True}
    assert fake_cv2.captures[0].released is True
    assert driver._opencv_capture is None

    assert driver.open() == {"camera_index": 4, "opened": True}
    assert len(fake_cv2.captures) == 2


def test_rgb_camera_coerces_serialized_numeric_camera_index(monkeypatch):
    fake_cv2 = FakeCV2()
    monkeypatch.setattr(
        "AFL.automation.vision.RGBCamera.lazy.load", lambda *args, **kwargs: fake_cv2
    )

    driver = RGBCamera(overrides={
        "background_capture_on_init": False,
        "camera_index": "0",
    })

    assert driver._opencv_capture.camera_index == 0
    assert driver.open() == {"camera_index": 0, "opened": True}


def test_rgb_camera_preserves_non_numeric_camera_source(monkeypatch):
    fake_cv2 = FakeCV2()
    monkeypatch.setattr(
        "AFL.automation.vision.RGBCamera.lazy.load", lambda *args, **kwargs: fake_cv2
    )
    stream_url = "rtsp://camera.example.test/live"

    driver = RGBCamera(overrides={
        "background_capture_on_init": False,
        "camera_index": stream_url,
    })

    assert driver._opencv_capture.camera_index == stream_url


def test_rgb_camera_initializes_without_the_optional_opencv_dependency(monkeypatch):
    def missing_cv2(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'cv2'")

    monkeypatch.setattr("AFL.automation.vision.RGBCamera.lazy.load", missing_cv2)

    driver = RGBCamera(overrides={"background_capture_on_init": False})

    assert driver._opencv_capture is None
    with pytest.raises(ImportError, match="opencv-python"):
        driver.open()


def test_neutron_sample_cell_extracts_shared_crop_and_circle(monkeypatch):
    cell = NeutronSampleCell()
    image = np.zeros((6, 6, 3), dtype=np.uint8)

    monkeypatch.setattr(cell, "find_circular_region", lambda image, radii: (2, 2, 1))
    sample = cell.extract_sample_image(
        image,
        row_crop=[1, 5],
        col_crop=[1, 5],
        hough_radii=1,
        color_order="BGR",
    )

    assert sample["cropped_img"].shape == (4, 4, 3)
    assert sample["mask"].shape == (4, 4)
    assert sample["row_crop"] == [1, 5]
    assert sample["col_crop"] == [1, 5]


def test_screw_cap_vial_extracts_rectangular_body_without_cap():
    cell = ScrewCapVial(
        row_crop=[1, 7],
        col_crop=[2, 6],
        cap_height=2,
    )
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    image[1:3, 2:6] = [200, 100, 50]
    image[3:7, 2:6] = [20, 40, 60]

    sample = cell.extract_sample_image(image)

    assert sample["cropped_img"].shape == (6, 4, 3)
    assert sample["gray_img"].shape == (6, 4)
    assert sample["geometry"] == "cylindrical_vial"
    assert sample["cap_height"] == 2
    assert sample["body_bbox"] == [0, 2, 4, 6]
    assert (sample["cx"], sample["cy"], sample["radius"]) == (2, 4, 2)
    assert not sample["mask"][:2].any()
    assert sample["mask"][2:].all()
    assert cell.rgb_values(sample["cropped_img"], sample["mask"]) == {
        "R": 20.0,
        "G": 40.0,
        "B": 60.0,
    }


def test_screw_cap_vial_uses_fractional_cap_height_and_validates_it():
    image = np.zeros((10, 4, 3), dtype=np.uint8)

    sample = ScrewCapVial(
        row_crop=[0, 10], col_crop=[0, 4], cap_height_fraction=0.25
    ).extract_sample_image(image)

    assert sample["cap_height"] == 3
    assert not sample["mask"][:3].any()
    assert sample["mask"][3:].all()
    with pytest.raises(ValueError, match="cap_height_fraction"):
        ScrewCapVial(
            row_crop=[0, 10], col_crop=[0, 4], cap_height_fraction=1
        ).extract_sample_image(image)


def test_camera_accepts_sample_cell_subclasses_and_rejects_other_objects():
    class CustomSampleCell(SampleCell):
        def extract_sample_image(self, image, **kwargs):
            image = np.asarray(image)
            return {
                "cropped_img": image,
                "mask": np.ones(image.shape[:2], dtype=bool),
                "cx": 0,
                "cy": 0,
                "radius": 1,
                "row_crop": [0, image.shape[0]],
                "col_crop": [0, image.shape[1]],
            }

    cell = CustomSampleCell(label="custom")
    driver = RGBCamera(
        overrides={"background_capture_on_init": False}, sample_cell=cell
    )

    assert driver.sample_cell is cell
    assert cell.config == {"label": "custom"}
    assert cell.save_geometry_plot.__func__ is SampleCell.save_geometry_plot
    assert cell.save_mask_comparison_plot.__func__ is SampleCell.save_mask_comparison_plot
    with pytest.raises(TypeError, match="SampleCell"):
        RGBCamera(overrides={"background_capture_on_init": False}, sample_cell=object())


def test_rgb_geometry_plot_keeps_full_image_pixel_axes(monkeypatch, tmp_path):
    driver = RGBCamera(overrides={"background_capture_on_init": False})
    captured = {}

    original_subplots = plt.subplots

    def capture_subplots(*args, **kwargs):
        figure, axes = original_subplots(*args, **kwargs)
        captured["axes"] = axes
        return figure, axes

    monkeypatch.setattr(plt, "subplots", capture_subplots)
    sample = {
        "cropped_img": np.zeros((2, 2, 3), dtype=np.uint8),
        "cx": 1,
        "cy": 1,
        "radius": 1,
        "row_crop": [1, 3],
        "col_crop": [2, 4],
    }

    driver.sample_cell.save_geometry_plot(
        np.zeros((5, 5, 3), dtype=np.uint8),
        sample,
        save_path=tmp_path,
        filename="geometry.png",
        show_full_image_axes=True,
    )

    assert captured["axes"][0].get_xlabel() == "px"
    assert captured["axes"][0].get_ylabel() == "py"
    assert captured["axes"][0].get_xticks().size > 0
    assert captured["axes"][0].get_yticks().size > 0
