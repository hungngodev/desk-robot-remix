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


def _stationary_body(body: object) -> bool:
    """Consume canonical WROOM motor.m0/m1, never assume legacy flat fields.

    Reject contradictory dual representations rather than trusting the
    quieter pair during a real motor command or an out-of-order callback.
    """
    if (not isinstance(body, dict) or type(body.get("drive_ms")) is not int
            or body["drive_ms"] != 0):
        return False
    motors = body.get("motor")
    if motors is not None:
        if (not isinstance(motors, dict)
                or type(motors.get("m0")) is not int
                or type(motors.get("m1")) is not int):
            return False
        if (("left" in body and
             (type(body["left"]) is not int or body["left"] != motors["m0"]))
                or ("right" in body and
                    (type(body["right"]) is not int or
                     body["right"] != motors["m1"]))):
            return False
        return motors["m0"] == 0 and motors["m1"] == 0
    return (type(body.get("left")) is int and body["left"] == 0 and
            type(body.get("right")) is int and body["right"] == 0)


def raw_mpu6050(
    body: dict, *, request_elapsed_ms: float = 0.0,
) -> tuple[tuple[float, ...], float] | None:
    """Validate stationary WROOM evidence before deriving handling context."""
    if not _stationary_body(body):
        return None
    return _decode_mpu6050(body, request_elapsed_ms=request_elapsed_ms)


def _decode_mpu6050(
    body: dict, *, request_elapsed_ms: float,
) -> tuple[tuple[float, ...], float] | None:
    """Validate acquisition identity and axes, including during drive."""
    if (not isinstance(body, dict)
            or type(request_elapsed_ms) not in (int, float)
            or not 0 <= request_elapsed_ms <= 200):
        return None
    imu = body.get("imu")
    if not isinstance(imu, dict):
        return None
    if (type(imu.get("family")) is not int or imu["family"] != 4
            or type(imu.get("gyro_id")) is not int or imu["gyro_id"] != 0x68
            or imu.get("valid") is not True
            or type(imu.get("age_ms")) is not int
            or not 0 <= imu["age_ms"] <= 200
            or imu["age_ms"] + request_elapsed_ms > 200
            or type(imu.get("sample_ms")) is not int
            or not 0 <= imu["sample_ms"] <= 0xffffffff
            or type(imu.get("boot_id")) is not int
            or not 1 <= imu["boot_id"] <= 0xffffffff):
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


def trial_low_g_counter(imu: dict) -> int | None:
    """Reject unsafe native IRQ evidence without qualifying legacy trial logs."""
    fields = ("low_g_valid", "low_g_irq", "low_g_seq")
    if not any(key in imu for key in fields):
        return None
    seq = imu.get("low_g_seq")
    if (imu.get("low_g_valid") is not True or imu.get("low_g_irq") is not False
            or type(seq) is not int or not 0 <= seq <= 0xffffffff):
        raise ValueError("Invalid native low-g status in handling trial")
    return seq


def mpu6050_temperature_raw(body: dict) -> int | None:
    """Expose the current signed MPU register for later measured bias trials.

    The raw number is not degrees Celsius, a compensated gyro rate, or
    evidence of physical orientation. Only accept a fresh stationary WROOM
    conversion with its explicit MPU-specific temperature validity flag.
    """
    if raw_mpu6050(body) is None:
        return None
    imu = body["imu"]
    value = imu.get("temp_raw")
    if (imu.get("temp_valid") is not True or type(value) is not int
            or not -32768 <= value <= 32767):
        return None
    return value


def _gravity_reference(
    samples: list[tuple[float, float, float]],
) -> tuple[float, float, float] | None:
    """Normalize the mean of eight validated stationary accelerometer samples."""
    x, y, z = (sum(v[i] for v in samples) / 8 for i in range(3))
    norm = math.hypot(x, y, z)
    if not 0.91 <= norm <= 1.09:
        return None
    return x / norm, y / norm, z / norm


def _relative_tilt_degrees(
    acceleration: tuple[float, ...], reference: tuple[float, float, float], g: float,
) -> float:
    """Angle to the unit baseline; caller has already gated gravity magnitude."""
    dot = sum(a * b for a, b in zip(acceleration, reference, strict=True)) / g
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


@dataclass
class HandlingGate:
    """Relative upright baseline and bounded event edges, not motion authority."""

    startup_samples: list[tuple[float, float, float]] = field(default_factory=list)
    startup_gyro_samples: list[tuple[float, float, float]] = field(default_factory=list)
    reference: tuple[float, float, float] | None = None
    gyro_bias_dps: tuple[float, float, float] | None = None
    tilt_hits: int = 0
    shake_hits: int = 0
    tilt_active: bool = False
    last_shake: float = -math.inf
    last_at: float | None = None
    last_boot_id: int | None = None
    last_sample_ms: int | None = None
    last_native_low_g: tuple[bool, object, object, object] | None = None
    last_low_g_seq: int | None = None  # MPU FF interrupt counter for same boot
    native_low_g_seen: bool = False  # session-sticky telemetry capability
    retired_boot_ids: list[int] = field(default_factory=list)

    @staticmethod
    def _native_low_g_snapshot(imu: dict) -> tuple[bool, object, object, object]:
        fields = ("low_g_valid", "low_g_irq", "low_g_seq")
        return (
            any(key in imu for key in fields),
            imu.get("low_g_valid"),
            imu.get("low_g_irq"),
            imu.get("low_g_seq"),
        )

    def reset(self, *, preserve_shake_cooldown: bool = False) -> None:
        """Clear a stale pose without rearming a recent gesture cooldown.

        An explicit session reset clears the cooldown by default. Telemetry
        gaps, invalid samples and qualification changes must preserve it.
        """
        last_shake = self.last_shake if preserve_shake_cooldown else -math.inf
        low_g_seq = self.last_low_g_seq if preserve_shake_cooldown else None
        self.startup_samples.clear()
        self.startup_gyro_samples.clear()
        self.reference = None
        self.gyro_bias_dps = None
        self.tilt_hits = 0
        self.shake_hits = 0
        self.tilt_active = False
        self.last_shake = last_shake
        self.last_at = None
        self.last_boot_id = None
        self.last_sample_ms = None
        self.last_native_low_g = None
        self.last_low_g_seq = low_g_seq
        if not preserve_shake_cooldown:
            # The bounded retired-boot replay fence belongs to one operator
            # session. Keep it through every automatic sensor fault/reset,
            # but let an explicit session restart recover after eight real
            # device boot changes. This never authorizes motors or motion.
            self.retired_boot_ids.clear()
            self.native_low_g_seen = False

    def observe(
        self, body: dict, now: float, *, qualified: bool,
        calibrated: bool = False,
        tilt_threshold_deg: float = 38.0,
        shake_delta_mg: int = 550,
        request_elapsed_ms: float = 0.0,
    ) -> tuple[str, ...]:
        if (type(qualified) is not bool
                or type(calibrated) is not bool
                or type(now) not in (int, float)
                or not -1e15 <= now <= 1e15
                or not math.isfinite(now)
                or type(shake_delta_mg) is not int
                or not 300 <= shake_delta_mg <= 1400
                or type(tilt_threshold_deg) not in (int, float)
                or not 25 <= tilt_threshold_deg <= 75
                or not math.isfinite(tilt_threshold_deg)):
            raise ValueError("Physically qualified MPU6050 thresholds required")
        if not qualified or not calibrated:
            # Heuristic thresholds remain provisional until operator attestation.
            # Revoking qualification clears pose, never trusted source identity.
            # Otherwise an old conversion can seed calibration when reenabled.
            previous = (self.last_boot_id, self.last_sample_ms, self.last_native_low_g)
            self.reset(preserve_shake_cooldown=True)
            self.last_boot_id, self.last_sample_ms, self.last_native_low_g = previous
            return ()
        # Retired packets cannot reset a current pose on late delivery.
        imu = body.get("imu") if isinstance(body, dict) else None
        if (isinstance(imu, dict) and type(imu.get("boot_id")) is int
                and imu["boot_id"] in self.retired_boot_ids):
            return ()
        stationary = _stationary_body(body)
        if not stationary:
            # Invalidate pose even for delayed motor-active callbacks. Still
            # consume new valid IMU identities below so a cached conversion
            # cannot count as stationary when the motor envelope changes.
            previous = (self.last_boot_id, self.last_sample_ms, self.last_native_low_g)
            self.reset(preserve_shake_cooldown=True)
            self.last_boot_id, self.last_sample_ms, self.last_native_low_g = previous
        # Conflicting same-acquisition native low-g metadata must revoke any
        # relative pose even when cached/replayed or arriving with a backdated
        # host callback timestamp.
        if (isinstance(imu, dict) and self.last_boot_id is not None
                and type(imu.get("boot_id")) is int
                and imu["boot_id"] == self.last_boot_id
                and type(imu.get("sample_ms")) is int
                and imu["sample_ms"] == self.last_sample_ms
                and self.last_native_low_g is not None):
            current_native = self._native_low_g_snapshot(imu)
            if current_native != self.last_native_low_g:
                if current_native[0]:
                    self.native_low_g_seen = True
                seq = imu.get("low_g_seq")
                valid = imu.get("low_g_valid")
                irq = imu.get("low_g_irq")
                if (type(valid) is bool and type(irq) is bool and type(seq) is int
                        and 0 <= seq <= 0xffffffff and valid
                        and not (irq and seq == 0)
                        and (self.last_low_g_seq is None or seq >= self.last_low_g_seq)):
                    self.last_low_g_seq = seq
                previous = (self.last_boot_id, self.last_sample_ms, self.last_native_low_g)
                previous_at = self.last_at
                self.reset(preserve_shake_cooldown=True)
                self.last_boot_id, self.last_sample_ms, self.last_native_low_g = previous
                self.last_at = previous_at
                return ()
        if self.last_at is not None and now <= self.last_at:
            # Old stationary observations cannot replace newer calibration.
            # An explicit motor-active status must still revoke the pose:
            # host callback ordering is not a motor safety interlock.
            if (isinstance(imu, dict)
                    and type(imu.get("boot_id")) is int
                    and self.last_boot_id is not None
                    and imu["boot_id"] != self.last_boot_id):
                # A new WROOM boot revokes the old pose even when its host
                # callback timestamp precedes the last delivered callback.
                pass
            elif _stationary_body(body):
                # A callback timestamp alone cannot establish acquisition
                # order. Reject only a replay of an older conversion; a
                # malformed NEW conversion must still revoke calibration.
                if (isinstance(imu, dict)
                        and type(imu.get("sample_ms")) is int
                        and self.last_sample_ms is not None
                        and 0 <= imu["sample_ms"] <= 0xffffffff
                        and imu["sample_ms"] <= self.last_sample_ms
                        and not (self.last_sample_ms >= 0xffff0000
                                 and imu["sample_ms"] <= 0xffff)):
                    return ()
        # An older acquisition with an intact stationary safety envelope
        # cannot revoke a newer pose merely because its IMU payload was
        # corrupted in transit. Invalid CURRENT acquisitions still fail closed.
        if (stationary and self.last_boot_id is not None
                and isinstance(imu, dict)
                and type(imu.get("boot_id")) is int
                and imu["boot_id"] == self.last_boot_id
                and type(imu.get("sample_ms")) is int
                and 0 <= imu["sample_ms"] <= 0xffffffff
                and self.last_sample_ms is not None
                and (
                    imu["sample_ms"] - self.last_sample_ms > 0x7fffffff
                    or (imu["sample_ms"] < self.last_sample_ms
                        and not (self.last_sample_ms >= 0xffff0000
                                 and imu["sample_ms"] <= 0xffff))
                )):
            return ()
        # A valid late conversion must not impersonate a polling outage.
        # Invalid current telemetry still falls through to fail closed.
        if (self.last_boot_id is not None and isinstance(imu, dict)
                and imu.get("boot_id") == self.last_boot_id
                and type(imu.get("sample_ms")) is int
                and self.last_sample_ms is not None
                and raw_mpu6050(body, request_elapsed_ms=request_elapsed_ms) is not None):
            stamp = imu["sample_ms"]
            if stamp == self.last_sample_ms:
                if self.last_at is not None and now - self.last_at > 1.0:
                    # The reader may have reconnected after a long gap while
                    # still exposing the last cached conversion as fresh.
                    # Invalidate the pose/baseline, but retain the exact
                    # acquisition identity so that cached data cannot seed it.
                    previous = (self.last_boot_id, self.last_sample_ms, self.last_native_low_g)
                    self.reset(preserve_shake_cooldown=True)
                    self.last_boot_id, self.last_sample_ms, self.last_native_low_g = previous
                return ()
            if (stamp < self.last_sample_ms
                    and not (self.last_sample_ms >= 0xffff0000
                             and stamp <= 0xffff)):
                # A late older conversion is not evidence of a NEW polling
                # outage; never erase the newer trusted pose on replay.
                return ()
        if self.last_at is not None and now - self.last_at > 1.0:
            # Host reconnect invalidates calibration, not source identity.
            previous = (self.last_boot_id, self.last_sample_ms, self.last_native_low_g)
            self.reset(preserve_shake_cooldown=True)
            self.last_boot_id, self.last_sample_ms, self.last_native_low_g = previous
            # A transport gap invalidates pose, not the gesture cooldown.
        sample = _decode_mpu6050(body, request_elapsed_ms=request_elapsed_ms)
        if sample is None:
            # Bad telemetry invalidates pose, not the last trusted acquisition.
            # Otherwise replaying that conversion after a malformed status
            # could seed a fresh calibration with stale sensor data.
            previous = (self.last_boot_id, self.last_sample_ms, self.last_native_low_g)
            self.reset(preserve_shake_cooldown=True)
            self.last_boot_id, self.last_sample_ms, self.last_native_low_g = previous
            # Bad telemetry revokes pose, not the recent gesture cooldown.
            # Otherwise a quick recalibration can repeat a shake announcement.
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
                    previous = (self.last_boot_id, self.last_sample_ms, self.last_native_low_g)
                    self.reset(preserve_shake_cooldown=True)
                    self.last_boot_id, self.last_sample_ms, self.last_native_low_g = previous
                    return ()
                old_boot = self.last_boot_id
                self.reset(preserve_shake_cooldown=True)  # new WROOM boot identity requires fresh calibration
                self.last_low_g_seq = None  # MCU counter begins at zero per boot
                self.retired_boot_ids.append(old_boot)
            elif sample_ms < self.last_sample_ms:
                # Only a near-uint32 wrap can legitimately restart the clock.
                # A backward sample from the same boot must not be treated as
                # a new conversion or become the new calibration baseline.
                if not (self.last_sample_ms >= 0xffff0000 and sample_ms <= 0xffff):
                    # A delayed conversion cannot invalidate a newer pose.
                    # Real boot changes and forward host gaps still reset it.
                    return ()
                # A 32-bit sensor clock rollover invalidates pose but must
                # not reset the human gesture cooldown on the host clock.
                previous_at = self.last_at
                self.reset(preserve_shake_cooldown=True)
                self.last_at = previous_at
            elif sample_ms - self.last_sample_ms > 0x7fffffff:
                # A pre-wrap conversion arriving after wrap looks numerically
                # newer. Reject implausibly large forward jumps as replay.
                return ()
            elif sample_ms == self.last_sample_ms:
                return ()  # same physical conversion; do not update last_at
        self.last_boot_id = boot_id
        self.last_sample_ms = sample_ms
        # Accepted sensor acquisitions may arrive with an older host callback
        # time. Never rewind the gate's cooldown and polling clock.
        self.last_at = max(now, self.last_at) if self.last_at is not None else now
        # FF_THR/FF_DUR are sampled by the WROOM silicon, not inferred from
        # the last accelerometer snapshot. A brief hardware IRQ can vanish
        # before a slow Mac body poll; preserve the monotonically increasing
        # count across automatic telemetry faults. This is an unqualified
        # low-g candidate, never a verified fall or motor/speech command.
        source = body["imu"]
        self.last_native_low_g = self._native_low_g_snapshot(source)
        fields = ("low_g_valid", "low_g_irq", "low_g_seq")
        if any(key in source for key in fields):
            self.native_low_g_seen = True
        # Once native FF status is present, a partial or downgraded adapter
        # cannot silently recover a trusted pose by omitting all three fields.
        # Keep the capability fence across faults and WROOM reboots until an
        # explicit operator session reset; legacy read-only adapters can still
        # operate before any native FF metadata is observed.
        if self.native_low_g_seen:
            seq = source.get("low_g_seq")
            valid = source.get("low_g_valid")
            irq = source.get("low_g_irq")
            malformed = (
                type(valid) is not bool or type(irq) is not bool
                or type(seq) is not int or not 0 <= seq <= 0xffffffff
                or (irq and not valid) or (irq and seq == 0)
            )
            new_irq = (
                not malformed and valid
                and (self.last_low_g_seq is None and seq > 0
                     or self.last_low_g_seq is not None
                     and seq > self.last_low_g_seq)
            )
            backward = (
                not malformed and valid and self.last_low_g_seq is not None
                and seq < self.last_low_g_seq
            )
            if not malformed and valid and not backward:
                self.last_low_g_seq = seq
            if malformed or not valid or irq or new_irq or backward:
                # A failed FF status read cannot rule out an unseen fall.
                # Keep acquisition identity and event fence, but revoke
                # relative pose until eight fresh quiet observations return.
                # This never initiates motion or reports a verified fall.
                previous = (self.last_boot_id, self.last_sample_ms, self.last_native_low_g)
                self.reset(preserve_shake_cooldown=True)
                self.last_boot_id, self.last_sample_ms, self.last_native_low_g = previous
                return ()
        if not stationary:
            # The acquisition fence and native low-g metadata are current,
            # but motion-contaminated axes must never seed or emit a gesture.
            return ()
        acceleration, rotation_dps = sample
        # Decode the same validated MPU6050 axes, not a new I2C reader.
        # Estimating stationary bias follows the standard mean-zero-rate
        # gyro calibration pattern; it does NOT replace per-unit bench trials,
        # temperature characterization or a complete Fusion AHRS.
        gyro_axes = tuple(
            raw / GYRO_COUNTS_PER_DPS for raw in body["imu"]["gyro"]
        )
        g = math.hypot(*acceleration)
        if not 0.5 <= g <= 3.5:
            # InvenSense's MPU6050 free-fall guidance identifies a sustained
            # low-acceleration interval as a possible drop. A low-g sample
            # cannot preserve a trusted upright mount pose through a possible
            # fall or impact. Revoke relative calibration conservatively;
            # this is NOT a free-fall event or verified drop detector.
            # https://cdn.sparkfun.com/datasheets/Components/General%20IC/PS-MPU-6000A.pdf
            # Keep acquisition identity so a replay cannot seed calibration.
            previous = (self.last_boot_id, self.last_sample_ms)
            self.reset(preserve_shake_cooldown=True)
            self.last_boot_id, self.last_sample_ms = previous
            # Implausible acceleration revokes pose, not the host cooldown.
            return ()
        if self.reference is None:
            # Startup is an intentional physical calibration step. Accel
            # must be near 1g and gyro quiet for 8 consecutive fresh reads.
            if not (0.91 <= g <= 1.09 and rotation_dps <= 7):
                self.startup_samples.clear()
                self.startup_gyro_samples.clear()
                return ()
            self.startup_samples.append(acceleration)
            self.startup_gyro_samples.append(gyro_axes)
            if len(self.startup_samples) == 8:
                reference = _gravity_reference(self.startup_samples)
                if reference is None:
                    # Conflicting stationary vectors invalidate calibration,
                    # not the identity of the conversion just consumed.
                    previous = (self.last_boot_id, self.last_sample_ms)
                    self.reset(preserve_shake_cooldown=True)
                    self.last_boot_id, self.last_sample_ms = previous
                    return ()
                mean_gyro = tuple(
                    sum(v[i] for v in self.startup_gyro_samples) / 8
                    for i in range(3)
                )
                # An average of moving samples is not a gyro zero point.
                # A stationary calibration must hold every axis within one
                # degree per second of the whole-window mean.
                if any(
                    abs(v[axis] - mean_gyro[axis]) > 1.0
                    for v in self.startup_gyro_samples
                    for axis in range(3)
                ):
                    self.startup_samples.clear()
                    self.startup_gyro_samples.clear()
                    return ()
                self.reference = reference
                self.gyro_bias_dps = mean_gyro
                self.startup_samples.clear()
                self.startup_gyro_samples.clear()
            return ()

        if self.gyro_bias_dps is None:
            # Missing stationary gyro evidence revokes the pose, but the
            # consumed conversion must remain fenced against replay.
            previous = (self.last_boot_id, self.last_sample_ms)
            self.reset(preserve_shake_cooldown=True)
            self.last_boot_id, self.last_sample_ms = previous
            return ()
        rotation_dps = math.hypot(*(
            raw - bias for raw, bias in
            zip(gyro_axes, self.gyro_bias_dps, strict=True)
        ))
        events = []
        # Shake requires a simultaneous accelerometer departure from 1g
        # AND noticeable gyro motion, unlike a normal soft static tilt.
        shook = (abs(g - 1.0) * 1000 >= shake_delta_mg and rotation_dps >= 50)
        self.shake_hits = min(2, self.shake_hits + 1) if shook else 0
        if self.shake_hits >= 2 and self.last_at - self.last_shake >= 3.0:
            self.last_shake = self.last_at
            events.append("handling_shake")
        if not 0.75 <= g <= 1.25 or rotation_dps > 70:
            # Dynamic acceleration has no reliable gravity direction.
            self.tilt_hits = 0
            return tuple(events)

        angle = _relative_tilt_degrees(acceleration, self.reference, g)
        tilted = angle >= tilt_threshold_deg
        self.tilt_hits = min(2, self.tilt_hits + 1) if tilted else 0
        if self.tilt_hits >= 2 and not self.tilt_active:
            self.tilt_active = True
            events.append("handling_tilt")
        elif angle <= tilt_threshold_deg * 0.5:
            self.tilt_active = False
        return tuple(events)
