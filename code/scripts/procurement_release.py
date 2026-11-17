"""Generate the five-robot order quantities and FAIL CLOSED on purchase readiness.

This checks documented evidence, not real electrical safety. A supplier URL, test
stub or green unit test is not a physical assembly receipt. The release signer
must independently inspect the original measurements before ordering.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/hardware/full-feature-plan.json"

# A vendor-specific reference is not necessarily a final production carrier.
SOURCE_REFERENCES = {
    "cliff_obstacle": ("Generic", "GY-530 VL53L0X", "https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html"),
    "i2c_mux": ("Generic", "TCA9548A", "https://www.ti.com/product/TCA9548A"),
    "mcp23017": ("Generic", "MCP23017", "https://www.microchip.com/en-us/product/MCP23017"),
    "amp": ("Generic", "MAX98357A", "https://www.analog.com/en/products/max98357a.html"),
    "speaker": ("SparkFun", "COM-26553", "https://www.sparkfun.com/mini-speaker-1w-8-ohm.html"),
}

# Each gate must carry a real, operator-reviewed evidence receipt, not a bool.
SYSTEM_GATES = (
    "commercial_mechanical_license", "fitted_assembly_and_print",
    "loaded_drive_and_stopping", "four_cliff_sensor_surface_trials",
    "full_power_load_and_faults", "protected_1s_charger_and_dock_contacts",
    "real_dual_ir_terminal_docking", "lift_and_grip_calibration",
    "sense_speaker_mic_double_talk", "five_robot_integration",
    "room_pod_usb_serial_and_five_pet_observers",
    # Both are requested physical features, not merely reserved BOM slots.
    # Existing optional RGB/haptic source and disabled room soil firmware
    # must not quietly count as a finished five-pet purchase.
    "rgb_and_haptic_real_device_effects_and_power",
    "room_soil_probe_enabled_and_calibrated",
    "source_builds_and_tests",
    "battery_pack_ntc_to_charger_ts_thermal_fault_trial",
    "battery_pack_actual_length_and_enclosure_clearance",
    "amplifier_speaker_power_limit_and_thermal_trial",
    "dock_contacts_recess_reverse_polarity_and_current_limit",
    "fuel_gauge_single_owner_and_telemetry_contract",
    "user_approved_costed_exact_carrier_bill_of_materials",
    "source_first_upstream_reuse_and_license_audit",
)
PART_GATES = (
    "exact_carrier_schematic", "measured_3v3_bus_and_pullups",
    "power_load_record", "firmware_and_source_reference",
    "mechanical_fit_receipt", "functional_or_fault_trial",
    "alternative_comparison",
    "verified_landed_unit_price",
    "received_quantity_revision_and_owned_stock_inspection",
)


# Frozen minimum scope for the user-selected full feature build. A plan edit
# cannot silently remove a robot feature or reduce its quantity and then
# release an otherwise fully signed purchasing ledger. Revising these minima
# is a separate reviewed architecture decision, not a cart optimization.
REQUIRED_PET_PER_ROBOT = {
    "xiao_sense": 1,
    "wroom": 1,
    "oled": 1,
    "stepper": 2,
    "uln2003": 2,
    "mg90s": 2,
    "imu": 1,
    "head_touch": 1,
    "max30102": 1,
    "cliff_obstacle": 8,
    "i2c_mux": 2,
    "amp": 1,
    "speaker": 1,
    "cap1188": 1,
    "touch_electrodes": 1,
    "apds9960": 1,
    "fsr": 2,
    "ads1115": 1,
    "rgb": 1,
    "logic_level": 1,
    "as5600": 3,
    "encoder_magnets": 3,
    "ina226": 1,
    "max17048": 1,
    "cap_power": 1,
    "sensor_3v3": 1,
    "switch_power": 1,
    "bumper": 2,
    "reed": 1,
    "pir": 1,
    "bmp280": 1,
    "sht41": 1,
    "pn532": 1,
    "mcp23017": 1,
    "haptic_motor": 1,
    "haptic_driver": 1,
    "dock_ir_receivers": 2,
    "dock_ir_beacon_controller": 1,
    "dock_ir_emitter_channels": 2,
    "dock_contacts": 1,
    "dock_fixture": 1,
    "assembly": 1,
}
REQUIRED_ROOM_PER_STATION = {
    "scd40": 1,
    "bme688": 1,
    "ld2410c": 1,
    "soil_probe": 1,
    "nfc_game_props": 10,
    "amg8833": 1,
    "room_controller": 1,
}

# Fourteen linked assembly parts or alternatives from the detailed purchasing
# register. The main 49 roles do not authorize an unreviewed charger, motor,
# dock contact driver, pack or station subpart. These are NOT 14 more automatic
# purchases; each needs a human reviewed selection, reuse or rejection receipt.
SUPPLEMENTAL_DECISIONS = {
    "n20_motor_candidate": ("stepper", 10),
    "drv8833_driver_candidate": ("uln2003", 5),
    "bq24075_charger_candidate": ("cap_power", 5),
    "boost_5v_candidate": ("cap_power", 5),
    "protected_ntc_pack": ("cap_power", 5),
    "dock_5v_adapter": ("dock_fixture", 5),
    "dock_ir_transistor_channels": ("dock_ir_emitter_channels", 10),
    "shared_room_controller": ("room_controller", 1),
    "room_scd40": ("scd40", 1),
    "room_bme688": ("bme688", 1),
    "room_ld2410c": ("ld2410c", 1),
    "room_amg8833": ("amg8833", 1),
    "room_soil_probe": ("soil_probe", 1),
    "room_nfc_game_tokens": ("nfc_game_props", 10),
}



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


def _ad_fruit_new_hardware(vendor: object, quantity: int) -> bool:
    """Do not purchase Adafruit branded boards; already-owned Feather is exempt."""
    return quantity > 0 and isinstance(vendor, str) and (
        "adafruit" in vendor.casefold()
    )


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
        # The user explicitly selected inexpensive VL53L0X for desk ranging.
        # Reject premium substitutions before an agent can generate a cart.
        if ident == "cliff_obstacle" and "VL53L0X" not in str(part.get("name", "")):
            raise ValueError("Cliff sensor must be the approved low-cost VL53L0X")
        if ident in seen:
            raise ValueError(f"Duplicate part ID: {ident}")
        seen.add(ident)
        if part.get("group") != "pet":
            raise ValueError(f"Unexpected scope for {ident}")
        per = _count(part.get("per_robot"), f"{ident}.per_robot")
        owned = _count(part.get("reported_owned_total"), f"{ident}.reported_owned_total")
        estimated = _count(part.get("estimated_owned_total", 0), f"{ident}.estimated_owned_total")
        ordered = _count(part.get("ordered_unreceived_total", 0), f"{ident}.ordered_unreceived_total")
        needed = fleet * per
        # Reported ownership is not physical stock verification. An ordered
        # head is explicitly NOT counted as a delivered/accepted board.
        if owned + estimated + ordered > needed:
            raise ValueError(f"Reported stock exceeds total design slots: {ident}")
        ev = approvals.get(ident, {})
        if not isinstance(ev, dict):
            raise ValueError(f"Invalid part evidence: {ident}")
        missing = [name for name in PART_GATES if not _receipt(ev.get(name))]
        if not (isinstance(ev.get("vendor"), str) and ev["vendor"].strip()
                and isinstance(ev.get("sku"), str) and ev["sku"].strip()
                and isinstance(ev.get("pcb_revision"), str) and ev["pcb_revision"].strip()):
            missing.insert(0, "exact_vendor_sku_and_pcb_revision")
        if _ad_fruit_new_hardware(ev.get("vendor"), max(needed - owned, 0)):
            missing.append("no_new_adafruit_hardware")
        vendor = SOURCE_REFERENCES.get(ident)
        rows.append({
            "id": ident, "name": part.get("name"), "per_robot": per,
            "fleet_total": needed, "reported_owned_not_verified": owned,
            "estimated_owned_not_verified": estimated,
            "ordered_unreceived_not_verified": ordered,
            "remaining_if_reported_stock_works": max(needed - owned - estimated - ordered, 0),
            "shopping_decision": part.get("shopping_decision", "hold_until_qualified"),
            "notes": part.get("notes", ""),
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
    # Reject fake boolean, negative, float or text trial counts. A truthy
    # value is not evidence that a physical prototype was actually tested.
    trials = plan.get("physical_trial_count", 0)
    if (type(trials) is not int or trials < 1
            or plan.get("qualified_assumptions") is not True
            or plan.get("prices_complete") is not True):
        missing_system.append("plan_unqualified_or_price_incomplete")
    pod = plan.get("room_pod", {})
    if not isinstance(pod, dict) or not isinstance(pod.get("modules"), list):
        raise ValueError("Missing shared room station inventory")
    # The shared station is part of the FULL product. Previously it was
    # always printed as "not_proven" yet was ignored by order_released.
    # That bug could approve a five-robot order with no qualified room pod.
    room_evidence = evidence.get("room_pod", {})
    if not isinstance(room_evidence, dict):
        raise ValueError("Invalid shared station evidence")
    room, room_ids = [], set()
    for module in pod["modules"]:
        ident = module.get("id") if isinstance(module, dict) else None
        if not isinstance(ident, str) or not ident or ident in room_ids:
            raise ValueError("Missing or duplicate shared station part ID")
        room_ids.add(ident)
        qty = _count(module.get("quantity_per_room"), ident + ".quantity_per_room")
        estimated = _count(module.get("estimated_owned_total", 0),
                           ident + ".estimated_owned_total")
        if estimated > qty:
            raise ValueError("Room station estimated stock exceeds design slots")
        ev = room_evidence.get(ident, {})
        if not isinstance(ev, dict):
            raise ValueError(f"Invalid shared station evidence: {ident}")
        missing = [name for name in PART_GATES if not _receipt(ev.get(name))]
        if not (isinstance(ev.get("vendor"), str) and ev["vendor"].strip()
                and isinstance(ev.get("sku"), str) and ev["sku"].strip()
                and isinstance(ev.get("pcb_revision"), str) and ev["pcb_revision"].strip()):
            missing.insert(0, "exact_vendor_sku_and_pcb_revision")
        if _ad_fruit_new_hardware(ev.get("vendor"), qty - estimated):
            missing.append("no_new_adafruit_hardware")
        room.append({"id": ident, "name": module.get("name"),
                     "shared_total": qty, "per_robot": 0,
                     "reported_owned_not_verified": 0,
                     "estimated_owned_not_verified": estimated,
                     "ordered_unreceived_not_verified": 0,
                     "remaining_if_reported_stock_works": qty - estimated,
                     "notes": module.get("location", ""),
                     "shopping_decision": "hold_until_qualified",
                     "reference_only": None,
                     "approved_for_fleet_purchase": not missing,
                     "missing_part_evidence": missing})
    if set(room_evidence) - room_ids:
        raise ValueError("Evidence refers to nonexistent shared station part IDs")
    selected_pet = {row["id"]: row["per_robot"] for row in rows}
    selected_room = {row["id"]: row["shared_total"] for row in room}
    reduced = [
        "pet:" + ident for ident, minimum in REQUIRED_PET_PER_ROBOT.items()
        if selected_pet.get(ident, -1) < minimum
    ] + [
        "room:" + ident for ident, minimum in REQUIRED_ROOM_PER_STATION.items()
        if selected_room.get(ident, -1) < minimum
    ]
    if reduced:
        missing_system.append("missing_or_reduced_full_feature_roles: " +
                              ", ".join(reduced))

    # The same fourteen details have their labels, parent identities and
    # quantities in the canonical hardware JSON. The code's independent
    # minimum contract protects against accidental deletion or reduction.
    linked = plan.get("linked_subassemblies", [])
    if not isinstance(linked, list):
        raise ValueError("Invalid linked subassembly plan")
    linked_plan = {}
    for detail in linked:
        if not isinstance(detail, dict) or not isinstance(detail.get("id"), str):
            raise ValueError("Malformed linked subassembly")
        ident = detail["id"]
        if ident in linked_plan:
            raise ValueError("Duplicate linked subassembly: " + ident)
        linked_plan[ident] = detail
    if set(linked_plan) - set(SUPPLEMENTAL_DECISIONS):
        raise ValueError("Unexpected linked subassembly ID")
    for ident, (parent, units) in SUPPLEMENTAL_DECISIONS.items():
        detail = linked_plan.get(ident, {})
        if (detail.get("parent_role") != parent
                or type(detail.get("fleet_quantity")) is not int
                or detail["fleet_quantity"] != units
                or not isinstance(detail.get("name"), str)
                or not detail["name"].strip()):
            missing_system.append("missing_or_reduced_linked_subassembly:" + ident)

    # The human-priced register also has fourteen linked physical subparts.
    # A fully approved 49-role abstract plan must not skip exact motor, cell,
    # boost, charge, dock and station sourcing decisions. An alternative may
    # be rejected, but its replacement and evidence must be recorded explicitly.
    decisions = evidence.get("supplemental_decisions", {})
    if not isinstance(decisions, dict):
        raise ValueError("Invalid supplemental purchasing decisions")
    unknown_decisions = set(decisions) - set(SUPPLEMENTAL_DECISIONS)
    if unknown_decisions:
        raise ValueError("Unknown supplemental purchasing decisions: " +
                         ", ".join(sorted(unknown_decisions)))
    approved_decisions = []
    for ident, (parent, units) in SUPPLEMENTAL_DECISIONS.items():
        declared = decisions.get(ident, {})
        valid = isinstance(declared, dict) and (
            declared.get("parent_role") == parent
            and type(declared.get("fleet_quantity")) is int
            and declared["fleet_quantity"] == units
            and declared.get("disposition") in (
                "selected", "reuse_existing", "included_in_parent",
                "rejected_in_favor_of_qualified_alternative")
            and isinstance(declared.get("resolved_item"), str)
            and bool(declared["resolved_item"].strip())
            and _receipt(declared.get("decision_receipt")))
        if valid and declared.get("disposition") in ("selected", "reuse_existing"):
            valid = (all(_receipt(declared.get(g)) for g in PART_GATES)
                     and all(isinstance(declared.get(k), str)
                             and declared[k].strip()
                             for k in ("vendor", "sku", "pcb_revision"))
                     and not _ad_fruit_new_hardware(
                         declared.get("vendor"),
                         units if declared.get("disposition") == "selected" else 0))
        if valid and declared.get("disposition") in (
                "included_in_parent", "rejected_in_favor_of_qualified_alternative"):
            # No automatic approval from simply writing 'not selected'.
            # The disposition receipt must link an independently reviewed
            # qualified parent/alternate and name the physical replacement.
            valid = (_receipt(declared.get("alternative_or_parent_receipt"))
                     and isinstance(declared.get("replacement_sku"), str)
                     and bool(declared["replacement_sku"].strip()))
        approved_decisions.append({"id": ident, "name": linked_plan.get(ident, {}).get("name", ident),
                                   "parent_role": parent, "fleet_quantity": units,
                                   "reviewed": valid,
                                   "disposition": declared.get("disposition")
                                   if isinstance(declared, dict) else None})
        if not valid:
            missing_system.append("unresolved_supplemental_part:" + ident)

    # The guarded DC backend needs N20-class motors AND a compatible
    # DRV8833 controller; the legacy stepper backend needs 28BYJ48 AND
    # ULN2003. Two individually reviewed candidate rows are not permission
    # to mix motor types and drivers, or to buy both architectures by default.
    dc_selected = {"selected", "reuse_existing"}
    motor_choice = decisions.get("n20_motor_candidate", {})
    driver_choice = decisions.get("drv8833_driver_candidate", {})
    motor_is_dc = (isinstance(motor_choice, dict)
                   and motor_choice.get("disposition") in dc_selected)
    driver_is_dc = (isinstance(driver_choice, dict)
                    and driver_choice.get("disposition") in dc_selected)
    if motor_is_dc != driver_is_dc:
        missing_system.append("motor_driver_variant_mismatch")

    # The SparkFun PRT-13777 Battery Babysitter already carries a BQ27441
    # fuel gauge. Refuse a second separate MAX17048 design by default;
    # both gauge ICs are legitimate but their telemetry paths are different.
    power = approvals.get("cap_power", {})
    if isinstance(power, dict):
        sku = str(power.get("sku", "")).replace("-", "").upper()
        # A generic carrier may include the same BQ27441/MAX17048 even if
        # it is not SparkFun PRT-13777. Inspect its schematic and declare
        # the gauge chip rather than relying on brand or SKU alone.
        gauge = str(power.get("integrated_fuel_gauge_ic", "")).strip().upper()
        if gauge and gauge not in ("NONE", "BQ27441", "MAX17048"):
            missing_system.append("unrecognized_integrated_fuel_gauge")
        if (sku == "PRT13777" or gauge in ("BQ27441", "MAX17048")) and any(
                x["id"] == "max17048" and x["per_robot"] for x in rows):
            missing_system.append("duplicate_bq27441_and_max17048_gauges")
    approved = (not missing_system
                and all(row["approved_for_fleet_purchase"] for row in rows)
                and all(row["approved_for_fleet_purchase"] for row in room))
    return {"fleet_robots": fleet, "docks": fleet, "room_stations": 1,
            "order_released": approved, "order_release_is_not_an_electrical_guarantee": True,
            "supplemental_decisions": approved_decisions,
            "known_one_head_ordered_unreceived": 1,
            "reported_mg90s_approximately_ten_not_counted_as_verified": True,
            "missing_system_evidence": missing_system, "robots": rows, "room_pod": room}



def _purchase_rows(report: dict):
    for row in report["robots"]:
        yield "pet or dock", row
    for row in report["room_pod"]:
        yield "shared station", row


def render_csv(report: dict) -> str:
    """Authoritative machine-readable 49-role view of the physical gated plan."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow((
        "scope", "part_id", "component", "per_robot", "fleet_total",
        "reported_owned_unverified", "estimated_owned_unverified",
        "ordered_unreceived", "remaining_if_all_reported_stock_works",
        "purchase_approved", "reference_vendor", "reference_sku",
        "reference_url", "shopping_decision", "notes",
    ))
    for scope, part in _purchase_rows(report):
        ref = part.get("reference_only") or {}
        writer.writerow((
            scope, part["id"], part["name"], part["per_robot"],
            part.get("fleet_total", part.get("shared_total", 0)),
            part["reported_owned_not_verified"],
            part["estimated_owned_not_verified"],
            part["ordered_unreceived_not_verified"],
            part["remaining_if_reported_stock_works"],
            "yes" if part["approved_for_fleet_purchase"] else "NO",
            ref.get("vendor", ""), ref.get("sku", ""), ref.get("url", ""),
            part["shopping_decision"], part["notes"],
        ))
    return output.getvalue()


def render_markdown(report: dict) -> str:
    """Only two shopping lists, with explicit counts and no implied purchase."""
    def cell(value: object) -> str:
        return str(value).replace("|", r"\|").replace("\n", " ").strip()

    output = [
        "> **CANONICAL FIVE PET BUYING REGISTER (2026-11-16):** [42 required pet/dock roles plus 14 separately orderable DC motor, power and shared station parts](2026-11-16-five-pet-purchase-register.md). This is the only current full-fleet purchasing candidate table. It incorporates exact seller links, one incoming XIAO, estimated already owned MG90S/MAX30102, selected guarded DC motor candidate and explicit first-pet qualification. This older checklist remains an engineering explanation, NOT an independently approved alternate cart. All power/contact/printing/loaded-drive hold conditions remain effective.",
        "",
        "# Five desk pets, five docks, and the shared room station",
        "",
        "Generated from docs/hardware/full-feature-plan.json by "
        "code/scripts/procurement_release.py. This file is a projection "
        "of the plan, never a second editable bill of materials.",
        "",
        "**FULL FLEET PURCHASE: " +
        ("APPROVED BY RECORDED EVIDENCE" if report["order_released"]
         else "HOLD. No complete electrical, mechanical or physical acceptance.") +
        "** Quantities are design slots, not certified supplier checkouts. "
        "Estimated owned counts and ordered units have not been inspected.",
        "",
        "## 1. Owned or ordered, as reported",
        "",
        "| Component | Reported on hand, unverified | Estimated on hand, unverified | Ordered, not received |",
        "| --- | ---: | ---: | ---: |",
    ]
    for _, part in _purchase_rows(report):
        owned = part["reported_owned_not_verified"]
        estimate = part["estimated_owned_not_verified"]
        ordered = part["ordered_unreceived_not_verified"]
        if owned or estimate or ordered:
            output.append(
                f"| {cell(part['name'])} | {owned} | {estimate} | {ordered} |"
            )
    output.extend((
        "",
        "Other reported spares are not interchangeable with chosen modules: "
        "BerryIMU, MAX9814, an extra camera, GY61, PAM8403, spare DRV8833 "
        "and assorted IR sensors. The owned Feather nRF52840 is only "
        "an estimated station controller until its actual firmware works.",
        "",
        "## 2. Remaining components or unqualified roles",
        "",
        "| Scope | Component | Fleet required | Conditional remaining | Status | Vendor reference or design blocker |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ))
    for scope, part in _purchase_rows(report):
        total = part.get("fleet_total", part.get("shared_total", 0))
        remaining = part["remaining_if_reported_stock_works"]
        status = "APPROVED" if part["approved_for_fleet_purchase"] else "HOLD"
        if part["shopping_decision"].startswith("hold_until_drivetrain"):
            status = "HOLD MOTOR CHOICE"
        reference = part.get("reference_only") or {}
        note = (f"{reference['vendor']} {reference['sku']}: {reference['url']}"
                if reference else part["notes"])
        output.append(
            f"| {cell(scope)} | {cell(part['name'])} | {total} | "
            f"{remaining} | {status} | {cell(note)} |"
        )
    # These fourteen are alternatives or parts already covered by a parent
    # role. Expose all of them in the SAME remaining-components list without
    # double counting either physical quantities or automatic purchases.
    for detail in report["supplemental_decisions"]:
        name = detail["name"]
        status = ("REVIEWED DECISION, CHECK DISPOSITION" if detail["reviewed"]
                  else "HOLD SUBASSEMBLY DECISION")
        output.append(
            f"| linked detail (not additive) | {cell(name)} | "
            f"{detail['fleet_quantity']} if selected | not independently counted | "
            f"{status} | Linked parent {detail['parent_role']}; "
            f"disposition {detail['disposition'] or 'unresolved'}; "
            "see the canonical 14-row source register before buying |"
        )
    output.extend((
        "",
        "A zero remaining quantity can mean a component is estimated owned "
        "or ordered, NOT physically counted, delivered or qualified. "
        "Recount the estimated ten MG90S and five MAX30102 and verify "
        "arrival of the one ordered XIAO Sense before buying duplicates.",
        "",
        "Existing 28BYJ48 and ULN2003 totals belong to the STEP motor "
        "variant. The new guarded DC firmware does not mean that N20 "
        "motors have been selected, fitted or load tested. Do not buy "
        "the missing steppers or new N20 motors before that decision.",
        "",
        "Protected single-cell charging, contact isolation, IR baffles, "
        "station USB readings, and commercially reusable fitted CAD "
        "remain unqualified. Do not energize any lithium charging circuit "
        "based on this design ledger.",
        "",
    ))
    return "\n".join(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--evidence", type=Path,
                        help="Operator-recorded measured qualification JSON, if any")
    parser.add_argument("--require-release", action="store_true",
                        help="Exit 2 unless every part and system receipt has passed")
    parser.add_argument("--format", choices=("json", "csv", "markdown"),
                        default="json", help="Render one verified quantity ledger")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    evidence = (json.loads(args.evidence.read_text(encoding="utf-8"))
                if args.evidence else {})
    report = generate(plan, evidence)
    if args.format == "csv":
        print(render_csv(report), end="")
    elif args.format == "markdown":
        print(render_markdown(report), end="")
    else:
        print(json.dumps(report, indent=2))
    return 2 if args.require_release and not report["order_released"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
