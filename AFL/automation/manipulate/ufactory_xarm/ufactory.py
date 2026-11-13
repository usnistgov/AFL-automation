#!/usr/bin/env python3
"""Direct xArm SDK operations with station geometry and labware tracking.

Simulation uses the controller's simulated arm and virtual rail/gripper actions.
Cartesian targets are sent once, directly to set_position; there is no motion
planner, station-bound enforcement, or kinematics cache. Approach compatibility
is checked before loaded moves; bottom holder targets receive endpoint IK checks.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
import logging
import math
from pathlib import Path
import time

import lazy_loader as lazy
import numpy as np

yaml = lazy.load("yaml", require="AFL-automation[ufactory]")

from .helpers import _joint_pose, _rotation, _rpy, pose


# Direct xarm-python-sdk APIState/UxbusState codes (not AFL wrapper codes).
XARM_API_CODE_DESCRIPTIONS = {
    0: "success",
    -1: "xArm API is not connected",
    -2: "xArm API is not ready",
    -3: "xArm SDK exception",
    -4: "xArm command does not exist",
    -6: "xArm TCP limit exceeded",
    -7: "xArm joint angle limit exceeded",
    -8: "xArm parameter out of range",
    -9: "xArm emergency stop",
    -10: "xArm servo does not exist",
    -11: "xArm Blockly conversion failed",
    -12: "xArm Blockly execution failed",
    1: "xArm controller has an uncleared error",
    2: "xArm controller has an uncleared warning",
    3: "xArm API response timeout",
    4: "xArm response length error",
    5: "xArm response sequence number error",
    6: "xArm response protocol error",
    7: "xArm response command mismatch",
    8: "xArm command send failed",
    9: "xArm controller is not ready to move",
    10: "xArm result invalid or execution failed",
    11: "xArm other error",
    12: "xArm parameter error",
    51: "xArm mode is not correct",
    80: "linear rail has a fault; inspect the rail error code",
    81: "linear rail safety input (SCI) is low",
    82: "linear rail has not been initialized/homed",
    100: "xArm operation completion timeout",
    101: "xArm status checks failed while waiting for completion",
}

LINEAR_MOTOR_ERROR_DESCRIPTIONS = {
    0: "no rail fault",
    10: "current detection error",
    11: "current over limit",
    12: "speed over limit",
    13: "position deviation too large (check for an obstruction)",
    14: "position command over limit",
    20: "driver IC hardware error",
    21: "driver IC initialization error",
    25: "command exceeded the software limit",
    26: "feedback position exceeded the software limit",
    33: "rail drive overloaded",
    34: "rail motor overloaded",
    35: "motor type error",
    36: "driver type error",
    39: "over-voltage",
    40: "under-voltage",
    49: "EEPROM read/write error",
}

_UNSET = object()


def _stop_on_error(method):
    """Latch the first command error and reject commands after it."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        self._ensure_commands_allowed()
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:
            self._stop_commands(exc)
            raise
    return guarded


@dataclass(frozen=True)
class Placement:
    item: object
    station: object
    address: object
    pose: tuple


@dataclass(frozen=True)
class Attachment:
    item: object
    tcp_to_object: tuple
    approach: str | None = None
    source_station: str | None = None
    grasp: float | None = None
    # Measured grip metadata; station targets never inherit this correction.
    grasp_offset_mm: tuple | None = None


@dataclass
class StationContext:
    """A resumable station endpoint and its station-approved exit route."""

    station: object
    operation: str
    item: object | None
    address: object
    expected_pose: tuple
    retreat_rpy: tuple
    rail_position_mm: float
    entry_poses: tuple
    approach: str | None
    retreat_waypoints: tuple
    release_allowed: bool = False
    hold_time_s: float = 0.
    phase: str = "at_target"


class xArmManipulator:
    """Run station operations through XArmAPI, using metres and radians.

    Motion and gripper defaults come from workcell YAML; explicit arguments override them.
    Set simulation=False to command physical arm, rail, and gripper hardware.
    """

    # None in an HTTP startup config defers to the workcell YAML.
    gripper_defaults = {
        "gripper_type": None,
        "gripper_force": None,
        "gripper_speed": None,
    }
    gripper_models = {
        "xarm": {
            "span_mm": 86., "span_sdk": 688,
            "speed": None, "force": None,
            "speed_range": (1, None), "force_range": None,
            "speed_units": "r/min", "position_method": "set_gripper_position",
        },
        "xarm_g2": {
            "span_mm": 84., "span_sdk": 84.,
            "speed": 100, "force": 50,
            "speed_range": (15, 225), "force_range": (1, 100),
            "speed_units": "mm/s", "position_method": "set_gripper_g2_position",
        },
        "bio": {
            "span_mm": 130., "span_sdk": 130.,
            "speed": 2000, "force": None,
            "speed_range": (1, 4000), "force_range": (10, 100),
            "speed_units": "pulse/s", "position_method": None,
        },
    }

    def __init__(self, ip_address=None, *, simulation=True, initialize_rail=False,
                 sdk=None, stations=(),
                 workcell_config=None, arm_speed_mm_s=_UNSET, joint_speed_deg_s=_UNSET,
                 rail_speed_mm_s=_UNSET, rail_min_position_mm=_UNSET,
                 rail_max_position_mm=_UNSET, gripper_span_mm=_UNSET, gripper_span_sdk=_UNSET,
                 gripper_type=_UNSET, gripper_force=_UNSET,
                 gripper_speed=_UNSET, logger=None):
        self.ip_address = ip_address
        self.simulation = simulation
        if not isinstance(initialize_rail, bool):
            raise TypeError("initialize_rail must be a boolean")
        self.initialize_rail = initialize_rail
        self._arm = sdk
        self.logger = logger or logging.getLogger(f"{__name__}.xArmManipulator")
        path = Path(workcell_config) if workcell_config else Path(__file__).with_name("configs") / "workcell.yaml"
        with path.open() as stream:
            self._workcell = yaml.safe_load(stream) or {}
        arm = self._workcell.get("arm", {})
        rail = self._workcell.get("rail", {})
        gripper = self._workcell.get("gripper", {})
        tool = self._workcell.get("tool", {})
        if not isinstance(gripper, dict):
            raise ValueError("workcell gripper configuration must be a mapping")
        self.gripper_type = gripper.get("type") if gripper_type is _UNSET else gripper_type
        if self.gripper_type is None:
            raise ValueError("specify gripper.type in the workcell config or gripper_type at startup")
        if not isinstance(self.gripper_type, str) or self.gripper_type not in self.gripper_models:
            raise ValueError(f"unknown gripper type {self.gripper_type!r}; "
                             f"choose from {tuple(self.gripper_models)}")
        model = self.gripper_models[self.gripper_type]
        self.arm_speed_mm_s = arm.get("speed_mm_s") if arm_speed_mm_s is _UNSET else arm_speed_mm_s
        self.joint_speed_deg_s = (arm.get("joint_speed_deg_s")
                                  if joint_speed_deg_s is _UNSET else joint_speed_deg_s)
        self.rail_speed_mm_s = rail.get("speed_mm_s") if rail_speed_mm_s is _UNSET else rail_speed_mm_s
        self.rail_min_position_mm = float(
            rail.get("min_position_mm", 0.)
            if rail_min_position_mm is _UNSET else rail_min_position_mm)
        self.rail_max_position_mm = float(
            rail.get("max_position_mm", 700.)
            if rail_max_position_mm is _UNSET else rail_max_position_mm)
        if not all(math.isfinite(value) for value in
                   (self.rail_min_position_mm, self.rail_max_position_mm)):
            raise ValueError("rail position limits must be finite")
        if self.rail_min_position_mm > self.rail_max_position_mm:
            raise ValueError("rail min_position_mm must not exceed max_position_mm")
        # A startup model change must not reuse another model's calibration.
        geometry = gripper if gripper.get("type", self.gripper_type) == self.gripper_type else {}
        self.gripper_span_mm = float(geometry.get("span_mm", model["span_mm"])
                                     if gripper_span_mm is _UNSET else gripper_span_mm)
        self.gripper_span_sdk = float(geometry.get("span_sdk", model["span_sdk"])
                                      if gripper_span_sdk is _UNSET else gripper_span_sdk)
        self.gripper_speed = gripper.get("speed") if gripper_speed is _UNSET else gripper_speed
        self.gripper_force = gripper.get("force") if gripper_force is _UNSET else gripper_force
        if self.gripper_speed is None:
            self.gripper_speed = model["speed"]
        if self.gripper_force is None:
            self.gripper_force = model["force"]
        self.gripper_force, self.gripper_speed = self._resolve_gripper_settings()
        self.gripper_open_clearance_mm = float(gripper.get("open_clearance_mm", 5.))
        if not math.isfinite(self.gripper_span_mm) or self.gripper_span_mm <= 0:
            raise ValueError("gripper span_mm must be finite and positive")
        if not math.isfinite(self.gripper_span_sdk) or self.gripper_span_sdk <= 0:
            raise ValueError("gripper span_sdk must be finite and positive")
        if self.gripper_type == "xarm_g2" and self.gripper_span_mm > model["span_mm"]:
            raise ValueError("xarm_g2 gripper span_mm must be at most 84 mm")
        if not math.isfinite(self.gripper_open_clearance_mm) or self.gripper_open_clearance_mm < 0:
            raise ValueError("gripper open_clearance_mm must be finite and nonnegative")
        self.tcp_offset_mm = tuple(tool.get("tcp_offset_mm", (0., 0., 0.)))
        if len(self.tcp_offset_mm) != 3 or not all(
                isinstance(value, (int, float)) and math.isfinite(value)
                for value in self.tcp_offset_mm):
            raise ValueError("tool tcp_offset_mm must contain three finite values")
        self._rail_position_mm = float(rail.get("robot_position", 0.))
        self._validate_rail_position(self._rail_position_mm)
        self.stations = {}
        self.add_stations(stations)
        self._current_station = None
        self._current_approach = None
        self._last_tcp_pose = None
        self._attachment = None
        self._placements = {}
        self._station_context = None
        self.command_log = []
        self._operation_steps = []
        self._operation_step = "initialize"
        self._command_error = None

    def _stop_commands(self, error):
        """Permanently fault this manipulator instance after its first error."""
        if self._command_error is None:
            self._command_error = str(error)
            self.logger.error("xArm command lockout engaged: %s", self._command_error)

    def _ensure_commands_allowed(self):
        if self._command_error is not None:
            raise RuntimeError(
                "xArm commands are stopped after a previous error: "
                f"{self._command_error}")

    @staticmethod
    def _describe_api_code(code):
        return XARM_API_CODE_DESCRIPTIONS.get(code, f"unknown API code {code}")

    @classmethod
    def _check_code(cls, action, result):
        code = result[0] if isinstance(result, (tuple, list)) else result
        if code not in (None, 0):
            raise RuntimeError(f"{action} failed: SDK code {code} ({cls._describe_api_code(code)})")
        return result

    def _check_motion_code(self, action, result):
        """Capture read-only diagnostics before cleanup can change controller state."""
        try:
            return self._check_code(action, result)
        except RuntimeError as exc:
            details = []
            for name, method in (("state", "get_state"), ("error/warning", "get_err_warn_code")):
                try:
                    response = getattr(self._arm, method)()
                    if not isinstance(response, (tuple, list)) or len(response) < 2:
                        raise RuntimeError("invalid status response")
                    self._check_code(f"read controller {name}", response)
                    details.append(f"controller {name}={response[1]}")
                    if name == "error/warning" and response[1][0] == 23:
                        details.append("controller error 23: joints angle exceed limit")
                except Exception as read_error:
                    details.append(f"controller {name} unavailable: {read_error}")
            raise RuntimeError(f"{exc}; {'; '.join(details)}") from exc

    @_stop_on_error
    def connect(self):
        if self._arm is None:
            xarm_wrapper = lazy.load(
                "xarm.wrapper", require="AFL-automation[ufactory]"
            )
            self._arm = xarm_wrapper.XArmAPI(self.ip_address)
        elif not getattr(self._arm, "connected", True):
            self._check_code("connect", self._arm.connect())
        self._check_code("set controller simulation", self._arm.set_simulation_robot(self.simulation))
        if not self.simulation:
            self._check_code("enable arm", self._arm.motion_enable(enable=True))
        self._check_code("set position mode", self._arm.set_mode(0))
        if any(self.tcp_offset_mm):
            self._check_code("set TCP offset", self._arm.set_tcp_offset(
                [*self.tcp_offset_mm, 0., 0., 0.], wait=True))
        self._check_code("set ready state", self._arm.set_state(0))
        if not self.simulation:
            if self.gripper_type == "bio":
                self._check_code("enable BIO gripper", self._arm.set_bio_gripper_enable(True))
                if self.gripper_speed is not None:
                    self._check_code("set BIO gripper speed", self._arm.set_bio_gripper_speed(self.gripper_speed))
                if self.gripper_force is not None:
                    self._check_code("set BIO gripper force", self._arm.set_bio_gripper_force(self.gripper_force))
            else:
                self._check_code("enable gripper", self._arm.set_gripper_enable(True))
                if self.gripper_type == "xarm" and self.gripper_speed is not None:
                    self._check_code("set gripper speed", self._arm.set_gripper_speed(self.gripper_speed))
            if self.initialize_rail:
                self._initialize_rail()
        return self

    def _read_rail_status(self):
        result = self._arm.get_linear_motor_registers()
        self._check_code("read rail status", result)
        if not isinstance(result, (tuple, list)) or len(result) < 2 \
                or not isinstance(result[1], dict):
            raise RuntimeError(f"read rail status returned an invalid response: {result!r}")
        status = result[1]
        required = {"pos", "error", "is_enabled", "on_zero", "sci"}
        missing = required.difference(status)
        if missing:
            raise RuntimeError(
                f"read rail status omitted {', '.join(sorted(missing))}")
        return status

    def _initialize_rail(self):
        """Probe, recover, home when necessary, and enable the configured rail."""
        self.logger.info("Initialize linear rail")
        status = self._read_rail_status()
        if status["sci"] != 1:
            raise RuntimeError("initialize rail failed: safety input (SCI) is low")

        if status["error"] != 0:
            self._check_code("clear rail error", self._arm.clean_linear_motor_error())
            status = self._read_rail_status()
            if status["error"] != 0:
                description = LINEAR_MOTOR_ERROR_DESCRIPTIONS.get(
                    status["error"], "unknown rail drive fault")
                raise RuntimeError(
                    f"initialize rail failed: rail error={status['error']} ({description})")

        if status["on_zero"] != 1:
            # Disable the SDK's implicit post-home enable so a successful enable
            # cannot mask a homing timeout in affected SDK versions.
            self._check_code(
                "home rail",
                self._arm.set_linear_motor_back_origin(
                    wait=True, auto_enable=False),
            )
            status = self._read_rail_status()
            if status["on_zero"] != 1:
                raise RuntimeError("initialize rail failed: rail did not reach its origin")

        if status["is_enabled"] != 1:
            self._check_code("enable rail", self._arm.set_linear_motor_enable(True))
        if self.rail_speed_mm_s is not None:
            self._check_code(
                "set rail speed",
                self._arm.set_linear_motor_speed(self.rail_speed_mm_s),
            )
        self._rail_position_mm = self._validate_rail_position(status["pos"])

    def disconnect(self):
        if self._arm is not None:
            self._arm.disconnect()

    def _record(self, command, **parameters):
        self.command_log.append({"command": command, **parameters})
        self.logger.debug("xArm command: %s %s", command, parameters)

    @staticmethod
    def _sdk_pose_to_si(values):
        return (*tuple(value / 1000. for value in values[:3]),
                *tuple(math.radians(value) for value in values[3:]))

    @staticmethod
    def _si_pose_to_sdk(values):
        """Render an internal metres/radians pose in xArm mm/degree units."""
        return [*(value * 1000. for value in values[:3]),
                *(math.degrees(value) for value in values[3:])]

    def _log_motion_feedback(self, station_name, kind, requested, reported, units):
        self.logger.debug(
            "%s completed at %s: requested %s (%s)=%s; xArmAPI reported %s (%s)=%s",
            self._operation_step, station_name, kind, units, list(requested),
            kind, units, list(reported))

    def _read_tcp(self):
        result = self._check_code("read TCP", self._arm.get_position())
        return self._sdk_pose_to_si(result[1])

    def _check_cartesian_target(self, target):
        """Read-only endpoint IK/limit check; does not certify the intervening path."""
        target = pose(target)
        result = self._check_code("solve target IK", self._arm.get_inverse_kinematics(
            [*(v * 1000. for v in target[:3]), *(math.degrees(v) for v in target[3:])],
            input_is_radian=False, return_is_radian=False))
        joints = _joint_pose(result[1], "target IK joints")
        result = self._check_code("check target joint limits",
                                  self._arm.is_joint_limit(list(joints), is_radian=False))
        if result[1] is not False:
            raise RuntimeError(f"Cartesian target {target[:3]} has no confirmed in-limit joint solution; "
                               "re-teach the station entry for this approach")

    def _read_joints(self):
        result = self._check_code("read joints", self._arm.get_servo_angle(is_radian=False))
        return _joint_pose(result[1], "controller joints")

    @_stop_on_error
    def _move_joints(self, target, station_name):
        target = _joint_pose(target, "joint target")
        self._record("move_joints", joint_angles_deg=list(target), station=station_name)
        options = {"wait": True, "is_radian": False}
        if self.joint_speed_deg_s is not None:
            options["speed"] = self.joint_speed_deg_s
        self._check_motion_code("move joints", self._arm.set_servo_angle(angle=list(target), **options))
        joints = self._read_joints()
        self._log_motion_feedback(station_name, "joints", target, joints, "deg")
        if max(abs(a - b) for a, b in zip(joints, target)) > 1.:
            raise RuntimeError(f"{station_name} joint target not reached: {joints}")
        self._last_tcp_pose = self._read_tcp()

    @_stop_on_error
    def _move_pose(self, target, station_name, *, intent="station motion"):
        """Request an unblended Cartesian line with no joint-planning fallback."""
        target = tuple(target)
        sdk_pose = self._si_pose_to_sdk(target)
        self.logger.debug("%s: %s TCP target at %s (mm, deg): %s",
                         self._operation_step, intent, station_name, sdk_pose)
        self._record("move_tcp", pose=list(target), station=station_name, intent=intent)
        options = {"wait": True, "radius": -1, "motion_type": 0}
        if self.arm_speed_mm_s is not None:
            options["speed"] = self.arm_speed_mm_s
        self._check_motion_code("move TCP", self._arm.set_position(*sdk_pose, **options))
        self._last_tcp_pose = self._read_tcp()
        self._log_motion_feedback(
            station_name, "TCP pose", sdk_pose,
            self._si_pose_to_sdk(self._last_tcp_pose), "mm, deg")

    def _read_collision_sensitivity(self):
        # The SDK initializes the cached value to zero, even before any report.
        # These SDK internals are needed because there is no synchronous getter.
        controller = self._arm._arm
        if (not self._arm.connected or not controller._enable_report
                or controller._report_type != "rich" or not controller._first_report_over
                or controller._is_old_protocol
                or time.monotonic() - controller._last_report_time > 2.):
            raise RuntimeError("Collision sensitivity requires a current rich controller report")
        value = self._arm.collision_sensitivity
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
            raise RuntimeError("Controller reported an invalid collision sensitivity")
        return value

    @_stop_on_error
    def _set_collision_sensitivity(self, value, *, restore=False, preserve_state=False):
        self._record("set_collision_sensitivity", value=value, restore=restore)
        if preserve_state:
            # SDK 1.18's public setter waits for pause to end and calls set_state(0).
            # On failure, send only the setting command so cleanup never resumes
            # a stopped robot or hangs waiting for a paused robot.
            result = self._arm.core.set_collis_sens(value)
        else:
            # Successful restoration must include the SDK's ready transition;
            # the raw parameter command alone can leave subsequent motion unready.
            result = self._arm.set_collision_sensitivity(value)
        self._check_code("restore collision sensitivity" if restore else "set collision sensitivity", result)
        deadline = time.monotonic() + 2.
        while self._read_collision_sensitivity() != value:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Controller did not confirm collision sensitivity {value}")
            time.sleep(.02)

    @contextmanager
    def _temporary_collision_sensitivity(self, value):
        previous = self._step("read collision sensitivity", self._read_collision_sensitivity)
        failure = None
        failed_step = None
        try:
            self._step(f"set collision sensitivity to {value}",
                       lambda: self._set_collision_sensitivity(value))
            yield
        except BaseException as exc:
            failure, failed_step = exc, self._operation_step
            raise
        finally:
            if failure is None:
                self._step(f"restore collision sensitivity to {previous}",
                           lambda: self._set_collision_sensitivity(previous, restore=True))
            else:
                # Once a step fails, even cleanup writes are prohibited. In
                # particular, the public SDK setter can transition the arm back
                # to ready state and permit motion after the original failure.
                self.logger.warning(
                    "Skipping collision sensitivity restoration after failure at %s",
                    failed_step)
                self._operation_step = failed_step

    @staticmethod
    def _validate_gripper_setting(value, name, bounds, *, integer=False):
        if value is None:
            return None
        minimum, maximum = bounds
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < minimum
                or (maximum is not None and value > maximum)
                or (integer and not float(value).is_integer())):
            limits = f"at least {minimum}" if maximum is None else f"between {minimum} and {maximum}"
            kind = "integer" if integer else "number"
            raise ValueError(f"gripper {name} must be a finite {kind} {limits}")
        return int(value) if integer else value

    def _resolve_gripper_settings(self, *, force=None, speed=None):
        """Resolve one pick's settings without changing the configured defaults."""
        model = self.gripper_models[self.gripper_type]
        force = self.gripper_force if force is None else force
        speed = self.gripper_speed if speed is None else speed
        if model["force_range"] is None:
            if force is not None:
                raise ValueError(f"{self.gripper_type} gripper does not support force control")
        else:
            force = self._validate_gripper_setting(force, "force", model["force_range"], integer=True)
        speed = self._validate_gripper_setting(
            speed, "speed", model["speed_range"], integer=self.gripper_type in ("xarm", "bio"))
        return force, speed

    def gripper_position_for_gap(self, gap_mm):
        """Convert a jaw gap to native mm for G2, or calibrated original pulses."""
        if self.gripper_type == "bio":
            raise ValueError("BIO gripper uses full open/close commands, not a programmable jaw gap")
        if not math.isfinite(gap_mm) or not 0 <= gap_mm <= self.gripper_span_mm:
            raise ValueError(f"gripper gap must be between 0 and {self.gripper_span_mm:g} mm")
        if self.gripper_type == "xarm_g2":
            return gap_mm
        return round(gap_mm / self.gripper_span_mm * self.gripper_span_sdk)

    def _gripper_gap(self, labware, *, opened, grasp=None):
        if labware is None:
            return self.gripper_span_mm if opened else 0.
        width_mm = labware.resolve_grasp_mm(grasp)
        if width_mm > self.gripper_span_mm:
            raise ValueError(f"{labware.name} grasp must be at most "
                             f"{self.gripper_span_mm:g} mm (got {width_mm:g} mm)")
        return (min(width_mm + self.gripper_open_clearance_mm, self.gripper_span_mm)
                if opened else width_mm)

    @_stop_on_error
    def _set_gripper(self, *, opened, labware=None, grasp=None, force=None, speed=None):
        force, speed = self._resolve_gripper_settings(force=force, speed=speed)
        gap_mm = self._gripper_gap(labware, opened=opened, grasp=grasp)
        if self.gripper_type == "bio":
            # BIO's public open/close API cannot target a labware-specific gap.
            gap_mm = self.gripper_span_mm if opened else 0.
            position = None
        else:
            position = self.gripper_position_for_gap(gap_mm)
        self.logger.debug("%sgripper: %s (gap %.2f mm, SDK position %s)",
                          "Virtual " if self.simulation else "",
                          "open" if opened else "close", gap_mm, position)
        self._record("set_gripper", opened=opened, position=position, gap_mm=gap_mm,
                     gripper_type=self.gripper_type, force=force, speed=speed,
                     labware_id=labware.name if labware is not None else None, simulated=self.simulation)
        if not self.simulation:
            options = {"wait": True}
            if speed is not None:
                options["speed"] = speed
            if force is not None:
                options["force"] = force
            if self.gripper_type == "bio":
                # BIO's open/close helpers can discard setter errors (and
                # ignore force on older hardware). Check the setters ourselves.
                if speed is not None:
                    self._check_code("set BIO gripper speed", self._arm.set_bio_gripper_speed(speed))
                if force is not None:
                    self._check_code("set BIO gripper force", self._arm.set_bio_gripper_force(force))
                method = self._arm.open_bio_gripper if opened else self._arm.close_bio_gripper
                result = method(**options)
            else:
                method = getattr(self._arm, self.gripper_models[self.gripper_type]["position_method"])
                result = method(position, **options)
            self._check_code("set gripper", result)

    @_stop_on_error
    def home(self):
        self._ensure_station_context_clear()
        self.logger.info("Home arm")
        self._record("home_arm")
        options = {"wait": True}
        if self.joint_speed_deg_s is not None:
            options["speed"] = self.joint_speed_deg_s
        self._check_motion_code("home arm", self._arm.move_gohome(**options))
        self._current_station = None
        self._current_approach = None
        self._last_tcp_pose = None
        return {"success": True}

    @_stop_on_error
    def home_rail(self):
        self.logger.info("%srail: home", "Virtual " if self.simulation else "")
        self._record("home_rail", simulated=self.simulation)
        if not self.simulation:
            result = self._arm.set_linear_motor_back_origin(wait=True)
            code = result[0] if isinstance(result, (tuple, list)) else result
            if code not in (None, 0):
                raise RuntimeError(
                    f"home rail failed: {self._format_api_failure(code)}; "
                    f"{self._rail_diagnostics()}")
        self._rail_position_mm = 0.
        return {"success": True, "position_mm": 0.}

    @classmethod
    def _format_api_failure(cls, code):
        return f"SDK code {code} ({cls._describe_api_code(code)})"

    def _rail_diagnostics(self):
        """Best-effort rail state for an error message; never masks the command failure."""
        details = []
        reads = (
            ("error", "get_linear_motor_error"),
            ("status", "get_linear_motor_status"),
            ("enabled", "get_linear_motor_is_enabled"),
            ("at_origin", "get_linear_motor_on_zero"),
            ("SCI", "get_linear_motor_sci"),
        )
        for label, method_name in reads:
            try:
                response = getattr(self._arm, method_name)()
                if not isinstance(response, (tuple, list)) or len(response) < 2:
                    raise RuntimeError(f"invalid response {response!r}")
                read_code, value = response[0], response[1]
                if read_code not in (None, 0):
                    details.append(f"{label}=unavailable ({self._format_api_failure(read_code)})")
                elif label == "error":
                    description = LINEAR_MOTOR_ERROR_DESCRIPTIONS.get(
                        value, "unknown rail drive fault; consult the xArm rail error table")
                    details.append(f"rail error={value} ({description})")
                else:
                    details.append(f"{label}={value}")
            except Exception as exc:
                details.append(f"{label}=unavailable ({exc})")
        return "; ".join(details)

    def _validate_rail_position(self, position_mm):
        try:
            position_mm = float(position_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError("rail position must be a finite number in millimetres") from exc
        if not math.isfinite(position_mm):
            raise ValueError("rail position must be a finite number in millimetres")
        if not self.rail_min_position_mm <= position_mm <= self.rail_max_position_mm:
            raise ValueError(
                f"rail position {position_mm:g} mm is outside the configured limits "
                f"[{self.rail_min_position_mm:g}, {self.rail_max_position_mm:g}] mm")
        return position_mm

    @_stop_on_error
    def move_rail(self, position_mm):
        """Move the linear rail to an absolute position expressed in millimetres."""
        self._ensure_station_context_clear()
        position_mm = self._validate_rail_position(position_mm)
        self.logger.info("%srail: %s mm", "Virtual " if self.simulation else "", position_mm)
        self._record("move_rail", position_mm=position_mm, simulated=self.simulation)
        if not self.simulation and position_mm != self._rail_position_mm:
            options = {"wait": True}
            if self.rail_speed_mm_s is not None:
                options["speed"] = self.rail_speed_mm_s
            self._check_code("move rail", self._arm.set_linear_motor_pos(position_mm, **options))
        self._rail_position_mm = position_mm
        return {"success": True, "position_mm": position_mm}

    @_stop_on_error
    def enable_rail(self, enabled=True):
        if not self.simulation:
            self._check_code("enable rail", self._arm.set_linear_motor_enable(enabled))
        return {"success": True}

    @_stop_on_error
    def set_rail_speed(self, speed_mm_s):
        self.rail_speed_mm_s = speed_mm_s
        if not self.simulation:
            self._check_code("set rail speed", self._arm.set_linear_motor_speed(speed_mm_s))
        return {"success": True}

    @_stop_on_error
    def stop_rail(self):
        if not self.simulation:
            self._check_code("stop rail", self._arm.set_linear_motor_stop())
        return {"success": True}

    @_stop_on_error
    def clear_rail_error(self):
        if not self.simulation:
            self._check_code("clear rail error", self._arm.clean_linear_motor_error())
        return {"success": True}

    @_stop_on_error
    def clear_arm_errors(self, *, clear_warnings=True):
        self._check_code("clear arm error", self._arm.clean_error())
        if clear_warnings:
            self._check_code("clear arm warning", self._arm.clean_warn())
        return {"success": True}

    def add_stations(self, stations):
        self.stations.update((station.name, station) for station in stations)

    @_stop_on_error
    def station_operation(self, station, operation, *args, **kwargs):
        """Run a method decorated with stations.station_operation using this arm.

        Accepts a station instance or registered name. Options are forwarded to
        the station operation, which retains its motion and state handling.
        """
        station = self._resolve_station(station)
        method = getattr(station, operation, None)
        if not getattr(method, "_resumes_station_context", False):
            self._ensure_station_context_clear()
        if operation not in station.available_operations:
            raise ValueError(f"{station.name} does not support operation {operation!r}; "
                             f"available operations: {station.available_operations}")
        if getattr(method, "_station_arm_keyword", False):
            return method(*args, arm=self, **kwargs)
        return method(self, *args, **kwargs)

    def _ensure_station_context_clear(self):
        context = self._station_context
        if context is not None:
            next_action = "retreat()" if context.phase == "released" else "release() or retreat()"
            raise RuntimeError(
                f"{context.operation} at {context.station.name} is paused in phase "
                f"{context.phase!r}; call {next_action} before starting another "
                "station operation"
            )

    @staticmethod
    def _validate_operation_flags(*, release=None, retreat=False):
        if release is not None and type(release) is not bool:
            raise ValueError("release must be a boolean")
        if type(retreat) is not bool:
            raise ValueError("retreat must be a boolean")

    def _set_station_context(self, station, operation, item, address, expected_pose,
                             entry_poses, approach, retreat_waypoints, *, retreat_rpy=None,
                             release_allowed=False, hold_time_s=0.):
        self._ensure_station_context_clear()
        self._station_context = StationContext(
            station=station,
            operation=operation,
            item=item,
            address=address,
            expected_pose=tuple(expected_pose),
            retreat_rpy=tuple(expected_pose[3:] if retreat_rpy is None else retreat_rpy),
            rail_position_mm=self._rail_position_mm,
            entry_poses=tuple(tuple(entry) for entry in entry_poses),
            approach=approach,
            retreat_waypoints=tuple(tuple(waypoint) for waypoint in retreat_waypoints),
            release_allowed=release_allowed,
            hold_time_s=hold_time_s,
        )
        return self._station_context

    def _verify_station_context_pose(self, context):
        if self._last_tcp_pose is None:
            raise RuntimeError("cannot resume station operation without a known TCP pose")
        if self._current_station != context.station.name:
            raise RuntimeError(
                f"arm is no longer registered at the saved station {context.station.name}"
            )
        if self._rail_position_mm != context.rail_position_mm:
            raise RuntimeError(
                f"rail is no longer at the saved position {context.rail_position_mm:g} mm"
            )
        actual = tuple(self._read_tcp())
        self._last_tcp_pose = actual
        linear_error_mm = max(
            abs(actual[index] - context.expected_pose[index]) * 1000. for index in range(3)
        )
        angular_error_deg = max(
            abs(math.degrees(math.atan2(
                math.sin(actual[index] - context.expected_pose[index]),
                math.cos(actual[index] - context.expected_pose[index]),
            )))
            for index in range(3, 6)
        )
        if linear_error_mm > 1. or angular_error_deg > 1.:
            raise RuntimeError(
                f"arm is no longer at the saved {context.station.name} endpoint "
                f"(maximum error {linear_error_mm:.3f} mm, {angular_error_deg:.3f} deg)"
            )

    def _release_station_context(self, *, verify_pose):
        context = self._station_context
        if context is None:
            raise RuntimeError("release requires an active station operation")
        if not context.release_allowed:
            raise RuntimeError(f"{context.operation} at {context.station.name} cannot release labware")
        if context.phase != "at_target":
            raise RuntimeError(f"labware has already been released at {context.station.name}")
        attachment = self._attachment
        if attachment is None or attachment.item is not context.item:
            raise RuntimeError("active station context does not match the attached labware")
        if verify_pose:
            self._verify_station_context_pose(context)
        if context.hold_time_s > 0:
            self._step(
                f"hold {context.hold_time_s:g} s at {context.station.name} before release gripper",
                lambda: time.sleep(context.hold_time_s),
            )
        bottom = self._compose_pose(context.expected_pose, attachment.tcp_to_object)
        self._step("release gripper", lambda: self._set_gripper(
            opened=True, labware=attachment.item, grasp=attachment.grasp))
        self._record_placement(attachment.item, context.station, context.address, bottom)
        context.phase = "released"
        return context

    def _retreat_station_context(self, *, verify_pose):
        context = self._station_context
        if context is None:
            raise RuntimeError("retreat requires an active station operation")
        if verify_pose:
            self._verify_station_context_pose(context)
        for waypoint in context.retreat_waypoints:
            target = (*waypoint[:3], *context.retreat_rpy)
            self._step(f"retreat at {context.station.name}", lambda target=target: self._move_pose(
                target, context.station.name, intent="station retreat"))
        self._retreat_to_base(context.station, context.entry_poses, context.approach)
        context.phase = "at_base"
        self._station_context = None
        return context

    @_stop_on_error
    def release(self):
        """Release labware at the endpoint saved by the active station operation."""
        def operation():
            context = self._release_station_context(verify_pose=True)
            return {"station": context.station.name,
                    "labware_id": context.item.name if context.item is not None else None,
                    "phase": context.phase, "can_release": False, "can_retreat": True}
        return self._run_operation("release", operation)

    @_stop_on_error
    def retreat(self):
        """Follow the active station's saved collision-aware route back to base."""
        def operation():
            context = self._retreat_station_context(verify_pose=True)
            return {"station": context.station.name,
                    "labware_id": context.item.name if context.item is not None else None,
                    "phase": context.phase, "can_release": False, "can_retreat": False}
        return self._run_operation("retreat", operation)

    def _resolve_station(self, endpoint):
        station = endpoint[0] if isinstance(endpoint, tuple) else endpoint
        if isinstance(station, str):
            station = self.stations[station]
        self.stations[station.name] = station
        return station

    def _resolve_endpoint(self, endpoint):
        station = self._resolve_station(endpoint)
        address = endpoint[1] if isinstance(endpoint, tuple) else None
        resolver = getattr(station, "resolve_address", None)
        return station, resolver(address) if resolver is not None else address

    def _placement_approach(self, station, approach=None):
        """Keep the pickup approach while loaded; validate before any motion."""
        attachment = self._attachment
        if attachment is not None and attachment.approach is not None:
            if approach is not None and approach != attachment.approach:
                raise ValueError(f"cannot change loaded approach from {attachment.approach!r} to {approach!r}; "
                                 "place and regrasp the vial before changing approach")
            approach = attachment.approach
            source = self.stations.get(attachment.source_station)
            if source is not None:
                source.resolve_approach(approach)
        return station.resolve_approach(approach)

    def _enter(self, station, *, approach=None, location=None):
        approach = self._placement_approach(station, approach)
        entry_poses = station.resolve_entry_pose(approach, location=location, all_entries=True)
        self.stations[station.name] = station
        if station.linear_rail_position is not None:
            self.move_rail(station.linear_rail_position)
        for entry_pose in entry_poses:
            self._move_entry_pose(station, entry_pose, approach)
        return self._last_tcp_pose

    def _retreat_to_base(self, station, entry_poses, approach):
        """After the station sequence returns to its specific entry, exit to base."""
        if len(entry_poses) > 1:
            self._step(f"return to {station.name} base",
                       lambda: self._move_entry_pose(station, entry_poses[0], approach))

    @_stop_on_error
    def _move_entry_pose(self, station, entry_pose, approach):
        self.logger.info("%s entry joint target (deg): %s", station.name, entry_pose)
        self._record("station_entry", station=station.name, joint_angles_deg=list(entry_pose))
        self._current_station = None
        options = {"wait": True}
        if self.joint_speed_deg_s is not None:
            options["speed"] = self.joint_speed_deg_s
        self._check_motion_code("station entry", self._arm.set_servo_angle(angle=list(entry_pose), **options))
        # This is the entry feedback check used by example_xarm_native.py.
        result = self._check_code("read entry joints", self._arm.get_servo_angle())
        joints = _joint_pose(result[1], f"{station.name} entry joint feedback")
        self._log_motion_feedback(station.name, "joints", entry_pose, joints, "deg")
        if max(abs(a - b) for a, b in zip(joints, entry_pose)) > 1.:
            raise RuntimeError(f"{station.name} entry joint pose not reached: {joints}")
        self._last_tcp_pose = self._read_tcp()
        self._current_station = station.name
        self._current_approach = approach
        return self._last_tcp_pose

    def _step(self, label, operation):
        self._ensure_commands_allowed()
        self._operation_step = label
        number = len(self._operation_steps) + 1
        self.logger.info("Step %d starting: %s", number, label)
        try:
            result = operation()
        except Exception as exc:
            self._stop_commands(exc)
            raise
        self._operation_steps.append(label)
        self.logger.debug("Step %d completed: %s", number, label)
        return result

    def _run_operation(self, name, operation):
        self._operation_steps = []
        self._operation_step = name
        self.logger.info("Starting %s", name)
        try:
            self._ensure_commands_allowed()
            details = operation() or {}
        except Exception as exc:
            self._stop_commands(exc)
            self.logger.error("%s failed at %s: %s", name, self._operation_step, exc)
            return {"success": False, "message": str(exc), "failed_step": self._operation_step,
                    "completed_steps": list(self._operation_steps), "simulation": self.simulation}
        self.logger.info("Completed %s", name)
        return {"success": True, "message": f"{name} completed", "failed_step": None,
                "completed_steps": list(self._operation_steps), "simulation": self.simulation, **details}

    def move_to_station(self, station, *, approach=None):
        def operation():
            self._ensure_station_context_clear()
            destination = self._resolve_station(station)
            location = station[1] if isinstance(station, tuple) else None
            self._step(f"enter {destination.name}", lambda: self._enter(
                destination, approach=approach, location=location))
            return {"station": destination.name, "loaded": self.attached_labware is not None}
        return self._run_operation("station move", operation)

    @staticmethod
    def _compose_pose(parent, child):
        rotation = np.asarray(_rotation(parent[3:]))
        offset = rotation @ np.asarray(child[:3])
        return (*tuple(parent[i] + offset[i] for i in range(3)),
                *_rpy(rotation @ np.asarray(_rotation(child[3:]))))

    @staticmethod
    def _inverse_pose(value):
        rotation = np.asarray(_rotation(value[3:])).T
        return (*tuple(rotation @ -np.asarray(value[:3])), *_rpy(rotation))

    def _capture_attachment(self, item, tcp, bottom, *, grasp=None):
        object_to_tcp = self._compose_pose(self._inverse_pose(bottom), tcp)
        self._attachment = Attachment(item, self._compose_pose(self._inverse_pose(tcp), bottom),
                                      self._current_approach, self._current_station, grasp,
                                      tuple(value * 1000. - (item.height_mm if i == 2 else 0.)
                                            for i, value in enumerate(object_to_tcp[:3])))
        self._placements.pop(item.name, None)

    def _log_tcp_offset(self, operation, station, address, item, *, grasp, source,
                          base_offset_mm, reference, final, use_labware_offset, target):
        """Log each contribution to the target in millimetres before approach."""
        mm = lambda values: tuple(round(value * 1000., 3) for value in values[:3])
        self.logger.info(
            "%s target: station=%s location=%s labware=%s reference=%s; "
            "reference XYZ (mm)=%s; use_labware_offset=%s height added (mm)=%.3f; "
            "final reference XYZ (mm)=%s; grasp gap (mm)=%s source=%s "
            "TCP offset in robot-base XYZ (mm)=%s; TCP target XYZ (mm)=%s",
            operation, station.name, address, item.name if item is not None else None,
            station.location_reference,
            mm(reference), use_labware_offset,
            item.height_mm if use_labware_offset and item is not None else 0., mm(final),
            grasp, source, tuple(round(v, 3) for v in base_offset_mm), mm(target))

    def _record_placement(self, item, station, address, bottom):
        self._placements[item.name] = Placement(item, station, address, tuple(bottom))
        self._attachment = None

    @property
    def attached_labware(self):
        return None if self._attachment is None else self._attachment.item

    def locate_labware(self, item, station, address=None):
        """Record a bottom pose resolved in the arm-base frame."""
        station, address = self._resolve_endpoint((station, address))
        self._placements[item.name] = Placement(item, station, address,
                                                station.resolve_location(address))
        return self.labware_state(item)

    def labware_state(self, item):
        if self.attached_labware is item:
            return {"state": "held", "station": None, "location": None,
                    "tcp_to_object": self._attachment.tcp_to_object,
                    "grasp": self._attachment.grasp,
                    "grasp_offset_mm": self._attachment.grasp_offset_mm}
        record = self._placements.get(item.name)
        return {"state": "placed" if record else "unknown",
                "station": record.station.name if record else None,
                "location": record.pose if record else None}

    def status(self):
        context = self._station_context
        return {"station": self._current_station, "tcp_pose": self._last_tcp_pose,
                "rail_position_mm": self._rail_position_mm, "simulation": self.simulation,
                "gripper": {"type": self.gripper_type, "force": self.gripper_force,
                            "speed": self.gripper_speed,
                            "speed_units": self.gripper_models[self.gripper_type]["speed_units"]},
                "labware_id": self.attached_labware.name if self.attached_labware else None,
                "station_phase": context.phase if context is not None else None,
                "can_release": bool(context and context.release_allowed
                                    and context.phase == "at_target"),
                "can_retreat": context is not None,
                "commands_stopped": self._command_error is not None,
                "command_error": self._command_error}

    def describe_workcell(self):
        return {"stations": {station.name: {"pose": station.pose, "poses": station.poses,
                                            "location": station.location,
                                            "location_frame": station.location_frame,
                                            "linear_rail_position": station.linear_rail_position}
                             for station in self.stations.values()}}
