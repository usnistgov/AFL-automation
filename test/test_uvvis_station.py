import math

import pytest
import yaml

from AFL.automation.manipulate.ufactory_xarm import UVVis
from AFL.automation.manipulate.ufactory_xarm.labware import Vial
from AFL.automation.manipulate.ufactory_xarm.stations import CONFIG_DIRECTORY, VialTurbidity
from AFL.automation.manipulate.ufactory_xarm.ufactory import xArmManipulator


class MotionSDK:
    connected = True

    def __init__(self, wrist_roll_deg=0.):
        self.entry_position = [100., 150., 300., wrist_roll_deg, 0., 0.]
        self.position = list(self.entry_position)
        self.joints = [0.] * 7
        self.targets = []

    def set_servo_angle(self, *, angle, **options):
        self.joints = list(angle)
        self.position = list(self.entry_position)
        return 0

    def get_servo_angle(self):
        return 0, list(self.joints)

    def set_position(self, *target, **options):
        self.targets.append(tuple(target))
        self.position = list(target)
        return 0

    def get_position(self):
        return 0, list(self.position)


def test_uvvis_defaults_are_separate_from_turbidity():
    uvvis = UVVis()
    turbidity = VialTurbidity()

    assert uvvis.name == "UVVis"
    assert uvvis.linear_rail_position == 600
    assert turbidity.name == "VialTurbidity"
    assert turbidity.linear_rail_position == 350
    assert uvvis.available_operations == turbidity.available_operations


@pytest.mark.parametrize("release", [False, True])
@pytest.mark.parametrize("use_labware_offset", [False, True])
@pytest.mark.parametrize("height_mm", [30., 50., 70.])
@pytest.mark.parametrize("wrist_roll_deg", [0., 180.])
def test_uvvis_uses_custom_geometry_and_retraces_placement(
    tmp_path, release, use_labware_offset, height_mm, wrist_roll_deg,
):
    config = yaml.safe_load((CONFIG_DIRECTORY / "uvvis.yaml").read_text())
    config["poses"]["vertical"]["top"] = [10, 20, 30, 40, 50, 60, 70]
    config["locations"]["measure"]["xyz"] = [450, 75, 200]
    config_path = tmp_path / "uvvis.yaml"
    config_path.write_text(yaml.safe_dump(config))
    station = UVVis(config_path=config_path)
    sdk = MotionSDK(wrist_roll_deg)
    arm = xArmManipulator(sdk=sdk, stations=[station], simulation=True)
    vial = Vial("test_vial", height_mm=height_mm)
    arm._capture_attachment(
        vial, (.1, .15, .3, math.radians(wrist_roll_deg), 0., 0.),
        (.1, .15, .3 - height_mm / 1000., 0., 0., 0.), grasp=9.,
    )

    placed = arm.station_operation(
        "UVVis", "place", tcp_offset_mm=[10, -5, 2],
        use_labware_offset=use_labware_offset,
    )

    assert placed["success"], placed
    assert placed["message"] == "UVVis placement completed"
    assert placed["phase"] == "at_target"
    assert arm._rail_position_mm == 600
    assert station.resolve_location("measure")[:3] == pytest.approx((.45, .075, .2))
    target_z = 202 + (height_mm if use_labware_offset else 0.)
    for target, expected in zip(sdk.targets, [(460, 150, 300), (460, 70, 300), (460, 70, target_z)]):
        assert target[:3] == pytest.approx(expected)
    assert len(sdk.targets) == 3

    if release:
        released = arm.release()
        assert released["success"], released
        assert released["phase"] == "released"
        assert arm.attached_labware is None
    else:
        assert arm.attached_labware is vial

    retreated = arm.retreat()

    assert retreated["success"], retreated
    assert retreated["station"] == "UVVis"
    assert retreated["phase"] == "at_base"
    assert arm._station_context is None
    assert len(sdk.targets) == 6
    for target, expected in zip(sdk.targets[3:], [(460, 70, 300), (460, 150, 300), (100, 150, 300)]):
        assert target[:3] == pytest.approx(expected)
