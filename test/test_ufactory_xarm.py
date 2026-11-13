from AFL.automation.manipulate.ufactory_xarm.ufactory import xArmManipulator


class FakeXArmSDK:
    connected = True

    def __init__(self, *, on_zero=0, enabled=0, error=0, sci=1, position=0):
        self.status = {
            "pos": position,
            "status": 0,
            "error": error,
            "is_enabled": enabled,
            "on_zero": on_zero,
            "sci": sci,
            "sco": [0, 0],
        }
        self.rail_calls = []

    def set_simulation_robot(self, simulation):
        return 0

    def motion_enable(self, enable):
        return 0

    def set_mode(self, mode):
        return 0

    def set_state(self, state):
        return 0

    def set_gripper_enable(self, enabled):
        return 0

    def get_linear_motor_registers(self):
        self.rail_calls.append(("status",))
        return 0, dict(self.status)

    def clean_linear_motor_error(self):
        self.rail_calls.append(("clear_error",))
        self.status["error"] = 0
        return 0

    def set_linear_motor_back_origin(self, **kwargs):
        self.rail_calls.append(("home", kwargs))
        self.status.update(pos=0, on_zero=1, is_enabled=0)
        return 0

    def set_linear_motor_enable(self, enabled):
        self.rail_calls.append(("enable", enabled))
        self.status["is_enabled"] = int(enabled)
        return 0

    def set_linear_motor_speed(self, speed):
        self.rail_calls.append(("speed", speed))
        return 0


def test_connect_does_not_touch_rail_unless_configured():
    sdk = FakeXArmSDK()

    xArmManipulator(simulation=False, sdk=sdk).connect()

    assert sdk.rail_calls == []


def test_connect_initializes_unhomed_configured_rail():
    sdk = FakeXArmSDK(on_zero=0, enabled=0, position=123)

    arm = xArmManipulator(
        simulation=False,
        initialize_rail=True,
        rail_speed_mm_s=75,
        sdk=sdk,
    ).connect()

    assert sdk.rail_calls == [
        ("status",),
        ("home", {"wait": True, "auto_enable": False}),
        ("status",),
        ("enable", True),
        ("speed", 75),
    ]
    assert arm._rail_position_mm == 0


def test_connect_uses_actual_position_without_rehoming_initialized_rail():
    sdk = FakeXArmSDK(on_zero=1, enabled=1, position=350)

    arm = xArmManipulator(
        simulation=False,
        initialize_rail=True,
        rail_speed_mm_s=None,
        sdk=sdk,
    ).connect()

    assert sdk.rail_calls == [("status",)]
    assert arm._rail_position_mm == 350


def test_connect_clears_rail_fault_before_homing():
    sdk = FakeXArmSDK(on_zero=0, error=13)

    xArmManipulator(
        simulation=False,
        initialize_rail=True,
        rail_speed_mm_s=None,
        sdk=sdk,
    ).connect()

    assert sdk.rail_calls[:3] == [("status",), ("clear_error",), ("status",)]
