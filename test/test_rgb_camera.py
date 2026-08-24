import numpy as np
from types import SimpleNamespace

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


def test_capture_processed_frame_reopens_camera_for_each_acquisition():
    driver = object.__new__(RGBCamera)
    driver.config = {
        "px_crop": [0, 1],
        "py_crop": [0, 1],
        "hough_radii": 1,
        "camera_warmup_delay": 0,
    }
    resets = []
    frames = ["first", "second"]
    driver._reset_camera = lambda: resets.append("reset")
    driver._collect_image = lambda **kwargs: (True, frames.pop(0))
    driver._process_image = lambda image: {"image": image}
    driver.log_info = lambda message: None
    driver.log_debug = lambda message: None

    _, first = driver._capture_processed_frame()
    _, second = driver._capture_processed_frame()

    assert resets == ["reset", "reset"]
    assert first["image"] == "first"
    assert second["image"] == "second"
