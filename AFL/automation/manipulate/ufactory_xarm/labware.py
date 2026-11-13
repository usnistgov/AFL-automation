"""Immutable labware geometry. Stations and the driver own all spatial state."""

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping


def _offset_mm(value, *, name):
    """Validate an optional XYZ offset in millimetres."""
    if value is None:
        return (0., 0., 0.)
    message = f"{name} must be None or three finite values (dx, dy, dz) in mm"
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError(message)
    try:
        result = tuple(float(component) for component in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(message) from exc
    if not all(math.isfinite(component) for component in result):
        raise ValueError(message)
    return result


@dataclass(frozen=True)
class Labware:
    """Geometry parameters in mm; spatial poses use metres and radians internally."""

    name: str
    kind: str
    parameters: Mapping[str, float]
    grasps_mm: Mapping[str, float] | None = None

    def __post_init__(self):
        values = {key: float(value) for key, value in self.parameters.items()}
        object.__setattr__(self, "parameters", MappingProxyType(values))
        default_width = (2 * values["radius"] if self.kind == "cylinder"
                         else values.get("grasp_width", values["x"]))
        supplied = {"default": default_width} if self.grasps_mm is None else self.grasps_mm
        if not isinstance(supplied, Mapping) or not supplied:
            raise ValueError("grasps_mm must be a nonempty mapping of names to millimetres")
        grasps = {}
        for name, value in supplied.items():
            if not isinstance(name, str) or not name.isidentifier() or hasattr(type(self), name):
                raise ValueError(f"invalid grasp name: {name!r}")
            try:
                width = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"grasp {name!r} must be a finite positive width in mm") from exc
            if not math.isfinite(width) or width <= 0:
                raise ValueError(f"grasp {name!r} must be a finite positive width in mm")
            grasps[name] = width
        object.__setattr__(self, "grasps_mm", MappingProxyType(grasps))

    def __getattr__(self, name):
        """Expose configured grasp widths as attributes, e.g. ``vial.cap``."""
        grasps = object.__getattribute__(self, "grasps_mm")
        try:
            return grasps[name]
        except KeyError as exc:
            raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}") from exc

    def resolve_grasp_mm(self, grasp=None):
        """Return an explicit grasp gap, or the labware's default body width."""
        value = self.grasp_width_mm if grasp is None else grasp
        try:
            width = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("grasp must be a finite positive width in mm") from exc
        if not math.isfinite(width) or width <= 0:
            raise ValueError("grasp must be a finite positive width in mm")
        return width

    @property
    def height_mm(self):
        """Height in mm from the bottom reference to the top surface."""
        return self.parameters["height" if self.kind == "cylinder" else "z"]

    @property
    def height_m(self):
        """Height in metres for internal pose calculations."""
        return self.height_mm / 1000.

    @property
    def grasp_width_mm(self):
        """Object width in mm between the jaws in the intended grasp orientation."""
        if self.kind == "cylinder":
            return 2 * self.parameters["radius"]
        return self.parameters.get("grasp_width", self.parameters["x"])

    @property
    def center_offset(self):
        """Geometric center relative to the labware's bottom-center reference."""
        return (0., 0., self.height_m / 2, 0., 0., 0.)

    @property
    def top_offset(self):
        """Top-center relative to the labware's bottom-center reference."""
        return (0., 0., self.height_m, 0., 0., 0.)

    @property
    def grasp_offsets_mm(self):
        """Named grasp points relative to the labware bottom, in local mm."""
        return MappingProxyType({"bottom": (0., 0., 0.),
                                 "center": (0., 0., self.height_mm / 2),
                                 "top": (0., 0., self.height_mm)})

    def resolve_grasp_offset_mm(self, grasp, grasp_offset_mm=None):
        """Select a labware offset; an explicit XYZ tuple replaces it entirely."""
        if grasp not in self.grasp_offsets_mm:
            raise ValueError(f"{self.name} has no grasp {grasp!r}; choose from {tuple(self.grasp_offsets_mm)}")
        selected = self.grasp_offsets_mm[grasp] if grasp_offset_mm is None else grasp_offset_mm
        return _offset_mm(selected, name="grasp_offset_mm")

    def grasp_at(self, bottom_pose, grasp, *, grasp_offset_mm=None):
        """Transform the selected bottom-relative grasp point to arm-base metres."""
        point = tuple(value / 1000. for value in self.resolve_grasp_offset_mm(grasp, grasp_offset_mm))
        roll, pitch, yaw = bottom_pose[3:]
        cr, sr = math.cos(roll), math.sin(roll)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cy, sy = math.cos(yaw), math.sin(yaw)
        rotation = ((cy*cp, cy*sp*sr-sy*cr, cy*sp*cr+sy*sr),
                    (sy*cp, sy*sp*sr+cy*cr, sy*sp*cr-cy*sr),
                    (-sp, cp*sr, cp*cr))
        return tuple(bottom_pose[i] + sum(rotation[i][j] * point[j] for j in range(3))
                     for i in range(3))

    def top_at(self, bottom_pose, *, grasp_offset_mm=None):
        """Top grasp, or an explicit bottom-relative XYZ grasp point in mm."""
        return self.grasp_at(bottom_pose, "top", grasp_offset_mm=grasp_offset_mm)

    def center_at(self, bottom_pose, *, grasp_offset_mm=None):
        """Center grasp, or an explicit bottom-relative XYZ grasp point in mm."""
        return self.grasp_at(bottom_pose, "center", grasp_offset_mm=grasp_offset_mm)

    def bottom_at(self, bottom_pose, *, grasp_offset_mm=None):
        """Bottom grasp, or an explicit bottom-relative XYZ grasp point in mm."""
        return self.grasp_at(bottom_pose, "bottom", grasp_offset_mm=grasp_offset_mm)

    @property
    def shape(self):
        """Human-readable geometric shape; no station or motion state."""
        return {"cylinder": "cylindrical", "box": "rectangular"}[self.kind]


class RectangularLabware(Labware):
    """Rectangular labware, with dimensions in millimetres."""

    def __init__(self, object_id: str, *, width_mm: float, depth_mm: float, height_mm: float,
                 grasp_axis: str = "x", grasps_mm: Mapping[str, float] | None = None):
        if grasp_axis not in ("x", "y"):
            raise ValueError("grasp_axis must be 'x' (width) or 'y' (depth)")
        super().__init__(object_id, "box", {"x": width_mm, "y": depth_mm, "z": height_mm,
                                          "grasp_width": width_mm if grasp_axis == "x" else depth_mm},
                         grasps_mm)


class Vial(Labware):
    """Standard 25 mm diameter, 70 mm tall vial."""

    def __init__(self, object_id: str = "vial", *, radius_mm: float = 12.5, height_mm: float = 70.,
                 grasps_mm: Mapping[str, float] | None = None):
        diameter = 2 * float(radius_mm)
        if grasps_mm is None:
            grasps_mm = {"cap": diameter, "bottom": diameter}
        super().__init__(object_id, "cylinder", {"radius": radius_mm, "height": height_mm},
                         grasps_mm)

    @property
    def radius_mm(self):
        return self.parameters["radius"]
