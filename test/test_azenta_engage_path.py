from contextlib import nullcontext
import json
import math

import pytest
import yaml

from AFL.automation.manipulate.ufactory_xarm.labware import Vial
from AFL.automation.manipulate.ufactory_xarm.stations import (
    AzentaIntelliXCapS1, CONFIG_DIRECTORY,
)
from AFL.automation.manipulate.ufactory_xarm.ufactory import xArmManipulator


class MotionSDK:
    """Record commanded TCP segments and provide controller pose feedback."""

    connected = True

    def __init__(self):
        self.position = [500., 50., 300., 180., 0., 0.]
        self.joints = [0.] * 7
        self.segments = []
        self.commands = []
        self.fail_move = None

    def set_servo_angle(self, *, angle, **options):
        self.commands.append("joints")
        self.joints = list(angle)
        self.position = [500., 50., 300., 180., 0., 0.]
        return 0

    def get_servo_angle(self, **options):
        return 0, list(self.joints)

    def set_position(self, *target, **options):
        self.commands.append("TCP")
        self.segments.append((tuple(self.position), tuple(target), options))
        if len(self.segments) == self.fail_move:
            return 12
        self.position = list(target)
        return 0

    def get_position(self):
        return 0, list(self.position)


@pytest.fixture
def station_config():
    return yaml.safe_load((CONFIG_DIRECTORY / "azenta_intellixcap_s1.yaml").read_text())


def configured_station(tmp_path, station_config):
    path = tmp_path / "azenta.yaml"
    path.write_text(json.dumps(station_config))
    return AzentaIntelliXCapS1(config_path=path)


def make_arm(monkeypatch, station):
    sdk = MotionSDK()
    arm = xArmManipulator(sdk=sdk, stations=[station], simulation=True,
                          arm_speed_mm_s=20.)
    # Keep the real entry, SDK motion, feedback, and resumable retreat paths.
    # Collision-setting reports and the capper's dwell use no hardware here.
    monkeypatch.setattr(arm, "_temporary_collision_sensitivity", lambda _: nullcontext())
    monkeypatch.setattr("AFL.automation.manipulate.ufactory_xarm.stations.time.sleep",
                        lambda _: None)
    return arm, sdk


def assert_engage_segment(segment, *, distance_mm, angle_deg, withdrawing=False):
    start, end, options = segment
    delta = [end[i] - start[i] for i in range(3)]
    if withdrawing:
        delta = [-value for value in delta]
    assert math.dist(start[:3], end[:3]) == pytest.approx(distance_mm)
    assert end[1] == pytest.approx(start[1])
    assert math.degrees(math.atan2(delta[0], delta[2])) == pytest.approx(angle_deg)
    assert end[3:] == pytest.approx(start[3:])
    assert options == {"wait": True, "radius": -1, "motion_type": 0, "speed": 20.}


@pytest.mark.parametrize("distance,angle", [(45., 20.), (30., 0.), (60., 35.), (25., -20.)])
@pytest.mark.parametrize("immediate_retreat", [False, True])
def test_decap_approach_and_retreat_follow_configured_line(
    tmp_path, station_config, monkeypatch, distance, angle, immediate_retreat,
):
    station_config["engage_approach"] = {"distance_mm": distance, "angle_deg": angle}
    station = configured_station(tmp_path, station_config)
    arm, sdk = make_arm(monkeypatch, station)

    result = station.decap(arm, dwell_s=0., retreat=immediate_retreat)

    assert result["success"], result
    if not immediate_retreat:
        assert len(sdk.segments) == 2
        assert result["phase"] == "at_target"
        result = arm.retreat()
        assert result["success"], result
    assert result["phase"] == "at_base"
    assert len(sdk.segments) == 4
    assert sdk.segments[1][1][:3] == pytest.approx(station_config["locations"]["engage"]["xyz"])
    assert_engage_segment(sdk.segments[1], distance_mm=distance, angle_deg=angle)
    assert_engage_segment(sdk.segments[2], distance_mm=distance, angle_deg=angle,
                          withdrawing=True)
    assert sdk.segments[2][1] == pytest.approx(sdk.segments[1][0])
    # The taught joint entries still handle station travel, but the old
    # independently calibrated bottom XYZ is no longer a Cartesian waypoint.
    bottom = station_config["locations"]["bottom"]["xyz"]
    assert all(segment[1][:3] != tuple(bottom) for segment in sdk.segments)
    assert sdk.commands == ["joints", "joints", "TCP", "TCP", "TCP", "TCP", "joints"]
    assert arm._station_context is None


def test_final_path_does_not_require_an_independent_bottom_xyz(
    tmp_path, station_config, monkeypatch,
):
    del station_config["locations"]["bottom"]
    station = configured_station(tmp_path, station_config)
    arm, sdk = make_arm(monkeypatch, station)

    result = station.decap(arm, dwell_s=0., retreat=True)

    assert result["success"], result
    assert sdk.segments[1][1][:3] == pytest.approx(station_config["locations"]["engage"]["xyz"])
    assert_engage_segment(sdk.segments[1], distance_mm=45., angle_deg=20.)
    assert_engage_segment(sdk.segments[2], distance_mm=45., angle_deg=20., withdrawing=True)


def test_withdrawal_and_next_cap_use_measured_dwell_endpoint(monkeypatch):
    station = AzentaIntelliXCapS1()
    arm, sdk = make_arm(monkeypatch, station)

    def capper_displacement(_):
        sdk.position[:3] = [sdk.position[i] + shift for i, shift in enumerate((2., 3., -4.))]

    monkeypatch.setattr("AFL.automation.manipulate.ufactory_xarm.stations.time.sleep",
                        capper_displacement)
    result = station.decap(arm, dwell_s=0., retreat=False)
    assert result["success"], result
    measured_engage = tuple(sdk.position)
    assert measured_engage[:3] != sdk.segments[1][1][:3]
    assert arm.retreat()["success"]
    assert sdk.segments[2][0] == measured_engage
    assert_engage_segment(sdk.segments[2], distance_mm=45., angle_deg=20., withdrawing=True)

    monkeypatch.setattr("AFL.automation.manipulate.ufactory_xarm.stations.time.sleep",
                        lambda _: None)
    result = station.cap(arm, dwell_s=0., retreat=True)

    assert result["success"], result
    assert result["vial_capped"] is True
    assert station.has_cap is False
    assert sdk.segments[5][1] == pytest.approx(measured_engage)
    assert_engage_segment(sdk.segments[5], distance_mm=45., angle_deg=20.)
    assert_engage_segment(sdk.segments[6], distance_mm=45., angle_deg=20., withdrawing=True)


@pytest.mark.parametrize("add_height", [False, True])
def test_tcp_correction_translates_segment_without_changing_its_geometry(
    station_config, monkeypatch, add_height,
):
    station = AzentaIntelliXCapS1()
    arm, sdk = make_arm(monkeypatch, station)
    item = Vial("test_vial", height_mm=70.)

    result = station.decap(arm, labware=item, tcp_offset_mm=[5., -2., 3.],
                          use_labware_offset=add_height, dwell_s=0., retreat=True)

    assert result["success"], result
    engage = station_config["locations"]["engage"]["xyz"]
    expected = [engage[0] + 5., engage[1] - 2., engage[2] + 3. + (70. if add_height else 0.)]
    assert sdk.segments[1][1][:3] == pytest.approx(expected)
    assert_engage_segment(sdk.segments[1], distance_mm=45., angle_deg=20.)
    assert_engage_segment(sdk.segments[2], distance_mm=45., angle_deg=20., withdrawing=True)


@pytest.mark.parametrize("geometry,field", [
    (None, "engage_approach"),
    ({}, "distance_mm"),
    ({"distance_mm": 45.}, "angle_deg"),
    ({"distance_mm": 0., "angle_deg": 20.}, "distance_mm"),
    ({"distance_mm": -1., "angle_deg": 20.}, "distance_mm"),
    ({"distance_mm": float("inf"), "angle_deg": 20.}, "distance_mm"),
    ({"distance_mm": True, "angle_deg": 20.}, "distance_mm"),
    ({"distance_mm": "45", "angle_deg": 20.}, "distance_mm"),
    ({"distance_mm": 45., "angle_deg": float("nan")}, "angle_deg"),
    ({"distance_mm": 45., "angle_deg": True}, "angle_deg"),
    ({"distance_mm": 45., "angle_deg": 90.}, "angle_deg"),
    ({"distance_mm": 45., "angle_deg": -90.}, "angle_deg"),
])
def test_invalid_engage_geometry_is_rejected_at_load(tmp_path, station_config, geometry, field):
    station_config["engage_approach"] = geometry

    with pytest.raises(ValueError, match=field):
        configured_station(tmp_path, station_config)


def test_rejected_linear_engage_move_stops_without_joint_fallback(monkeypatch):
    station = AzentaIntelliXCapS1()
    arm, sdk = make_arm(monkeypatch, station)
    sdk.fail_move = 2

    result = station.decap(arm, dwell_s=0., retreat=True)

    assert result["success"] is False
    assert "SDK code 12" in result["message"]
    assert sdk.commands == ["joints", "joints", "TCP", "TCP"]
    assert sdk.segments[-1][2]["motion_type"] == 0
    assert station.has_cap is False
    assert station.post_dwell_tcp_pose is None
    assert arm._station_context is None
