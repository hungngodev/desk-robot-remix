"""Planar rigid transforms in millimetres/radians, without localization authority.

REP-105: https://github.com/ros-infrastructure/rep/blob/master/rep-0105.rst
A transform stores the child frame in the parent frame. Positive yaw is
counterclockwise (+X forward, +Y left). A localization correction changes
map -> odom, not the continuous odom -> base_link receipt. These are geometric
calculations only; an authenticated stationary camera bracket must separately
qualify the input before any map is anchored.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .spatial_pose import PoseReceipt

_MAX_MM = 1_000_000
_FRAMES = frozenset({"map", "odom", "base_link"})


class FrameError(ValueError):
    """Invalid or incompatible planar frame geometry."""


def _bounded(value: object, maximum: float) -> bool:
    # Compare the bound before converting to float: enormous ints must not
    # escape as OverflowError or reach trigonometry.
    return type(value) in (int, float) and -maximum <= value <= maximum


def wrap_yaw_rad(angle: float) -> float:
    """Wrap a finite angle to [-pi, pi], preserving remainder endpoint semantics."""
    return math.remainder(angle, math.tau)


def rotate_xy(x: float, y: float, yaw_rad: float) -> tuple[float, float]:
    """Rotate prevalidated coordinates counterclockwise; callers bound the result."""
    c, s = math.cos(yaw_rad), math.sin(yaw_rad)
    return c * x - s * y, s * x + c * y


@dataclass(frozen=True)
class PlanarTransform:
    parent: str
    child: str
    x_mm: float
    y_mm: float
    yaw_rad: float

    def __post_init__(self):
        if (type(self.parent) is not str or self.parent not in _FRAMES
                or type(self.child) is not str or self.child not in _FRAMES
                or not _bounded(self.x_mm, _MAX_MM)
                or not _bounded(self.y_mm, _MAX_MM)
                or not _bounded(self.yaw_rad, math.pi)):
            raise FrameError("Invalid planar transform")
        if self.parent == self.child and (self.x_mm != 0 or self.y_mm != 0
                                          or self.yaw_rad != 0):
            raise FrameError("Same-frame transform must be identity")

    def point(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        """Transform a point expressed in child coordinates into parent."""
        if not _bounded(x_mm, _MAX_MM) or not _bounded(y_mm, _MAX_MM):
            raise FrameError("Invalid planar point")
        dx, dy = rotate_xy(x_mm, y_mm, self.yaw_rad)
        x = self.x_mm + dx
        y = self.y_mm + dy
        if not _bounded(x, _MAX_MM) or not _bounded(y, _MAX_MM):
            raise FrameError("Transformed point outside coordinate bounds")
        return x, y

    def compose(self, other: PlanarTransform) -> PlanarTransform:
        """A<-B composed with B<-C gives A<-C."""
        if type(other) is not PlanarTransform or self.child != other.parent:
            raise FrameError("Incompatible transform frames")
        x, y = self.point(other.x_mm, other.y_mm)
        yaw = wrap_yaw_rad(self.yaw_rad + other.yaw_rad)
        if self.parent == other.child:
            # A cycle is admissible only when it closes to numerical identity.
            if max(abs(x), abs(y), abs(yaw)) > 1e-8:
                raise FrameError("Inconsistent same-frame transform cycle")
            x = y = yaw = 0.0
        return PlanarTransform(self.parent, other.child, x, y, yaw)

    def inverse(self) -> PlanarTransform:
        yaw = wrap_yaw_rad(-self.yaw_rad)
        x, y = rotate_xy(-self.x_mm, -self.y_mm, yaw)
        return PlanarTransform(self.child, self.parent, x, y, yaw)


def odom_base_transform(receipt: PoseReceipt) -> PlanarTransform:
    """Convert a typed receipt for geometry, not as proof of freshness."""
    if (type(receipt) is not PoseReceipt or receipt.quality != "valid"
            or type(receipt.origin) is not int or receipt.origin <= 0
            or type(receipt.head_boot) is not int
            or not 0 <= receipt.head_boot <= 0xffffffff
            or type(receipt.x_mm) is not int or type(receipt.y_mm) is not int
            or type(receipt.yaw_mrad) is not int
            or not -3142 <= receipt.yaw_mrad <= 3142):
        raise FrameError("Valid identified odometry receipt required")
    return PlanarTransform(
        "odom", "base_link", receipt.x_mm, receipt.y_mm, wrap_yaw_rad(receipt.yaw_rad),
    )


def map_odom_transform(
    map_base: PlanarTransform, odom_base: PlanarTransform,
) -> PlanarTransform:
    """Calculate map<-odom = map<-base * inverse(odom<-base).

    Does not mutate either input or establish a qualified localization.
    """
    if (type(map_base) is not PlanarTransform
            or (map_base.parent, map_base.child) != ("map", "base_link")
            or type(odom_base) is not PlanarTransform
            or (odom_base.parent, odom_base.child) != ("odom", "base_link")):
        raise FrameError("Expected map and odom poses of the same base frame")
    return map_base.compose(odom_base.inverse())
