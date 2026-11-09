"""Calibrated, YAML-backed station classes for the direct xArm workcell."""

from __future__ import annotations

from copy import deepcopy
import json
import math
import re
import logging
import time
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import lazy_loader as lazy
import numpy as np

yaml = lazy.load("yaml", require="AFL-automation[ufactory]")

from .helpers import _joint_pose, _rotation, _rpy, pose
from .labware import Labware, _offset_mm

Pose = Tuple[float, float, float, float, float, float]
Vector3 = Tuple[float, float, float]
CONFIG_DIRECTORY = Path(__file__).with_name("configs")
_UNSET = object()


def station_operation(method=None, *, resumes_context=False, arm_keyword=False):
    """Expose an operation; continuations must validate their saved context.

    arm_keyword preserves positional arguments on APIs also called directly.
    """
    if method is None:
        return partial(station_operation, resumes_context=resumes_context, arm_keyword=arm_keyword)
    method._station_operation = True
    method._station_arm_keyword = arm_keyword
    method._resumes_station_context = resumes_context
    return method


def _vector(value: object, name: str) -> Vector3:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must contain three finite values")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} must contain three finite values")
    return result  # type: ignore[return-value]


def _poses_config(value, default_approach=None):
    """Normalize entries to approach -> base/named location -> joint pose.

    Legacy single joint lists become a base, either for the default approach
    or for the approach containing that list. Only base may be null.
    """
    if not isinstance(value, dict):
        value = {default_approach: {"base": _joint_pose(value, "poses")}}
    result = {}
    for approach, entries in value.items():
        name = f"poses.{approach}"
        if not isinstance(entries, dict):
            entries = {"base": _joint_pose(entries, name)}
        normalized = {}
        for location, entry in entries.items():
            if not isinstance(location, str) or not location.strip():
                raise ValueError(f"{name} location names must be nonempty strings")
            key = location.strip().lower()
            if key in normalized:
                raise ValueError(f"{name} has duplicate location {location!r}")
            normalized[key] = (None if key == "base" and entry is None
                               else _joint_pose(entry, f"{name}.{location}"))
        result[approach] = {"base": None, **normalized}
    return result

class StationMotion:
    """Execute a station sequence immediately, retaining its entry RPY."""

    def __init__(self, station, arm, entry, target, item=None, bottom=None, *, hold_time_s=0.,
                 grasp=None, force=None, speed=None):
        self.station = station
        self.arm = arm
        self.entry = tuple(entry)
        self.target = tuple(target)
        self.position = self.entry
        self.item = item
        self.bottom = bottom
        self.hold_time_s = hold_time_s
        self.grasp_width_mm = grasp
        self.gripper_force = force
        self.gripper_speed = speed

    @property
    def target_delta(self):
        rotation = np.asarray(_rotation(self.station.pose[3:]))
        return tuple(rotation.T @ (np.asarray(self.target[:3]) - np.asarray(self.position[:3])))

    def move_to(self, x, y, z):
        """Execute one linear TCP leg while retaining the entry orientation."""
        target = (x, y, z, *self.entry[3:])
        self.arm._step(f"move at {self.station.name}",
                       lambda: self.arm._move_pose(target, self.station.name))
        self.position = target

    def move_relative(self, dx=0., dy=0., dz=0.):
        delta = np.asarray(_rotation(self.station.pose[3:])) @ np.asarray((dx, dy, dz))
        self.move_to(*(self.position[i] + delta[i] for i in range(3)))

    def open_gripper(self):
        self.arm._step("open gripper", lambda: self.arm._set_gripper(
            opened=True, labware=self.item, grasp=self.grasp_width_mm,
            force=self.gripper_force, speed=self.gripper_speed))

    def _hold_before_gripper(self, action):
        if self.hold_time_s > 0:
            label = f"hold {self.hold_time_s:g} s at {self.station.name} before {action}"
            self.arm._step(label, lambda: time.sleep(self.hold_time_s))

    def grasp(self):
        self._hold_before_gripper("close gripper")
        self.arm._step("close gripper", lambda: self.arm._set_gripper(
            opened=False, labware=self.item, grasp=self.grasp_width_mm,
            force=self.gripper_force, speed=self.gripper_speed))
        self.arm._capture_attachment(self.item, self.position, self.bottom,
                                     grasp=self.grasp_width_mm)

class Station:
    """Station geometry, calibrated joint entries, and directly executed operations.

    Runtime Cartesian pose/locations and direct config dictionaries use metres/radians.
    Rail positions use millimetres. YAML loaders convert Cartesian millimetres before
    construction. Entry joints use degrees. Station-geometry bounds in existing YAML
    files do not constrain Cartesian motion.
    """

    location_reference = "configured location"
    location_frame = "link_base"
    default_approach = None

    @staticmethod
    def _load_config(filename: str, config_path: Optional[str]) -> Dict[str, object]:
        """Load YAML geometry, keeping rail positions in mm and converting Cartesian distances to m."""
        path = Path(config_path) if config_path is not None else CONFIG_DIRECTORY / filename
        try:
            with path.open(encoding="utf-8") as stream:
                data = yaml.safe_load(stream)
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"could not load station configuration {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"station configuration {path} must be a mapping")
        if "pose" in data:
            values = data["pose"]
            data["pose"] = [*(float(value) / 1000. for value in values[:3]), *values[3:]]
        if data.get("rail_position") is not None:
            data["rail_position"] = float(data["rail_position"])
        for key in ("location", "engage_location"):
            if data.get(key) is not None:
                data[key] = [value / 1000. for value in _vector(data[key], key)]
        if "locations" in data:
            if not isinstance(data["locations"], dict):
                raise ValueError("locations must be a mapping")
            converted = {}
            for key, location in data["locations"].items():
                if isinstance(location, dict):
                    location = dict(location)
                    location["xyz"] = [
                        value / 1000.
                        for value in _vector(location.get("xyz"), f"locations.{key}.xyz")
                    ]
                    converted[key] = location
                else:
                    converted[key] = [
                        value / 1000. for value in _vector(location, f"locations.{key}")
                    ]
            data["locations"] = converted
        return data

    def __init__(self, config):
        self.name = config["name"]
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError("station name must contain only letters, numbers, and underscores")
        raw_pose = tuple(config.get("pose", (0.,) * 6))
        if len(raw_pose) == 3:
            raw_pose = (*raw_pose, 0., 0., 0.)
        self.pose = pose(raw_pose)
        self.frame_id = "link_base"
        rail_position = config.get("rail_position")
        if rail_position is not None:
            if (isinstance(rail_position, bool) or not isinstance(rail_position, (int, float))
                    or not math.isfinite(rail_position)):
                raise ValueError("rail_position must be a finite number in millimetres")
            rail_position = float(rail_position)
        self.linear_rail_position = rail_position
        self.location = config.get("location")
        self.locations = {}
        self.location_entries = {}
        self.location_routes = {}
        raw_locations = config.get("locations", {})
        if not isinstance(raw_locations, dict):
            raise ValueError("locations must be a mapping")
        for name, definition in raw_locations.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("location names must be nonempty strings")
            key = name.strip().upper()
            if key in self.locations:
                raise ValueError(f"duplicate location {name!r}")
            if isinstance(definition, dict):
                missing = {"xyz", "entries", "route"} - definition.keys()
                if missing:
                    raise ValueError(
                        f"locations.{name} requires xyz, entries, and route; "
                        f"missing {tuple(sorted(missing))}"
                    )
                unknown = definition.keys() - {"xyz", "entries", "route"}
                if unknown:
                    raise ValueError(f"locations.{name} has unknown fields {tuple(sorted(unknown))}")
                entries = definition["entries"]
                if not isinstance(entries, dict) or not entries:
                    raise ValueError(f"locations.{name}.entries must be a nonempty mapping")
                normalized_entries = {}
                for approach, entry in entries.items():
                    if not isinstance(approach, str) or not approach.strip():
                        raise ValueError(
                            f"locations.{name}.entries approaches must be nonempty strings"
                        )
                    if not isinstance(entry, str) or not entry.strip():
                        raise ValueError(
                            f"locations.{name}.entries.{approach} must name an entry pose"
                        )
                    normalized_entries[approach.strip()] = entry.strip().lower()
                route = definition["route"]
                if not isinstance(route, str) or not route.strip():
                    raise ValueError(f"locations.{name}.route must be a nonempty string")
                xyz = definition["xyz"]
                self.location_entries[key] = normalized_entries
                self.location_routes[key] = route.strip().lower()
            else:
                xyz = definition
            self.locations[key] = _vector(xyz, f"locations.{name}.xyz")
        self.poses = _poses_config(config["poses"], self.default_approach)
        for location_name, entries in self.location_entries.items():
            for approach, entry in entries.items():
                if approach not in self.poses:
                    raise ValueError(
                        f"location {location_name!r} references unknown approach {approach!r}"
                    )
                if entry not in self.poses[approach] or entry == "base":
                    raise ValueError(
                        f"location {location_name!r} references unknown entry pose "
                        f"poses.{approach}.{entry}"
                    )

    @property
    def available_operations(self):
        """Discover decorated class methods, including inherited operations."""
        return tuple(name for name in dir(type(self))
                     if not name.startswith("_")
                     and getattr(getattr(type(self), name), "_station_operation", False) is True)

    @property
    def available_approaches(self):
        return tuple(self.poses) if isinstance(self.poses, dict) else (self.default_approach,)

    def resolve_approach(self, approach=None):
        selected = self.default_approach if approach is None else approach
        if selected not in self.available_approaches:
            raise ValueError(f"{self.name} has no calibrated {selected!r} approach; "
                             f"available approaches: {self.available_approaches}")
        return selected

    def resolve_entry_pose(self, approach=None, *, location=None, all_entries=False):
        """Resolve the final entry, or the complete base-to-location sequence."""
        selected = self.resolve_approach(approach)
        entries = _poses_config(self.poses, self.default_approach)[selected]
        base = entries["base"]
        specifics = {key: entry for key, entry in entries.items() if key != "base"}
        key = self._entry_location_key(location)
        if isinstance(location, str):
            configured = self.location_entries.get(location.strip().upper(), {})
            key = configured.get(selected, key)
        if key in specifics:
            resolved = (specifics[key],) if base is None else (base, specifics[key])
        elif base is not None and (location is None or not specifics):
            resolved = (base,)
        else:
            raise ValueError(f"{self.name} {selected} entry requires a calibrated location "
                             f"from {tuple(specifics)}; got {location!r}")
        return resolved if all_entries else resolved[-1]

    def _entry_location_key(self, location):
        return location.strip().lower() if isinstance(location, str) else None

    def resolve_location_route(self, location):
        """Resolve motion-route semantics independently of a location's public name."""
        if not isinstance(location, str):
            return None
        key = location.strip().upper()
        return self.location_routes.get(key, key.lower())

    def to_arm(self, local_xyz):
        offset = np.asarray(_rotation(self.pose[3:])) @ np.asarray(local_xyz)
        return tuple(self.pose[i] + offset[i] for i in range(3))

    def to_local(self, arm_xyz):
        rotation = np.asarray(_rotation(self.pose[3:]))
        return tuple(rotation.T @ (np.asarray(arm_xyz) - np.asarray(self.pose[:3])))

    def resolve_local_location(self, address=None):
        if address is None:
            if self.location is None:
                raise ValueError(f"{self.name} requires a named location; choose from {', '.join(self.locations)}")
            return self.location
        if isinstance(address, (tuple, list)):
            return tuple(address)
        return self.locations[address.upper()]

    def resolve_location(self, address=None):
        """Locations are arm-base XYZ; pose RPY supplies the labware orientation."""
        location = self.resolve_local_location(address)
        return (*location, *self.pose[3:])

    def enter(self, arm, *, approach=None, location=None):
        return arm.move_to_station((self, location), approach=approach)

    @contextmanager
    def relative_motion(self, arm):
        previous = getattr(arm, "_station_relative_motion", None)
        arm._station_relative_motion = StationMotion(self, arm, arm._last_tcp_pose, arm._last_tcp_pose)
        try:
            yield self
        finally:
            arm._station_relative_motion = previous

    def move_relative(self, arm, dx=0., dy=0., dz=0.):
        motion = getattr(arm, "_station_relative_motion", None)
        if motion is None:
            motion = StationMotion(self, arm, arm._last_tcp_pose, arm._last_tcp_pose)
        motion.move_relative(dx, dy, dz)
        return motion.position

    @staticmethod
    def _hold_duration(hold_time_s):
        duration = float(hold_time_s)
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("hold_time_s must be finite and nonnegative")
        return duration

    def _pause_at_endpoint(self, arm, operation, motion, entry_poses, retreat_waypoints,
                           *, release=None, retreat=False, release_allowed=False,
                           hold_time_s=0.):
        """Save an endpoint and optionally execute its release and retreat phases."""
        arm._validate_operation_flags(release=release, retreat=retreat)
        context = arm._set_station_context(
            self, operation, motion.item, getattr(motion, "address", None), motion.position,
            entry_poses, getattr(motion, "approach", None), retreat_waypoints,
            retreat_rpy=motion.entry[3:],
            release_allowed=release_allowed, hold_time_s=hold_time_s,
        )
        if release:
            arm._release_station_context(verify_pose=False)
        if retreat:
            arm._retreat_station_context(verify_pose=False)
        return {
            "labware_id": context.item.name if context.item is not None else None,
            "phase": context.phase,
            "can_release": bool(release_allowed and context.phase == "at_target"),
            "can_retreat": context.phase != "at_base",
        }

    @staticmethod
    def _resolve_grasp_width(item, grasp=None, grasp_offset_mm=None):
        """Return the jaw gap sent to the SDK after a scalar correction."""
        if grasp_offset_mm is None:
            correction = 0.
        elif (isinstance(grasp_offset_mm, bool)
              or not isinstance(grasp_offset_mm, (int, float))):
            raise ValueError("grasp_offset_mm must be a finite float")
        else:
            correction = float(grasp_offset_mm)
        if not math.isfinite(correction):
            raise ValueError("grasp_offset_mm must be a finite float")
        width_mm = item.resolve_grasp_mm(grasp) + correction
        if not math.isfinite(width_mm) or width_mm <= 0:
            raise ValueError("grasp plus grasp_offset_mm must be finite and positive")
        return width_mm

    @staticmethod
    def _validate_target_options(item, use_labware_offset, tcp_offset_mm=None):
        if not isinstance(use_labware_offset, bool):
            raise ValueError("use_labware_offset must be a boolean")
        if use_labware_offset and item is None:
            raise ValueError("labware is required when use_labware_offset=True")
        if item is not None and (not math.isfinite(item.height_mm) or item.height_mm < 0):
            raise ValueError("labware height must be finite and nonnegative")
        return _offset_mm(tcp_offset_mm, name="tcp_offset_mm")

    def _target_geometry(self, item, reference, rpy, *, tcp_offset_mm=None,
                         use_labware_offset=False):
        """Reference + optional local height + additive robot-base XYZ correction.

        The physical object bottom remains one full object height below the
        final reference, including when the station already supplies that height.
        """
        correction = self._validate_target_options(item, use_labware_offset, tcp_offset_mm)
        height = item.height_m if item is not None else 0.
        rotation = np.asarray(_rotation(reference[3:]))
        dimension = rotation @ np.asarray((0., 0., height if use_labware_offset else 0.))
        final = tuple(reference[i] + dimension[i] for i in range(3))
        delta = tuple(v / 1000. for v in correction)
        target = (*tuple(final[i] + delta[i] for i in range(3)), *rpy)
        physical_height = rotation @ np.asarray((0., 0., height))
        bottom = (*tuple(final[i] - physical_height[i] for i in range(3)), *reference[3:])
        return target, bottom, final

    def _pickup_target(self, item, location, rpy, *, grasp=None, tcp_offset_mm=None,
                       use_labware_offset=False):
        return self._target_geometry(item, location, rpy, tcp_offset_mm=tcp_offset_mm,
                                     use_labware_offset=use_labware_offset)[0]

    def _held_reference(self, arm, location, rpy):
        # Carry the measured object orientation through a changed wrist attitude.
        orientation = arm._compose_pose((0., 0., 0., *rpy), arm._attachment.tcp_to_object)[3:]
        return (*location[:3], *orientation)

    def _placement_target(self, arm, location, rpy, *, tcp_offset_mm=None, use_labware_offset=False):
        reference = self._held_reference(arm, location, rpy)
        return self._target_geometry(arm.attached_labware, reference, rpy,
                                     tcp_offset_mm=tcp_offset_mm,
                                     use_labware_offset=use_labware_offset)[0]
class OT2(Station):
    """OT-2 station with Opentrons-native labware geometry.

    The Opentrons simulator expresses deck points in millimetres.  This class
    converts them to metres before applying the measured deck-to-``link_base``
    rigid transform from its station YAML file.

    Pick and place define their own relative XYZ sequences to top-center.
    Approach and retreat retain the entry attitude.
    """

    default_approach = "vertical"
    location_reference = "Opentrons well top"

    @staticmethod
    def _debug_filter(record: logging.LogRecord) -> bool:
        """Keep Opentrons progress messages out of operator INFO logs."""
        if not record.name.startswith("opentrons") or record.levelno >= logging.WARNING:
            return True
        if not logging.getLogger().isEnabledFor(logging.DEBUG):
            return False
        record.levelno = logging.DEBUG
        record.levelname = "DEBUG"
        return True

    @classmethod
    def _configure_logging(cls) -> None:
        root = logging.getLogger()
        for handler in root.handlers:
            if cls._debug_filter not in handler.filters:
                handler.addFilter(cls._debug_filter)

    def loaded_labware_max_z(self):
        """Return the highest loaded well top in ``link_base`` coordinates."""
        if self.deck_rotation is None:
            raise RuntimeError("OT-2 deck calibration is required before planning deck clearance")
        tops = [self._well_pose(well)[2]
                for labware in self.loaded_labware.values()
                for well in labware.wells_by_name().values()]
        if not tops:
            raise RuntimeError("OT-2 requires loaded labware before planning deck clearance")
        return max(tops)

    def _deck_travel_z(self, motion, *, carrying=False):
        """Calculate a TCP Z that clears all loaded labware by the configured margin."""
        item_height = motion.item.height_m if carrying and motion.item is not None else 0.
        obstacle_z = self.loaded_labware_max_z() + self.deck_clearance_m + item_height
        entry_z = motion.entry[2] + (item_height if carrying else 0.)
        return max(obstacle_z, entry_z, motion.target[2])

    @staticmethod
    def _raise_before_deck_travel(motion, travel_z):
        if motion.position[2] < travel_z:
            motion.move_to(motion.position[0], motion.position[1], travel_z)

    @station_operation
    def pick(self, arm, labware, location=None, *, grasp=None, grasp_offset_mm=None,
             tcp_offset_mm=None, use_labware_offset=False, hold_time_s=0.,
             approach="vertical", retreat=False, force=None, speed=None):
        """Pick labware with optional gripper force and speed overrides."""
        def perform():
            arm._ensure_station_context_clear()
            arm._validate_operation_flags(retreat=retreat)
            pick_force, pick_speed = arm._resolve_gripper_settings(force=force, speed=speed)
            duration = self._hold_duration(hold_time_s)
            address = self.resolve_address(location)
            grasp_width_mm = self._resolve_grasp_width(labware, grasp, grasp_offset_mm)
            source = "zero correction" if tcp_offset_mm is None else "explicit additive correction"
            correction = self._validate_target_options(labware, use_labware_offset, tcp_offset_mm)
            selected = self.resolve_approach(approach)
            entries = self.resolve_entry_pose(selected, location=address, all_entries=True)
            arm._gripper_gap(labware, opened=True, grasp=grasp_width_mm)
            entry = arm._step(f"enter {self.name}",
                              lambda: arm._enter(self, approach=selected, location=address))
            record = arm._placements.get(labware.name)
            reference = self.resolve_location(address)
            if record is not None and record.station is self and record.address == address:
                reference = (*reference[:3], *record.pose[3:])
            target, bottom, final = self._target_geometry(
                labware, reference, entry[3:], tcp_offset_mm=correction,
                use_labware_offset=use_labware_offset)
            arm._log_tcp_offset("pickup", self, address, labware, grasp=grasp_width_mm, source=source,
                                base_offset_mm=correction, reference=reference, final=final,
                                use_labware_offset=use_labware_offset, target=target)
            motion = StationMotion(self, arm, entry, target, labware, bottom,
                                   hold_time_s=duration, grasp=grasp_width_mm,
                                   force=pick_force, speed=pick_speed)
            motion.address = address
            motion.approach = selected
            motion.open_gripper()
            approach_z = self._deck_travel_z(motion)
            self._raise_before_deck_travel(motion, approach_z)
            motion.move_to(motion.entry[0], motion.target[1], approach_z)
            motion.move_to(*motion.target[:2], approach_z)
            motion.move_to(*motion.target[:3])
            motion.grasp()
            retreat_z = self._deck_travel_z(motion, carrying=True)
            route = [
                (*motion.target[:2], retreat_z),
                (motion.entry[0], motion.target[1], retreat_z),
                (*motion.entry[:2], retreat_z),
            ]
            return self._pause_at_endpoint(
                arm, "pickup", motion, entries, route, retreat=retreat)

        return arm._run_operation("pickup", perform)

    @station_operation
    def place(self, arm, location=None, *, tcp_offset_mm=None, use_labware_offset=False, hold_time_s=0.,
              approach=None, release=False, retreat=False):
        def perform():
            arm._ensure_station_context_clear()
            arm._validate_operation_flags(release=release, retreat=retreat)
            duration = self._hold_duration(hold_time_s)
            item = arm.attached_labware
            if item is None:
                raise ValueError("placement requires attached labware")
            source = "zero correction" if tcp_offset_mm is None else "explicit additive correction"
            correction = self._validate_target_options(item, use_labware_offset, tcp_offset_mm)
            address = self.resolve_address(location)
            selected = arm._placement_approach(self, approach)
            entries = self.resolve_entry_pose(selected, location=address, all_entries=True)
            entry = arm._step(f"enter {self.name}",
                              lambda: arm._enter(self, approach=selected, location=address))
            reference = self._held_reference(arm, self.resolve_location(address), entry[3:])
            target, _, final = self._target_geometry(
                item, reference, entry[3:], tcp_offset_mm=correction,
                use_labware_offset=use_labware_offset)
            arm._log_tcp_offset("placement", self, address, item, grasp=arm._attachment.grasp,
                                source=source, base_offset_mm=correction, reference=reference,
                                final=final, use_labware_offset=use_labware_offset, target=target)
            motion = StationMotion(self, arm, entry, target, item, hold_time_s=duration)
            motion.address = address
            motion.approach = selected
            approach_z = self._deck_travel_z(motion, carrying=True)
            self._raise_before_deck_travel(motion, approach_z)
            motion.move_to(motion.entry[0], motion.target[1], approach_z)
            motion.move_to(*motion.target[:2], approach_z)
            motion.move_to(*motion.target[:3])
            route = [
                (*motion.target[:2], approach_z),
                (motion.entry[0], motion.target[1], approach_z),
                (*motion.entry[:2], approach_z),
            ]
            return self._pause_at_endpoint(
                arm, "placement", motion, entries, route, release=release,
                retreat=retreat, release_allowed=True, hold_time_s=duration)

        return arm._run_operation("placement", perform)

    def __init__(
        self,
        config_path: Optional[str] = None,
        *,
        linear_rail_position: object = _UNSET,
        api_level: str = "2.15",
        module_definitions: Optional[Dict[str, Dict[str, object]]] = None,
        labware_definitions: Optional[Dict[str, Dict[str, object]]] = None,
    ) -> None:
        self._configure_logging()
        config = self._load_config("ot2.yaml", config_path)
        if linear_rail_position is not _UNSET:
            config["rail_position"] = linear_rail_position
        super().__init__(config)
        if not self.poses or not set(self.poses) <= {"horizontal", "vertical"}:
            raise ValueError("OT2 poses must use horizontal or vertical approaches")
        if not isinstance(api_level, str) or re.fullmatch(r"2\.\d+", api_level) is None:
            raise ValueError("OT-2 api_level must look like '2.15'")
        self.api_level = api_level
        clearance = config.get("deck_clearance_mm")
        if (isinstance(clearance, bool) or not isinstance(clearance, (int, float))
                or not math.isfinite(clearance) or clearance < 0):
            raise ValueError("OT2 deck_clearance_mm must be a finite nonnegative number")
        self.deck_clearance_m = float(clearance) / 1000.
        calibration = self._parse_deck_calibration(config.get("deck_calibration"))
        self.deck_rotation, self.deck_translation, self.deck_max_residual_m = calibration
        self.loaded_labware: Dict[str, Any] = {}
        self.loaded_modules: Dict[str, Any] = {}
        self._custom_labware_definitions: Dict[str, Dict[str, Any]] = {}
        self._labware_slots: Dict[int, str] = {}
        self._module_slots: Dict[int, str] = {}
        self._registered_wells: Dict[int, Tuple[Any, str, str]] = {}
        self._protocol: Any = None
        self._load_configured_deck(module_definitions, labware_definitions)

    @staticmethod
    def _named_definitions(value, name):
        """Validate a JSON-safe mapping of stable names to constructor options."""
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be a mapping of names to definitions")
        normalized = {}
        for label, definition in value.items():
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f"{name} names must be nonempty strings")
            if not isinstance(definition, dict):
                raise ValueError(f"{name}.{label} must be a mapping")
            normalized[label.strip()] = dict(definition)
        return normalized

    def _load_configured_deck(self, module_definitions, labware_definitions):
        """Load named modules, then labware whose location may name a module."""
        modules = self._named_definitions(module_definitions, "module_definitions")
        labware = self._named_definitions(labware_definitions, "labware_definitions")
        for label, definition in modules.items():
            unknown = set(definition) - {"model", "slot"}
            missing = {"model", "slot"} - set(definition)
            if missing or unknown:
                details = []
                if missing:
                    details.append(f"missing {tuple(sorted(missing))}")
                if unknown:
                    details.append(f"unknown {tuple(sorted(unknown))}")
                raise ValueError(f"module_definitions.{label} has " + "; ".join(details))
            self.load_module(definition["model"], definition["slot"], label=label)
        for label, definition in labware.items():
            allowed = {"load_name", "location", "namespace", "version", "definition", "definition_path"}
            unknown = set(definition) - allowed
            missing = {"location"} - set(definition)
            if missing or unknown:
                details = []
                if missing:
                    details.append(f"missing {tuple(sorted(missing))}")
                if unknown:
                    details.append(f"unknown {tuple(sorted(unknown))}")
                raise ValueError(f"labware_definitions.{label} has " + "; ".join(details))
            sources = set(definition) & {"load_name", "definition", "definition_path"}
            if len(sources) != 1:
                raise ValueError(
                    f"labware_definitions.{label} requires exactly one of "
                    "load_name, definition, or definition_path"
                )
            options = {
                key: definition[key]
                for key in ("load_name", "definition", "namespace", "version")
                if key in definition
            }
            if "definition_path" in definition:
                path_value = definition["definition_path"]
                if not isinstance(path_value, str) or not path_value.strip():
                    raise ValueError(f"labware_definitions.{label}.definition_path must be a nonempty string")
                path = Path(path_value).expanduser()
                try:
                    with path.open(encoding="utf-8") as stream:
                        options["definition"] = json.load(stream)
                except (OSError, json.JSONDecodeError) as exc:
                    raise ValueError(f"could not read OT-2 labware definition {path}: {exc}") from exc
            self.load_labware(slot=definition["location"], label=label, **options)

    pickup_reference = "top"

    @staticmethod
    def _parse_deck_calibration(value: object):
        """Build a metre-based rigid transform from three YAML surveys in mm."""
        if value is None:
            return None, None, None
        if not isinstance(value, dict):
            raise ValueError("OT2 deck_calibration must be null or a mapping")
        points = value.get("points")
        if not isinstance(points, list) or len(points) != 3:
            raise ValueError("OT2 deck_calibration.points must contain exactly three points")
        if "max_residual_m" in value:
            raise ValueError("use max_residual_mm and millimetre deck calibration coordinates")
        max_residual_m = float(value.get("max_residual_mm", 2.)) / 1000.
        if not math.isfinite(max_residual_m) or max_residual_m <= 0.0:
            raise ValueError("OT2 deck_calibration.max_residual_mm must be a positive finite value")
        deck_points = []
        arm_points = []
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                raise ValueError(f"OT2 deck_calibration.points[{index}] must be a mapping")
            deck_points.append(tuple(v / 1000. for v in _vector(
                point.get("deck"), f"OT2 deck calibration deck point {index}")))
            arm_points.append(tuple(v / 1000. for v in _vector(
                point.get("link_base"), f"OT2 deck calibration link_base point {index}")))
        bases = []
        for calibration_points, name in (
                (deck_points, "OT2 deck calibration deck"),
                (arm_points, "OT2 deck calibration link_base")):
            first, second, third = (np.asarray(point, dtype=float)
                                    for point in calibration_points)
            x_axis = second - first
            x_length = np.linalg.norm(x_axis)
            if x_length <= 1e-9:
                raise ValueError(f"{name} points must be distinct and non-collinear")
            x_axis /= x_length
            z_axis = np.cross(x_axis, third - first)
            z_length = np.linalg.norm(z_axis)
            if z_length <= 1e-9:
                raise ValueError(f"{name} points must be distinct and non-collinear")
            z_axis /= z_length
            bases.append((x_axis, np.cross(z_axis, x_axis), z_axis))
        deck_basis, arm_basis = bases
        # The basis vectors are columns. R = B_arm * B_deck^T.
        deck_matrix = np.column_stack(deck_basis)
        arm_matrix = np.column_stack(arm_basis)
        rotation = tuple(map(tuple, arm_matrix @ deck_matrix.T))
        mapped_origin = np.asarray(rotation) @ np.asarray(deck_points[0])
        translation = tuple(np.asarray(arm_points[0]) - mapped_origin)
        residuals = []
        for deck_point, arm_point in zip(deck_points, arm_points):
            mapped = np.asarray(rotation) @ np.asarray(deck_point)
            residuals.append(float(np.linalg.norm(
                np.asarray(mapped) + np.asarray(translation) - np.asarray(arm_point))))
        max_residual = max(residuals)
        if max_residual > max_residual_m:
            raise ValueError(
                "OT2 deck calibration maximum residual "
                f"{max_residual * 1000.0:.3f} mm exceeds {max_residual_m * 1000.0:.3f} mm"
            )
        return rotation, translation, max_residual

    @staticmethod
    def _well_name(value: object) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z]+[1-9]\d*", value) is None:
            raise ValueError("well name must look like 'B3'")
        return value.upper()

    def _apply_deck_transform(self, point: Sequence[float]) -> Vector3:
        if self.deck_rotation is None or self.deck_translation is None:
            raise RuntimeError("OT-2 deck calibration is required")
        source = _vector(point, "deck point")
        return tuple(np.asarray(self.deck_rotation) @ source + np.asarray(self.deck_translation))  # type: ignore[return-value]

    @property
    def deck_transform(self):
        """Expose the OT-2 itself as its deck transform for compatibility."""
        return self if self.deck_rotation is not None else None

    @property
    def max_residual_m(self):
        return self.deck_max_residual_m

    def apply(self, point: Sequence[float]) -> Vector3:
        return self._apply_deck_transform(point)

    def _deck_pose(self, point: Sequence[float]) -> Pose:
        return (*self._apply_deck_transform(point), *_rpy(self.deck_rotation))

    def _simulator_protocol(self) -> Any:
        """Create one lazy protocol context shared by modules and labware."""
        if self._protocol is not None:
            return self._protocol
        opentrons_simulate = lazy.load(
            "opentrons.simulate", require="AFL-automation[ufactory]"
        )
        try:
            self._protocol = opentrons_simulate.get_protocol_api(self.api_level)
            return self._protocol
        except ImportError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"could not create an Opentrons API {self.api_level} simulation context: {exc}"
            ) from exc

    @property
    def protocol(self) -> Any:
        """The underlying simulated ProtocolContext for advanced API use."""
        return self._simulator_protocol()

    def __getattr__(self, name: str) -> Any:
        """Delegate standard ProtocolContext commands, e.g. ``ot2.comment()``."""
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._simulator_protocol(), name)

    @staticmethod
    def _point_xyz_m(point: object) -> Vector3:
        """Read an Opentrons Location/Point and convert millimetres to metres."""
        # Modern protocol APIs return a Location from ``well.top()``;
        # earlier variants may return the Point itself.
        point = getattr(point, "point", point)
        try:
            values = (point.x, point.y, point.z)  # type: ignore[attr-defined]
        except AttributeError:
            try:
                values = tuple(point)  # type: ignore[arg-type]
            except TypeError as exc:
                raise RuntimeError("Opentrons returned an unreadable well position") from exc
        return tuple(float(item) / 1000.0 for item in values)  # type: ignore[return-value]

    def load_module(
        self, model: str, slot: object, *, label: Optional[str] = None
    ) -> Any:
        """Load an Opentrons module into a deck slot in this station context."""
        if not isinstance(model, str) or not model:
            raise ValueError("OT-2 module model must be a non-empty string")
        if not isinstance(slot, (str, int)) or re.fullmatch(r"[1-9]|1[0-2]", str(slot)) is None:
            raise ValueError("OT-2 module slot must be a deck slot from 1 through 12")
        resolved_label = label if label is not None else f"slot{slot}_{model}"
        if not isinstance(resolved_label, str) or not resolved_label:
            raise ValueError("OT-2 module label must be a non-empty string")
        if resolved_label in self.loaded_modules:
            raise ValueError(f"OT-2 module label {resolved_label!r} is already registered")
        try:
            native_module = self._simulator_protocol().load_module(model, str(slot))
        except Exception as exc:
            raise RuntimeError(
                f"could not simulate OT-2 module {model!r} in slot {slot}: {exc}"
            ) from exc
        self.loaded_modules[resolved_label] = native_module
        self._module_slots[id(native_module)] = str(slot)
        return native_module

    @station_operation(arm_keyword=True)
    def load_labware(
        self,
        load_name: Optional[str] = None,
        slot: object = None,
        *,
        namespace: Optional[str] = None,
        version: Optional[int] = None,
        label: Optional[str] = None,
        definition: Optional[Dict[str, Any]] = None,
        arm: Any = None,
    ) -> Any:
        """Load named labware or a custom JSON definition in this station.

        Direct calls return native Opentrons labware. The station dispatcher
        supplies the arm by keyword and receives JSON-safe rack metadata.
        Identical custom definitions reuse their existing label and slot.
        """
        if arm is not None:
            arm._ensure_station_context_clear()
            if arm.attached_labware is not None:
                raise ValueError("load OT-2 labware before picking up a vial")
        custom = definition is not None
        if custom:
            if not isinstance(definition, dict):
                raise ValueError("OT-2 labware definition must be a mapping")
            parameters = definition.get("parameters")
            definition_name = parameters.get("loadName") if isinstance(parameters, dict) else None
            if not isinstance(definition_name, str) or not definition_name.strip():
                raise ValueError("OT-2 labware definition requires parameters.loadName")
            if load_name is not None and load_name != definition_name:
                raise ValueError("load_name must match the custom definition's parameters.loadName")
            if namespace is not None or version is not None:
                raise ValueError("namespace and version are supplied by the custom definition")
            load_name = definition_name
        if not isinstance(load_name, str) or not load_name.strip():
            raise ValueError("OT-2 load_name must be a non-empty string")
        if isinstance(slot, str) and slot in self.loaded_modules:
            slot = self.loaded_modules[slot]
        is_module = id(slot) in self._module_slots
        if not is_module and (isinstance(slot, bool) or not isinstance(slot, (str, int))
                              or re.fullmatch(r"[1-9]|1[0-2]", str(slot)) is None):
            raise ValueError("OT-2 location must be a deck slot from 1 through 12 or a registered module")
        if namespace is not None and (not isinstance(namespace, str) or not namespace):
            raise ValueError("OT-2 namespace must be a non-empty string or None")
        if version is not None and (isinstance(version, bool) or not isinstance(version, int) or version < 1):
            raise ValueError("OT-2 version must be a positive integer or None")
        slot_name = self._module_slots[id(slot)] if is_module else str(slot)
        module_label = next((name for name, module in self.loaded_modules.items() if module is slot), None)
        location_label = module_label if is_module else f"slot{slot_name}"
        resolved_label = label if label is not None else f"{location_label}_{load_name}"
        if not isinstance(resolved_label, str) or not resolved_label.strip():
            raise ValueError("OT-2 labware label must be a non-empty string")
        existing = self.loaded_labware.get(resolved_label)
        if existing is not None:
            if not (custom and self._labware_slots[id(existing)] == slot_name
                    and self._custom_labware_definitions.get(resolved_label) == definition):
                raise ValueError(f"OT-2 labware label {resolved_label!r} is already registered")
            native_labware = existing
        else:
            if (slot_name in self._labware_slots.values()
                    or not is_module and slot_name in self._module_slots.values()):
                raise ValueError(f"OT-2 slot {slot_name} is already occupied")
            kwargs = {}
            if namespace is not None:
                kwargs["namespace"] = namespace
            if version is not None:
                kwargs["version"] = version
            stored_definition = deepcopy(definition) if custom else None
            try:
                if custom:
                    if is_module:
                        native_labware = slot.load_labware_from_definition(definition, label=resolved_label)
                    else:
                        native_labware = self._simulator_protocol().load_labware_from_definition(
                            definition, location=slot_name, label=resolved_label)
                elif is_module:
                    native_labware = slot.load_labware(load_name, **kwargs)
                else:
                    native_labware = self._simulator_protocol().load_labware(
                        load_name, location=slot_name, **kwargs)
            except Exception as exc:
                raise RuntimeError(
                    f"could not simulate OT-2 labware {load_name!r} at {location_label!r}: {exc}"
                ) from exc
            self._register_labware(resolved_label, native_labware, slot_name)
            if custom:
                self._custom_labware_definitions[resolved_label] = stored_definition
        if arm is not None:
            return {"name": resolved_label, "slot": slot_name, "wells": list(native_labware.wells_by_name())}
        return native_labware

    def _register_labware(self, label, native_labware, slot):
        """Index a simulator labware object and its native wells."""
        wells = native_labware.wells_by_name()
        if not wells:
            raise RuntimeError(f"Opentrons returned no wells for {label!r}")
        self.loaded_labware[label] = native_labware
        self._labware_slots[id(native_labware)] = str(slot)
        for name, well in wells.items():
            normalized = self._well_name(name)
            self._registered_wells[id(well)] = (well, str(slot), normalized)
        return native_labware

    def resolve_well(
        self, loaded_labware: Any, well_name: str, *, z_offset_m: float = 0.0
    ) -> Pose:
        """Return a calibrated xArm pose for an Opentrons well-top center."""
        if not any(item is loaded_labware for item in self.loaded_labware.values()):
            raise ValueError("labware must be registered on this OT-2 station")
        if not math.isfinite(float(z_offset_m)):
            raise ValueError("z_offset_m must be finite")
        normalized = self._well_name(well_name)
        try:
            well = loaded_labware.wells_by_name()[normalized]
        except KeyError as exc:
            raise ValueError(f"unknown well {well_name!r}") from exc
        return self._well_pose(well, z_offset_m=float(z_offset_m))

    def _well_pose(self, well, *, z_offset_m=0.0) -> Pose:
        """Transform a native simulated well top from deck space to arm space."""
        if self.deck_rotation is None:
            raise RuntimeError("OT-2 deck calibration is required before resolving labware wells")

        def deck_to_arm(point):
            deck_point = self._point_xyz_m(point)
            deck_point = (deck_point[0], deck_point[1], deck_point[2] + z_offset_m)
            return self._deck_pose(deck_point)

        return deck_to_arm(well.top())

    def _registered_well(self, value):
        record = self._registered_wells.get(id(value))
        return record if record is not None and record[0] is value else None

    def _entry_location_key(self, location):
        record = self._registered_well(location)
        if record is not None:
            _, slot, name = record
            return f"{slot}{name}".lower()
        return super()._entry_location_key(location)

    @staticmethod
    def ot2_location(xyz):
        """Validate arm-base XYZ millimetres and return a JSON-safe location."""
        if (not isinstance(xyz, (list, tuple)) or len(xyz) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in xyz)):
            raise ValueError("Set OT2_LOCATION_BASE_MM to three finite XYZ values in millimetres")
        return {"link_base_mm": list(xyz)}

    def resolve_address(self, address):
        """Resolve a native well or an explicit {"link_base_mm": [x, y, z]}."""
        if isinstance(address, dict):
            if set(address) != {"link_base_mm"}:
                raise ValueError("OT2 explicit location requires only link_base_mm")
            return self.ot2_location(address["link_base_mm"])
        if not isinstance(address, str):
            return address
        match = re.fullmatch(r"(1[0-2]|[1-9])([A-Z]+[1-9]\d*)", address.strip().upper())
        if match is None:
            raise ValueError("OT2 location must use slot+well notation, e.g. '3B3'")
        slot, well = match.groups()
        labware = [item for item in self.loaded_labware.values()
                   if self._labware_slots.get(id(item)) == slot]
        if not labware:
            raise ValueError(f"no labware loaded in OT2 slot {slot}")
        if len(labware) > 1:
            raise ValueError(f"multiple labware registered in OT2 slot {slot}; use a labware well handle")
        try:
            return labware[0].wells_by_name()[well]
        except KeyError as exc:
            raise ValueError(f"unknown well {well!r} in OT-2 slot {slot}") from exc

    def resolve_local_location(self, address=None) -> Vector3:
        address = self.resolve_address(address)
        if self._registered_well(address) is None:
            return super().resolve_local_location(address)
        return self.to_local(self._well_pose(address)[:3])

    def resolve_location(self, address=None) -> Pose:
        address = self.resolve_address(address)
        if isinstance(address, dict):
            # Already in link_base: bypass native well lookup and deck transform.
            return (*(value / 1000. for value in address["link_base_mm"]), *self.pose[3:])
        if self._registered_well(address) is None:
            raise ValueError("OT2 requires a slot+well address such as '3B3'")
        return self._well_pose(address)


class VialHandling(Station):
    """Arm-base holder locations with calibrated approach and retreat routes."""

    default_approach = "horizontal"

    def resolve_location(self, location=None):
        """Resolve and validate a named holder location."""
        if location is None:
            if self.location is None:
                choices = ", ".join(name.lower() for name in self.locations)
                raise ValueError(f"VialHandling requires a named location; choose from {choices}")
            return super().resolve_location()
        if isinstance(location, (tuple, list)):
            return super().resolve_location(location)
        if not isinstance(location, str) or location.upper() not in self.locations:
            raise ValueError(f"unknown VialHandling location: {location!r}")
        return super().resolve_location(location.upper())

    @station_operation
    def pick(self, arm, labware, location=None, *, grasp=None, grasp_offset_mm=None,
             tcp_offset_mm=None, use_labware_offset=False, hold_time_s=0.,
             approach=None, retreat=False, force=None, speed=None):
        """Pick at a holder location using its calibrated approach."""
        def perform():
            arm._ensure_station_context_clear()
            arm._validate_operation_flags(retreat=retreat)
            pick_force, pick_speed = arm._resolve_gripper_settings(force=force, speed=speed)
            duration = self._hold_duration(hold_time_s)
            address = location.upper() if isinstance(location, str) else location
            reference = self.resolve_location(address)
            grasp_width_mm = self._resolve_grasp_width(labware, grasp, grasp_offset_mm)
            source = "zero correction" if tcp_offset_mm is None else "explicit additive correction"
            correction = self._validate_target_options(labware, use_labware_offset, tcp_offset_mm)
            selected = self.resolve_approach(approach)
            entries = self.resolve_entry_pose(selected, location=address, all_entries=True)
            arm._gripper_gap(labware, opened=True, grasp=grasp_width_mm)
            entry = arm._step(f"enter {self.name}",
                              lambda: arm._enter(self, approach=selected, location=address))
            record = arm._placements.get(labware.name)
            if record is not None and record.station is self and record.address == address:
                reference = (*reference[:3], *record.pose[3:])
            target, bottom, final = self._target_geometry(
                labware, reference, entry[3:], tcp_offset_mm=correction,
                use_labware_offset=use_labware_offset)
            arm._log_tcp_offset("pickup", self, address, labware, grasp=grasp_width_mm,
                                source=source, base_offset_mm=correction, reference=reference,
                                final=final, use_labware_offset=use_labware_offset, target=target)
            motion = StationMotion(self, arm, entry, target, labware, bottom,
                                   hold_time_s=duration, grasp=grasp_width_mm,
                                   force=pick_force, speed=pick_speed)
            motion.address = address
            motion.approach = selected
            route = self._holder_approach(motion)
            if selected == "horizontal" and self.resolve_location_route(address) == "bottom":
                for index, waypoint in enumerate(route, 1):
                    arm._step(f"check bottom approach leg {index} at {self.name}",
                              lambda waypoint=waypoint: arm._check_cartesian_target(
                                  (*waypoint, *motion.entry[3:])))
            motion.open_gripper()
            for waypoint in route:
                motion.move_to(*waypoint)
            motion.grasp()
            retreat_route = list(reversed([motion.entry[:3], *route[:-1]]))
            return self._pause_at_endpoint(
                arm, "pickup", motion, entries, retreat_route, retreat=retreat)

        return arm._run_operation("pickup", perform)

    @station_operation(resumes_context=True)
    def raise_pickup(self, arm, *, dz_mm=10.0):
        """Raise a paused horizontal bottom pickup in base Z, ready for release.

        The external holder must be open before this move and closed before
        release. Keep the pickup's XY, wrist orientation, and retreat route.
        """
        def perform():
            distance = float(dz_mm)
            if not math.isfinite(distance) or distance <= 0:
                raise ValueError("dz_mm must be finite and positive")
            context = arm._station_context
            if (context is None or context.station is not self
                    or context.operation != "pickup" or context.phase != "at_target"
                    or context.approach != "horizontal"
                    or self.resolve_location_route(context.address) != "bottom"):
                raise RuntimeError("raise_pickup requires a paused horizontal bottom pickup")
            if arm.attached_labware is not context.item:
                raise RuntimeError("pickup context does not match the attached labware")
            arm._verify_station_context_pose(context)
            x, y, z, *rpy = context.expected_pose
            target = (x, y, z + distance / 1000., *rpy)
            arm._step(f"raise pickup at {self.name}",
                      lambda: arm._move_pose(target, self.name))
            context.expected_pose = target
            context.operation = "placement"
            context.release_allowed = True
            return {"labware_id": context.item.name, "phase": context.phase,
                    "can_release": True, "can_retreat": True}

        return arm._run_operation("raise_pickup", perform)

    def _holder_approach(self, motion):
        """Align across the approach axis before advancing to the holder."""
        x, y, z = motion.target[:3]
        ex, _, ez = motion.entry[:3]
        if motion.approach == "vertical":
            return [(x, y, ez), (x, y, z)]
        return [(ex, y, z), (x, y, z)]

    @station_operation
    def place(self, arm, location=None, *, labware=None, tcp_offset_mm=None, use_labware_offset=False, hold_time_s=0.,
              approach=None, release=False, retreat=False):
        """Place the attached labware at the selected holder; retain it on motion.item."""
        def perform():
            arm._ensure_station_context_clear()
            arm._validate_operation_flags(release=release, retreat=retreat)
            duration = self._hold_duration(hold_time_s)
            item = arm.attached_labware
            if labware is not None and labware is not item:
                raise ValueError("placement labware must match the labware attached to the arm")
            if item is None:
                raise ValueError("placement requires attached labware")
            address = location.upper() if isinstance(location, str) else location
            target_location = self.resolve_location(address)
            source = "zero correction" if tcp_offset_mm is None else "explicit additive correction"
            correction = self._validate_target_options(item, use_labware_offset, tcp_offset_mm)
            selected = arm._placement_approach(self, approach)
            entries = self.resolve_entry_pose(selected, location=address, all_entries=True)
            entry = arm._step(f"enter {self.name}",
                              lambda: arm._enter(self, approach=selected, location=address))
            reference = self._held_reference(arm, target_location, entry[3:])
            target, _, final = self._target_geometry(
                item, reference, entry[3:], tcp_offset_mm=correction,
                use_labware_offset=use_labware_offset)
            arm._log_tcp_offset("placement", self, address, item, grasp=arm._attachment.grasp,
                                source=source, base_offset_mm=correction, reference=reference,
                                final=final, use_labware_offset=use_labware_offset, target=target)
            motion = StationMotion(self, arm, entry, target, item, hold_time_s=duration)
            motion.address = address
            motion.approach = selected
            route = self._holder_approach(motion)
            for waypoint in route:
                motion.move_to(*waypoint)
            retreat_route = list(reversed([motion.entry[:3], *route[:-1]]))
            return self._pause_at_endpoint(
                arm, "placement", motion, entries, retreat_route, release=release,
                retreat=retreat, release_allowed=True, hold_time_s=duration)

        return arm._run_operation("placement", perform)

    def __init__(self, config_path: Optional[str] = None, *, linear_rail_position: object = _UNSET) -> None:
        config = self._load_config("vial_handling.yaml", config_path)
        if linear_rail_position is not _UNSET:
            config["rail_position"] = linear_rail_position
        super().__init__(config)


class VialTurbidity(Station):
    """Move a held vial into and out of the turbidity measurement position."""

    default_approach = "vertical"

    def __init__(self, config_path: Optional[str] = None, *,
                 linear_rail_position: object = _UNSET) -> None:
        config = self._load_config("vial_turbidity.yaml", config_path)
        if linear_rail_position is not _UNSET:
            config["rail_position"] = linear_rail_position
        super().__init__(config)
        self.dwell_s = self._hold_duration(config.get("dwell_s", 2.0))

    @station_operation
    def place(self, arm, labware=None, location="measure", *, tcp_offset_mm=None,
              use_labware_offset=False, approach="vertical", release=False,
              retreat=False):
        """Move base-to-top, then move X, Y, and Z to the measurement position."""
        def perform():
            arm._ensure_station_context_clear()
            arm._validate_operation_flags(release=release, retreat=retreat)
            item = arm.attached_labware
            if labware is not None and labware is not item:
                raise ValueError("placement labware must match the labware attached to the arm")
            if item is None:
                raise ValueError("placement requires attached labware")
            address = location.upper() if isinstance(location, str) else location
            target_location = self.resolve_location(address)
            source = "zero correction" if tcp_offset_mm is None else "explicit additive correction"
            correction = self._validate_target_options(
                item, use_labware_offset, tcp_offset_mm)
            selected = arm._placement_approach(self, approach)
            entries = self.resolve_entry_pose(selected, location=address, all_entries=True)
            entry = arm._step(f"enter {self.name}", lambda: arm._enter(
                self, approach=selected, location=address))
            reference = self._held_reference(arm, target_location, entry[3:])
            target, _, final = self._target_geometry(
                item, reference, entry[3:], tcp_offset_mm=correction,
                use_labware_offset=use_labware_offset)
            arm._log_tcp_offset(
                "turbidity placement", self, address, item, grasp=arm._attachment.grasp,
                source=source, base_offset_mm=correction, reference=reference,
                final=final, use_labware_offset=use_labware_offset, target=target)
            motion = StationMotion(self, arm, entry, target, item)
            dx, dy, dz = motion.target_delta
            approach_route = []
            for delta in ({"dx": dx}, {"dy": dy}, {"dz": dz}):
                motion.move_relative(**delta)
                approach_route.append(motion.position[:3])
            motion.address = address
            motion.approach = selected
            retreat_route = list(reversed([entry[:3], *approach_route[:-1]]))
            return self._pause_at_endpoint(
                arm, "turbidity placement", motion, entries, retreat_route,
                release=release, retreat=retreat, release_allowed=True)

        return arm._run_operation("turbidity placement", perform)


class AzentaIntelliXCapS1(Station):
    """Cap/decap along a configured X-Z line into and out of engage."""

    default_approach = "horizontal"

    def __init__(self, config_path: Optional[str] = None, *, linear_rail_position: object = _UNSET) -> None:
        config = self._load_config("azenta_intellixcap_s1.yaml", config_path)
        if linear_rail_position is not _UNSET:
            config["rail_position"] = linear_rail_position
        super().__init__(config)
        geometry = config.get("engage_approach")
        if not isinstance(geometry, dict):
            raise ValueError("engage_approach requires distance_mm and angle_deg")
        distance = geometry.get("distance_mm")
        if (isinstance(distance, bool) or not isinstance(distance, (int, float))
                or not math.isfinite(distance) or distance <= 0):
            raise ValueError("engage_approach.distance_mm must be finite and positive")
        angle = geometry.get("angle_deg")
        if (isinstance(angle, bool) or not isinstance(angle, (int, float))
                or not math.isfinite(angle) or not -90 < angle < 90):
            raise ValueError("engage_approach.angle_deg must be finite and strictly between -90 and 90")
        self.engage_approach_distance_mm = float(distance)
        self.engage_approach_angle_deg = float(angle)
        self.has_cap = False
        self.last_operation = None
        self.last_capped_vial = None
        self.pre_dwell_tcp_pose = None
        self.post_dwell_tcp_pose = None

    def _engage_base_point(self, engage_xyz):
        """Offset below engage in robot-base X-Z; angle is measured from +Z.

        Positive angles advance toward +X on approach. Y stays at engage Y.
        The distance is the length of the line, rather than its Z projection.
        """
        x, y, z = _vector(engage_xyz, "engage XYZ")
        distance = self.engage_approach_distance_mm / 1000.
        angle = math.radians(self.engage_approach_angle_deg)
        return (x - distance * math.sin(angle), y, z - distance * math.cos(angle))

    @station_operation
    def cap(self, arm, labware=None, address=None, *, dwell_s=2.0,
            collision_sensitivity=0, tcp_offset_mm=None, use_labware_offset=False,
            retreat=False):
        """Use the stored cap on a vial; decap must have completed first."""
        result = arm._run_operation("cap", partial(
            self._sequence, arm, "cap", labware, address, dwell_s,
            collision_sensitivity, tcp_offset_mm, use_labware_offset, retreat))
        result["has_cap"] = self.has_cap
        return result

    @station_operation
    def decap(self, arm, labware=None, address=None, *, dwell_s=2.0,
              collision_sensitivity=0, tcp_offset_mm=None, use_labware_offset=False,
              retreat=False):
        """Remove a vial's cap into the station's empty cap slot."""
        result = arm._run_operation("decap", partial(
            self._sequence, arm, "decap", labware, address, dwell_s,
            collision_sensitivity, tcp_offset_mm, use_labware_offset, retreat))
        result["has_cap"] = self.has_cap
        return result

    def _sequence(self, arm, operation, labware, address, dwell_s,
                  collision_sensitivity, tcp_offset_mm, use_labware_offset,
                  retreat=False):
        arm._ensure_station_context_clear()
        arm._validate_operation_flags(retreat=retreat)
        if (isinstance(collision_sensitivity, bool) or not isinstance(collision_sensitivity, int)
                or not 0 <= collision_sensitivity <= 5):
            raise ValueError("collision_sensitivity must be an integer from 0 to 5")
        if operation == "cap" and not self.has_cap:
            raise RuntimeError("Azenta has no cap; decap must complete before cap")
        if operation == "decap" and self.has_cap:
            raise RuntimeError("Azenta already has a cap; the next operation must be cap")
        try:
            dwell = float(dwell_s)
        except (TypeError, ValueError) as exc:
            raise ValueError("dwell_s must be finite and nonnegative") from exc
        if not math.isfinite(dwell) or dwell < 0:
            raise ValueError("dwell_s must be finite and nonnegative")
        target_address = "bottom" if address is None else address
        item = labware if labware is not None else arm.attached_labware
        correction = self._validate_target_options(item, use_labware_offset, tcp_offset_mm)
        source = "zero correction" if tcp_offset_mm is None else "explicit additive correction"
        approach = arm._placement_approach(self, "horizontal")
        entries = _poses_config(self.poses, self.default_approach)[approach]
        key = target_address.strip().lower() if isinstance(target_address, str) else None
        if key is None or key == "base" or key not in entries:
            raise ValueError(f"{self.name} requires a calibrated location entry for {target_address!r}")
        if operation == "cap":
            if self.post_dwell_tcp_pose is None:
                raise RuntimeError("Azenta has no recorded post-decap dwell TCP pose")
            engage_xyz = self.post_dwell_tcp_pose[:3]
        else:
            engage_xyz = self.resolve_location("engage")[:3]
        entry_poses = self.resolve_entry_pose(approach, location=target_address, all_entries=True)
        entry = arm._step(f"enter {self.name}", lambda: arm._enter(
            self, approach=approach, location=target_address))
        location = (*engage_xyz, *self.pose[3:])
        reference = (self._held_reference(arm, location, entry[3:])
                     if item is not None and item is arm.attached_labware else location)
        target, _, final = self._target_geometry(
            item, reference, entry[3:], tcp_offset_mm=correction,
            use_labware_offset=use_labware_offset)
        arm._log_tcp_offset(operation, self, "engage", item, grasp=None, source=source,
                            base_offset_mm=correction, reference=reference, final=final,
                            use_labware_offset=use_labware_offset, target=target)
        # Apply TCP/labware corrections to the engage endpoint first, then
        # derive the base so corrections cannot change the line's geometry.
        base_xyz = self._engage_base_point(target[:3])
        motion = StationMotion(self, arm, entry, target, item)
        with arm._temporary_collision_sensitivity(collision_sensitivity):
            motion.move_to(*base_xyz)
            if operation == "cap":
                arm.logger.info(
                    "%s cap reference uses post-decap TCP XYZ (mm)=%s",
                    self.name, tuple(value * 1000. for value in engage_xyz),
                )
                arm._record(
                    "azenta_cap_engage_reference", station=self.name,
                    tcp_xyz_m=list(engage_xyz),
                )
            motion.move_to(*target[:3])
            arm._step(
                f"record pre-dwell pose at {self.name}",
                lambda: self._capture_dwell_tcp(arm, "pre"),
            )
            arm._step(f"dwell {dwell:g} s at {self.name}", lambda: time.sleep(dwell))
            arm._step(
                f"record post-dwell pose at {self.name}",
                lambda: self._capture_dwell_tcp(arm, "post"),
            )
            motion.position = self.post_dwell_tcp_pose
        self.has_cap = operation == "decap"
        self.last_operation = operation
        if operation == "cap":
            self.last_capped_vial = item
        arm.logger.info("%s %s completed; cap at station: %s", self.name, operation, self.has_cap)
        motion.address = target_address
        motion.approach = approach
        # The capper can displace the TCP during dwell. Anchor withdrawal at
        # the measured endpoint to keep its Y fixed and its X-Z angle exact.
        retreat_base_xyz = self._engage_base_point(motion.position[:3])
        result = self._pause_at_endpoint(
            arm, operation, motion, entry_poses, [retreat_base_xyz, motion.entry[:3]],
            retreat=retreat)
        return {**result, "vial_capped": operation == "cap", "has_cap": self.has_cap}

    def _capture_dwell_tcp(self, arm, phase):
        tcp_pose = tuple(arm._read_tcp())
        setattr(self, f"{phase}_dwell_tcp_pose", tcp_pose)
        arm._last_tcp_pose = tcp_pose
        arm._record(
            "azenta_dwell_pose", station=self.name, phase=phase,
            tcp_pose=list(tcp_pose),
        )
        arm.logger.info(
            "%s %s-dwell TCP XYZ (mm)=%s",
            self.name, phase, tuple(value * 1000. for value in tcp_pose[:3]),
        )
        return tcp_pose
