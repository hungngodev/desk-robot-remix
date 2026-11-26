"""Local WROOM USB bench diagnostics and bounded commands. Never flashes a board.

Reuses the existing BodyControl UART protocol and pyserial. No default motor
arming, no automatic calibration, no remote safety rearm and no retry of an
uncertain actuator ACK. Reading status is not a physical qualification trial.
"""

import argparse
import json
import statistics
import time

import serial
from desk_robot.serial_device import require_local_serial_device
from desk_robot.transport import drive_duration_ms, expected_ack, validate_command


def inspect_native_low_g(imu: dict, family: int, raw_valid: bool) -> dict:
    """Read-only MPU FF_INT evidence from the existing WROOM status sample.

    A latched event may have ended by the USB read, so preserve its counter.
    Nothing here calibrates an actual fall or licenses robot motion.
    """
    fields = ("low_g_valid", "low_g_irq", "low_g_seq")
    if not any(key in imu for key in fields):
        return {
            "reported": False, "status_valid": False,
            "interrupt_in_last_sample": False, "event_seq": None,
            "physical_qualification_pass": False,
        }
    if not all(key in imu for key in fields):
        raise ValueError("Incomplete MPU6050 free-fall interrupt telemetry")
    status_valid, irq, seq = (imu[key] for key in fields)
    if (type(status_valid) is not bool or type(irq) is not bool
            or type(seq) is not int or not 0 <= seq <= 0xffffffff
            or (status_valid and (family != 4 or not raw_valid))
            or (irq and (not status_valid or seq == 0))
            or (family != 4 and (irq or seq != 0))):
        raise ValueError("Invalid MPU6050 free-fall interrupt provenance")
    return {
        "reported": True,
        "status_valid": status_valid,
        "interrupt_in_last_sample": irq,
        "event_seq": seq,
        "physical_qualification_pass": False,
    }


def _valid_range_arrays(mm, ages, count: int) -> bool:
    return (
        isinstance(mm, list) and len(mm) == count
        and isinstance(ages, list) and len(ages) == count
        and all(type(n) is int and 0 <= n <= 1300 for n in mm)
        and all(type(n) is int and n >= 0 for n in ages)
    )


def _inspect_primary_status(status: dict) -> tuple[dict, dict, dict]:
    if (not isinstance(status, dict)
            or status.get("backend") not in ("stepper_28byj48", "dc_pwm_guarded")):
        raise ValueError("Expected guarded WROOM stepper or DC body, not unguarded/mocked motion")
    touch, safety, ranges = (
        status.get("touch"), status.get("safety"), status.get("ranges")
    )
    if not all(isinstance(value, dict) for value in (touch, safety, ranges)):
        raise ValueError("Missing touch, safety or range diagnostics")
    present, valid = ranges.get("present_mask"), ranges.get("valid_mask")
    mm, ages = ranges.get("mm"), ranges.get("age_ms")
    if (
        type(present) is not int or not 0 <= present <= 31
        or type(valid) is not int or not 0 <= valid <= 31
        or not _valid_range_arrays(mm, ages, 5)
        or type(touch.get("active")) is not bool
        or type(safety.get("ready")) is not bool
    ):
        raise ValueError("Malformed or out-of-range WROOM status")
    fault = safety.get("fault")
    if fault is not None and (type(fault) is not str or len(fault) > 80):
        raise ValueError("Invalid WROOM local fault identity")
    return touch, safety, ranges


def _inspect_imu_identity(status: dict) -> tuple[dict, int, int, int]:
    imu = status.get("imu", {})
    if not isinstance(imu, dict):
        raise ValueError("Malformed optional IMU identity")
    family = imu.get("family", 0)
    gyro = imu.get("gyro_id", 0)
    aux = imu.get("aux_id", 0)
    if any(type(n) is not int or not 0 <= n <= 255 for n in (family, gyro, aux)):
        raise ValueError("Malformed optional IMU chip identity")
    if family > 4:
        raise ValueError("Unsupported IMU family code")
    if family == 4 and (gyro != 0x68 or aux != 0):
        raise ValueError("MPU6050 identity must match the official 0x75 response")
    return imu, family, gyro, aux


def _inspect_imu_sample(imu: dict, family: int) -> tuple:
    raw_present = any(key in imu for key in ("valid", "acc", "gyro", "age_ms"))
    identity_keys = ("boot_id", "sample_ms")
    boot_id = sample_ms = None
    if any(key in imu for key in identity_keys):
        boot_id, sample_ms = (imu.get(key) for key in identity_keys)
        if (type(boot_id) is not int or not 1 <= boot_id <= 0xffffffff
                or type(sample_ms) is not int or not 0 <= sample_ms <= 0xffffffff):
            raise ValueError("Malformed IMU boot/acquisition source identity")
    raw_valid = False
    accelerometer = gyroscope = None
    sample_age = None
    if raw_present:
        raw_valid = imu.get("valid")
        accelerometer = imu.get("acc")
        gyroscope = imu.get("gyro")
        sample_age = imu.get("age_ms")
        if (
            type(raw_valid) is not bool
            or any(
                not isinstance(axis, list) or len(axis) != 3
                or any(type(value) is not int or not -32768 <= value <= 32767
                       for value in axis)
                for axis in (accelerometer, gyroscope)
            )
            or type(sample_age) is not int or sample_age < 0
            or (raw_valid and (family == 0 or sample_age > 200))
        ):
            raise ValueError("Malformed or stale IMU six-axis diagnostics")
    return raw_valid, accelerometer, gyroscope, sample_age, boot_id, sample_ms


def _inspect_imu(status: dict, fault: str | None) -> tuple[dict, int, dict]:
    imu, family, gyro, aux = _inspect_imu_identity(status)
    raw_valid, accelerometer, gyroscope, sample_age, boot_id, sample_ms = (
        _inspect_imu_sample(imu, family)
    )
    attitude_faults = {
        "imu_attitude_latched", "imu_attitude_unqualified",
        "imu_attitude_not_upright",
    }
    return imu, family, {
        "family": ("unverified", "berryimu_v1", "berryimu_v2", "berryimu_v3", "mpu6050")[family],
        "gyro_who_am_i": gyro,
        "aux_who_am_i": aux,
        # The WROOM now has its own local MPU6050 attitude latch.
        # Its status fault can PROVE an active latch, but a generic
        # "none" or another higher-priority fault cannot prove the
        # guard is absent, configured or physically qualified.
        "raw_six_axis_available": raw_valid,
        "attitude_interlock_active": (
            True if fault == "imu_attitude_latched" else None
        ),
        "attitude_local_fault": fault if fault in attitude_faults else None,
        "accelerometer_raw": accelerometer,
        "gyroscope_raw": gyroscope,
        "sample_age_ms": sample_age,
        "source_boot_id": boot_id,
        "source_sample_ms": sample_ms,
    }


def _inspect_optional_inputs(extras) -> dict:
    if extras is None:
        return {
            "status_reported": False, "enabled_mask": 0,
            "bumper": False, "bumper_events": 0,
            "reed": False, "reed_events": 0,
            "pir": False, "pir_events": 0,
            "physical_qualification_pass": False,
        }
    if not isinstance(extras, dict):
        raise ValueError("Malformed optional WROOM extras")
    mask = extras.get("mask")
    if type(mask) is not int or not 0 <= mask <= 7:
        raise ValueError("Invalid optional sensor enable mask")
    for key in ("bumper", "reed", "pir"):
        if type(extras.get(key)) is not bool:
            raise ValueError("Invalid optional sensor input level")
    for key in ("bumps", "reed_count", "pir_count"):
        if type(extras.get(key)) is not int or not 0 <= extras[key] <= 0xffffffff:
            raise ValueError("Invalid optional sensor edge counter")
    if any(extras[name] for bit, name in (
        (1, "bumper"), (2, "reed"), (4, "pir")
    ) if not mask & bit):
        raise ValueError("Unenabled optional sensor cannot report active")
    return {
        "status_reported": True, "enabled_mask": mask,
        "bumper": extras["bumper"], "bumper_events": extras["bumps"],
        "reed": extras["reed"], "reed_events": extras["reed_count"],
        "pir": extras["pir"], "pir_events": extras["pir_count"],
        "physical_qualification_pass": False,
    }


def _inspect_cap_touch(extras) -> dict:
    cap_keys = ("cap", "cap_ok", "cap_events")
    if extras is None or not any(key in extras for key in cap_keys):
        return {"reported": False, "valid": False, "zone_mask": 0,
                "rising_zone_events": 0, "physical_qualification_pass": False}
    if not all(key in extras for key in cap_keys):
        raise ValueError("Incomplete CAP1188 optional telemetry")
    zones, cap_ok, events = (extras[key] for key in cap_keys)
    if (type(zones) is not int or not 0 <= zones <= 255
            or type(cap_ok) is not bool
            or type(events) is not int or not 0 <= events <= 0xffffffff
            or (not cap_ok and zones != 0)):
        raise ValueError("Invalid CAP1188 touch source or zone mask")
    return {
        "reported": True, "valid": cap_ok, "zone_mask": zones,
        "rising_zone_events": events, "physical_qualification_pass": False,
    }


def _inspect_side_ranges(side) -> dict:
    if side is None:
        return {"reported": False, "present_mask": 0, "valid_mask": 0,
                "readings": [], "motion_certified": False,
                "physical_qualification_pass": False}
    if not isinstance(side, dict):
        raise ValueError("Malformed left/right/rear ToF diagnostics")
    side_mm, side_age = side.get("mm"), side.get("age_ms")
    side_present, side_valid = side.get("present_mask"), side.get("valid_mask")
    if (not _valid_range_arrays(side_mm, side_age, 3)
            or type(side_present) is not int or not 0 <= side_present <= 7
            or type(side_valid) is not int or not 0 <= side_valid <= 7
            or side_valid & ~side_present
            or side.get("motion_certified") is not False
            or any(not 1 <= side_mm[i] <= 1300 for i in range(3) if side_valid & (1 << i))):
        raise ValueError("Invalid read-only side and rear ToF data")
    return {
        "reported": True, "present_mask": side_present, "valid_mask": side_valid,
        "readings": [
            {"direction": label, "distance_mm": side_mm[i],
             "age_ms": side_age[i], "present": bool(side_present & (1 << i)),
             "valid": bool(side_valid & (1 << i))}
            for i, label in enumerate(("left", "right", "rear"))
        ],
        "motion_certified": False, "physical_qualification_pass": False,
    }


def _summarize_guarded_ranges(ranges: dict) -> list[dict]:
    present, valid = ranges["present_mask"], ranges["valid_mask"]
    mm, ages = ranges["mm"], ranges["age_ms"]
    return [
        {
            "channel": index,
            "position": ("front_left", "front_right", "rear_left", "rear_right", "forward")[index],
            "distance_mm": mm[index],
            "age_ms": ages[index],
            "present": bool(present & (1 << index)),
            "valid": bool(valid & (1 << index)),
        }
        for index in range(5)
    ]


def _eligible_for_manual_local_rearm(status: dict, touch: dict, ranges: dict,
                                     extra_data: dict) -> bool:
    present, valid = ranges["present_mask"], ranges["valid_mask"]
    mm, ages = ranges["mm"], ranges["age_ms"]
    return (
        # The guarded DC profile has its own nFAULT, dock and external
        # watchdog prerequisites. This generic bench may INSPECT DC but
        # must not advertise a physical DC rearm permit based on ToF alone.
        status.get("backend") == "stepper_28byj48"
        and status.get("armed") is False
        and touch["active"] is False
        and not extra_data["bumper"]
        and present == 31 and valid == 31
        and all(1 <= value <= 1300 for value in mm)
        and all(0 <= age < 200 for age in ages)
    )


def inspect_status(status: dict) -> dict:
    """Summarize the actual five-channel WROOM JSON without granting movement."""
    touch, safety, ranges = _inspect_primary_status(status)
    imu, family, imu_data = _inspect_imu(status, safety.get("fault"))
    extras = status.get("extras")
    extra_data = _inspect_optional_inputs(extras)
    cap_input = _inspect_cap_touch(extras)
    side_input = _inspect_side_ranges(status.get("side_ranges"))
    # Keep low-g validation after the optional inputs, preserving error precedence.
    imu_data["native_low_g"] = inspect_native_low_g(
        imu, family, imu_data["raw_six_axis_available"]
    )
    imu_data["physical_qualification_pass"] = False
    return {
        "side_ranges": side_input,
        "cap_touch": cap_input,
        "optional_inputs": extra_data,
        "imu": imu_data,
        "armed": status.get("armed") is True,
        "touch_active": touch["active"],
        "local_guard_ready": safety["ready"],
        "local_guard_fault": safety.get("fault"),
        "fault_sensor": safety.get("sensor"),
        "ranges": _summarize_guarded_ranges(ranges),
        "eligible_for_manual_local_rearm": _eligible_for_manual_local_rearm(
            status, touch, ranges, extra_data
        ),
        "physical_qualification_pass": False,
    }


def transact_serial(port, command: str, *, receipt: dict | None = None) -> dict | str:
    """One bounded USB request; never accept a partial or short-written frame."""
    # Validate the complete command BEFORE writing any bytes to the body.
    expected = "OK rearm" if command == "rearm" else expected_ack(command)
    request = (command + "\n").encode("ascii")
    started_at = time.monotonic()
    if port.write(request) != len(request):
        raise RuntimeError("Short USB write; command delivery uncertain, no retry")
    deadline = time.monotonic() + 0.5
    pending = bytearray()
    while time.monotonic() < deadline:
        # read_until applies a whole-line timeout, unlike readline's per-read timeout.
        # Request only the remaining capacity, including the newline.
        remaining = 1920 - len(pending)
        fragment = port.read_until(b"\n", size=remaining)
        received_at = time.monotonic()
        if received_at >= deadline:
            break
        if len(fragment) > remaining:
            raise RuntimeError("USB response exceeds reply capacity")
        pending.extend(fragment)
        if len(pending) == 1920 and not pending.endswith(b"\n"):
            raise RuntimeError("USB response exceeds reply capacity")
        if not pending.endswith(b"\n"):
            continue
        response_bytes = len(pending)
        raw = bytes(pending[:-1]).removesuffix(b"\r")
        pending.clear()
        if b"\r" in raw or b"\n" in raw:
            raise RuntimeError("Malformed USB response framing")
        line = raw.decode("ascii", errors="strict")
        if line.startswith("ERR "):
            raise RuntimeError(line)
        if command == "status" and line.startswith("{"):
            response = json.loads(line)
            if not isinstance(response, dict):
                raise ValueError("Expected one body JSON object")
        elif command != "status" and line == expected:
            response = line
        else:
            continue
        if receipt is not None:
            receipt.update(
                request_bytes=len(request),
                matched_response_bytes=response_bytes,
                round_trip_ms=(received_at - started_at) * 1000,
            )
        return response
    raise TimeoutError("Uncertain USB response; no movement command will be retried")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True, help="Exact USB serial port for the WROOM")
    request = p.add_mutually_exclusive_group(required=True)
    request.add_argument("--inspect", action="store_true",
                         help="Read raw status on a stationary catch tray without arming")
    request.add_argument("--command", help='One bounded command, e.g. "grip 95"')
    p.add_argument("--samples", type=int, default=10,
                   help="Read-only status samples, 1..50, inspect mode only")
    p.add_argument("--local-rearm", action="store_true",
                   help="Explicit operator USB rearm after qualified sensors and a catch tray")
    args = p.parse_args()
    if args.inspect:
        if args.local_rearm or not 1 <= args.samples <= 50:
            p.error("Inspect needs 1..50 samples and never permits --local-rearm")
    else:
        if args.samples != 10:
            p.error("--samples is for --inspect only")
        op = validate_command(args.command)
        if op not in {"drive", "lift", "grip", "stop", "disarm", "halt"}:
            p.error("Choose bounded drive/lift/grip or stop/disarm/halt")
        if args.local_rearm and op in {"stop", "disarm", "halt"}:
            p.error("Stopping does not require and must not invoke rearm")
        # validate_command accepts an omitted drive duration (250ms). Compute
        # this before opening USB or issuing motion, never after actuation.
        if op == "drive":
            duration = drive_duration_ms(args.command) / 1000 + 0.05
        else:
            duration = 1.5

    try:
        require_local_serial_device(args.port)
    except ValueError as exc:
        p.error(str(exc))
    with serial.Serial(args.port, 115200, timeout=0.03, write_timeout=0.15) as port:
        # Opening USB may reset the dev board. Boot starts disarmed even if
        # a previous calibration was stored in NVS.
        time.sleep(2)
        port.reset_input_buffer()

        def transact(command):
            return transact_serial(port, command)

        if args.inspect:
            samples = []
            receipts = []
            started_at = time.monotonic()
            for i in range(args.samples):
                receipt = {}
                samples.append(inspect_status(
                    transact_serial(port, "status", receipt=receipt)
                ))
                receipts.append(receipt)
                if i + 1 < args.samples:
                    time.sleep(0.1)
            elapsed = time.monotonic() - started_at
            tx = sum(row["request_bytes"] for row in receipts)
            rx = sum(row["matched_response_bytes"] for row in receipts)
            latencies = [row["round_trip_ms"] for row in receipts]
            print(json.dumps({
                "samples": samples,
                "serial_bench": {
                    "configured_baud": 115200,
                    "successful_status_transactions": len(receipts),
                    "request_bytes": tx,
                    "matched_response_bytes": rx,
                    "sample_window_ms": round(elapsed * 1000, 3),
                    "status_transactions_per_second": (
                        round(len(receipts) / elapsed, 3) if elapsed > 0 else None
                    ),
                    "matched_response_bytes_per_second": (
                        round(rx / elapsed, 3) if elapsed > 0 else None
                    ),
                    "matched_request_response_bytes_per_second": (
                        round((tx + rx) / elapsed, 3) if elapsed > 0 else None
                    ),
                    "round_trip_ms": {
                        "min": round(min(latencies), 3),
                        "median": round(statistics.median(latencies), 3),
                        "max": round(max(latencies), 3),
                    },
                    "per_transaction": receipts,
                    "physical_line_rate_verified": False,
                    "note": "Host request/reply timing; goodput includes sample pacing",
                },
                "all_five_present_and_valid": all(
                    all(row["present"] and row["valid"] for row in s["ranges"])
                    for s in samples
                ),
                "physical_qualification_pass": False,
                "note": "Read-only bench evidence; measure stopping and power separately",
            }, indent=2))
            return

        if op in {"stop", "disarm", "halt"}:
            transact(args.command)
            print("Acknowledged " + op)
            return

        # A standalone terminal reconnect usually resets the WROOM; attempting
        # arm without explicit local rearm would fail and hides the sensor state.
        status = inspect_status(transact("status"))
        if not status["eligible_for_manual_local_rearm"]:
            raise RuntimeError(
                "Unqualified touch/range state; inspect first on catch tray. "
                "No arming or sensor configuration attempted."
            )
        if not args.local_rearm:
            raise RuntimeError(
                "Refusing implicit safety recovery. Use --local-rearm only after "
                "a real measured calibration and with tracks suspended over a catch tray."
            )
        try:
            transact("rearm")  # Direct body USB only; the guard can reject it.
            transact("arm")
            transact(args.command)
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                transact("keepalive")
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        finally:
            # End the standalone job without leaving an armed body lease.
            # HALT retains servo PWM rather than dropping a held object.
            transact("halt")
        print("Job ended; halt acknowledged. Servo angle is commanded, not measured.")


if __name__ == "__main__":
    main()
