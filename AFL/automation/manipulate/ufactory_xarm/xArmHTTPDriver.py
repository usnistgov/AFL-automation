#!/usr/bin/env python3
"""AFL HTTP driver facade for the station-based xArm workcell."""

import logging
import math

from AFL.automation.APIServer.Driver import Driver

from .labware import Labware, RectangularLabware, Vial
from .stations import Station
from .ufactory import xArmManipulator


class xArmHTTPDriver(Driver):
    """Expose :class:`xArmManipulator` through AFL's queued command API.

    Stations and initial labware are ordinary Python instances so AFL's launcher
    can construct them from nested ``_classname`` configuration entries. HTTP
    tasks refer to those objects by their stable ``name`` values.
    """

    defaults = {
        "robot_ip": "ROBOT_IP",
        "simulation": False,
        "initialize_rail": False,
        "workcell_config": "configs/workcell.yaml",
        "log_level": logging.INFO,
        **xArmManipulator.gripper_defaults,
    }

    def __init__(self, stations, labware=(), overrides=None, sdk=None):
        Driver.__init__(
            self,
            name="xArmHTTPDriver",
            defaults=self.gather_defaults(),
            overrides=overrides,
        )
        self.stations = self._registry(stations, Station, "station")
        self.labware = self._registry(labware, Labware, "labware")
        self.arm = xArmManipulator(
            self.config["robot_ip"],
            simulation=self.config["simulation"],
            initialize_rail=self.config["initialize_rail"],
            sdk=sdk,
            stations=tuple(self.stations.values()),
            workcell_config=self.config["workcell_config"],
            logger=self.logger,
            **{key: self.config[key] for key in xArmManipulator.gripper_defaults
               if self.config[key] is not None},
        )
        self.arm.connect()

    @staticmethod
    def _registry(items, expected_type, item_name):
        if items is None:
            items = ()
        if not isinstance(items, (list, tuple)):
            raise TypeError(f"{item_name}s must be a list or tuple")
        registry = {}
        for item in items:
            if not isinstance(item, expected_type):
                raise TypeError(
                    f"{item_name}s must contain {expected_type.__name__} instances"
                )
            if item.name in registry:
                raise ValueError(f"duplicate {item_name} name {item.name!r}")
            registry[item.name] = item
        return registry

    def _station(self, name):
        if not isinstance(name, str):
            raise TypeError("station must be the configured station name")
        try:
            return self.stations[name]
        except KeyError as exc:
            raise ValueError(
                f"unknown station {name!r}; choose from {tuple(self.stations)}"
            ) from exc

    def _labware(self, name):
        if not isinstance(name, str):
            raise TypeError("labware must be the configured labware name")
        try:
            return self.labware[name]
        except KeyError as exc:
            raise ValueError(
                f"unknown labware {name!r}; choose from {tuple(self.labware)}"
            ) from exc

    @staticmethod
    def _require_success(action, result):
        if isinstance(result, dict) and result.get("success") is False:
            detail = result.get("message", result)
            raise RuntimeError(f"{action} failed: {detail}")
        return result

    @staticmethod
    def _positive_dimension(value, name):
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a finite positive number")
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a finite positive number") from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a finite positive number")
        return value

    @Driver.queued()
    def station_operation(self, station, operation, labware=None, force=None, speed=None, **kwargs):
        """Run a station operation; picks accept gripper force and speed overrides.

        Omitted force/speed use the startup defaults. Speed units and force
        support depend on the configured gripper_type; see the driver status.
        """
        station_object = self._station(station)
        labware_object = None if labware is None else self._labware(labware)
        if "grasp" in kwargs and isinstance(kwargs["grasp"], str):
            if labware_object is None:
                raise ValueError("a named grasp requires a labware name")
            grasp_name = kwargs["grasp"]
            try:
                kwargs["grasp"] = labware_object.grasps_mm[grasp_name]
            except KeyError as exc:
                raise ValueError(
                    f"unknown grasp {grasp_name!r} for {labware_object.name!r}; "
                    f"choose from {tuple(labware_object.grasps_mm)}"
                ) from exc
        if labware_object is not None:
            kwargs["labware"] = labware_object
        if force is not None:
            kwargs["force"] = force
        if speed is not None:
            kwargs["speed"] = speed
        result = self.arm.station_operation(station_object, operation, **kwargs)
        return self._require_success(f"{station}.{operation}", result)

    @Driver.queued()
    def add_labware(
        self,
        name,
        labware_type="vial",
        radius_mm=None,
        height_mm=None,
        width_mm=None,
        depth_mm=None,
        grasp_axis="x",
        grasps_mm=None,
    ):
        """Construct and register allowlisted labware from JSON-safe geometry."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("labware name must be a nonempty string")
        name = name.strip()
        if name in self.labware:
            raise ValueError(f"duplicate labware name {name!r}")
        if not isinstance(labware_type, str):
            raise ValueError("labware_type must be 'vial' or 'rectangular'")
        labware_type = labware_type.strip().lower()
        if labware_type == "vial":
            options = {"grasps_mm": grasps_mm}
            if radius_mm is not None:
                options["radius_mm"] = self._positive_dimension(radius_mm, "radius_mm")
            if height_mm is not None:
                options["height_mm"] = self._positive_dimension(height_mm, "height_mm")
            item = Vial(name, **options)
        elif labware_type in ("rectangular", "rectangular_labware"):
            missing = [field for field, value in (
                ("width_mm", width_mm), ("depth_mm", depth_mm),
                ("height_mm", height_mm),
            ) if value is None]
            if missing:
                raise ValueError(
                    f"rectangular labware requires {', '.join(missing)}"
                )
            item = RectangularLabware(
                name,
                width_mm=self._positive_dimension(width_mm, "width_mm"),
                depth_mm=self._positive_dimension(depth_mm, "depth_mm"),
                height_mm=self._positive_dimension(height_mm, "height_mm"),
                grasp_axis=grasp_axis,
                grasps_mm=grasps_mm,
            )
        else:
            raise ValueError("labware_type must be 'vial' or 'rectangular'")
        self.labware[name] = item
        return self._labware_description(item)

    @Driver.queued()
    def release(self):
        return self._require_success("release", self.arm.release())

    @Driver.queued()
    def retreat(self):
        return self._require_success("retreat", self.arm.retreat())

    @Driver.queued()
    def move_rail(self, position_mm):
        return self._require_success("move_rail", self.arm.move_rail(position_mm))

    @Driver.queued()
    def home(self):
        return self._require_success("home", self.arm.home())

    @Driver.queued()
    def disconnect(self):
        self.arm.disconnect()
        return {"success": True, "connected": False}

    @staticmethod
    def _labware_description(item):
        return {
            "name": item.name,
            "kind": item.kind,
            "parameters": dict(item.parameters),
            "grasps_mm": dict(item.grasps_mm),
        }

    @Driver.unqueued()
    def list_stations(self):
        return {
            name: {"operations": list(station.available_operations)}
            for name, station in self.stations.items()
        }

    @Driver.unqueued()
    def list_labware(self):
        return {
            name: self._labware_description(item)
            for name, item in self.labware.items()
        }

    @Driver.unqueued()
    def status(self):
        result = dict(self.arm.status())
        result["connected"] = bool(
            self.arm._arm is not None and getattr(self.arm._arm, "connected", True)
        )
        result["stations"] = {
            name: list(station.available_operations)
            for name, station in self.stations.items()
        }
        result["labware"] = list(self.labware)
        return result


_DEFAULT_PORT = 5059
_DEFAULT_CUSTOM_CONFIG = {
    "_classname": "AFL.automation.manipulate.ufactory_xarm.xArmHTTPDriver.xArmHTTPDriver",
    "stations": [
        {
            "_classname": "AFL.automation.manipulate.ufactory_xarm.stations.OT2",
            "config_path": "configs/ot2.yaml",
            "module_definitions": {
                "temperature_module": {
                    "model": "temperatureModuleV1",
                    "slot": "3",
                }
            },
            "labware_definitions": {
                "vial_rack": {
                    "load_name": "opentrons_24_aluminumblock_generic_2ml_screwcap",
                    "location": "temperature_module",
                }
            },
        },
        {
            "_classname": "AFL.automation.manipulate.ufactory_xarm.stations.VialHandling",
            "config_path": "configs/vial_handling.yaml",
        },
        {
            "_classname": "AFL.automation.manipulate.ufactory_xarm.stations.AzentaIntelliXCapS1",
            "config_path": "configs/azenta_intellixcap_s1.yaml",
        },
        {
            "_classname": "AFL.automation.manipulate.ufactory_xarm.stations.VialTurbidity",
            "config_path": "configs/vial_turbidity.yaml",
        },
        {
            "_classname": "AFL.automation.manipulate.ufactory_xarm.stations.UVVis",
            "config_path": "configs/uvvis.yaml",
        },
    ],
    "labware": [
        {
            "_classname": "AFL.automation.manipulate.ufactory_xarm.labware.Vial",
            "radius_mm": 4.5,
            "height_mm": 50,
            "grasps_mm": {"cap": 9.0, "bottom": 7.0},
        }
    ],
    "overrides": {
        "robot_ip": "ROBOT_IP",
        "simulation": False,
        "initialize_rail": False,
        "workcell_config": "configs/workcell.yaml",
        "log_level": logging.DEBUG,
        **xArmManipulator.gripper_defaults,
    },
}


if __name__ == "__main__":
    from AFL.automation.shared.launcher import *  # noqa: F401,F403
