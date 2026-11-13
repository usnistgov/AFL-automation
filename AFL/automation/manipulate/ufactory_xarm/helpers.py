"""Shared pose and joint-validation helpers for the xArm workcell."""

import math
from typing import Sequence, Tuple

import numpy as np


Pose = Tuple[float, float, float, float, float, float]
Vector3 = Tuple[float, float, float]


def pose(values) -> Pose:
    """Validate an absolute ``link_base`` pose in metres and radians."""
    if not isinstance(values, (tuple, list)) or len(values) != 6:
        raise ValueError("pose must contain six finite values")
    result = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in result):
        raise ValueError("pose values must be finite")
    return result  # type: ignore[return-value]


def _joint_pose(value, name):
    """Validate seven joint angles in degrees, without unit conversion."""
    if not isinstance(value, (list, tuple)) or len(value) != 7:
        raise ValueError(f"{name} must contain seven finite joint angles in degrees")
    result = tuple(float(angle) for angle in value)
    if not all(math.isfinite(angle) for angle in result):
        raise ValueError(f"{name} must contain seven finite joint angles in degrees")
    return result


def _rotation(rpy):
    """Return the rotation matrix for roll, pitch, and yaw in radians."""
    roll, pitch, yaw = rpy
    cr, sr, cp, sp, cy, sy = (np.cos(roll), np.sin(roll), np.cos(pitch),
                              np.sin(pitch), np.cos(yaw), np.sin(yaw))
    return ((cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
            (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
            (-sp, cp * sr, cp * cr))


def _rpy(matrix: Sequence[Sequence[float]]) -> Vector3:
    """Return roll, pitch, and yaw for a rotation matrix."""
    values = np.asarray(matrix, dtype=float)
    pitch = np.arctan2(-values[2, 0], np.hypot(values[0, 0], values[1, 0]))
    if abs(np.cos(pitch)) > 1e-9:
        return (
            float(np.arctan2(values[2, 1], values[2, 2])),
            float(pitch),
            float(np.arctan2(values[1, 0], values[0, 0])),
        )
    return float(np.arctan2(-values[1, 2], values[1, 1])), float(pitch), 0.0
