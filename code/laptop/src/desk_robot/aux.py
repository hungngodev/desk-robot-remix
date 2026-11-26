"""Strict read-only source validation for one robot's optional sensor telemetry.

Raw samples are never evidence of medical data, a real grasp force, charging,
calibrated locomotion, or authorization to move motors.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .sensor_event_contract import (
    fuel_sample_is_fresh,
    is_int_in_range,
    is_uint,
    is_valid_fuel_measurement,
)


def _bool(value: object) -> bool:
    return type(value) is bool


def _array(value: object, length: int, predicate: Callable[[object], bool]) -> bool:
    return isinstance(value, list) and len(value) == length and all(
        predicate(v) for v in value
    )


def _valid_angle_acquisition(angles: dict[str, Any]) -> bool:
    """Check optional AS5600 wire clocks against WROOM's 350 ms lifetime."""
    if "boot_id" in angles and not is_int_in_range(angles["boot_id"], 1, 0xffffffff):
        return False
    if "seq" not in angles and "age_ms" not in angles:
        return True  # Legacy raw diagnostics have no acquisition clock.
    seqs, ages = angles.get("seq"), angles.get("age_ms")
    if (not _array(seqs, 3, lambda n: is_uint(n, 0xffffffff))
            or not _array(ages, 3, lambda n: is_uint(n, 0xffffffff))):
        return False
    return all(
        not angles["valid_mask"] & (1 << i) or (seqs[i] != 0 and ages[i] < 350)
        for i in range(3)
    )


def _fresh_aux_acquisition(
    reading: object, *, previous_seq: int | None, max_age_ms: int,
    elapsed_ms: float = 0.0,
) -> bool:
    """Require a recent, genuinely newer acquisition for spoken tool context.

    Old firmware may omit a clock in its raw read-only diagnostics. That
    compatibility must not turn one indefinitely cached sensor value into a
    succession of new live observations for the model.
    """
    if not isinstance(reading, dict) or reading.get("valid") is not True:
        return False
    seq, age = reading.get("seq"), reading.get("age_ms")
    if (type(seq) is not int or not 1 <= seq <= 0xffffffff
            or type(age) is not int or not 0 <= age < max_age_ms
            or type(elapsed_ms) not in (int, float)
            or not 0 <= elapsed_ms < max_age_ms
            or age + elapsed_ms >= max_age_ms):
        return False
    if previous_seq is None:
        return True
    # Unsigned half-range ordering accepts genuine uint32 sequence rollover,
    # but rejects duplicate and reordered old observations.
    delta = (seq - previous_seq) & 0xffffffff
    return 0 < delta < 0x80000000


def _aux_boot_epoch(data: dict[str, Any]) -> int | None:
    """Bind conversational ambient samples to one explicit WROOM boot."""
    force, proximity = data.get("force"), data.get("proximity")
    if not isinstance(force, dict) or not isinstance(proximity, dict):
        return None
    first, second = force.get("boot_id"), proximity.get("boot_id")
    if (type(first) is int and 1 <= first <= 0xffffffff
            and type(second) is int and first == second):
        return first
    return None


class NoseDialGate:
    """Interpret only fresh, calibrated nose samples from one WROOM boot."""

    def __init__(self) -> None:
        self.last_angle: int | None = None
        self.last_seq: int | None = None

    def invalidate(self) -> None:
        # A read failure breaks angle continuity, not the anti-replay fence.
        self.last_angle = None

    def reset(self) -> None:
        self.invalidate()
        self.last_seq = None

    def observe(
        self, angles: dict[str, Any], *, boot_id: int | None,
        threshold: int | None, request_elapsed_ms: float,
    ) -> bool:
        seqs, ages = angles.get("seq"), angles.get("age_ms")
        # Legacy packets remain raw diagnostics; they cannot generate turns.
        if (threshold is None or boot_id is None
                or type(angles.get("boot_id")) is not int or angles["boot_id"] != boot_id
                or not _array(seqs, 3, lambda n: is_uint(n, 0xffffffff))
                or not _array(ages, 3, lambda n: is_uint(n, 0xffffffff))):
            self.invalidate()
            return False
        reading = {
            "valid": bool(angles["valid_mask"] & 1), "seq": seqs[0], "age_ms": ages[0],
        }
        if (not _fresh_aux_acquisition(reading, previous_seq=None, max_age_ms=350)
                or type(request_elapsed_ms) not in (int, float)
                or not 0 <= request_elapsed_ms < 350
                or ages[0] + request_elapsed_ms >= 350):
            self.invalidate()
            return False
        if not _fresh_aux_acquisition(reading, previous_seq=self.last_seq, max_age_ms=350):
            return False
        previous = self.last_angle
        self.last_angle, self.last_seq = angles["raw"][0], seqs[0]
        # The calibrated threshold itself is inside the deadband.
        return previous is not None and (
            abs((self.last_angle - previous + 2048) % 4096 - 2048) > threshold
        )


def ina226_monitor_warning(power: dict[str, Any]) -> str | None:
    """Describe the last observed fault without treating it as a fresh sample."""
    if "monitor_fault" not in power:
        return None  # Older firmware cannot distinguish a fault from missing data.
    fault = power["monitor_fault"]
    if fault == "none":
        return None
    if (fault not in ("math_overflow", "shunt_saturated")
            or power.get("monitor_valid") is not False
            or power.get("pack_valid", False) is not False):
        raise ValueError("Invalid INA226 monitor fault provenance")
    if fault == "math_overflow":
        return "Last INA226 conversion reported math overflow; current unavailable."
    return "Last INA226 shunt reading saturated; current unavailable."


def validate_aux(data: dict[str, Any], robot_id: str) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("robot_id") != robot_id:
        raise ValueError("Aux sensor identity mismatch")
    pulse, angles = data.get("pulse"), data.get("angles")
    force, climate = data.get("force"), data.get("climate")
    power, proximity = data.get("power"), data.get("proximity")
    if not all(isinstance(group, dict) for group in (
        pulse, angles, force, climate, power, proximity,
    )):
        raise ValueError("Incomplete auxiliary sensor payload")

    if (not _bool(pulse.get("present")) or not _bool(pulse.get("valid"))
            or not is_uint(pulse.get("part_id"), 255)
            or not is_uint(pulse.get("red"), 262143)
            or not is_uint(pulse.get("ir"), 262143)
            or not is_uint(pulse.get("age_ms"), 0xffffffff)
            or (pulse.get("seq") is not None and (
                not is_uint(pulse["seq"], 0xffffffff)
                or (pulse["valid"] and pulse["seq"] == 0)
            ))
            or pulse.get("bpm", "missing") is not None
            or pulse.get("medical") is not False
            or ("fifo_ir_first" in pulse and not _bool(pulse["fifo_ir_first"]))
            or ("fifo_layout_physically_verified" in pulse
                and pulse["fifo_layout_physically_verified"] is not False)
            or (pulse["valid"] and not pulse["present"])):
        raise ValueError("Invalid raw MAX30102 paw source")

    present, valid = angles.get("present_mask"), angles.get("valid_mask")
    if (not is_uint(present, 7) or not is_uint(valid, 7)
            or valid & ~present
            or ("wheel_travel_qualified" in angles
                and angles["wheel_travel_qualified"] is not False)
            or not _array(angles.get("raw"), 3, lambda n: is_uint(n, 4095))
            or not _array(angles.get("magnet"), 3, lambda n: is_uint(n, 0x38))
            or any(valid & (1 << i) and angles["magnet"][i] != 0x20
                   for i in range(3))):
        raise ValueError("Invalid AS5600 magnetic angle source")
    if not _valid_angle_acquisition(angles):
        raise ValueError("Invalid AS5600 acquisition provenance")

    jaw_valid = force.get("jaw_valid")
    belly_valid = force.get("belly_valid")
    belly_seq = force.get("belly_seq")
    belly_age = force.get("belly_age_ms")
    jaw_age = force.get("jaw_age_ms")

    if (not _array(force.get("adc"), 2, lambda n: is_int_in_range(n, -32768, 32767))
            or not _bool(force.get("valid"))
            or force.get("calibrated") is not False
            or not is_uint(force.get("jaw_seq"), 0xffffffff)
            or ("boot_id" in force and not is_uint(force["boot_id"], 0xffffffff))
            or ("jaw_age_ms" in force and not is_uint(jaw_age, 0xffffffff))
            or ("jaw_valid" in force and not _bool(jaw_valid))
            or ("belly_seq" in force and not is_uint(belly_seq, 0xffffffff))
            or ("belly_age_ms" in force and not is_uint(belly_age, 0xffffffff))
            or ("belly_valid" in force and not _bool(belly_valid))
            # Saturated ADC clipping or staleness invalidates the corresponding channel
            or (jaw_valid is True and (
                force["adc"][1] in (-32768, 32767)
                or force["jaw_seq"] == 0
                or (jaw_age is not None and jaw_age >= 500)))
            or (belly_valid is True and (
                force["adc"][0] in (-32768, 32767)
                or (belly_seq is not None and belly_seq == 0)
                or (belly_age is not None and belly_age >= 500)))
            # Composite validity requires both channels to be fresh and unclipped
            or (force.get("valid") is True and (
                force["adc"][0] in (-32768, 32767)
                or force["adc"][1] in (-32768, 32767)
                or (jaw_age is not None and jaw_age >= 500)
                or (belly_age is not None and belly_age >= 500)
                or jaw_valid is False
                or belly_valid is False))
            # Typed per-channel validities must match composite valid
            or (jaw_valid is not None and belly_valid is not None and (
                force.get("valid") != (jaw_valid and belly_valid)))):
        raise ValueError("Invalid uncalibrated FSR sample")

    if (not is_int_in_range(climate.get("temp_centi"), -4500, 13000)
            or not is_uint(climate.get("rh_centi"), 10000)
            or not _bool(climate.get("valid"))
            or (climate.get("seq") is not None and (
                not is_uint(climate["seq"], 0xffffffff)
                or (climate["valid"] and climate["seq"] == 0)
            ))
            or (climate.get("age_ms") is not None and (
                not is_uint(climate["age_ms"], 0xffffffff)
                or (climate["valid"] and climate["age_ms"] >= 1000)
            ))):
        raise ValueError("Invalid SHT41 climate sample")

    if (not is_uint(power.get("cell_mv"), 4500)
            or not is_uint(power.get("soc_centi"), 10000)
            or not is_uint(power.get("bus_mv"), 40959)
            or not is_int_in_range(power.get("shunt_uv"), -81920, 81920)
            or not _bool(power.get("fuel_valid"))
            or not _bool(power.get("monitor_valid"))
            or power.get("current_calibrated") is not False):
        raise ValueError("Invalid uncalibrated battery or shunt source")
    if power["fuel_valid"] and not is_valid_fuel_measurement(
        power["cell_mv"], power["soc_centi"],
    ):
        raise ValueError("Invalid MAX17048 battery measurement")
    # TI INA226 raw rails 0x7fff and 0x8000 are rejected by the WROOM
    # before conversion. The nonrail codes -32767..32766 truncate toward
    # zero to -81917..81915 uV (the signed bounds are asymmetric).
    if power["monitor_valid"] and not -81917 <= power["shunt_uv"] <= 81915:
        raise ValueError("Invalid INA226 saturated shunt source")
    ina226_monitor_warning(power)
    # Missing sequence is accepted for old read-only firmware, but cannot
    # trigger proactive low-battery speech on the Mac.
    fuel_seq = power.get("fuel_seq")
    if fuel_seq is not None and (
        not is_uint(fuel_seq, 0xffffffff)
        or (power["fuel_valid"] and fuel_seq == 0)
    ):
        raise ValueError("Invalid MAX17048 fuel acquisition provenance")
    # Old read-only firmware may omit acquisition age, but then the
    # model must not infer a new battery observation from a cached number.
    fuel_age = power.get("fuel_age_ms")
    if ("fuel_age_ms" in power and (
        not is_uint(fuel_age, 0xffffffff)
        or (power["fuel_valid"] and not fuel_sample_is_fresh(fuel_age))
    )):
        raise ValueError("Invalid MAX17048 fuel acquisition age")
    # Optional until an inspected 5mOhm Kelvin sensor and matching WROOM
    # firmware actually exist. Raw calculated milliamp telemetry is not a
    # calibrated battery ammeter or charging authorization.
    current_fields = ("pack_ma", "pack_valid", "pack_seq")
    pack_age = power.get("pack_age_ms")
    if ("pack_age_ms" in power and not is_uint(pack_age, 0xffffffff)):
        raise ValueError("Invalid INA226 pack conversion age")
    if any(key in power for key in current_fields):
        if (not all(key in power for key in current_fields)
                or not is_int_in_range(power["pack_ma"], -16384, 16384)
                or not _bool(power["pack_valid"])
                or not is_uint(power["pack_seq"], 0xffffffff)
                or (power["pack_valid"] and (
                    not power["monitor_valid"] or power["pack_seq"] == 0
                    or (pack_age is not None and pack_age >= 500)
                    or not -81920 < power["shunt_uv"] < 81920
                    or power["pack_ma"] != int(power["shunt_uv"] / 5)))
                or (not power["pack_valid"] and power["pack_ma"] != 0)):
            raise ValueError("Invalid INA226 pack-line current provenance")

    if (not is_uint(proximity.get("raw"), 255)
            or not _bool(proximity.get("valid"))
            or ("saturated" in proximity and not _bool(proximity["saturated"]))
            or not is_uint(proximity.get("gesture"), 4)
            or not is_uint(proximity.get("gesture_events"), 0xffffffff)
            or ("boot_id" in proximity and not is_uint(proximity["boot_id"], 0xffffffff))
            or proximity.get("physically_qualified") is not False):
        raise ValueError("Invalid APDS9960 source")
    # A single WROOM response serializes both sensor groups under the same
    # boot epoch. Legacy bench captures can omit IDs, but any explicit ID
    # must be nonzero and two explicit IDs must agree. Otherwise an
    # out-of-order reply can rebase all optional counters on the wrong boot.
    force_boot = force.get("boot_id")
    proximity_boot = proximity.get("boot_id")
    if (force_boot == 0 or proximity_boot == 0
            or (force_boot is not None and proximity_boot is not None
                and force_boot != proximity_boot)):
        raise ValueError("Inconsistent WROOM auxiliary boot provenance")

    bmp = data.get("bmp280")
    if bmp is not None:
        if (not isinstance(bmp, dict)
                or not _bool(bmp.get("present"))
                or not _bool(bmp.get("valid"))
                or not is_uint(bmp.get("chip_id"), 255)
                or not is_int_in_range(bmp.get("temp_centi"), -4000, 8500)
                or not is_uint(bmp.get("pressure_pa"), 120000)
                or bmp.get("physically_verified") is not False
                or (bmp.get("seq") is not None and (
                    not is_uint(bmp["seq"], 0xffffffff)
                    or (bmp["valid"] and bmp["seq"] == 0)
                ))
                or (bmp.get("age_ms") is not None and (
                    not is_uint(bmp["age_ms"], 0xffffffff)
                    or (bmp["valid"] and bmp["age_ms"] >= 2000)
                ))
                or (bmp["valid"] and (not bmp["present"]
                    or bmp["chip_id"] != 0x58
                    or not 30000 <= bmp["pressure_pa"] <= 120000))
                or (not bmp["valid"] and (
                    bmp["pressure_pa"] != 0 or bmp["temp_centi"] != 0))):
            raise ValueError("Invalid optional BMP280 ambient sample")
    dock = data.get("dock")
    if dock is not None:
        if (not isinstance(dock, dict)
                or any(not _bool(dock.get(key)) for key in (
                    "present", "valid", "left_seated", "right_seated",
                    "input_good", "charge_indicated",
                ))
                or dock.get("charging_verified") is not False
                or not is_uint(dock.get("seq"), 0xffffffff)
                or not is_uint(dock.get("age_ms"), 0xffffffff)
                or (dock["valid"] and (
                    not dock["present"] or dock["seq"] == 0
                    or dock["age_ms"] >= 500))
                # Independent CHG-low / PGOOD-high is a real electrical
                # contradiction to report, not a malformed JSON frame.
                # The read-only dock classifier labels it a fault and no
                # physical or charging privilege can come from this telemetry.
                or (not dock["valid"] and any(dock[key] for key in (
                    "left_seated", "right_seated", "input_good",
                    "charge_indicated",
                )))):
            raise ValueError("Invalid optional read only dock pin status")
    nfc = data.get("nfc")
    if nfc is not None:
        if (not isinstance(nfc, dict) or type(nfc.get("v")) is not bool
                or not is_uint(nfc.get("t"), 0xffffffff)
                or not is_uint(nfc.get("e"), 0xffffffff)
                or not is_uint(nfc.get("s"), 0xffffffff)
                or (nfc["v"] and nfc["s"] == 0)
                or (nfc["t"] != 0 and not nfc["v"])):
            raise ValueError("Invalid read only PN532 toy tag evidence")
    # Stale or clipped optical FIFO samples cannot establish contact.
    # Match the WROOM 18-bit ADC rail rejection without invalidating other
    # sensors. Preserve raw diagnostics and do not mutate the caller's frame.
    if pulse["valid"] and (
        pulse["age_ms"] > 250 or pulse["red"] == 262143 or pulse["ir"] == 262143
    ):
        data = {**data, "pulse": {**pulse, "valid": False}}
    # Older firmware lacks the flag, so independently reject the raw rail.
    if proximity["raw"] == 255 or proximity.get("saturated") is True:
        data = {**data, "proximity": {**proximity, "valid": False, "saturated": True}}
    return data
