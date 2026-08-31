from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.motors import ServoMotor


_DEFAULT_SERVO_CONFIG = {
    "channel": 4,
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


class ElectrochemGripper(Driver):
    """
    AFL driver for a Pi-hosted single-servo electrochem gripper.

    The driver wraps a single :class:`ServoMotor` helper and exposes a minimal
    control surface suitable for direct AFL server use on a Raspberry Pi.
    """

    defaults = {
        "servo": {},
        "servo_speed": 90.0,
        "home_open": True,
        "log_level": logging.INFO,
    }

    def __init__(
        self,
        servo: ServoMotor,
        overrides: Optional[Dict[str, Any]] = None,
        name: str = "ElectrochemGripper",
        afl_home: Optional[str] = None,
    ) -> None:
        self._app = None
        self._data = None
        self.servo = None

        defaults = self.gather_defaults()
        defaults["servo"] = dict(ServoMotor.DEFAULTS)
        Driver.__init__(self, name=name, defaults=defaults, overrides=overrides, afl_home=afl_home)

        if not isinstance(servo, ServoMotor):
            raise TypeError(
                f"servo must be an instance of {ServoMotor.__module__}.{ServoMotor.__name__}"
            )

        self.logger.setLevel(self.config["log_level"])
        self.servo = servo
        self.connected = False
        self.last_action: Optional[Dict[str, Any]] = None

        self._sync_servo_config_from_helper()
        if hasattr(self.servo, "app"):
            self.servo.app = self._app
        if hasattr(self.servo, "data"):
            self.servo.data = self._data

    @property
    def app(self):
        return self._app

    @app.setter
    def app(self, app):
        self._app = app
        servo = getattr(self, "servo", None)
        if app is not None and servo is not None:
            servo.app = app

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, data):
        self._data = data
        servo = getattr(self, "servo", None)
        if data is not None and servo is not None:
            servo.data = data

    @Driver.quickbar(qb={"button_text": "Connect"})
    @Driver.unqueued()
    def connect(self) -> str:
        """Mark the gripper ready for motion commands."""
        self.connected = True
        self.last_action = {"action": "connect"}
        self.log_info("ElectrochemGripper connected")
        return "connected"

    @Driver.quickbar(qb={"button_text": "Home"})
    @Driver.unqueued()
    def home(self, open_gripper: Optional[bool] = None) -> Dict[str, Any]:
        """Return the driver to its software home state."""
        self._ensure_connected()
        open_gripper = self.config["home_open"] if open_gripper is None else open_gripper
        if open_gripper:
            self.servo.open(speed=self._resolve_servo_speed(None))
        self.last_action = {"action": "home", "open_gripper": open_gripper}
        self.log_info("ElectrochemGripper homed")
        return self.status()

    @Driver.quickbar(qb={"button_text": "Open"})
    def open(self, speed: Optional[float] = None) -> Dict[str, Any]:
        """Open the gripper servo."""
        self._ensure_connected()
        resolved_speed = self._resolve_servo_speed(speed)
        self.servo.open(speed=resolved_speed)
        self.last_action = {"action": "open", "speed": resolved_speed}
        return self.status()

    @Driver.quickbar(qb={"button_text": "Close"})
    def close(self, speed: Optional[float] = None) -> Dict[str, Any]:
        """Close the gripper servo."""
        self._ensure_connected()
        resolved_speed = self._resolve_servo_speed(speed)
        self.servo.close(speed=resolved_speed)
        self.last_action = {"action": "close", "speed": resolved_speed}
        return self.status()

    @Driver.quickbar(
        qb={
            "button_text": "Set Default Speed",
            "params": {
                "speed": {
                    "label": "Default Speed",
                    "type": "float",
                    "default": 90.0,
                },
            },
        }
    )
    def set_default_speed(self, speed: float) -> Dict[str, Any]:
        """Persist the default motion speed used by gripper commands."""
        speed = self._validate_speed(speed)
        self.config["servo_speed"] = speed
        if hasattr(self.servo, "default_speed"):
            self.servo.default_speed = speed
        self._persist_servo_setting("default_speed", speed)
        self.last_action = {"action": "set_default_speed", "speed": speed}
        return self.status()

    @Driver.quickbar(
        qb={
            "button_text": "Set Angle",
            "params": {
                "angle": {
                    "label": "Angle (0-180)",
                    "type": "int",
                    "default": 90,
                },
            },
        }
    )
    def set_angle(self, angle: int, speed: Optional[float] = None) -> Dict[str, Any]:
        """Move the servo to an explicit angle."""
        self._ensure_connected()
        angle = self._validate_angle(angle)
        resolved_speed = self._resolve_servo_speed(speed)
        self.servo.set_angle(angle, speed=resolved_speed)
        self.last_action = {
            "action": "set_angle",
            "requested_angle": angle,
            "applied_angle": self.servo.angle,
            "speed": resolved_speed,
        }
        return self.status()

    @Driver.quickbar(
        qb={
            "button_text": "Set Open Angle",
            "params": {
                "angle": {
                    "label": "Open Angle (0-180)",
                    "type": "int",
                    "default": 0,
                }
            },
        }
    )
    def set_open_angle(self, angle: int) -> Dict[str, Any]:
        """Persist a new open calibration angle."""
        angle = self._validate_angle(angle)
        self.servo.open_angle = angle
        self._update_servo_state()
        self._persist_servo_setting("open_angle", angle)
        self.last_action = {"action": "set_open_angle", "angle": angle}
        return self.status()

    @Driver.quickbar(
        qb={
            "button_text": "Set Close Angle",
            "params": {
                "angle": {
                    "label": "Close Angle (0-180)",
                    "type": "int",
                    "default": 90,
                }
            },
        }
    )
    def set_close_angle(self, angle: int) -> Dict[str, Any]:
        """Persist a new closed calibration angle."""
        angle = self._validate_angle(angle)
        self.servo.close_angle = angle
        self._update_servo_state()
        self._persist_servo_setting("close_angle", angle)
        self.last_action = {"action": "set_close_angle", "angle": angle}
        return self.status()

    @Driver.quickbar(qb={"button_text": "Status"})
    def status(self) -> Dict[str, Any]:
        """Return the driver and servo state."""
        return {
            "connected": self.connected,
            "last_action": self.last_action,
            "open_angle": self.servo.open_angle,
            "close_angle": self.servo.close_angle,
            "home_open": self.config["home_open"],
            "servo_speed": self.config["servo_speed"],
            "servo": self.servo.status(),
        }

    def _ensure_connected(self) -> None:
        if not self.connected:
            self.connect()

    def _resolve_servo_speed(self, speed: Optional[float]) -> float:
        return self.config["servo_speed"] if speed is None else speed

    def _validate_angle(self, angle: int) -> int:
        angle = int(angle)
        if not 0 <= angle <= 180:
            raise ValueError(f"angle must be between 0 and 180 degrees, got {angle}")
        return angle

    def _validate_speed(self, speed: float) -> float:
        speed = float(speed)
        if speed < 0:
            raise ValueError(f"speed must be non-negative, got {speed}")
        return speed

    def _persist_servo_setting(self, key: str, value: Any) -> None:
        servo_config = dict(self.config["servo"])
        servo_config[key] = value
        self.config["servo"] = servo_config

    def _update_servo_state(self) -> None:
        if self.servo.angle is not None and hasattr(self.servo, "_state_from_angle"):
            self.servo.state = self.servo._state_from_angle(self.servo.angle)

    def _sync_servo_config_from_helper(self) -> None:
        servo_config = dict(self.config["servo"])
        for key in list(servo_config.keys()):
            if hasattr(self.servo, key):
                servo_config[key] = getattr(self.servo, key)
        self.config["servo"] = servo_config


_DEFAULT_PORT = 5058
_DEFAULT_CUSTOM_CONFIG = {
    "_classname": "AFL.automation.manipulate.ElectrochemGripper.ElectrochemGripper",
    "_args": [
        {
            "_classname": "AFL.automation.shared.motors.ServoMotor",
            **dict(_DEFAULT_SERVO_CONFIG),
        }
    ],
    "overrides": {"servo_speed": 90.0, "home_open": True, "log_level": logging.INFO},
}


if __name__ == "__main__":
    from AFL.automation.shared.launcher import *
