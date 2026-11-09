import pytest

from AFL.automation.manipulate.ufactory_xarm.labware import Vial
from AFL.automation.manipulate.ufactory_xarm.ufactory import xArmManipulator


class BioSDK:
    connected = True

    def __init__(self):
        self.calls = []
        self.force_result = 0
        self.speed_result = 0

    def set_simulation_robot(self, simulation):
        return 0

    def motion_enable(self, enable):
        return 0

    def set_mode(self, mode):
        return 0

    def set_state(self, state):
        return 0

    def set_bio_gripper_enable(self, enabled):
        self.calls.append(("enable", enabled))
        return 0

    def set_bio_gripper_speed(self, speed):
        self.calls.append(("speed", speed))
        return self.speed_result

    def set_bio_gripper_force(self, force):
        self.calls.append(("force", force))
        return self.force_result

    def open_bio_gripper(self, **kwargs):
        self.calls.append(("open", kwargs))
        return 0

    def close_bio_gripper(self, **kwargs):
        self.calls.append(("close", kwargs))
        return 0


def test_bio_connect_uses_bio_enable_and_configured_settings():
    sdk = BioSDK()

    xArmManipulator(
        simulation=False, sdk=sdk, gripper_type="bio", gripper_force=30, gripper_speed=1500,
    ).connect()

    assert sdk.calls == [("enable", True), ("speed", 1500), ("force", 30)]


def test_bio_pick_settings_are_checked_and_passed_to_full_open_close_commands():
    sdk = BioSDK()
    arm = xArmManipulator(
        simulation=False, sdk=sdk, gripper_type="bio", gripper_force=30, gripper_speed=1500,
    )

    arm._set_gripper(opened=True, labware=Vial("vial"), force=20, speed=1000)
    arm._set_gripper(opened=False, labware=Vial("vial"), force=20, speed=1000)
    arm._set_gripper(opened=True, labware=Vial("vial"))

    assert sdk.calls == [
        ("speed", 1000), ("force", 20), ("open", {"wait": True, "speed": 1000, "force": 20}),
        ("speed", 1000), ("force", 20), ("close", {"wait": True, "speed": 1000, "force": 20}),
        ("speed", 1500), ("force", 30), ("open", {"wait": True, "speed": 1500, "force": 30}),
    ]
    assert (arm.gripper_force, arm.gripper_speed) == (30, 1500)


@pytest.mark.parametrize("setting", ["force", "speed"])
def test_bio_setter_error_prevents_open_close_command(setting):
    sdk = BioSDK()
    setattr(sdk, f"{setting}_result", 12)
    arm = xArmManipulator(simulation=False, sdk=sdk, gripper_type="bio")

    with pytest.raises(RuntimeError, match=f"BIO gripper {setting}.*SDK code 12"):
        arm._set_gripper(opened=False, labware=Vial("vial"), force=20, speed=1000)

    assert not any(call[0] in ("open", "close") for call in sdk.calls)
    assert arm.status()["commands_stopped"]


def test_bio_null_force_does_not_send_force_setter_to_older_hardware():
    sdk = BioSDK()
    arm = xArmManipulator(simulation=False, sdk=sdk, gripper_type="bio").connect()

    arm._set_gripper(opened=False, labware=Vial("vial"))

    assert not any(call[0] == "force" for call in sdk.calls)
    assert sdk.calls[-1] == ("close", {"wait": True, "speed": 2000})


def test_bio_simulation_records_full_actions_without_hardware_commands():
    sdk = BioSDK()
    arm = xArmManipulator(simulation=True, sdk=sdk, gripper_type="bio")

    arm._set_gripper(opened=False, labware=Vial("vial"), force=20, speed=1000)

    assert sdk.calls == []
    assert arm.command_log[-1]["position"] is None
    assert arm.command_log[-1]["force"] == 20
    assert arm.command_log[-1]["speed"] == 1000


@pytest.mark.parametrize("options", [{"gripper_force": 9}, {"gripper_force": 101}, {"gripper_speed": 4001}])
def test_bio_invalid_defaults_fail_before_connect(options):
    sdk = BioSDK()

    with pytest.raises(ValueError, match="gripper"):
        xArmManipulator(sdk=sdk, gripper_type="bio", **options)

    assert sdk.calls == []
