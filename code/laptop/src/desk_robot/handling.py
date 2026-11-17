"""Read-only physical MPU6050 handling events from the existing WROOM driver.

Reuses the InvenSense official +/-2g and +/-250dps register scales configured
by BerryImu.cpp and xioTechnologies/Fusion's principle that accelerometer
orientation needs stationarity/gyro rejection. This is deliberately NOT a
copied AHRS library or a replacement for the local cliff / tilt motor guard.
Orientation is RELATIVE to an operator-qualified stationary startup pose;
it is NOT an absolute room pose, fall measurement, pickup or force sensor.

No extra MCU polling, calibrated Euler axes, servo command or motor permit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

ACC_COUNTS_PER_G = 16384.0  # MPU6050: ACCEL_CONFIG 0x00, +/-2g.
GYRO_COUNTS_PER_DPS = 131.0  # MPU6050: GYRO_CONFIG 0x00, +/-250dps.


def raw_mpu6050(body: dict) -> tuple[tuple[float, ...], float] | None:
    """Validate the WROOM 6-axis and source metadata before deriving context."""
    if not isinstance(body, dict):
        return None
    imu = body.get("imu")
    if not isinstance(imu, dict):
        return None
    if (type(imu.get("family")) is not int or imu["family"] != 4
            or type(imu.get("gyro_id")) is not int or imu["gyro_id"] != 0x68
            or imu.get("valid") is not True
            or type(imu.get("age_ms")) is not int
            or not 0 <= imu["age_ms"] <= 200
            or type(imu.get("sample_ms")) is not int
            or not 0 <= imu["sample_ms"] <= 0xffffffff
            or type(imu.get("boot_id")) is not int
            or not 1 <= imu["boot_id"] <= 0xffffffff
            or type(body.get("left")) is not int
            or type(body.get("right")) is not int
            or body["left"] != 0 or body["right"] != 0
            or type(body.get("drive_ms")) is not int
            or body["drive_ms"] != 0):
        return None
    accel, gyro = imu.get("acc"), imu.get("gyro")
    if any(
        not isinstance(v, list) or len(v) != 3 or
        any(type(n) is not int or not -32768 <= n <= 32767 for n in v)
        for v in (accel, gyro)
    ):
        return None
    scaled = tuple(v / ACC_COUNTS_PER_G for v in accel)
    rate = math.hypot(*(v / GYRO_COUNTS_PER_DPS for v in gyro))
    if not math.isfinite(rate) or rate > 450:
        return None
    return scaled, rate


@dataclass
class HandlingGate:
    """Relative upright baseline and bounded event edges, not motion authority."""

    startup_samples: list[tuple[float, float, float]] = field(default_factory=list)
    reference: tuple[float, float, float] | None = None
    tilt_hits: int = 0
    shake_hits: int = 0
    tilt_active: bool = False
    last_shake: float = -math.inf
    last_at: float | None = None
    last_boot_id: int | None = None
    last_sample_ms: int | None = None
    retired_boot_ids: list[int] = field(default_factory=list)

    def reset(self) -> None:
        self.startup_samples.clear()
        self.reference = None
        self.tilt_hits = 0
        self.shake_hits = 0
        self.tilt_active = False
        self.last_shake = -math.inf
        self.last_at = None
        self.last_boot_id = None
        self.last_sample_ms = None

    def observe(
        self, body: dict, now: float, *, qualified: bool,
        tilt_threshold_deg: float = 38.0,
        shake_delta_mg: int = 550,
    ) -> tuple[str, ...]:
        if (type(qualified) is not bool
                or type(now) not in (int, float)
                or not -1e15 <= now <= 1e15
                or not math.isfinite(now)
                or type(shake_delta_mg) is not int
                or not 300 <= shake_delta_mg <= 1400
                or type(tilt_threshold_deg) not in (int, float)
                or not 25 <= tilt_threshold_deg <= 75
                or not math.isfinite(tilt_threshold_deg)):
            raise ValueError("Physically qualified MPU6050 thresholds required")
        if not qualified:
            # Revoking qualification clears pose, never trusted source identity.
            # Otherwise an old conversion can seed calibration when reenabled.
            previous = (self.last_boot_id, self.last_sample_ms)
            self.reset()
            self.last_boot_id, self.last_sample_ms = previous
            return ()
        # Retired packets cannot reset a current pose on late delivery.
        imu = body.get("imu") if isinstance(body, dict) else None
        if (isinstance(imu, dict) and type(imu.get("boot_id")) is int
                and imu["boot_id"] in self.retired_boot_ids):
            return ()
        if self.last_at is not None and now <= self.last_at:
            # Old stationary observations cannot replace newer calibration.
            # An explicit motor-active status must still revoke the pose:
            # host callback ordering is not a motor safety interlock.
            if (isinstance(body, dict)
                    and type(body.get("left")) is int and body["left"] == 0
                    and type(body.get("right")) is int and body["right"] == 0
                    and type(body.get("drive_ms")) is int
                    and body["drive_ms"] == 0):
                return ()
        # An older acquisition with an intact stationary safety envelope
        # cannot revoke a newer pose merely because its IMU payload was
        # corrupted in transit. Invalid CURRENT acquisitions still fail closed.
        stationary = (isinstance(body, dict)
                      and type(body.get("left")) is int and body["left"] == 0
                      and type(body.get("right")) is int and body["right"] == 0
                      and type(body.get("drive_ms")) is int
                      and body["drive_ms"] == 0)
        if (stationary and self.last_boot_id is not None
                and isinstance(imu, dict)
                and type(imu.get("boot_id")) is int
                and imu["boot_id"] == self.last_boot_id
                and type(imu.get("sample_ms")) is int
                and 0 <= imu["sample_ms"] <= 0xffffffff
                and self.last_sample_ms is not None
                and imu["sample_ms"] < self.last_sample_ms
                and not (self.last_sample_ms >= 0xffff0000
                         and imu["sample_ms"] <= 0xffff)):
            return ()
        # A valid late conversion must not impersonate a polling outage.
        # Invalid current telemetry still falls through to fail closed.
        if (self.last_boot_id is not None and isinstance(imu, dict)
                and imu.get("boot_id") == self.last_boot_id
                and type(imu.get("sample_ms")) is int
                and self.last_sample_ms is not None
                and raw_mpu6050(body) is not None):
            stamp = imu["sample_ms"]
            if stamp == self.last_sample_ms:
                if self.last_at is not None and now - self.last_at > 1.0:
                    # The reader may have reconnected after a long gap while
                    # still exposing the last cached conversion as fresh.
                    # Invalidate the pose/baseline, but retain the exact
                    # acquisition identity so that cached data cannot seed it.
                    previous = (self.last_boot_id, self.last_sample_ms)
                    self.reset()
                    self.last_boot_id, self.last_sample_ms = previous
                return ()
            if (stamp < self.last_sample_ms
                    and not (self.last_sample_ms >= 0xffff0000
                             and stamp <= 0xffff)):
                # A late older conversion is not evidence of a NEW polling
                # outage; never erase the newer trusted pose on replay.
                return ()
        if self.last_at is not None and now - self.last_at > 1.0:
            # Host reconnect invalidates calibration, not source identity.
            previous = (self.last_boot_id, self.last_sample_ms)
            self.reset()
            self.last_boot_id, self.last_sample_ms = previous
        sample = raw_mpu6050(body)
        if sample is None:
            # Bad telemetry invalidates pose, not the last trusted acquisition.
            # Otherwise replaying that conversion after a malformed status
            # could seed a fresh calibration with stale sensor data.
            previous = (self.last_boot_id, self.last_sample_ms)
            self.reset()
            self.last_boot_id, self.last_sample_ms = previous
            return ()
        boot_id = body["imu"]["boot_id"]
        sample_ms = body["imu"]["sample_ms"]
        if boot_id in self.retired_boot_ids:
            # Delayed status from a prior boot must not displace the current
            # calibration or revive a previously accepted conversion.
            return ()
        if self.last_boot_id is not None:
            if boot_id != self.last_boot_id:
                # Never evict a retired identity: its delayed packets could
                # otherwise impersonate a new boot and reset live calibration.
                # Require an operator/session restart after this bounded limit.
                if len(self.retired_boot_ids) >= 8:
                    # An unrecognized generation cannot be trusted. Keep the
                    # replay fence, but revoke any calibrated handling pose.
                    previous = (self.last_boot_id, self.last_sample_ms)
                    self.reset()
                    self.last_boot_id, self.last_sample_ms = previous
                    return ()
                old_boot = self.last_boot_id
                self.reset()  # new WROOM boot identity requires fresh calibration
                self.retired_boot_ids.append(old_boot)
            elif sample_ms < self.last_sample_ms:
                # Only a near-uint32 wrap can legitimately restart the clock.
                # A backward sample from the same boot must not be treated as
                # a new conversion or become the new calibration baseline.
                if not (self.last_sample_ms >= 0xffff0000 and sample_ms <= 0xffff):
                    # A delayed conversion cannot invalidate a newer pose.
                    # Real boot changes and forward host gaps still reset it.
                    return ()
                self.reset()
            elif sample_ms - self.last_sample_ms > 0x7fffffff:
                # A pre-wrap conversion arriving after wrap looks numerically
                # newer. Reject implausibly large forward jumps as replay.
                return ()
            elif sample_ms == self.last_sample_ms:
                return ()  # same physical conversion; do not update last_at
        self.last_boot_id = boot_id
        self.last_sample_ms = sample_ms
        self.last_at = now
        acceleration, rotation_dps = sample
        g = math.hypot(*acceleration)
        if not 0.05 <= g <= 3.5:
            # Reject implausible acceleration without forgetting the source
            # conversion. A replay after the fault must not seed calibration.
            previous = (self.last_boot_id, self.last_sample_ms)
            self.reset()
            self.last_boot_id, self.last_sample_ms = previous
            return ()
        if self.reference is None:
            # Startup is an intentional physical calibration step. Accel
            # must be near 1g and gyro quiet for 8 consecutive fresh reads.
            if not (0.91 <= g <= 1.09 and rotation_dps <= 7):
                self.startup_samples.clear()
                return ()
            self.startup_samples.append(acceleration)
            if len(self.startup_samples) == 8:
                x, y, z = (
                    sum(v[i] for v in self.startup_samples) / 8 for i in range(3)
                )
                norm = math.hypot(x, y, z)
                if not 0.91 <= norm <= 1.09:
                    # Conflicting stationary vectors invalidate calibration,
                    # not the identity of the conversion just consumed.
                    previous = (self.last_boot_id, self.last_sample_ms)
                    self.reset()
                    self.last_boot_id, self.last_sample_ms = previous
                    return ()
                self.reference = (x / norm, y / norm, z / norm)
                self.startup_samples.clear()
            return ()

        events = []
        # Shake requires a simultaneous accelerometer departure from 1g
        # AND noticeable gyro motion, unlike a normal soft static tilt.
        shook = (abs(g - 1.0) * 1000 >= shake_delta_mg and rotation_dps >= 50)
        self.shake_hits = min(2, self.shake_hits + 1) if shook else 0
        if self.shake_hits >= 2 and now - self.last_shake >= 3.0:
            self.last_shake = now
            events.append("handling_shake")
        if not 0.75 <= g <= 1.25 or rotation_dps > 70:
            # Dynamic acceleration has no reliable gravity direction.
            self.tilt_hits = 0
            return tuple(events)

        dot = sum(a*b for a, b in zip(acceleration, self.reference, strict=True)) / g
        angle = math.degrees(math.acos(max(-1.0, min(1.0, dot))))
        tilted = angle >= tilt_threshold_deg
        self.tilt_hits = min(2, self.tilt_hits + 1) if tilted else 0
        if self.tilt_hits >= 2 and not self.tilt_active:
            self.tilt_active = True
            events.append("handling_tilt")
        elif angle <= tilt_threshold_deg * 0.5:
            self.tilt_active = False
        return tuple(events)
