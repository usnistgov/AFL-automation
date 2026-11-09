import json

import pytest

from AFL.automation.manipulate.ufactory_xarm.labware import Vial
from AFL.automation.manipulate.ufactory_xarm.stations import OT2, VialHandling
from AFL.automation.manipulate.ufactory_xarm.ufactory import xArmManipulator
from AFL.automation.manipulate.ufactory_xarm.xArmHTTPDriver import xArmHTTPDriver


class GripperSDK:
    connected = True

    def __init__(self):
        self.calls = []
        self.gripper_result = 0

    def set_simulation_robot(self, simulation):
        self.calls.append(("simulation", simulation))
        return 0

    def motion_enable(self, enable):
        self.calls.append(("motion_enable", enable))
        return 0

    def set_mode(self, mode):
        return 0

    def set_state(self, state):
        return 0

    def set_gripper_enable(self, enabled):
        self.calls.append(("enable_gripper", enabled))
        return 0

    def set_gripper_speed(self, speed):
        self.calls.append(("gripper_speed", speed))
        return 0

    def set_gripper_position(self, position, **kwargs):
        self.calls.append(("xarm", position, kwargs))
        return self.gripper_result

    def set_gripper_g2_position(self, position, **kwargs):
        self.calls.append(("xarm_g2", position, kwargs))
        return self.gripper_result


def workcell(tmp_path, gripper):
    path = tmp_path / "workcell.yaml"
    path.write_text(json.dumps({"gripper": gripper}))
    return path


@pytest.mark.parametrize("gripper", [{}, {"type": None}, {"type": "unknown"}, {"type": []}, None])
def test_missing_or_unknown_gripper_fails_before_connect(tmp_path, gripper):
    sdk = GripperSDK()

    with pytest.raises(ValueError, match="gripper"):
        xArmManipulator(workcell_config=workcell(tmp_path, gripper), sdk=sdk)

    assert sdk.calls == []


def test_startup_can_supply_required_model_and_override_yaml_settings(tmp_path):
    arm = xArmManipulator(
        workcell_config=workcell(tmp_path, {"speed": 70, "force": 30}),
        gripper_type="xarm_g2", gripper_force=20, gripper_speed=40,
    )

    assert arm.status()["gripper"] == {
        "type": "xarm_g2", "force": 20, "speed": 40, "speed_units": "mm/s",
    }


def test_g2_uses_mm_and_restores_configured_defaults_after_override(tmp_path):
    sdk = GripperSDK()
    arm = xArmManipulator(
        simulation=False, sdk=sdk,
        workcell_config=workcell(tmp_path, {"type": "xarm_g2", "force": 30, "speed": 70}),
    ).connect()

    arm._set_gripper(opened=False, labware=Vial("vial"), grasp=9, force=20, speed=40)
    arm._set_gripper(opened=True, labware=Vial("vial"), grasp=9)

    assert sdk.calls[-2:] == [
        ("xarm_g2", 9, {"wait": True, "force": 20, "speed": 40}),
        ("xarm_g2", 14, {"wait": True, "force": 30, "speed": 70}),
    ]
    assert not any(call[0] == "gripper_speed" for call in sdk.calls)
    assert (arm.gripper_force, arm.gripper_speed) == (30, 70)


def test_original_gripper_keeps_pulse_calibration_and_per_command_speed(tmp_path):
    sdk = GripperSDK()
    arm = xArmManipulator(
        simulation=False, sdk=sdk,
        workcell_config=workcell(tmp_path, {
            "type": "xarm", "span_mm": 84.4, "span_sdk": 840, "speed": 1000,
        }),
    ).connect()

    arm._set_gripper(opened=False, labware=Vial("vial"), grasp=8.44, speed=500)
    arm._set_gripper(opened=False, labware=Vial("vial"), grasp=8.44)

    assert sdk.calls[-2:] == [
        ("xarm", 84, {"wait": True, "speed": 500}),
        ("xarm", 84, {"wait": True, "speed": 1000}),
    ]


@pytest.mark.parametrize("model,setting,value", [
    ("xarm", "force", 20),
    ("xarm", "speed", 0),
    ("xarm", "speed", 1.5),
    ("xarm_g2", "force", 0),
    ("xarm_g2", "force", 101),
    ("xarm_g2", "force", 20.5),
    ("xarm_g2", "speed", 14),
    ("xarm_g2", "speed", 226),
    ("xarm_g2", "speed", float("inf")),
    ("xarm_g2", "force", float("nan")),
    ("xarm_g2", "force", True),
    ("xarm_g2", "speed", "50"),
])
def test_invalid_startup_settings_fail_before_any_sdk_commands(tmp_path, model, setting, value):
    sdk = GripperSDK()

    with pytest.raises(ValueError, match=f"gripper.*{setting}|force control"):
        xArmManipulator(
            sdk=sdk, workcell_config=workcell(tmp_path, {"type": model, setting: value}),
        )

    assert sdk.calls == []


def test_g2_null_settings_select_model_defaults(tmp_path):
    arm = xArmManipulator(workcell_config=workcell(tmp_path, {
        "type": "xarm_g2", "speed": None, "force": None,
    }))

    assert (arm.gripper_force, arm.gripper_speed) == (50, 100)


def test_model_change_does_not_reuse_original_pulse_calibration():
    arm = xArmManipulator(gripper_type="xarm_g2")

    assert arm.gripper_position_for_gap(84) == 84


def test_g2_span_cannot_exceed_sdk_range(tmp_path):
    with pytest.raises(ValueError, match="at most 84"):
        xArmManipulator(workcell_config=workcell(tmp_path, {"type": "xarm_g2", "span_mm": 85}))


def prepare_motion(monkeypatch, arm):
    # Exercise the real station pick and gripper code without driving the arm.
    def enter(station, *, approach=None, location=None):
        arm._current_station = station.name
        arm._current_approach = approach
        arm._last_tcp_pose = (.3, .2, .5, 0., 0., 0.)
        return arm._last_tcp_pose

    def move(target, station):
        arm._last_tcp_pose = tuple(target)

    monkeypatch.setattr(arm, "_enter", enter)
    monkeypatch.setattr(arm, "_move_pose", move)


@pytest.fixture(params=["OT2", "VialHandling"])
def station_and_location(request, monkeypatch):
    if request.param == "OT2":
        station = OT2()
        # Supply a deck obstacle height without loading an Opentrons protocol.
        monkeypatch.setattr(station, "loaded_labware_max_z", lambda: .25)
        return station, {"link_base_mm": [100, 200, 50]}
    return VialHandling(), "top"


def test_pick_forwards_overrides_to_both_gripper_actions(tmp_path, monkeypatch, station_and_location):
    station, location = station_and_location
    sdk = GripperSDK()
    arm = xArmManipulator(
        simulation=False, sdk=sdk, stations=[station],
        workcell_config=workcell(tmp_path, {"type": "xarm_g2", "force": 30, "speed": 70}),
    )
    prepare_motion(monkeypatch, arm)

    result = arm.station_operation(
        station.name, "pick", labware=Vial("vial"), location=location,
        approach="vertical", grasp=9, force=20, speed=40,
    )

    assert result["success"], result
    assert sdk.calls == [
        ("xarm_g2", 14, {"wait": True, "force": 20, "speed": 40}),
        ("xarm_g2", 9, {"wait": True, "force": 20, "speed": 40}),
    ]
    assert (arm.gripper_force, arm.gripper_speed) == (30, 70)


@pytest.mark.parametrize("options", [{"force": 101}, {"speed": 14}])
def test_invalid_pick_settings_fail_before_arm_motion(tmp_path, monkeypatch, station_and_location, options):
    station, location = station_and_location
    sdk = GripperSDK()
    arm = xArmManipulator(
        simulation=False, sdk=sdk, stations=[station],
        workcell_config=workcell(tmp_path, {"type": "xarm_g2"}),
    )
    entries = []
    monkeypatch.setattr(arm, "_enter", lambda *args, **kwargs: entries.append(args))

    result = arm.station_operation(
        station.name, "pick", labware=Vial("vial"), location=location, **options,
    )

    assert result["success"] is False
    assert entries == sdk.calls == []


def test_simulated_gripper_records_settings_without_hardware_commands(tmp_path):
    sdk = GripperSDK()
    arm = xArmManipulator(
        simulation=True, sdk=sdk, workcell_config=workcell(tmp_path, {"type": "xarm_g2"}),
    )

    arm._set_gripper(opened=False, labware=Vial("vial"), force=20, speed=40)

    assert sdk.calls == []
    assert arm.command_log[-1]["force"] == 20
    assert arm.command_log[-1]["speed"] == 40
    assert arm.command_log[-1]["gripper_type"] == "xarm_g2"


def test_gripper_sdk_failure_preserves_command_lockout(tmp_path):
    sdk = GripperSDK()
    sdk.gripper_result = 12
    arm = xArmManipulator(
        simulation=False, sdk=sdk, workcell_config=workcell(tmp_path, {"type": "xarm_g2"}),
    )

    with pytest.raises(RuntimeError, match="SDK code 12"):
        arm._set_gripper(opened=False, labware=Vial("vial"))
    with pytest.raises(RuntimeError, match="commands are stopped"):
        arm._set_gripper(opened=True, labware=Vial("vial"))

    assert len(sdk.calls) == 1


@pytest.mark.parametrize("startup", [{}, {"gripper_force": 20, "gripper_speed": 40}])
@pytest.mark.parametrize("pick_options", [{}, {"force": 10, "speed": 25}, {"force": 10}, {"speed": 25}])
def test_http_driver_uses_yaml_or_startup_defaults_and_per_pick_values(
    tmp_path, monkeypatch, startup, pick_options,
):
    monkeypatch.setenv("AFL_HOME", str(tmp_path / "afl"))
    monkeypatch.setenv("AFL_FRESH_DRIVER_CONFIG", "1")
    sdk = GripperSDK()
    station = VialHandling()
    vial = Vial("vial")
    driver = xArmHTTPDriver(
        stations=[station], labware=[vial], sdk=sdk,
        overrides={
            "simulation": False,
            "workcell_config": str(workcell(tmp_path, {"type": "xarm_g2", "force": 30, "speed": 70})),
            **startup,
        },
    )
    prepare_motion(monkeypatch, driver.arm)
    sdk.calls.clear()

    result = driver.station_operation(
        station.name, "pick", labware=vial.name, location="top", approach="vertical",
        grasp="cap", **pick_options,
    )

    assert result["success"]
    expected = {
        "wait": True,
        "force": pick_options.get("force", startup.get("gripper_force", 30)),
        "speed": pick_options.get("speed", startup.get("gripper_speed", 70)),
    }
    assert [call[2] for call in sdk.calls] == [expected, expected]
    assert driver.arm.gripper_force == startup.get("gripper_force", 30)
    assert driver.arm.gripper_speed == startup.get("gripper_speed", 70)


def test_http_startup_model_overrides_workcell_model(tmp_path, monkeypatch):
    monkeypatch.setenv("AFL_HOME", str(tmp_path / "afl"))
    monkeypatch.setenv("AFL_FRESH_DRIVER_CONFIG", "1")
    driver = xArmHTTPDriver(
        stations=[], sdk=GripperSDK(), overrides={
            "simulation": True, "gripper_type": "xarm_g2", "gripper_force": 20, "gripper_speed": 40,
            "workcell_config": str(workcell(tmp_path, {"type": "xarm"})),
        },
    )

    assert driver.status()["gripper"] == {
        "type": "xarm_g2", "force": 20, "speed": 40, "speed_units": "mm/s",
    }
