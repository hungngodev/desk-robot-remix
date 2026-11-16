"""Generate the five-robot order quantities and FAIL CLOSED on purchase readiness.

This checks documented evidence, not real electrical safety. A supplier URL, test
stub or green unit test is not a physical assembly receipt. The release signer
must independently inspect the original measurements before ordering.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/hardware/full-feature-plan.json"

# A vendor-specific reference is not necessarily a final production carrier.
SOURCE_REFERENCES = {
    "cliff_obstacle": ("Pololu", "3692", "https://www.pololu.com/product/3692"),
    "i2c_mux": ("SparkFun", "BOB-16784", "https://www.sparkfun.com/sparkfun-qwiic-mux-breakout-8-channel-tca9548a.html"),
    "mcp23017": ("Waveshare", "15391", "https://www.waveshare.com/mcp23017-io-expansion-board.htm"),
    "amp": ("SparkFun", "DEV-14809", "https://www.sparkfun.com/sparkfun-i2s-audio-breakout-max98357a.html"),
    "speaker": ("SparkFun", "COM-26553", "https://www.sparkfun.com/mini-speaker-1w-8-ohm.html"),
}

# Each gate must carry a real, operator-reviewed evidence receipt, not a bool.
SYSTEM_GATES = (
    "commercial_mechanical_license", "fitted_assembly_and_print",
    "loaded_drive_and_stopping", "four_cliff_sensor_surface_trials",
    "full_power_load_and_faults", "protected_1s_charger_and_dock_contacts",
    "real_dual_ir_terminal_docking", "lift_and_grip_calibration",
    "sense_speaker_mic_double_talk", "five_robot_integration",
    "source_builds_and_tests",
)
PART_GATES = (
    "exact_carrier_schematic", "measured_3v3_bus_and_pullups",
    "power_load_record", "firmware_and_source_reference",
    "mechanical_fit_receipt", "functional_or_fault_trial",
    "alternative_comparison",
)


def _count(v: object, name: str) -> int:
    if type(v) is not int or v < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return v


def _receipt(obj: object) -> bool:
    # Explicitly reject True, fake booleans, empty strings and unqualified labels.
    return (isinstance(obj, dict)
            and obj.get("result") == "pass"
            and isinstance(obj.get("evidence_url"), str)
            and obj["evidence_url"].startswith("https://")
            and isinstance(obj.get("tested_on"), str)
            and bool(obj["tested_on"].strip())
            and isinstance(obj.get("reviewer"), str)
            and bool(obj["reviewer"].strip()))


def generate(plan: dict, evidence: dict | None = None) -> dict:
    """Produce all design quantities, distinguish reported stock from proof."""
    if not isinstance(plan, dict):
        raise ValueError("Missing hardware plan")
    fleet = _count(plan.get("target_robots"), "target_robots")
    if fleet != 5:
        raise ValueError("This procurement is defined for exactly five robots")
    items = plan.get("parts")
    if not isinstance(items, list) or not items:
        raise ValueError("Missing part ledger")
    evidence = evidence if isinstance(evidence, dict) else {}
    approvals = evidence.get("parts", {})
    if not isinstance(approvals, dict):
        raise ValueError("Invalid parts evidence")
    rows = []
    seen = set()
    for part in items:
        if not isinstance(part, dict) or not isinstance(part.get("id"), str):
            raise ValueError("Part without stable ID")
        ident = part["id"]
        if ident in seen:
            raise ValueError(f"Duplicate part ID: {ident}")
        seen.add(ident)
        if part.get("group") != "pet":
            raise ValueError(f"Unexpected scope for {ident}")
        per = _count(part.get("per_robot"), f"{ident}.per_robot")
        owned = _count(part.get("reported_owned_total"), f"{ident}.reported_owned_total")
        needed = fleet * per
        # Reported ownership is not physical stock verification. An ordered
        # head is explicitly NOT counted as a delivered/accepted board.
        if owned > needed:
            raise ValueError(f"Reported stock exceeds total design slots: {ident}")
        ev = approvals.get(ident, {})
        if not isinstance(ev, dict):
            raise ValueError(f"Invalid part evidence: {ident}")
        missing = [name for name in PART_GATES if not _receipt(ev.get(name))]
        if not (isinstance(ev.get("vendor"), str) and ev["vendor"].strip()
                and isinstance(ev.get("sku"), str) and ev["sku"].strip()
                and isinstance(ev.get("pcb_revision"), str) and ev["pcb_revision"].strip()):
            missing.insert(0, "exact_vendor_sku_and_pcb_revision")
        vendor = SOURCE_REFERENCES.get(ident)
        rows.append({
            "id": ident, "name": part.get("name"), "per_robot": per,
            "fleet_total": needed, "reported_owned_not_verified": owned,
            "remaining_if_reported_stock_works": max(needed - owned, 0),
            "reference_only": ({"vendor": vendor[0], "sku": vendor[1],
                                "url": vendor[2]} if vendor else None),
            "approved_for_fleet_purchase": not missing,
            "missing_part_evidence": missing,
        })
    required = set(seen)
    if set(approvals) - required:
        raise ValueError("Evidence refers to nonexistent part IDs")
    system_evidence = evidence.get("system", {})
    if not isinstance(system_evidence, dict):
        raise ValueError("Invalid system evidence")
    missing_system = [g for g in SYSTEM_GATES if not _receipt(system_evidence.get(g))]
    if (plan.get("physical_trial_count", 0) == 0
            or plan.get("qualified_assumptions") is not True
            or plan.get("prices_complete") is not True):
        missing_system.append("plan_unqualified_or_price_incomplete")
    pod = plan.get("room_pod", {})
    if not isinstance(pod, dict) or not isinstance(pod.get("modules"), list):
        raise ValueError("Missing shared room station inventory")
    room = []
    for module in pod["modules"]:
        qty = _count(module.get("quantity_per_room"), "room module quantity")
        room.append({"name": module.get("name"), "shared_total": qty,
                     "physical_acceptance": "not_proven"})
    approved = not missing_system and all(row["approved_for_fleet_purchase"] for row in rows)
    return {"fleet_robots": fleet, "docks": fleet, "room_stations": 1,
            "order_released": approved, "order_release_is_not_an_electrical_guarantee": True,
            "known_one_head_ordered_unreceived": 1,
            "reported_mg90s_approximately_ten_not_counted_as_verified": True,
            "missing_system_evidence": missing_system, "robots": rows, "room_pod": room}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--evidence", type=Path,
                        help="Operator-recorded measured qualification JSON, if any")
    parser.add_argument("--require-release", action="store_true",
                        help="Exit 2 unless every part and system receipt has passed")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    evidence = (json.loads(args.evidence.read_text(encoding="utf-8"))
                if args.evidence else {})
    report = generate(plan, evidence)
    print(json.dumps(report, indent=2))
    return 2 if args.require_release and not report["order_released"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
