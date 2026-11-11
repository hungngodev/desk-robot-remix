"""Debounced interactions from the THREE existing read-only VL53L4CD extras.

The WROOM already samples mux channels 5..7 as side_ranges left/right/rear.
This source is NOT a new sensor driver, cliff guard or movement permission.
A physical operator must first measure geometry and opt in per robot.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

SIDE_NAMES = ("left", "right", "rear")


@dataclass
class Direction:
    previous_sample_at: float | None = None
    initialized: bool = False
    near: bool = False
    consecutive_near: int = 0
    consecutive_far: int = 0


@dataclass
class SideRangeEvents:
    directions: list[Direction] = field(
        default_factory=lambda: [Direction() for _ in range(3)]
    )

    def observe(self, body: dict, *, now: float, near_mm: int) -> list[tuple[str, int]]:
        """Only transition far -> near after two genuinely new fresh samples.

        A range-age clock is WROOM local uptime; the Mac reconstructs a
        monotonic estimate as receive_time - sample_age. Require the inferred
        sample time to advance by >=60ms, guarding against duplicate polling.
        A reconnect or invalid response forgets history; the first fresh
        reading is a baseline, never a fabricated arrival.
        """
        if (type(now) not in (int, float) or not math.isfinite(now)
                or type(near_mm) is not int or not 35 <= near_mm <= 1000):
            raise ValueError("Measured side range threshold and finite clock required")
        data = body.get("side_ranges") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            self._reset()
            return []
        present, valid = data.get("present_mask"), data.get("valid_mask")
        distances, ages = data.get("mm"), data.get("age_ms")
        if (type(present) is not int or type(valid) is not int
                or not 0 <= present <= 7 or not 0 <= valid <= 7
                or valid & ~present
                or data.get("motion_certified") is not False
                or not isinstance(distances, list) or len(distances) != 3
                or not isinstance(ages, list) or len(ages) != 3
                or any(type(d) is not int or not 0 <= d <= 1300
                       for d in distances)
                or any(type(a) is not int or not 0 <= a <= 0xffffffff
                       for a in ages)):
            self._reset()
            return []

        results: list[tuple[str, int]] = []
        for i, name in enumerate(SIDE_NAMES):
            track = self.directions[i]
            fresh = bool(valid & (1 << i)) and ages[i] <= 350
            if not fresh or not 1 <= distances[i] <= 1300:
                self.directions[i] = Direction()
                continue
            sample_at = now - ages[i] / 1000.0
            if track.previous_sample_at is not None:
                # Current Mac event may be a second HTTP read of the same
                # physical WROOM sample. Cannot earn confirmation twice.
                if sample_at - track.previous_sample_at < 0.06:
                    continue
                if sample_at - track.previous_sample_at > 2.0:
                    self.directions[i] = track = Direction()
            track.previous_sample_at = sample_at
            detected_near = distances[i] <= near_mm
            clearly_far = distances[i] >= near_mm + 60
            if not track.initialized:
                track.initialized = True
                track.near = detected_near
                continue
            if track.near:
                track.consecutive_near = 0
                track.consecutive_far = (
                    track.consecutive_far + 1 if clearly_far else 0
                )
                if track.consecutive_far >= 2:
                    track.near = False
                    track.consecutive_far = 0
            else:
                track.consecutive_far = 0
                track.consecutive_near = (
                    track.consecutive_near + 1 if detected_near else 0
                )
                if track.consecutive_near >= 2:
                    track.near = True
                    track.consecutive_near = 0
                    results.append((name, distances[i]))
        return results

    def _reset(self) -> None:
        self.directions = [Direction() for _ in range(3)]
