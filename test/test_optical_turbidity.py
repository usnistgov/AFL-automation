import numpy as np
import pytest
from unittest.mock import patch


xr = pytest.importorskip("xarray")


class _DummyCamera:
    def __init__(self, image):
        self._image = image

    def camera_reset(self):
        return None

    def collect(self, **kwargs):
        return True, self._image


def test_optical_turbidity_set_empty_returns_dataset(tmp_path):
    from AFL.automation.instrument.OpticalTurbidity import OpticalTurbidity

    rgb_image = np.zeros((4, 4, 3), dtype=np.uint8)
    rgb_image[..., 0] = 25
    rgb_image[..., 1] = 50
    rgb_image[..., 2] = 75

    with patch('AFL.automation.APIServer.Driver.pathlib.Path.home', return_value=tmp_path):
        driver = OpticalTurbidity(
            camera=_DummyCamera(rgb_image),
            overrides={
                'camera_interface': 'http',
                'row_crop': [1, 3],
                'col_crop': [1, 3],
            },
        )

    driver.data = {'sample_uuid': 'empty-sample-uuid'}

    dataset = driver.measure(set_empty=True, name='empty-reference')

    assert isinstance(dataset, xr.Dataset)
    assert dataset.attrs['name'] == 'empty-reference'
    assert dataset.attrs['turbidity_metric'] == 1.0
    assert dataset.attrs['empty_uuid'] == 'empty-sample-uuid'
    assert dataset.attrs['empty_available'] is True
    assert dataset.attrs['is_empty_reference'] is True
    assert dataset.attrs['located_center'] == [0, 0]
    assert float(dataset['turbidity'].item()) == 1.0
    assert set(dataset.data_vars) == {'turbidity', 'img', 'img_MT', 'mask'}
    np.testing.assert_array_equal(dataset['img'].values, driver.empty_img)
    np.testing.assert_array_equal(dataset['img_MT'].values, driver.empty_img)
    np.testing.assert_array_equal(dataset['mask'].values, np.ones_like(driver.empty_img, dtype=bool))
