#!/usr/bin/env python3
"""Reusable motor helpers with lazy-loaded Raspberry Pi dependencies."""

from __future__ import annotations

import atexit
import importlib
import logging
import time
from typing import Dict, Optional

import lazy_loader as lazy


class Motor:
    """
    Base class for reusable motor helpers.

    Parameters
    ----------
    name : str, optional
        Logger name to use for this motor instance. If omitted, the class name is
        used.
    log_level : int or str, default=logging.INFO
        Logging level for this motor instance. Accepts standard logging constants
        or names such as ``"DEBUG"`` and ``"INFO"``.

    Attributes
    ----------
    logger : logging.Logger
        Logger used by derived motor classes.

    Examples
    --------
    Create a base motor logger for a custom helper class.

    >>> motor = Motor(name="gripper", log_level="DEBUG")
    >>> motor.logger.name
    'gripper'
    """
    def __init__(self, name: Optional[str] = None, log_level: int | str = logging.INFO) -> None:
        self.logger = logging.getLogger(name if name is not None else self.__class__.__name__)
        self.logger.setLevel(log_level)


class ServoMotor(Motor):
    """
    Control a PCA9685-backed hobby servo with lazy-loaded dependencies.

    Parameters
    ----------
    channel : int, default=8
        PCA9685 output channel that the servo signal wire is connected to.
    address : int, default=0x40
        I2C address of the PCA9685 board. Change this if the board address pins
        are configured differently.
    bus : int, default=1
        I2C bus number on the host system. Use the bus your PCA9685 is wired to.
    min_angle : int, default=0
        Lowest allowed commanded angle in degrees.
    max_angle : int, default=90
        Highest allowed commanded angle in degrees.
    open_angle : int, default=0
        Angle treated as the open position for your mechanism.
    close_angle : int, default=90
        Angle treated as the closed position for your mechanism.
    pulse_min : int, default=700
        Minimum pulse width in microseconds for servo calibration.
    pulse_max : int, default=2400
        Maximum pulse width in microseconds for servo calibration.
    channels : int, default=16
        Number of channels exposed by the attached PCA9685 board.
    default_speed : float, default=90.0
        Default software ramp speed in degrees per second.
    register_cleanup : bool, default=True
        Register cleanup with ``atexit`` so the servo output is released on exit.
    name : str, optional
        Logger name override for this motor instance.
    log_level : int or str, default=logging.INFO
        Logging verbosity for this motor instance.

    Attributes
    ----------
    channel : int
        PCA9685 output channel used by the servo.
    address : int
        I2C address of the PCA9685 controller.
    angle : int or None
        Last commanded servo angle.
    state : str
        Human-readable servo state derived from the current angle.

    Examples
    --------
    Create a servo on channel 8 and move it to the configured open position.

    >>> servo = ServoMotor(channel=8, open_angle=5)
    >>> servo.open()

    Move the servo to a specific angle at a limited speed.

    >>> servo.set_angle(45, speed=30.0)
    >>> servo.status()["state"]
    'partial'
    """
    DEFAULTS = {
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

    def __init__(self, **kwargs) -> None:
        """
        Initialize the servo motor helper.

        Parameters
        ----------
        **kwargs
            Optional configuration overrides merged with :attr:`DEFAULTS`.
        """
        config = {**self.DEFAULTS, **kwargs}
        super().__init__(name=config.get("name"), log_level=config.get("log_level", logging.INFO))
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
        self.state = "unknown"
        self.angle: Optional[int] = None

        try:
            servokit_module = importlib.import_module("adafruit_servokit")
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "ServoMotor requires adafruit-circuitpython-servokit to be installed."
            ) from exc
        try:
            busio_module = importlib.import_module("busio")
            board_module = importlib.import_module("board")
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "ServoMotor requires adafruit-blinka to be installed."
            ) from exc
        self.ServoKit = servokit_module.ServoKit
        i2c = busio_module.I2C(board_module.SCL, board_module.SDA)
        self.kit = self.ServoKit(channels=self.channels, address=self.address, i2c=i2c)
        self.kit.servo[self.channel].set_pulse_width_range(self.pulse_min, self.pulse_max)
        self.logger.debug(
            "Initialized servo motor channel=%s address=%s bus=%s angle_range=(%s,%s) pulse_range=(%s,%s) default_speed=%s",
            self.channel,
            self.address,
            self.bus,
            self.min_angle,
            self.max_angle,
            self.pulse_min,
            self.pulse_max,
            self.default_speed,
        )

        if config["register_cleanup"]:
            atexit.register(self.cleanup)

    def set_angle(self, angle: int, speed: float = 0.0) -> None:
        """
        Move the servo to a target angle.

        Parameters
        ----------
        angle : int
            Target angle in degrees. Values are clamped to the configured
            ``min_angle`` and ``max_angle``.
        speed : float, default=0.0
            Approximate angular speed in degrees per second. A value less than or
            equal to zero applies the target angle immediately.

        Examples
        --------
        >>> servo = ServoMotor()
        >>> servo.set_angle(30)
        >>> servo.set_angle(60, speed=20.0)
        """
        requested_angle = angle
        angle = max(self.min_angle, min(self.max_angle, angle))
        self.logger.debug(
            "Servo set_angle requested=%s clamped=%s current=%s speed=%s",
            requested_angle,
            angle,
            self.angle,
            speed,
        )
        if self.angle is None or speed <= 0.0:
            self.kit.servo[self.channel].angle = angle
            self.angle = angle
            self.state = self._state_from_angle(angle)
            self.logger.info(f"Set servo channel {self.channel} to angle {angle}")
            time.sleep(0.1)
            return

        current_angle = self.angle
        delta = angle - current_angle
        steps = int(abs(delta))
        if steps == 0:
            self.logger.debug("Servo already at requested angle %s", angle)
            return

        speed = max(1.0, speed)
        step_delay = max((1.0 / speed) / steps, 0.005)
        step_direction = 1 if delta > 0 else -1
        self.logger.debug(
            "Servo ramping channel=%s delta=%s steps=%s step_direction=%s step_delay=%s",
            self.channel,
            delta,
            steps,
            step_direction,
            step_delay,
        )

        for _ in range(steps):
            current_angle += step_direction
            self.kit.servo[self.channel].angle = current_angle
            time.sleep(step_delay)

        self.angle = angle
        self.state = self._state_from_angle(angle)
        self.logger.info(f"Set servo channel {self.channel} to angle {angle} with speed {speed}")

    def open(self, speed: Optional[float] = None) -> None:
        """
        Move the servo to the configured open angle.

        Parameters
        ----------
        speed : float, optional
            Override for the configured default speed.

        Examples
        --------
        >>> servo = ServoMotor(open_angle=10)
        >>> servo.open()
        """
        resolved_speed = self.default_speed if speed is None else speed
        self.logger.debug("Opening servo to angle=%s speed=%s", self.open_angle, resolved_speed)
        self.set_angle(self.open_angle, speed=resolved_speed)

    def close(self, speed: Optional[float] = None) -> None:
        """
        Move the servo to the configured closed angle.

        Parameters
        ----------
        speed : float, optional
            Override for the configured default speed.

        Examples
        --------
        >>> servo = ServoMotor(close_angle=80)
        >>> servo.close(speed=45.0)
        """
        resolved_speed = self.default_speed if speed is None else speed
        self.logger.debug("Closing servo to angle=%s speed=%s", self.close_angle, resolved_speed)
        self.set_angle(self.close_angle, speed=resolved_speed)

    def status(self) -> Dict[str, object]:
        """
        Return the current servo state.

        Returns
        -------
        dict
            Dictionary containing the configured servo parameters and the last
            commanded state.

        Examples
        --------
        >>> servo = ServoMotor()
        >>> isinstance(servo.status(), dict)
        True
        """
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

    def cleanup(self) -> None:
        """
        Release the servo output.

        Examples
        --------
        >>> servo = ServoMotor(register_cleanup=False)
        >>> servo.cleanup()
        """
        try:
            self.logger.debug("Cleaning up servo channel=%s", self.channel)
            self.kit.servo[self.channel].angle = None
        except Exception:
            self.logger.debug("Servo cleanup failed")

    def _state_from_angle(self, angle: int) -> str:
        """
        Map a servo angle to a human-readable state label.

        Parameters
        ----------
        angle : int
            Servo angle in degrees.

        Returns
        -------
        str
            ``"open"`` when the angle matches ``open_angle``, ``"closed"``
            when it matches ``close_angle``, otherwise ``"partial"``.

        Examples
        --------
        >>> servo = ServoMotor(register_cleanup=False)
        >>> servo._state_from_angle(servo.open_angle)
        'open'
        """
        if angle == self.open_angle:
            return "open"
        if angle == self.close_angle:
            return "closed"
        return "partial"


class StepperMotor(Motor):
    """
    Control a GPIO-driven stepper motor using step and direction pins.

    Parameters
    ----------
    step_pin : int, default=20
        Raspberry Pi GPIO pin wired to the motor driver STEP input.
    dir_pin : int, default=21
        Raspberry Pi GPIO pin wired to the motor driver DIR input.
    steps_per_rev : int, default=200
        Full-step count per shaft revolution after accounting for driver
        microstepping.
    step_delay : float, default=0.001
        Delay in seconds between GPIO transitions when stepping.
    default_speed : float, default=1.0
        Default rotation speed in revolutions per second.
    mode : {"BCM", "BOARD"}, default="BCM"
        Pin numbering scheme used when choosing ``step_pin`` and ``dir_pin``.
    register_cleanup : bool, default=True
        Register cleanup with ``atexit`` so GPIO pins are reset on exit.
    name : str, optional
        Logger name override for this motor instance.
    log_level : int or str, default=logging.INFO
        Logging verbosity for this motor instance.

    Attributes
    ----------
    step_pin : int
        GPIO pin used for the step signal.
    dir_pin : int
        GPIO pin used for the direction signal.
    position : int
        Current tracked position in steps.
    connected : bool
        Whether GPIO pins have been configured for output.

    Examples
    --------
    Connect a stepper and rotate it clockwise.

    >>> motor = StepperMotor(step_pin=20, dir_pin=21)
    >>> motor.connect()
    >>> motor.rotate_cw(0.5)

    Rotate the motor counterclockwise with an explicit speed.

    >>> motor.rotate_ccw(1.0, speed=2.0)
    >>> motor.status()["connected"]
    True
    """
    DEFAULTS = {
        "step_pin": 20,
        "dir_pin": 21,
        "steps_per_rev": 200,
        "step_delay": 0.001,
        "default_speed": 1.0,
        "mode": "BCM",
        "register_cleanup": True,
        "name": None,
        "log_level": logging.INFO,
    }

    def __init__(self, **kwargs) -> None:
        """
        Initialize the stepper motor helper.

        Parameters
        ----------
        **kwargs
            Optional configuration overrides merged with :attr:`DEFAULTS`.
        """
        config = {**self.DEFAULTS, **kwargs}
        super().__init__(name=config.get("name"), log_level=config.get("log_level", logging.INFO))
        self.step_pin = config["step_pin"]
        self.dir_pin = config["dir_pin"]
        self.steps_per_rev = config["steps_per_rev"]
        self.step_delay = config["step_delay"]
        self.default_speed = config["default_speed"]
        self.mode = config["mode"]
        self.position = 0
        self.connected = False
        self.GPIO = lazy.load("RPi.GPIO", require="AFL-automation[rpi-gpio]")
        self.logger.debug(
            "Initialized stepper motor step_pin=%s dir_pin=%s steps_per_rev=%s step_delay=%s default_speed=%s mode=%s",
            self.step_pin,
            self.dir_pin,
            self.steps_per_rev,
            self.step_delay,
            self.default_speed,
            self.mode,
        )

        if config["register_cleanup"]:
            atexit.register(self.cleanup)

    def connect(self) -> None:
        """
        Configure the GPIO pins for stepper control.

        Raises
        ------
        ValueError
            If ``mode`` is not ``"BCM"`` or ``"BOARD"``.

        Examples
        --------
        >>> motor = StepperMotor(mode="BCM")
        >>> motor.connect()
        """
        if self.connected:
            self.logger.debug("Stepper already connected on STEP=%s DIR=%s", self.step_pin, self.dir_pin)
            return

        self.logger.debug("Connecting stepper with mode=%s", self.mode)
        self.GPIO.setwarnings(False)
        if self.mode == "BCM":
            self.GPIO.setmode(self.GPIO.BCM)
        elif self.mode == "BOARD":
            self.GPIO.setmode(self.GPIO.BOARD)
        else:
            raise ValueError("invalid mode in StepperMotor")

        self.GPIO.setup(self.step_pin, self.GPIO.OUT, initial=self.GPIO.LOW)
        self.GPIO.setup(self.dir_pin, self.GPIO.OUT, initial=self.GPIO.LOW)
        self.connected = True
        self.logger.info(f"Stepper motor connected on STEP={self.step_pin} DIR={self.dir_pin}")

    def cleanup(self) -> None:
        """
        Reset the configured GPIO pins and mark the motor disconnected.

        Examples
        --------
        >>> motor = StepperMotor(register_cleanup=False)
        >>> motor.cleanup()
        """
        if not self.connected:
            self.logger.debug("Stepper cleanup skipped because motor is not connected")
            return
        try:
            self.logger.debug("Cleaning up stepper STEP=%s DIR=%s", self.step_pin, self.dir_pin)
            self.GPIO.output(self.step_pin, self.GPIO.LOW)
            self.GPIO.output(self.dir_pin, self.GPIO.LOW)
            self.GPIO.cleanup((self.step_pin, self.dir_pin))
        except Exception:
            self.logger.debug("Stepper cleanup failed")
        finally:
            self.connected = False

    def rotate_cw(
        self,
        rotations: float,
        speed: Optional[float] = None,
        step_delay: Optional[float] = None,
    ) -> None:
        """
        Rotate the motor clockwise.

        Parameters
        ----------
        rotations : float
            Number of shaft rotations to execute.
        speed : float, optional
            Rotational speed in revolutions per second.
        step_delay : float, optional
            Explicit delay between GPIO transitions. If provided, it overrides the
            delay derived from ``speed``.

        Examples
        --------
        >>> motor = StepperMotor()
        >>> motor.connect()
        >>> motor.rotate_cw(0.25)
        """
        resolved_speed = self.default_speed if speed is None else speed
        self.logger.debug(
            "Requested clockwise rotation rotations=%s speed=%s step_delay=%s",
            rotations,
            resolved_speed,
            step_delay,
        )
        self._step(
            direction=self.GPIO.HIGH,
            rotations=rotations,
            speed=resolved_speed,
            step_delay=step_delay,
        )

    def rotate_ccw(
        self,
        rotations: float,
        speed: Optional[float] = None,
        step_delay: Optional[float] = None,
    ) -> None:
        """
        Rotate the motor counterclockwise.

        Parameters
        ----------
        rotations : float
            Number of shaft rotations to execute.
        speed : float, optional
            Rotational speed in revolutions per second.
        step_delay : float, optional
            Explicit delay between GPIO transitions. If provided, it overrides the
            delay derived from ``speed``.

        Examples
        --------
        >>> motor = StepperMotor()
        >>> motor.connect()
        >>> motor.rotate_ccw(0.25, speed=1.5)
        """
        resolved_speed = self.default_speed if speed is None else speed
        self.logger.debug(
            "Requested counterclockwise rotation rotations=%s speed=%s step_delay=%s",
            rotations,
            resolved_speed,
            step_delay,
        )
        self._step(
            direction=self.GPIO.LOW,
            rotations=rotations,
            speed=resolved_speed,
            step_delay=step_delay,
        )

    def home(self) -> None:
        """
        Reset the tracked position to zero.

        Notes
        -----
        This method only resets the software position counter. It does not move
        the motor to a physical home switch.

        Examples
        --------
        >>> motor = StepperMotor()
        >>> motor.home()
        """
        self.logger.debug("Resetting stepper tracked position from %s to 0", self.position)
        self.position = 0
        self.logger.info("Stepper motor homed to position 0")

    def status(self) -> Dict[str, object]:
        """
        Return the current stepper configuration and tracked position.

        Returns
        -------
        dict
            Dictionary containing GPIO configuration, connection state, and
            tracked position.

        Examples
        --------
        >>> motor = StepperMotor()
        >>> isinstance(motor.status(), dict)
        True
        """
        return {
            "step_pin": self.step_pin,
            "dir_pin": self.dir_pin,
            "steps_per_rev": self.steps_per_rev,
            "step_delay": self.step_delay,
            "position_steps": self.position,
            "position_rotations": self.position / self.steps_per_rev,
            "connected": self.connected,
            "mode": self.mode,
        }

    def _step(
        self,
        direction: int,
        rotations: float,
        speed: Optional[float] = None,
        step_delay: Optional[float] = None,
    ) -> None:
        """
        Execute a low-level stepper move.

        Parameters
        ----------
        direction : int
            GPIO direction value written to ``dir_pin``.
        rotations : float
            Number of shaft rotations to convert into step pulses.
        speed : float, optional
            Rotational speed in revolutions per second. When positive, this is
            used to derive ``step_delay``.
        step_delay : float, optional
            Explicit half-period delay between GPIO transitions. When omitted,
            the delay is derived from ``speed`` or falls back to the configured
            default.

        Raises
        ------
        RuntimeError
            Raised when the stepper has not been connected before motion is
            requested.

        Notes
        -----
        This helper performs the actual GPIO pulse generation used by
        :meth:`rotate_cw` and :meth:`rotate_ccw`.

        Examples
        --------
        >>> motor = StepperMotor(register_cleanup=False)
        >>> motor.connected = True
        >>> motor.position = 0
        """
        if not self.connected:
            raise RuntimeError("Stepper motor is not connected")
        if rotations <= 0:
            self.logger.debug("Ignoring non-positive stepper rotation request: %s", rotations)
            return

        n_steps = int(round(rotations * self.steps_per_rev))
        if n_steps == 0:
            self.logger.debug(
                "Rounded stepper rotation request to zero steps rotations=%s steps_per_rev=%s",
                rotations,
                self.steps_per_rev,
            )
            return

        if speed is not None and speed > 0.0:
            step_delay = 1.0 / (2.0 * self.steps_per_rev * speed)
        step_delay = self.step_delay if step_delay is None else step_delay
        direction_name = "cw" if direction == self.GPIO.HIGH else "ccw"
        self.logger.debug(
            "Executing stepper motion direction=%s rotations=%s n_steps=%s speed=%s step_delay=%s start_position=%s",
            direction_name,
            rotations,
            n_steps,
            speed,
            step_delay,
            self.position,
        )

        self.GPIO.output(self.dir_pin, direction)
        for _ in range(n_steps):
            self.GPIO.output(self.step_pin, self.GPIO.HIGH)
            time.sleep(step_delay)
            self.GPIO.output(self.step_pin, self.GPIO.LOW)
            time.sleep(step_delay)

        if direction == self.GPIO.HIGH:
            self.position += n_steps
        else:
            self.position = max(0, self.position - n_steps)
        self.logger.debug(
            "Completed stepper motion direction=%s end_position=%s end_rotations=%s",
            direction_name,
            self.position,
            self.position / self.steps_per_rev,
        )
