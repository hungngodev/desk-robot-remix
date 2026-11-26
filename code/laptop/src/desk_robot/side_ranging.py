"""Debounced interactions from the THREE existing read-only VL53L0X extras.

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
    previous_sample_ms: int | None = None
    initialized: bool = False
    near: bool = False
    consecutive_near: int = 0
    consecutive_far: int = 0


@dataclass
class SideRangeEvents:
    directions: list[Direction] = field(
        default_factory=lambda: [Direction() for _ in range(3)]
    )
    threshold_mm: int | None = None
    active_boot_id: int | None = None
    retired_boot_ids: set[int] = field(default_factory=set)
    last_receive_at: float | None = None

    def observe(self, body: dict, *, now: float, near_mm: int,
                require_hardware_identity: bool = False,
                request_elapsed_ms: float = 0.0) -> list[tuple[str, int]]:
        """Only transition far -> near after two genuinely new fresh samples.

        A range-age clock is WROOM local uptime; the Mac reconstructs a
        monotonic estimate as receive_time - sample_age. Require the inferred
        sample time to advance by >=60ms, guarding against duplicate polling.
        A reconnect or invalid response clears proximity votes; the first
        newer reading is a baseline, never a fabricated arrival.
        """
        if (type(now) not in (int, float) or not -1e15 <= now <= 1e15
                or not math.isfinite(now)
                or type(near_mm) is not int or not 35 <= near_mm <= 1000
                or type(require_hardware_identity) is not bool):
            raise ValueError("Measured side range threshold and finite clock required")
        # Source age_ms is measured when WROOM serialized the response.
        # An HTTP request that took too long cannot restore stale physical
        # evidence to a live Mac observation using its late receive clock.
        try:
            elapsed_ms = float(request_elapsed_ms)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Finite side status request duration required") from exc
        if (type(request_elapsed_ms) not in (int, float)
                or not math.isfinite(elapsed_ms) or elapsed_ms < 0):
            raise ValueError("Finite side status request duration required")
        # Hardware conversion sequence can advance independently of Mac time.
        # A receive-clock rollback must discard prior near/far votes.
        if self.last_receive_at is not None and now < self.last_receive_at:
            self._reset()
            self.last_receive_at = now
            return []
        self.last_receive_at = now
        # Changing a measured threshold is not a physical object arrival.
        # Start a new baseline instead of interpreting the same range twice.
        if self.threshold_mm != near_mm:
            self._reset()
            self.threshold_mm = near_mm
        data = body.get("side_ranges") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            self._reset()
            return []
        present, valid = data.get("present_mask"), data.get("valid_mask")
        distances, ages = data.get("mm"), data.get("age_ms")
        sample_times, boot_id = data.get("sample_ms"), data.get("boot_id")
        has_hardware_identity = sample_times is not None or boot_id is not None
        if require_hardware_identity:
            imu = body.get("imu")
            if (not has_hardware_identity or not isinstance(imu, dict)
                    or type(imu.get("boot_id")) is not int
                    or imu["boot_id"] != boot_id):
                # Hardware autonomy requires one consistent physical WROOM
                # source for side ranging and the existing IMU status.
                self._reset()
                return []
        if (type(present) is not int or type(valid) is not int
                or not 0 <= present <= 7 or not 0 <= valid <= 7
                or valid & ~present
                or data.get("motion_certified") is not False
                or not isinstance(distances, list) or len(distances) != 3
                or not isinstance(ages, list) or len(ages) != 3
                or any(type(d) is not int or not 0 <= d <= 0xffff
                       for d in distances)
                or any(type(a) is not int or not 0 <= a <= 0xffffffff
                       for a in ages)
                or (has_hardware_identity and (
                    not isinstance(sample_times, list) or len(sample_times) != 3
                    or any(type(t) is not int or not 0 <= t <= 0xffffffff
                           for t in sample_times)
                    or type(boot_id) is not int or not 1 <= boot_id <= 0xffffffff
                ))):
            self._reset()
            return []

        # Current WROOM frames carry physical acquisition time and per-boot
        # identity. Once verified, never fall back to host HTTP timing or
        # resurrect an earlier boot's delayed sensor observations.
        if has_hardware_identity:
            if boot_id in self.retired_boot_ids:
                return []
            if self.active_boot_id != boot_id:
                if self.active_boot_id is not None:
                    # Keep retired identities for this observer's entire life.
                    # The old eight-boot cutoff silently made every later
                    # legitimate WROOM reboot permanently lose side events.
                    # Evicting identities to bound the set would instead let a
                    # delayed old boot masquerade as a fresh one. A set grows
                    # by one small integer per actual distinct observed boot;
                    # only the explicit owner lifecycle can retire the tracker.
                    self.retired_boot_ids.add(self.active_boot_id)
                self._reset(new_boot=True)
                self.active_boot_id = boot_id
        elif self.active_boot_id is not None:
            self._reset()
            return []

        results: list[tuple[str, int]] = []
        for i, name in enumerate(SIDE_NAMES):
            track = self.directions[i]
            fresh = bool(valid & (1 << i)) and ages[i] + elapsed_ms <= 350
            # Match TofBus's accepted VL53L0X conversion range. Even a
            # contradictory valid bit cannot make a subminimum range usable.
            if not fresh or not 30 <= distances[i] <= 1300:
                # A rejected conversion is not a proximity vote, but its
                # present, same-boot timestamp still fences older readings.
                previous = track.previous_sample_ms
                if has_hardware_identity and present & (1 << i):
                    stamp = sample_times[i]
                    if previous is None or 0 < (stamp - previous) & 0xffffffff < 0x80000000:
                        previous = stamp
                self.directions[i] = Direction(previous_sample_ms=previous)
                continue
            sample_at = now - ages[i] / 1000.0
            if has_hardware_identity:
                stamp = sample_times[i]
                if track.previous_sample_ms is not None:
                    delta = (stamp - track.previous_sample_ms) & 0xffffffff
                    # Cached reads and backward packets cannot each earn a
                    # new near/far vote when Mac/network timing fluctuates.
                    if delta == 0 or delta >= 0x80000000 or delta < 60:
                        continue
                    if delta > 2000:
                        self.directions[i] = track = Direction()
                track.previous_sample_ms = stamp
            elif track.previous_sample_at is not None:
                # Legacy/simulation data lacks WROOM acquisition identity.
                if sample_at - track.previous_sample_at < 0.06:
                    continue
                if sample_at - track.previous_sample_at > 2.0:
                    self.directions[i] = track = Direction()
            track.previous_sample_at = sample_at
            detected_near = distances[i] <= near_mm
            clearly_far = distances[i] >= near_mm + 60
            if not track.initialized:
                # A reading inside the hysteresis band proves neither near nor far.
                # Preserve its acquisition fence without inventing an arrival baseline.
                if not detected_near and not clearly_far:
                    continue
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

    def _reset(self, *, new_boot: bool = False) -> None:
        # Reset votes, not same-boot acquisition history. Only a new boot
        # can start a different WROOM conversion clock.
        self.directions = [
            Direction(previous_sample_ms=None if new_boot else track.previous_sample_ms)
            for track in self.directions
        ]
