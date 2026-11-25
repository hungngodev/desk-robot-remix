"""Source-mapped two TCA9548A, sixteen-lane electrical preflight.

TI SCPS207H section 8.2.2 and NXP UM10204:
R(min)=(Vpullup-0.4V)/3mA; 30%-70% rise=0.8473*R*C.
At 400kHz Fast mode, rise is 20 to 300 ns (UM10204 Rev. 7 Table 11)
and segment capacitance <=400 pF.
The ONE selected downstream branch shares upstream sink and capacitance.
No component-vendor schematic, carrier voltage, pullup or wire is assumed.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/hardware/full-feature-plan.json"
TOF = ROOT / "code/firmware/body/lib/TofBus/TofBus.cpp"
SOURCE = "https://www.ti.com/lit/ds/symlink/tca9548a.pdf"
FAST_HZ = 400000
VCC = 3.3
# Literal endpoints avoid cancellation error at the inclusive voltage tolerance.
PULLUP_MIN_V = 3.25
PULLUP_MAX_V = 3.35
RISE_MIN_NS = 20.0
RISE_LIMIT_NS = 300.0
LOW_MAX_V = 0.4
SINK_MAX_MA = 3.0
MAX_CAP_PF = 400.0


def _num(value: object, label: str) -> float:
    if type(value) not in (float, int):
        raise ValueError(f"{label}: measured number required")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label}: numeric overflow") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label}: positive finite number required")
    return number


def topology(plan: dict | None = None) -> list[dict]:
    """Validate 16 populated mux lanes against THE CURRENT electrical plan."""
    if plan is None:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise ValueError("Missing source hardware plan")
    bus = plan.get("bus")
    if not isinstance(bus, dict):
        raise ValueError("Missing WROOM bus map")
    contract = plan.get("range_breakout_power_contract")
    if not isinstance(contract, dict):
        raise ValueError("Missing 3.3V sensor bus contract")
    for key in ("module_vin_v", "tca9548a_vcc_v",
                "upstream_pullup_target_v", "downstream_pullup_target_v"):
        if contract.get(key) != VCC:
            raise ValueError(f"Incorrect 3.3V sensor bus contract: {key}")
    upstream = bus.get("upstream")
    expected_upstream = {
        "MPU6050": {0x68, 0x69},
        "TCA9548A ranges": {0x70},
        "TCA9548A interactions": {0x71},
    }
    if (not isinstance(upstream, list) or len(upstream) != len(expected_upstream)
            or any(not isinstance(device, dict)
                   or not isinstance(device.get("device"), str)
                   or type(device.get("address")) is not int for device in upstream)
            or {device["device"] for device in upstream} != expected_upstream.keys()
            or any(device["address"] not in expected_upstream[device["device"]]
                   for device in upstream)):
        raise ValueError("Duplicate or changed upstream mux or MPU identity/address")
    addresses = {device["address"] for device in upstream}
    if "wire_.begin(sda, scl, 400000)" not in TOF.read_text(encoding="utf-8"):
        raise ValueError("Live firmware clock changed: recalibrate I2C timing model")

    results = []
    for key, address in (("mux_ranges", 0x70), ("mux_extras", 0x71)):
        mux = bus.get(key)
        if (not isinstance(mux, dict) or type(mux.get("address")) is not int
                or mux["address"] != address):
            raise ValueError(f"Incorrect mux address: {key}")
        lanes = mux.get("channels")
        if not isinstance(lanes, list) or len(lanes) != 8:
            raise ValueError(f"All eight lanes required: {key}")
        seen = set()
        for lane in lanes:
            if not isinstance(lane, dict):
                raise ValueError(f"Invalid mux lane: {key}")
            ch = lane.get("channel")
            if type(ch) is not int or not 0 <= ch <= 7 or ch in seen:
                raise ValueError(f"Duplicate, invalid or missing mux lane: {key}")
            seen.add(ch)
            devices = lane.get("devices")
            if (not isinstance(devices, list) or not devices
                    or any(not isinstance(device, dict)
                           or not isinstance(device.get("name"), str)
                           or not device["name"].strip() for device in devices)):
                raise ValueError("Each selected mux lane needs a real device")
            target_addresses = [d.get("address") for d in devices]
            if any(type(x) is not int or not 0x08 <= x <= 0x77 for x in target_addresses):
                raise ValueError("Invalid downstream I2C address")
            if len(set(target_addresses)) != len(target_addresses):
                raise ValueError("Address conflict WITHIN one live mux branch")
            if any(x in addresses for x in target_addresses):
                raise ValueError("Downstream device conflicts with upstream I2C target")
            if key == "mux_ranges" and (len(devices) != 1
                    or devices[0]["name"] != "VL53L0X" or target_addresses != [0x29]):
                raise ValueError("Range lane must contain one VL53L0X at 0x29")
            results.append({
                "branch": f"0x{address:02X}:{ch}",
                "devices": [{"name":d["name"], "address":d["address"]}
                            for d in devices],
                "required_v": VCC,
                "actual_carrier_electrical_qualified": False,
            })
        if seen != set(range(8)):
            raise ValueError("Mux lane continuity differs from source")
    return results


def screen_selected_segment(upstream: dict, selected: dict) -> dict:
    """Necessary RC model for one selected channel and upstream bus.

    Each line includes all installed physical pullups plus estimated total
    wire, pad and pin capacitance. Actual rise/low measurements are optional
    but cannot be fabricated; we never claim physical qualification.
    """
    report = {}
    for line in ("sda", "scl"):
        pullups = []
        total_pf = 0.0
        upstream_count = 0
        upstream_pf = 0.0
        measured_rises = []
        measured_lows = []
        for label, owner in (("upstream", upstream), ("selected", selected)):
            if not isinstance(owner, dict) or not isinstance(owner.get(line), dict):
                raise ValueError(f"Missing {label} {line} circuit")
            part = owner[line]
            power = _num(part.get("pullup_v"), f"{label}.{line}.pullup_v")
            # Design contract prohibits 5V generic carrier pullups on WROOM.
            if not PULLUP_MIN_V <= power <= PULLUP_MAX_V:
                raise ValueError(f"{label}.{line}: pullup not 3.3V")
            resistors = part.get("pullup_ohms")
            if not isinstance(resistors, list):
                raise ValueError(f"{label}.{line}: installed pullups must be listed")
            pullups.extend((_num(v, f"{label}.{line}.pullup_ohms"), power)
                           for v in resistors)
            total_pf += _num(part.get("cap_pf"), f"{label}.{line}.cap_pf")
            if label == "upstream":
                upstream_count = len(pullups)
                upstream_pf = total_pf
            if "measured_rise_ns" in part:
                measured_rises.append(_num(part["measured_rise_ns"],
                                           f"{label}.{line}.measured_rise_ns"))
            if "measured_low_v" in part:
                # A real low may be 0V; only reject bool/NaN/negative.
                v = part["measured_low_v"]
                if type(v) not in (float, int):
                    raise ValueError(f"{label}.{line}.measured_low_v invalid")
                try:
                    valid_low = math.isfinite(v) and v >= 0
                except OverflowError:
                    valid_low = False
                if not valid_low:
                    raise ValueError(f"{label}.{line}.measured_low_v invalid")
                measured_lows.append(float(v))
        if not pullups:
            raise ValueError(f"{line}: no verified pullup network")
        reciprocal_sum = sum(1.0 / r for r, _ in pullups)
        if not math.isfinite(reciprocal_sum) or reciprocal_sum <= 0:
            raise ValueError(f"{line}: pullup network cannot be evaluated safely")
        effective = 1.0 / reciprocal_sum
        rise_ns = 0.8473 * effective * total_pf / 1000
        # TI SLVA689A: each pullup contributes (Vpullup - VOL) / R.
        # Retain the nominal floor for measurements below the design target.
        sink_ma = sum((max(VCC, voltage) - LOW_MAX_V) / r
                      for r, voltage in pullups) * 1000
        if any(not math.isfinite(value) for value in
               (total_pf, effective, rise_ns, sink_ma)):
            raise ValueError(f"{line}: RC calculation overflowed")
        # Mux power-on/reset deselects every channel; the direct MPU and mux
        # control transactions must work without any downstream pullups.
        upstream_conductance = sum(1.0 / r for r, _ in pullups[:upstream_count])
        upstream_rise_ns = (0.8473 * upstream_pf / 1000 / upstream_conductance
                            if upstream_conductance > 0 else None)
        if upstream_rise_ns is not None and not math.isfinite(upstream_rise_ns):
            upstream_rise_ns = None
        upstream_ok = (upstream_rise_ns is not None
                       and RISE_MIN_NS <= upstream_rise_ns <= RISE_LIMIT_NS)
        downstream_present = len(pullups) > upstream_count
        model_ok = (upstream_ok and downstream_present
                    and total_pf <= MAX_CAP_PF
                    and RISE_MIN_NS <= rise_ns <= RISE_LIMIT_NS
                    and sink_ma <= SINK_MAX_MA
                    and all(RISE_MIN_NS <= v <= RISE_LIMIT_NS for v in measured_rises)
                    and all(v <= LOW_MAX_V for v in measured_lows))
        report[line] = {
            "installed_pullups": len(pullups),
            "upstream_only_estimated_rise_ns": (
                round(upstream_rise_ns, 3) if upstream_rise_ns is not None else None),
            "upstream_only_paper_pass": upstream_ok,
            "downstream_pullups_present": downstream_present,
            "combined_ohms": round(effective, 3),
            "combined_cap_pf": round(total_pf, 3),
            "estimated_rise_ns": round(rise_ns, 3),
            "estimated_sink_ma": round(sink_ma, 3),
            "paper_electrical_pass": model_ok,
            "actual_trace_and_carrier_verified": False,
        }
    return {
        "fast_mode_hz": FAST_HZ,
        "manufacturer_limits": {"rise_min_ns": RISE_MIN_NS,
                                "rise_ns": RISE_LIMIT_NS,
                                "sink_ma": SINK_MAX_MA,
                                "cap_pf": MAX_CAP_PF},
        "lines": report,
        "selected_branch_paper_pass": all(x["paper_electrical_pass"]
                                          for x in report.values()),
        "qualified_hardware": False,
    }


def audit(evidence: dict | None = None, plan: dict | None = None) -> dict:
    lanes = topology(plan)
    if evidence is None:
        evidence = {}
    if not isinstance(evidence, dict):
        raise ValueError("Evidence must map physical circuits")
    fields = ("upstream", "branches")
    if evidence and any(f not in evidence for f in fields):
        raise ValueError("Both upstream and selected branch evidence required")
    upstream = evidence.get("upstream")
    if evidence and not isinstance(upstream, dict):
        raise ValueError("Upstream evidence must be a dictionary")
    segments = evidence.get("branches", {})
    if not isinstance(segments, dict):
        raise ValueError("Branch evidence must be a dictionary")
    if any(k not in {lane["branch"] for lane in lanes} for k in segments):
        raise ValueError("Unknown source mux lane in evidence")
    reported = []
    for lane in lanes:
        key = lane["branch"]
        result = dict(lane)
        result["source"] = SOURCE
        if upstream is None or key not in segments:
            result["status"] = "HOLD_MISSING_ELECTRICAL_VALUES"
            result["selected_branch_paper_pass"] = False
        else:
            result.update(screen_selected_segment(upstream, segments[key]))
            result["status"] = ("PAPER_ONLY_PASS" if
                                result["selected_branch_paper_pass"] else
                                "PAPER_ELECTRICAL_FAIL")
        reported.append(result)
    return {
        "device_source_lanes": len(reported),
        "all_16_lanes_evaluated": len(reported) == 16,
        "all_16_lanes_paper_pass": all(x["selected_branch_paper_pass"]
                                       for x in reported),
        "all_16_lanes_physically_qualified": False,
        "entire_five_robot_order_electrically_approved": False,
        "lanes": reported,
    }


def strict_electrical_evidence_object(pairs: list[tuple[str, object]]) -> dict:
    """Reject overwritten measurements at every JSON nesting level."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate I2C electrical evidence key: " + key)
        result[key] = value
    return result


def reject_nonfinite_electrical_constant(token: str) -> None:
    raise ValueError("Nonfinite I2C electrical evidence constant: " + token)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path,
                        help="Measured per branch board and wire RC evidence JSON")
    args = parser.parse_args()
    values = (json.loads(
        args.evidence.read_text(encoding="utf-8"),
        object_pairs_hook=strict_electrical_evidence_object,
        parse_constant=reject_nonfinite_electrical_constant,
    ) if args.evidence else {})
    if not isinstance(values, dict):
        raise ValueError("Evidence must map physical circuits")
    print(json.dumps(audit(values), indent=2))


if __name__ == "__main__":
    main()
