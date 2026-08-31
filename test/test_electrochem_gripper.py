import importlib
import logging
import sys
import types

import pytest


caproto_module = types.ModuleType("caproto")
caproto_server_module = types.ModuleType("caproto.server")
units_module = types.ModuleType("AFL.automation.shared.units")


class _FakePVProperty:
    def scan(self, period=1.0):
        def decorator(func):
            return func

        return decorator


class _FakePVGroup:
    pass


def _fake_pvproperty(*args, **kwargs):
    return _FakePVProperty()


def _fake_run(*args, **kwargs):
    return None


caproto_server_module.PVGroup = _FakePVGroup
caproto_server_module.pvproperty = _fake_pvproperty
caproto_server_module.run = _fake_run
caproto_module.server = caproto_server_module

sys.modules.setdefault("caproto", caproto_module)
sys.modules.setdefault("caproto.server", caproto_server_module)
units_module.has_units = lambda value: False
units_module.units = object()
sys.modules.setdefault("AFL.automation.shared.units", units_module)


electrochem_gripper_module = importlib.import_module("AFL.automation.manipulate.ElectrochemGripper")
ElectrochemGripper = electrochem_gripper_module.ElectrochemGripper


class FakeServo:
    DEFAULTS = {
        "channel": 8,
        "address": 0x40,
        "bus": 1,
        "min_angle": 0,
        "max_angle": 90,
        "open_angle": 0,
        "close_angle": 90,
        "pulse_min": 700,
        "pulse_max": 2400,
        "channels": 16,
        "default_speed": 90.0,
        "register_cleanup": True,
        "name": None,
        "log_level": logging.INFO,
    }

    def __init__(self, **kwargs):
        config = {**self.DEFAULTS, **kwargs}
        self.channel = config["channel"]
        self.address = config["address"]
        self.bus = config["bus"]
        self.min_angle = config["min_angle"]
        self.max_angle = config["max_angle"]
        self.open_angle = config["open_angle"]
        self.close_angle = config["close_angle"]
        self.pulse_min = config["pulse_min"]
        self.pulse_max = config["pulse_max"]
        self.channels = config["channels"]
        self.default_speed = config["default_speed"]
        self.logger = logging.getLogger(config["name"] or self.__class__.__name__)
        self.logger.setLevel(config["log_level"])
        self.app = None
        self.data = None
        self.angle = None
        self.state = "unknown"
        self.open_calls = []
        self.close_calls = []
        self.set_angle_calls = []

    def set_angle(self, angle, speed=0.0):
        applied_angle = max(self.min_angle, min(self.max_angle, angle))
        self.set_angle_calls.append({"requested_angle": angle, "applied_angle": applied_angle, "speed": speed})
        self.angle = applied_angle
        self.state = self._state_from_angle(applied_angle)

    def open(self, speed=None):
        resolved_speed = self.default_speed if speed is None else speed
        self.open_calls.append(resolved_speed)
        self.set_angle(self.open_angle, speed=resolved_speed)

    def close(self, speed=None):
        resolved_speed = self.default_speed if speed is None else speed
        self.close_calls.append(resolved_speed)
        self.set_angle(self.close_angle, speed=resolved_speed)

    def status(self):
        return {
            "state": self.state,
            "angle": self.angle,
            "channel": self.channel,
            "address": self.address,
            "bus": self.bus,
            "min_angle": self.min_angle,
            "max_angle": self.max_angle,
            "open_angle": self.open_angle,
            "close_angle": self.close_angle,
        }

    def _state_from_angle(self, angle):
        if angle == self.open_angle:
            return "open"
        if angle == self.close_angle:
            return "closed"
        return "partial"


@pytest.fixture
def driver_factory(monkeypatch, tmp_path):
    monkeypatch.setattr(electrochem_gripper_module, "ServoMotor", FakeServo)

    def _make(*, servo=None, overrides=None):
        if servo is None:
            servo = FakeServo()
        return ElectrochemGripper(
            servo=servo,
            overrides=overrides,
            afl_home=tmp_path,
        )

    return _make


def test_auto_instantiates_servo_from_config(driver_factory):
    servo = FakeServo(open_angle=7, close_angle=61)
    driver = driver_factory(servo=servo, overrides={"servo_speed": 33.0})

    assert isinstance(driver.servo, FakeServo)
    assert driver.servo.open_angle == 7
    assert driver.servo.close_angle == 61
    assert driver.config["servo"]["open_angle"] == 7
    assert driver.config["servo"]["close_angle"] == 61
    assert driver.config["servo_speed"] == 33.0


def test_injected_servo_receives_app_and_data(driver_factory):
    servo = FakeServo(register_cleanup=False)
    driver = driver_factory(servo=servo)
    app = object()
    data = object()

    driver.app = app
    driver.data = data

    assert driver.servo is servo
    assert servo.app is app
    assert servo.data is data


def test_open_close_and_set_angle_use_expected_speed(driver_factory):
    driver = driver_factory(overrides={"servo_speed": 42.0})

    open_status = driver.open()
    close_status = driver.close(speed=21.0)
    angle_status = driver.set_angle(33)

    assert driver.connected is True
    assert driver.servo.open_calls == [42.0]
    assert driver.servo.close_calls == [21.0]
    assert driver.servo.set_angle_calls[-1] == {
        "requested_angle": 33,
        "applied_angle": 33,
        "speed": 42.0,
    }
    assert open_status["servo"]["state"] == "open"
    assert close_status["servo"]["state"] == "closed"
    assert angle_status["servo"]["angle"] == 33
    assert angle_status["last_action"]["action"] == "set_angle"


def test_set_default_speed_updates_config_and_future_moves(driver_factory):
    driver = driver_factory(overrides={"servo_speed": 42.0})

    result = driver.set_default_speed(12.5)
    open_status = driver.open()
    angle_status = driver.set_angle(18)

    assert driver.config["servo_speed"] == 12.5
    assert driver.config["servo"]["default_speed"] == 12.5
    assert driver.servo.default_speed == 12.5
    assert result["last_action"] == {"action": "set_default_speed", "speed": 12.5}
    assert driver.servo.open_calls == [12.5]
    assert driver.servo.set_angle_calls[-1]["speed"] == 12.5
    assert open_status["last_action"] == {"action": "open", "speed": 12.5}
    assert angle_status["last_action"]["speed"] == 12.5


def test_set_default_speed_rejects_negative_values(driver_factory):
    driver = driver_factory()

    with pytest.raises(ValueError, match="non-negative"):
        driver.set_default_speed(-0.1)


def test_home_can_skip_opening(driver_factory):
    driver = driver_factory(overrides={"home_open": False})

    result = driver.home()

    assert driver.servo.open_calls == []
    assert result["last_action"] == {"action": "home", "open_gripper": False}


def test_set_open_and_close_angle_persist_to_config(driver_factory):
    driver = driver_factory(servo=FakeServo(open_angle=10, close_angle=70))

    driver.set_angle(55, speed=10.0)
    driver.set_open_angle(12)
    result = driver.set_close_angle(55)

    assert driver.config["servo"]["open_angle"] == 12
    assert driver.config["servo"]["close_angle"] == 55
    assert driver.servo.open_angle == 12
    assert driver.servo.close_angle == 55
    assert driver.servo.state == "closed"
    assert result["last_action"] == {"action": "set_close_angle", "angle": 55}


def test_angle_commands_reject_values_outside_zero_to_180(driver_factory):
    driver = driver_factory()

    with pytest.raises(ValueError, match="between 0 and 180"):
        driver.set_angle(181)

    with pytest.raises(ValueError, match="between 0 and 180"):
        driver.set_open_angle(-1)

    with pytest.raises(ValueError, match="between 0 and 180"):
        driver.set_close_angle(999)


def test_status_shape_and_connect(driver_factory):
    driver = driver_factory()

    assert driver.connect() == "connected"

    status = driver.status()

    assert status["connected"] is True
    assert status["last_action"] == {"action": "connect"}
    assert status["open_angle"] == driver.servo.open_angle
    assert status["close_angle"] == driver.servo.close_angle
    assert status["servo"]["channel"] == driver.servo.channel


def test_quickbar_metadata_exposes_gripper_controls(driver_factory):
    driver = driver_factory()
    quickbar = driver.quickbar.function_info

    assert quickbar["connect"]["qb"] == {"button_text": "Connect"}
    assert quickbar["home"]["qb"] == {"button_text": "Home"}
    assert quickbar["open"]["qb"] == {"button_text": "Open"}
    assert quickbar["close"]["qb"] == {"button_text": "Close"}
    assert quickbar["set_default_speed"]["qb"]["params"] == {
        "speed": {"label": "Default Speed", "type": "float", "default": 90.0},
    }
    assert quickbar["set_angle"]["qb"]["params"] == {
        "angle": {"label": "Angle (0-180)", "type": "int", "default": 90},
    }
    assert quickbar["set_open_angle"]["qb"]["params"]["angle"] == {
        "label": "Open Angle (0-180)",
        "type": "int",
        "default": 0,
    }
    assert quickbar["set_close_angle"]["qb"]["params"]["angle"] == {
        "label": "Close Angle (0-180)",
        "type": "int",
        "default": 90,
    }
    assert quickbar["status"]["qb"] == {"button_text": "Status"}


def test_launcher_metadata_matches_driver_module():
    assert electrochem_gripper_module._DEFAULT_PORT == 5058
    assert electrochem_gripper_module._DEFAULT_CUSTOM_CONFIG["_classname"] == (
        "AFL.automation.manipulate.ElectrochemGripper.ElectrochemGripper"
    )
    assert electrochem_gripper_module._DEFAULT_CUSTOM_CONFIG["_args"][0] == {
        "_classname": "AFL.automation.shared.motors.ServoMotor",
        **electrochem_gripper_module._DEFAULT_SERVO_CONFIG,
    }
    assert electrochem_gripper_module._DEFAULT_CUSTOM_CONFIG["overrides"] == {
        "servo_speed": 90.0,
        "home_open": True,
        "log_level": logging.INFO,
    }


def test_constructor_requires_servo_instance(tmp_path):
    with pytest.raises(TypeError, match="servo must be an instance"):
        ElectrochemGripper(
            servo="not-a-servo",
            afl_home=tmp_path,
        )
