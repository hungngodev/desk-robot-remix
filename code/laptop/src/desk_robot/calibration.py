from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Self

import numpy as np
from numpy.typing import NDArray
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from .private_files import is_private_robot_id, replace_private_text


def _unique_calibration_json_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Do not silently choose a physical permission or geometry value."""
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError(f"Duplicate calibration JSON field: {key}")
        fields[key] = value
    return fields


class Calibration(BaseModel):
    simulation_only: bool = Field(default=False, strict=True)
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    measured: bool = Field(default=False, strict=True)
    # Bind physical measurements to the configured robot, not the file path.
    robot_id: str | None = Field(default=None, strict=True)
    # Explicit operator expiry; legacy files have no known expiry.
    expires_at: AwareDatetime | None = None
    _expiry_deadline: float | None = PrivateAttr(default=None)
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    pixel_points: list[tuple[float, float]] = Field(min_length=4)
    ground_points_mm: list[tuple[float, float]] = Field(min_length=4)
    work_area_mm: tuple[float, float, float, float]
    grip_ground_mm: tuple[float, float]
    # Conservative measured lower bound over the loaded jaw/lift sweep, after
    # desk unevenness, assembly tolerance and measurement error are deducted.
    # A 2D homography or commanded servo angle cannot supply this evidence.
    pickup_floor_clearance_mm: float | None = Field(default=None, strict=True, gt=0)
    lifted_roi_px: tuple[float, float, float, float]
    grip_open: int = Field(default=60, strict=True, ge=60, le=120)
    grip_closed: int = Field(default=110, strict=True, ge=60, le=120)
    # Configure measured FSR on ADS1115 channel 1 before a real grip.
    grip_force_delta_raw: int | None = Field(default=None, strict=True, ge=50, le=20000)
    grip_force_limit_raw: int | None = Field(default=None, strict=True, ge=100, le=30000)
    grip_force_sign: int = Field(default=1, strict=True)
    # WROOM permits at most four servo degrees per completed jaw conversion.
    # Do not let the Mac assume a larger physical angle than firmware moved.
    grip_step_deg: int = Field(default=4, strict=True, ge=1, le=4)
    lift_down: int = Field(default=60, ge=60, le=120)
    lift_up: int = Field(default=110, ge=60, le=120)
    alignment_tolerance_mm: float = Field(default=8, gt=0, le=30)
    min_confidence: float = Field(default=0.45, ge=0.1, le=1)
    min_lift_displacement_px: float = Field(default=20, ge=5)
    max_reprojection_error_mm: float = Field(default=3, gt=0, le=10)
    servo_settle_seconds: float = Field(default=2, ge=0.5, le=5)
    hold_seconds: float = Field(default=0.7, ge=0.5, le=3)
    # Confirm motor polarity on stands before setting measured=true.
    turn_sign: int = Field(default=1)
    forward_sign: int = Field(default=1)

    @model_validator(mode="after")
    def geometry(self) -> Self:
        if self.robot_id is not None and not is_private_robot_id(self.robot_id):
            raise ValueError("Invalid calibration robot_id")
        if len(self.pixel_points) != len(self.ground_points_mm):
            raise ValueError("Calibration point pairs must have equal length")
        for x, y in self.pixel_points:
            if not 0 <= x < self.image_width or not 0 <= y < self.image_height:
                raise ValueError("Calibration points outside image")
        x0, y0, x1, y1 = self.work_area_mm
        a, b, c, d = self.lifted_roi_px
        if (
            not x0 < x1
            or not y0 < y1
            or not (0 <= a < c <= self.image_width and 0 <= b < d <= self.image_height)
        ):
            raise ValueError("Work area and lifted ROI must be valid rectangles")
        if self.grip_force_sign not in {-1, 1}:
            raise ValueError("FSR polarity must be 1 or -1")
        if (self.grip_force_delta_raw is None) != (self.grip_force_limit_raw is None):
            raise ValueError("Measured gripper contact and upper limit must both be set")
        if (self.grip_force_delta_raw is not None
                and self.grip_force_limit_raw <= self.grip_force_delta_raw):
            raise ValueError("Gripper force ceiling must exceed contact threshold")
        if self.grip_open == self.grip_closed:
            raise ValueError("Gripper open and close cannot be identical")
        if self.turn_sign not in {-1, 1} or self.forward_sign not in {-1, 1}:
            raise ValueError("Motor polarity signs must be -1 or 1")
        if not self.within(self.grip_ground_mm):
            raise ValueError("Gripping point outside work area")
        self.matrix()  # reject degenerate or inaccurate point pairs immediately
        return self

    def matrix(self) -> NDArray[np.float64]:
        source = np.array(self.pixel_points, dtype=float)
        target = np.array(self.ground_points_mm, dtype=float)
        if np.linalg.matrix_rank(np.column_stack((source, np.ones(len(source))))) < 3:
            raise ValueError("Calibration points are collinear")
        rows = []
        for (x, y), (u, v) in zip(source, target, strict=True):
            rows.extend((
                [x, y, 1, 0, 0, 0, -u * x, -u * y],
                [0, 0, 0, x, y, 1, -v * x, -v * y],
            ))
        design = np.array(rows)
        if np.linalg.matrix_rank(design) < 8:
            raise ValueError("Degenerate homography point pairs")
        h = np.append(np.linalg.lstsq(design, target.reshape(-1), rcond=None)[0], 1).reshape(3, 3)
        if not np.isfinite(h).all() or abs(np.linalg.det(h)) < 1e-12:
            raise ValueError("Invalid homography")
        projected = np.c_[source, np.ones(len(source))] @ h.T
        if np.any(np.abs(projected[:, 2]) < 1e-9):
            raise ValueError("Singular calibration projection")
        errors = np.linalg.norm(projected[:, :2] / projected[:, 2:3] - target, axis=1)
        if max(errors) > self.max_reprojection_error_mm:
            raise ValueError("Calibration reprojection error exceeds threshold")
        return h

    def ground(self, point: tuple[float, float]) -> tuple[float, float]:
        p = self.matrix() @ np.array([*point, 1.0])
        if abs(p[2]) < 1e-9:
            raise ValueError("Point projects to infinity")
        result = (float(p[0] / p[2]), float(p[1] / p[2]))
        if not all(math.isfinite(v) for v in result):
            raise ValueError("Invalid projection")
        return result

    def within(self, point: tuple[float, float]) -> bool:
        x0, y0, x1, y1 = self.work_area_mm
        return x0 <= point[0] <= x1 and y0 <= point[1] <= y1

    def verify_ready(self, *, robot_id: str | None = None) -> None:
        """Validate readiness; robot-scoped callers must supply the exact routing ID."""
        if not self.measured:
            raise ValueError(
                "Calibration is an unmeasured example; measure this robot before pickup"
            )

        self._verify_expiry()

        if robot_id is not None:
            if not is_private_robot_id(robot_id):
                raise ValueError("Invalid requested calibration robot_id")
            if self.robot_id is None and not self.simulation_only:
                raise ValueError("Calibration has no robot_id; re-calibrate this robot")
            if self.robot_id is not None and self.robot_id != robot_id:
                raise ValueError("Calibration robot_id does not match requested robot")

    def _verify_expiry(self) -> None:
        if self.expires_at is None:
            return
        # A wall-clock correction may shorten, but never extend, readiness
        # for this loaded calibration. Keep the deadline process-local.
        now = monotonic()
        remaining = (self.expires_at - datetime.now(UTC)).total_seconds()
        deadline = now + remaining
        if self._expiry_deadline is None or deadline < self._expiry_deadline:
            self._expiry_deadline = deadline
        if now >= self._expiry_deadline:
            raise ValueError("Calibration expired; re-calibrate this robot before pickup")

    def has_pickup_floor_clearance(self) -> bool:
        """Require positive measured sweep clearance, not object thickness."""
        margin = self.pickup_floor_clearance_mm
        return self.measured is True and type(margin) is float and 0 < margin < math.inf

    @classmethod
    def load(cls, path: Path) -> Self:
        contents = path.read_text()
        # Pydantic accepts repeated JSON keys with the final value winning.
        # Refuse ambiguous measured permission and point geometry first, then
        # retain Pydantic's existing strict JSON model validation behavior.
        json.loads(contents, object_pairs_hook=_unique_calibration_json_fields)
        return cls.model_validate_json(contents)

    def save(self, path: Path) -> None:
        replace_private_text(path, json.dumps(self.model_dump(mode="json"), indent=2) + "\n")
