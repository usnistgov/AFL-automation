import numpy as np

from AFL.automation.vision.RGBCamera import RGBCamera


def test_build_dataset_includes_imshow_ready_rgb_image():
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

    np.testing.assert_array_equal(dataset["img_bgr"], image_bgr)
    np.testing.assert_array_equal(
        dataset["img_rgb"],
        np.array([[[30, 20, 10], [60, 50, 40]]], dtype=np.uint8),
    )
    assert dataset["img_rgb"].dims == ("height", "width", "rgb_channel")
    assert dataset["img_rgb"].coords["rgb_channel"].values.tolist() == ["R", "G", "B"]
