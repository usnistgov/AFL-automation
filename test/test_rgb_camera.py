import json
import pathlib
from types import SimpleNamespace

import numpy as np

from AFL.automation.shared.samplecells import NeutronSampleCell, ScrewCapVial
from AFL.automation.vision.RGBCamera import RGBCamera


def test_build_dataset_includes_tiled_ready_rgb_image():
    driver = object.__new__(RGBCamera)
    driver.config = {"camera_index": 0, "background_threshold": 25}
    driver.bkg = None
    image_bgr = np.array([[[10, 20, 30], [40, 50, 60]]], dtype=np.uint8)

    dataset = driver._build_dataset(
        name="sample",
        avg_rgb={"R": 45.0, "G": 35.0, "B": 25.0},
        measurement_img=image_bgr,
        mask=np.array([[True, True]]),
        cx=1,
        cy=0,
        radius=1,
        img_metadata={
            "timestamp": "2026-08-18T00:00:00",
            "height": 1,
            "width": 2,
            "background_subtracted": False,
        },
    )

    np.testing.assert_array_equal(
        dataset["img_rgb"],
        np.array([[[30, 20, 10], [60, 50, 40]]], dtype=np.uint8),
    )
    assert set(dataset.data_vars) == {"avg_rgb", "img_rgb", "mask"}
    assert dataset["img_rgb"].dims == ("height", "width", "rgb_channel")
    assert dataset["img_rgb"].coords["rgb_channel"].values.tolist() == ["R", "G", "B"]


def test_refresh_background_persists_and_reloads_local_background():
    driver = RGBCamera(overrides={"background_capture_on_init": False})
    cropped_image = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
    mask = np.array([[True, False, True], [False, True, True]])
    driver._capture_processed_frame = lambda **kwargs: (None, {
        "cropped_img": cropped_image,
        "mask": mask,
        "cx": 1,
        "cy": 0,
        "radius": 2,
    })

    dataset = driver.refresh_background()

    assert driver.bkg == str(driver.path / "RGBCamera" / "background.npz")
    assert driver.config["background"] == driver.bkg
    assert (driver.path / "RGBCamera" / "background.npz").is_file()
    np.testing.assert_array_equal(
        dataset["background_rgb"], np.where(mask[..., None], cropped_image, 0)[..., ::-1]
    )
    np.testing.assert_array_equal(dataset["background_mask"], mask)
    loaded = driver._load_background()
    np.testing.assert_array_equal(
        loaded["background"], np.where(mask[..., None], cropped_image, 0)
    )
    np.testing.assert_array_equal(loaded["mask"], mask)
    assert loaded["meta"] == {"cx": 1, "cy": 0, "radius": 2}


def test_rgb_camera_loads_tiled_background_and_updates_locator():
    driver = RGBCamera(overrides={"background_capture_on_init": False})
    driver.bkg = "tiled-background-id"
    background = np.ones((2, 2, 3), dtype=np.uint8)
    mask = np.array([[True, False], [False, True]])

    class Array:
        def __init__(self, array):
            self.array = array

        def __getitem__(self, key):
            assert key == ()
            return self.array

    class Entry(dict):
        metadata = {"attrs": {"located_center": [1, 1], "mask_radius": 1}}

    entry = Entry(background_rgb=Array(background[..., ::-1]), background_mask=Array(mask))
    driver.data = SimpleNamespace(tiled_client={"run_documents": {"tiled-background-id": entry}})

    loaded = driver._load_background()

    np.testing.assert_array_equal(loaded["background"], background)
    np.testing.assert_array_equal(loaded["mask"], mask)
    driver.post_tiled_finalize({"task_name": "refresh_background"}, "new-tiled-id")
    assert driver.bkg == "new-tiled-id"
    assert driver.config["background"] == "new-tiled-id"


def test_background_subtraction_handles_an_unchanged_frame():
    driver = RGBCamera(overrides={"background_capture_on_init": False})
    image = np.zeros((20, 20, 3), dtype=np.uint8)

    result = driver._process_image_with_background(
        image,
        image.copy(),
        roi_mask=np.ones((20, 20), dtype=bool),
    )

    assert result["changed_pixel_count"] == 0
    assert result["foreground_detected"] is False
    assert result["avg_rgb"] == {"R": 0.0, "G": 0.0, "B": 0.0}


def test_background_subtraction_uses_sample_cell_mask_without_circle_metadata():
    sample_cell = ScrewCapVial(
        row_crop=[0, 10], col_crop=[0, 10], cap_height=2
    )
    driver = RGBCamera(
        overrides={
            "background_capture_on_init": False,
            "background_threshold": 1,
        },
        sample_cell=sample_cell,
    )
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    image[2:] = [30, 20, 10]
    processed = sample_cell.extract_sample_image(image, color_order="BGR")
    processed["avg_rgb"] = sample_cell.rgb_values(
        processed["cropped_img"], processed["mask"], color_order="BGR"
    )
    for key in ("cx", "cy", "radius"):
        processed.pop(key)

    driver._capture_processed_frame = lambda **kwargs: (image, processed)
    driver.bkg = "sample-cell-agnostic-background"
    driver._load_background = lambda: {
        "background": np.zeros_like(image),
        "mask": processed["mask"].copy(),
        "meta": {"geometry": "cylindrical_vial"},
    }

    dataset = driver.capture_rgb(subtract_background=True)

    np.testing.assert_array_equal(dataset["mask"], processed["mask"])
    assert dataset["avg_rgb"].values.tolist() == [10.0, 20.0, 30.0]
    assert dataset.attrs["sample_cell"] == "ScrewCapVial"
    assert dataset.attrs["sample_geometry"] == "cylindrical_vial"
    assert dataset.attrs["body_bbox"] == [0, 2, 10, 10]
    assert json.loads(dataset.attrs["sample_geometry_metadata"])["cap_height"] == 2
    assert "located_center" not in dataset.attrs
    assert "mask_radius" not in dataset.attrs


def test_capture_processed_frame_reopens_camera_and_uses_latest_warmup_frame(monkeypatch):
    driver = object.__new__(RGBCamera)
    driver.config = {
        "camera_warmup_delay": 1.0,
    }
    driver.sample_cell = NeutronSampleCell()
    resets = []
    events = []
    frames = ["stale-first", "fresh-first", "stale-second", "fresh-second"]
    driver._reset_camera = lambda: resets.append("reset")
    clock = iter([0.0, 0.5, 1.0, 2.0, 2.5, 3.0])
    monkeypatch.setattr("AFL.automation.vision.RGBCamera.time.monotonic", lambda: next(clock))

    def collect_image(**kwargs):
        events.append(("capture", None))
        return True, frames.pop(0)

    def process_image(image):
        events.append(("process", image))
        return {"image": image}

    driver._collect_image = collect_image
    driver._process_image = process_image
    driver.log_info = lambda message: None
    driver.log_debug = lambda message: None

    _, first = driver._capture_processed_frame()
    _, second = driver._capture_processed_frame()

    assert resets == ["reset", "reset"]
    assert first["image"] == "fresh-first"
    assert second["image"] == "fresh-second"
    assert events == [
        ("capture", None),
        ("capture", None),
        ("process", "fresh-first"),
        ("capture", None),
        ("capture", None),
        ("process", "fresh-second"),
    ]


def test_plotting_saves_raw_frame_with_matching_timestamp(monkeypatch, tmp_path):
    driver = object.__new__(RGBCamera)
    driver.config = {
        "save_path": str(tmp_path),
        "subtract_background": False,
        "show_background_pipeline": False,
        "background_threshold": 25,
    }
    driver.bkg = None
    image = np.zeros((4, 5, 3), dtype=np.uint8)
    processed = {
        "cropped_img": image,
        "mask": np.ones((4, 5), dtype=bool),
        "avg_rgb": {"R": 0.0, "G": 0.0, "B": 0.0},
    }
    driver._capture_processed_frame = lambda **kwargs: (image, processed)
    driver._log_rgb_measurement = lambda *args, **kwargs: None
    driver._build_dataset = lambda **kwargs: "dataset"
    driver.log_info = lambda message: None
    driver.log_warning = lambda message: None

    saved = {}

    class FakeCV2:
        @staticmethod
        def imwrite(path, frame):
            saved["raw_path"] = path
            saved["raw_frame"] = frame
            return True

    class FakeSampleCell:
        @staticmethod
        def save_geometry_plot(image, processed, **kwargs):
            saved["plot_filename"] = kwargs["filename"]
            return tmp_path / kwargs["filename"]

    driver.sample_cell = FakeSampleCell()
    monkeypatch.setattr("AFL.automation.vision.RGBCamera.lazy.load", lambda *args, **kwargs: FakeCV2)

    assert driver.capture_rgb(plotting=True) == "dataset"
    assert saved["raw_frame"] is image
    raw_timestamp = pathlib.Path(saved["raw_path"]).name.removesuffix("-rgb-raw.png")
    plot_timestamp = saved["plot_filename"].removesuffix("-rgb-capture.png")
    assert raw_timestamp == plot_timestamp
