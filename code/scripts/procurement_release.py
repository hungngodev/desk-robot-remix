"""Generate the five-robot order quantities and FAIL CLOSED on purchase readiness.

This checks documented evidence, not real electrical safety. A supplier URL, test
stub or green unit test is not a physical assembly receipt. The release signer
must independently inspect the original measurements before ordering.
"""
from __future__ import annotations

import argparse
import copy
import csv
import io
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from landed_cost import account_landed_cost

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/hardware/full-feature-plan.json"

# A vendor-specific reference is not necessarily a final production carrier.
SOURCE_REFERENCES = {
    "cliff_obstacle": ("ElectroPeak", "SEN-19-006", "https://electropeak.com/gy-530-vl53l0x-laser-range-finder"),
    "i2c_mux": ("Generic", "TCA9548A", "https://www.ti.com/product/TCA9548A"),
    "mcp23017": ("Generic", "MCP23017", "https://www.microchip.com/en-us/product/MCP23017"),
    "amp": ("Generic", "MAX98357A", "https://www.analog.com/en/products/max98357a.html"),
    "speaker": ("Challenge Electronics", "CS20-02P110-04-1X", "https://www.digikey.com/en/products/detail/challenge-electronics/CS20-02P110-04-1X/30407069"),
}

# Never accept merely chip-compatible replacements for these exact carrier
# choices in a fully signed cart. A substitution needs a reviewed BOM edit.
FIXED_SOURCE_SKUS = {
    "cliff_obstacle": ("ElectroPeak", "SEN-19-006"),
    "speaker": ("Challenge Electronics", "CS20-02P110-04-1X"),
}

# Each gate must carry a real, operator-reviewed evidence receipt, not a bool.
SYSTEM_GATES = (
    "commercial_mechanical_license", "fitted_assembly_and_print",
    "loaded_drive_and_stopping",
    "hardware_motor_driver_fails_low_after_cpu_stall",
    "four_cliff_sensor_surface_trials",
    "cliff_sensor_mount_height_and_stopping_geometry",
    # Forward-only geometry cannot protect the side sweep on a pivot.
    "four_floor_sensor_reverse_pivot_arc_sweep",
    # TI TCA9548A fast-mode RC is a COMBINED upstream+selected branch
    # electrical problem, not something each breakout can approve alone.
    "sixteen_mux_channel_400khz_pullups_rise_and_sink_trials",
    "full_power_load_and_faults",
    "xiao_usb_backfeed_diode_and_servo_brownout_trial",
    "protected_1s_charger_and_dock_contacts",
    "signed_pack_current_three_new_samples_and_chg_mismatch_trial",
    "charger_out_full_voltage_range_to_fixed_5v_rail_physical_trial",
    "real_dual_ir_terminal_docking", "lift_and_grip_calibration",
    "sense_speaker_mic_double_talk", "five_robot_integration",
    "room_pod_usb_serial_and_five_pet_observers",
    # Both are requested physical features, not merely reserved BOM slots.
    # Existing optional RGB/haptic source and disabled room soil firmware
    # must not quietly count as a finished five-pet purchase.
    "rgb_and_haptic_real_device_effects_and_power",
    # The MCP23017 can hold GPIOB2 high across an I2C stall. A documented
    # one-shot circuit is NOT proof until the real motor is seen to shut off.
    "haptic_hc123_one_shot_stuck_i2c_and_motor_thermal_trial",
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
# Qualify one complete first robot BEFORE the other four exist. Only these
# two gates specifically need the later five-robot acoustic/observer fleet.
# Every electrical, physical, source, cost and part gate still applies to
# the first robot, and the full fleet retains the unchanged SYSTEM_GATES.
FLEET_ONLY_SYSTEM_GATES = frozenset({
    "five_robot_integration",
    "room_pod_usb_serial_and_five_pet_observers",
})
FIRST_ROBOT_ROOM_GATE = "room_pod_usb_serial_and_first_pet_observer"
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
    "room_controller": 1,
}
CONDITIONAL_ROOM_PER_STATION = {
    # Visible current options, not default first-unit or fleet purchases.
    "amg8833": 1,
    "nfc_game_props": 10,
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



def _evidence_https_url(value: str) -> bool:
    """Reject scheme-only, credential-bearing and malformed evidence URLs."""
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and not any(ch.isspace() for ch in value)
                and parsed.port != 0)
    except ValueError:
        return False

def _receipt(obj: object) -> bool:
    # Explicitly reject True, fake booleans, empty strings and unqualified labels.
    return (isinstance(obj, dict)
            and obj.get("result") == "pass"
            and isinstance(obj.get("evidence_url"), str)
            and _evidence_https_url(obj["evidence_url"])
            and isinstance(obj.get("tested_on"), str)
            and bool(obj["tested_on"].strip())
            and isinstance(obj.get("reviewer"), str)
            and bool(obj["reviewer"].strip()))


def _selected_carrier(part_evidence: object) -> dict | None:
    """Preserve the exact reviewed carrier identity in builder projections."""
    if not isinstance(part_evidence, dict):
        return None
    fields = {}
    for key in ("vendor", "sku", "pcb_revision"):
        value = part_evidence.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        fields[key] = value.strip()
    product_url = part_evidence.get("product_url")
    if isinstance(product_url, str) and _evidence_https_url(product_url):
        fields["product_url"] = product_url
    return fields


def _ad_fruit_new_hardware(part_evidence: object, quantity: int) -> bool:
    """Reject branded NEW boards, even when a reseller is named as vendor.

    Brand, seller, product/SKU and reviewed physical item must agree. An
    already-owned board is not a new purchase; open-source Adafruit drivers
    remain allowed without purchasing Adafruit-branded carriers.
    """
    if quantity <= 0 or not isinstance(part_evidence, dict):
        return False
    return any(
        isinstance(part_evidence.get(field), str)
        and "adafruit" in part_evidence[field].casefold()
        for field in ("vendor", "brand", "sku", "product_name",
                      "product_url", "resolved_item", "pcb_revision")
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
        selected_carrier = _selected_carrier(ev)
        if selected_carrier is None:
            missing.insert(0, "exact_vendor_sku_and_pcb_revision")
        if _ad_fruit_new_hardware(ev, max(needed - owned, 0)):
            missing.append("no_new_adafruit_hardware")
        chosen = FIXED_SOURCE_SKUS.get(ident)
        if chosen is not None and (
                ev.get("vendor"), ev.get("sku")) != chosen:
            missing.append("exact_frozen_vendor_and_sku_mismatch")
        vendor = SOURCE_REFERENCES.get(ident)
        rows.append({
            "id": ident, "name": part.get("name"), "per_robot": per,
            "fleet_total": needed, "reported_owned_not_verified": owned,
            "estimated_owned_not_verified": estimated,
            "ordered_unreceived_not_verified": ordered,
            "remaining_if_reported_stock_works": max(needed - owned - estimated - ordered, 0),
            "shopping_decision": part.get("shopping_decision", "hold_until_qualified"),
            "notes": part.get("notes", ""),
            "selected_carrier": selected_carrier,
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
    power = pod.get("power_reference")
    if not isinstance(power, dict):
        raise ValueError("Missing shared room station power reference")
    powered_roles = {
        "room_controller", "scd40", "bme688", "amg8833",
        "ld2410c", "soil_probe",
    }
    for role in powered_roles:
        entry = power.get(role)
        if not isinstance(entry, dict):
            raise ValueError("Missing room station power role: " + role)
        qualified_fields = [
            value for key, value in entry.items()
            if key.endswith("_qualified")
        ]
        if not qualified_fields or any(type(value) is not bool
                                       for value in qualified_fields):
            raise ValueError(
                "Room station power qualification flag missing: " + role
            )
    references = power.get("references")
    if (not isinstance(references, list) or not references
            or any(not isinstance(url, str) or not _evidence_https_url(url)
                   for url in references)):
        raise ValueError("Room station power references must be HTTPS sources")
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
        owned = _count(module.get("reported_owned_total", 0),
                       ident + ".reported_owned_total")
        estimated = _count(module.get("estimated_owned_total", 0),
                           ident + ".estimated_owned_total")
        ordered = _count(module.get("ordered_unreceived_total", 0),
                         ident + ".ordered_unreceived_total")
        if owned + estimated + ordered > qty:
            raise ValueError("Room station stock exceeds design slots")
        ev = room_evidence.get(ident, {})
        if not isinstance(ev, dict):
            raise ValueError(f"Invalid shared station evidence: {ident}")
        status = module.get("purchase_status", "required")
        if ident in CONDITIONAL_ROOM_PER_STATION:
            if status not in ("conditional_optional", "selected_optional"):
                raise ValueError(
                    "Conditional room role must declare current status: " + ident
                )
        elif status != "required":
            raise ValueError("Required room role cannot become optional: " + ident)
        optional_not_selected = (
            ident in CONDITIONAL_ROOM_PER_STATION
            and status == "conditional_optional"
        )
        missing = [name for name in PART_GATES if not _receipt(ev.get(name))]
        selected_carrier = _selected_carrier(ev)
        if selected_carrier is None:
            missing.insert(0, "exact_vendor_sku_and_pcb_revision")
        remaining = qty - owned - estimated - ordered
        if _ad_fruit_new_hardware(ev, remaining):
            missing.append("no_new_adafruit_hardware")
        room.append({"id": ident, "name": module.get("name"),
                     "shared_total": qty, "per_robot": 0,
                     "reported_owned_not_verified": owned,
                     "estimated_owned_not_verified": estimated,
                     "ordered_unreceived_not_verified": ordered,
                     "remaining_if_reported_stock_works":
                         0 if optional_not_selected else remaining,
                     "notes": module.get("location", ""),
                     "shopping_decision": (
                         "conditional_optional_not_selected"
                         if optional_not_selected else "hold_until_qualified"
                     ),
                     "selected_carrier": selected_carrier,
                     "power_reference": copy.deepcopy(power.get(ident)),
                     "reference_only": None,
                     "excluded_from_order_as_optional": optional_not_selected,
                     "effective_selected_fleet_total":
                         0 if optional_not_selected else qty,
                     "approved_for_fleet_purchase":
                         False if optional_not_selected else not missing,
                     "missing_part_evidence": missing})
    if set(room_evidence) - room_ids:
        raise ValueError("Evidence refers to nonexistent shared station part IDs")
    # A role ID and quantity are not proof that its actual controller remains
    # the already integrated hardware. Older research proposals swap the
    # XIAO Sense and WROOM for generic S3CAM/C3 boards, which have different
    # camera buses, GPIO budgets, safety ownership and wiring. That would
    # invalidate firmware/print acceptance even when all abstract role IDs
    # and inventory totals still appear unchanged. An architecture change
    # requires a separately reviewed plan and code revision, never a silent
    # purchase approval from this frozen five-pet source.
    named = {row["id"]: row.get("name") for row in rows}
    architecture = plan.get("architecture")
    # Require the exact frozen identities, not a substring an incompatible
    # candidate can append to pass. Free-form "XIAO ... + generic C3" labels
    # and unreviewed hybrid pinout proposals do not qualify a sourced board.
    canonical_owners = (
        architecture == (
            "Mac owner for fleet/memory/AI; XIAO ESP32S3 Sense for camera, "
            "microphone, display, speaker and facial response; WROOM32 local "
            "actuator/safety controller; two isolated I2C multiplexers and "
            "reusable plug-in sensor harness."
        )
        and named.get("xiao_sense") == "XIAO ESP32S3 Sense camera + microphone"
        and named.get("wroom") == "ESP32 WROOM32 development board"
    )
    if not canonical_owners:
        missing_system.append("unqualified_xiao_sense_wroom_architecture_substitution")
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
    conditional_drift = [
        "room:" + ident
        for ident, minimum in CONDITIONAL_ROOM_PER_STATION.items()
        if selected_room.get(ident, -1) < minimum
    ]
    if conditional_drift:
        missing_system.append(
            "missing_or_reduced_conditional_room_roles: "
            + ", ".join(conditional_drift)
        )
    # Checking only the shopping row's model name is insufficient: a parallel
    # agent could silently put premium VL53L4CD lanes into the wiring plan.
    # Every actual 0x70 lane must remain the chosen inexpensive VL53L0X at
    # 7-bit 0x29 before a five-pet purchasing release is possible.
    ranges = plan.get("bus", {}).get("mux_ranges", {}) if isinstance(
        plan.get("bus", {}), dict) else {}
    lanes = ranges.get("channels", []) if isinstance(ranges, dict) else []
    cheap_range_layout = (
        isinstance(ranges, dict)
        and type(ranges.get("address")) is int
        and ranges["address"] == 0x70
        and isinstance(lanes, list)
        and len(lanes) == 8
        and all(isinstance(lane, dict)
                and type(lane.get("channel")) is int
                and lane["channel"] == index
                and isinstance(lane.get("devices"), list)
                and len(lane["devices"]) == 1
                and isinstance(lane["devices"][0], dict)
                and lane["devices"][0].get("name") == "VL53L0X"
                and type(lane["devices"][0].get("address")) is int
                and lane["devices"][0]["address"] == 0x29
                for index, lane in enumerate(lanes)))
    if not cheap_range_layout:
        missing_system.append("invalid_selected_cheap_range_mux_layout")
    # The chip's SDA/SCL absolute maximum is 3.6V. Common GY-530 modules
    # level-shift to VIN, so using a nominal 5V VIN can kill the ESP32 pin.
    # This is a selected wiring topology only, never actual PCB acceptance.
    tof_voltage = plan.get("range_breakout_power_contract")
    voltage_suitable = (
        isinstance(tof_voltage, dict)
        and all(
            type(tof_voltage.get(key)) in (int, float)
            and tof_voltage[key] == 3.3
            for key in ("module_vin_v", "tca9548a_vcc_v",
                        "upstream_pullup_target_v",
                        "downstream_pullup_target_v")
        )
        and tof_voltage.get("selected_chip") == "VL53L0X"
        and tof_voltage.get("generic_module_family") == "GY-530"
        and type(tof_voltage.get("mux_address_7bit")) is int
        and tof_voltage["mux_address_7bit"] == 0x70
        and type(tof_voltage.get("modules_per_robot")) is int
        and tof_voltage["modules_per_robot"] == 8
    )
    if not voltage_suitable:
        missing_system.append("unsafe_gy530_voltage_or_pin_contract")
    # The old round 1W speaker was replaced by a SINGLE currently fixed
    # rectangular 2W candidate, not an alternative additive purchase. Keep
    # the selected source model and the 5V MAX98357A rail in agreement with
    # the generated harness and printable fit plate. Even a passing source
    # contract must still be accompanied by independent physical receipts.
    speaker_selected = next((row for row in rows if row["id"] == "speaker"), None)
    audio = plan.get("audio_output_power_contract")
    audio_suitable = (
        isinstance(speaker_selected, dict)
        and isinstance(speaker_selected.get("name"), str)
        and "CS20-02P110-04-1X" in speaker_selected["name"]
        and "2 watt" in speaker_selected["name"]
        and isinstance(audio, dict)
        and audio.get("amplifier_ic") == "MAX98357A"
        and type(audio.get("amplifier_vdd_v")) in (int, float)
        and audio["amplifier_vdd_v"] == 5.0
        and type(audio.get("speaker_nominal_impedance_ohm")) is int
        and audio["speaker_nominal_impedance_ohm"] == 8
        and type(audio.get("speaker_nominal_rating_w")) in (int, float)
        and audio["speaker_nominal_rating_w"] == 2
        and isinstance(audio.get("physical_release"), str)
        and bool(audio["physical_release"].strip())
    )
    if not audio_suitable:
        missing_system.append("unresolved_current_two_watt_speaker_contract")




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
    optional_deferred_parents = {
        row["id"] for row in room
        if row.get("excluded_from_order_as_optional")
    }
    for ident, (parent, units) in SUPPLEMENTAL_DECISIONS.items():
        plan_detail = linked_plan.get(ident, {})
        if parent in optional_deferred_parents:
            current = plan_detail.get("disposition")
            conflict = ident in decisions
            valid = current == "deferred_optional" and not conflict
            approved_decisions.append({
                "id": ident,
                "name": plan_detail.get("name", ident),
                "parent_role": parent,
                "fleet_quantity": units,
                "reviewed": valid,
                "disposition": current,
            })
            if not valid:
                missing_system.append(
                    "conditional_optional_decision_conflict:" + ident
                )
            continue
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
                         declared,
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
    reviewed = {item["id"]: item["reviewed"] for item in approved_decisions}
    motor_pair_reviewed = (reviewed["n20_motor_candidate"]
                           and reviewed["drv8833_driver_candidate"])
    if motor_is_dc != driver_is_dc:
        missing_system.append("motor_driver_variant_mismatch")
    # An absence of DC evidence is NOT affirmative selection of a STEP motor.
    # Before both linked decisions have qualified receipts there is no
    # chosen physical drivetrain, even when the old 28BYJ48 rows remain in
    # the fixed 42-role accounting baseline. This is critical for the first
    # robot cart: do not recommend a second set of stepper motors by default.
    if not motor_pair_reviewed or motor_is_dc != driver_is_dc:
        physical_motor_variant = "unresolved"
    else:
        physical_motor_variant = "dc" if motor_is_dc else "stepper"
    # Keep the 42 frozen conceptual feature IDs so agents cannot delete
    # mobility to bypass requirements. They are NOT 42 additive purchase
    # lines: the two legacy stepper rows are mutually exclusive alternatives
    # to selected N20+DRV8833. Never require a purchased DC drivetrain AND
    # a purchased stepper drivetrain in the same robot.
    if physical_motor_variant == "dc":
        for row in rows:
            if row["id"] in ("stepper", "uln2003"):
                row["excluded_from_order_as_alternative"] = True
                row["effective_selected_fleet_total"] = 0
                row["remaining_if_reported_stock_works"] = 0
                row["shopping_decision"] = "do_not_buy_legacy_stepper_when_dc_selected"
                row["approved_for_fleet_purchase"] = True
                row["missing_part_evidence"] = []
            else:
                row["effective_selected_fleet_total"] = row["fleet_total"]
                row["excluded_from_order_as_alternative"] = False
    else:
        for row in rows:
            row["effective_selected_fleet_total"] = row["fleet_total"]
            row["excluded_from_order_as_alternative"] = False
    if physical_motor_variant == "unresolved":
        missing_system.append("motor_driver_variant_mismatch")
    if physical_motor_variant == "dc" and any(
            row["id"] in ("stepper", "uln2003") and
            row["remaining_if_reported_stock_works"] != 0
            for row in rows):
        missing_system.append("double_purchase_dc_and_stepper_drivetrains")

    # The SparkFun PRT-13777 Battery Babysitter integrates BQ27441.
    # A separate MAX17048 would duplicate the gauge. Inspect BOTH the
    # primary power assembly and the selected charger subpart: the fourteen
    # detailed purchasing rows must not bypass the core duplicate check.
    power = approvals.get("cap_power", {})
    charger_detail = decisions.get("bq24075_charger_candidate", {})
    gauge_candidates = [power]
    if (isinstance(charger_detail, dict)
            and charger_detail.get("disposition") in ("selected", "reuse_existing")):
        gauge_candidates.append(charger_detail)
    duplicate_gauge = False
    unknown_gauge = False
    for carrier in gauge_candidates:
        if not isinstance(carrier, dict):
            continue
        sku = "".join(c for c in str(carrier.get("sku", "")).upper()
                      if c.isalnum())
        gauge = str(carrier.get("integrated_fuel_gauge_ic", "")).strip().upper()
        if gauge and gauge not in ("NONE", "BQ27441", "MAX17048"):
            unknown_gauge = True
        if sku == "PRT13777" or gauge in ("BQ27441", "MAX17048"):
            duplicate_gauge = True
    if unknown_gauge:
        missing_system.append("unrecognized_integrated_fuel_gauge")
    if duplicate_gauge and any(x["id"] == "max17048" and x["per_robot"]
                               for x in rows):
        missing_system.append("duplicate_bq27441_and_max17048_gauges")
    # One fully assembled first unit must not require proof that five robots
    # already operate together. Do not skip ANY of the shared safety or
    # purchasing evidence: only explicitly fleet-scale trials are deferred.
    first_robot_missing_system = [
        gate for gate in missing_system
        if gate not in FLEET_ONLY_SYSTEM_GATES
    ]
    # A qualified five-robot observer trial is stronger evidence for the
    # single observer, but an independently tested first observer suffices
    # before the remaining four robots have been built.
    if not (_receipt(system_evidence.get(FIRST_ROBOT_ROOM_GATE)) or
            _receipt(system_evidence.get(
                "room_pod_usb_serial_and_five_pet_observers"))):
        first_robot_missing_system.append(FIRST_ROBOT_ROOM_GATE)
    approved = (
        not missing_system
        and all(row["approved_for_fleet_purchase"] for row in rows)
        and all(
            row["approved_for_fleet_purchase"]
            for row in room
            if not row.get("excluded_from_order_as_optional")
        )
    )
    return {"fleet_robots": fleet, "docks": fleet, "room_stations": 1,
            "physical_motor_variant_in_cart": physical_motor_variant,
            "order_released": approved, "order_release_is_not_an_electrical_guarantee": True,
            "supplemental_decisions": approved_decisions,
            "known_one_head_ordered_unreceived": 1,
            "reported_mg90s_approximately_ten_not_counted_as_verified": True,
            "missing_system_evidence": missing_system,
            "missing_first_robot_system_evidence": first_robot_missing_system,
            "robots": rows, "room_pod": room}




def public_purchase_view(report: dict, *, live_receipts_verified: bool = False) -> dict:
    """Never expose synthetic gate eligibility as a real checkout approval.

    The pure generator intentionally accepts test receipts. Only the strict
    source-pinned receipt audit permits an APPROVED public CLI view.
    """
    if live_receipts_verified:
        return report
    visible = copy.deepcopy(report)
    visible["order_released"] = False
    visible["missing_first_robot_system_evidence"] = [
        *visible["missing_first_robot_system_evidence"],
        "live_scoped_purchase_receipts_not_verified",
    ]
    for row in (*visible["robots"], *visible["room_pod"]):
        row["approved_for_fleet_purchase"] = False
    # A synthetic decision receipt may pass the pure generator without the
    # source-pinned live audit. Do not print it as a reviewed linked purchase
    # decision in Markdown, JSON, or the first-unit/pilot projections.
    for detail in visible.get("supplemental_decisions", []):
        detail["reviewed"] = False
    return visible


def first_robot_projection(report: dict) -> dict:
    """One COMPLETE robot, its dock and shared station, with independent gates.

    The five-pet ledger remains authoritative. All 49 parent roles plus the
    fourteen linked decisions remain visible, but five-pet spare stock must
    never be mistaken for proof that a prototype part is physically in hand.
    A blank motor decision cannot silently order legacy stepper hardware.
    """
    if report.get("fleet_robots") != 5 or report.get("room_stations") != 1:
        raise ValueError("First robot must project from the canonical five-pet plan")
    motor = report.get("physical_motor_variant_in_cart")
    if motor not in {"stepper", "dc", "unresolved"}:
        raise ValueError("Unknown physical drivetrain selection")
    pet_rows = report["robots"]
    station_rows = report["room_pod"]
    # First-unit source and physical qualification must be possible before
    # the other four units exist. The fleet still has additional cross-robot
    # trials, while all shared electrical, power, print, supplier and system
    # gates remain mandatory here. No real receipts means HOLD as before.
    station_ids = {row["id"] for row in station_rows}
    pet_ids = {row["id"] for row in pet_rows}
    missing_linked_parents = sorted({
        item["parent_role"] for item in report.get("supplemental_decisions", [])
        if item["parent_role"] not in pet_ids | station_ids
    })
    qualified_one = (
        not missing_linked_parents
        and motor in {"stepper", "dc"}
        and not report.get("missing_first_robot_system_evidence", ["missing"])
        and all(
            not item.get("missing_part_evidence", ["missing"])
            for item in [*pet_rows, *station_rows]
            if not item.get("excluded_from_order_as_optional")
        )
        and all(item.get("reviewed") is True
                for item in report.get("supplemental_decisions", []))
        and len(report.get("supplemental_decisions", [])) == 14
    )
    rows = []
    for scope, entries in (("pet or dock", pet_rows),
                           ("shared station", station_rows)):
        for part in entries:
            ident = part["id"]
            if scope == "pet or dock":
                target = _count(part["per_robot"], ident + ".per_robot")
                if part.get("excluded_from_order_as_alternative") or (
                        motor == "unresolved"
                        and ident in ("stepper", "uln2003")):
                    target = 0
            else:
                target = _count(part["shared_total"], ident + ".shared_total")
                if part.get("excluded_from_order_as_optional"):
                    target = 0
            # A five-robot ownership claim is only a MAXIMUM candidate stock
            # allocation to the first unit, not verified possession.
            available = target
            allocations = {}
            for key in ("reported_owned_not_verified",
                        "estimated_owned_not_verified",
                        "ordered_unreceived_not_verified"):
                value = min(available, _count(part[key], ident + "." + key))
                allocations[key] = value
                available -= value
            rows.append({
                "id": ident, "name": part["name"], "scope": scope,
                "prototype_target": target,
                # Full reported inventory remains visible even if no first
                # robot slot currently uses this variant. Do not erase the
                # user's five owned steppers just because DC is undecided.
                "fleet_reported_owned_not_verified": part[
                    "reported_owned_not_verified"],
                "fleet_estimated_owned_not_verified": part[
                    "estimated_owned_not_verified"],
                "fleet_ordered_unreceived_not_verified": part[
                    "ordered_unreceived_not_verified"],
                **allocations,
                "conditional_remaining": available,
                "reference_only": part.get("reference_only"),
                "selected_carrier": part.get("selected_carrier"),
                "power_reference": copy.deepcopy(part.get("power_reference")),
                "verified_checkout_quotes": copy.deepcopy(
                    part.get("verified_checkout_quotes", [])
                ),
                "missing_part_evidence": part["missing_part_evidence"],
                "decision": (
                    "OPTIONAL NOT SELECTED, DO NOT BUY"
                    if part.get("excluded_from_order_as_optional")
                    else "HOLD MOTOR CHOICE" if motor == "unresolved"
                    and ident in ("stepper", "uln2003")
                    else "EXCLUDED MOTOR ALTERNATIVE" if target == 0
                    and ident in ("stepper", "uln2003")
                    else "QUALIFIED FIRST ROBOT BOM" if qualified_one
                    else "HOLD FIRST ROBOT QUALIFICATION"
                ),
            })
    linked = []
    for item in report["supplemental_decisions"]:
        parent = item["parent_role"]
        fleet_quantity = _count(item["fleet_quantity"], item["id"] + ".fleet_quantity")
        if parent in pet_ids:
            if fleet_quantity % 5:
                raise ValueError("Pet linked subassembly must scale to one robot")
            target = fleet_quantity // 5
        elif parent in station_ids:
            target = fleet_quantity
        else:
            # A shortened or invalid plan cannot invent a missing parent
            # assembly's checkout quantity. Keep its linked decision visible
            # with zero orderable units and a machine-readable HOLD reason.
            target = 0
        linked.append({
            "id": item["id"], "name": item["name"], "parent_role": parent,
            "conditional_one_robot_quantity": target,
            "parent_present_in_plan": parent in pet_ids | station_ids,
            "reviewed": item["reviewed"], "disposition": item["disposition"],
            "additive_purchase_authorized": False,
        })
    return {
        "robot_count": 1, "dock_count": 1, "shared_station_count": 1,
        "motor_variant": motor, "parent_role_count": len(rows),
        "linked_decision_count": len(linked),
        # Never authorize on source links or prices alone. Approval is
        # possible only after the unchanged complete physical system gates
        # have ALREADY passed through generate(), including installed parts.
        "purchase_approved": qualified_one,
        # Machine-readable first-unit blockers remain visible to shopping
        # clients without pretending five-robot integration is a prerequisite.
        "missing_first_robot_system_evidence": [
            *report.get("missing_first_robot_system_evidence", ["missing"]),
            *(f"linked_parent_missing:{parent}" for parent in missing_linked_parents),
        ],
        "reason": (
            "First complete unit has qualified shared and first-unit system "
            "receipts, supplier evidence and physical trials; the remaining "
            "four units require separate fleet integration evidence."
            if qualified_one else
            "Quantity projection, not a validated first-unit bill of "
            "materials. Verify exact sellers, safety, fit and actual "
            "owned stock before irreversible purchases."
        ),
        "roles": rows, "linked_decisions": linked,
        "verified_checkout_cost": copy.deepcopy(
            report.get("verified_checkout_cost")
        ),
    }



# An exact low-energy sample can be ordered for bench characterization before
# a complete robot exists. This does NOT lift lithium/motion/charging gates.
# Original choices derive from the November 16 register. Added inexpensive
# ElectroPeak carrier samples are independently linked product candidates.
# None of these listings verifies PCB revision, shipping, or US landed price.
PILOT_SAMPLE_PRODUCTS = {
    "cliff_obstacle": ("VL53L0X GY-530 small carrier candidate ElectroPeak SEN-19-006",
                       "ElectroPeak", "SEN-19-006",
                       "https://electropeak.com/gy-530-vl53l0x-laser-range-finder", 1, 1.44),
    # Source checked 2026-11-18: one PCB sample first, then approve seven
    # matching units only after 3.3V/I2C and short-range desk-edge trials.
    "i2c_mux": (
        "TCA9548A 8 channel 3.3V compatible I2C multiplexer",
        "ElectroPeak", "COM-05-067",
        "https://electropeak.com/tca9548a-1-to-8-i2c-8-way-multi-channel-expansion-board",
        2, 0.47),  # USD product quote checked 2026-11-18; not landed.
    "cap1188": (
        "CAP1188 8 zone capacitive touch breakout",
        "ElectroPeak", "SEN-25-020",
        "https://electropeak.com/cap1188-capacitive-touch-module", 1, 6.95),
    "apds9960": (
        "APDS9960 gesture proximity color light module",
        "ElectroPeak", "SEN-24-027",
        "https://electropeak.com/apds-9960-infrared-gesture-sensor-module",
        1, 2.25),
    "ads1115": (
        "ADS1115 4 channel ADC breakout",
        "ElectroPeak", "COM-05-045",
        "https://electropeak.com/ads1115-16-bit-adc-4-channel-programmable-gain-amplifier-b00soy52cu",
        1, 1.50),  # USD product quote checked 2026-11-18; not landed.
    "mcp23017": (
        "MCP23017 16 channel I2C GPIO expander",
        "ElectroPeak", "COM-05-093",
        "https://electropeak.com/mcp23017-e-ss-16-channel-i-o-expansion-module-i2c-interface",
        1, 4.50),

    "amp": (
        "MAX98357A I2S mono amplifier", "DFRobot", "DFR0954",
        "https://www.dfrobot.com/product-2614.html",
        1, 4.90),  # Manufacturer USD quote checked 2026-11-18; bench sample only.
    "bumper": (
        "Normally closed micro bumper switch",
        "Newark", "D2F-01L3",
        "https://www.newark.com/aratas/d2f-01l3/microswitch-d2f-01l3/dp/45Y5018",
        2, 2.48),  # USD exact-SKU quote 2026-11-18; NC/COM and fit untested.
    "speaker": ("Challenge Electronics CS20-02P110-04-1X 8 ohm 2 watt 20 x 16 mm speaker",
                "Challenge Electronics", "CS20-02P110-04-1X",
                "https://www.digikey.com/en/products/detail/challenge-electronics/CS20-02P110-04-1X/30407069", 1, 3.24),
    "sensor_3v3": ("Dedicated regulated 3.3V expansion sensor supply",
                   "Pololu", "2873", "https://www.pololu.com/product/2873", 1, 5.95),  # Single unit; $5.47 applies at quantity >= 5.
    "rgb": ("Single diffused WS2812B RGB pixel", "SparkFun", "BOB-13282",
            "https://www.sparkfun.com/sparkfun-rgb-led-breakout-ws2812b.html", 1, 1.50),
    "dock_ir_receivers": (
        "Two 38 kHz demodulated IR receivers, Vishay TSOP38438 reference, mounted behind separate directional baffles",
        "Vishay", "TSOP38438", "https://www.digikey.com/en/products/detail/vishay-semiconductor-opto-division/TSOP38438/4073478", 2, 0.79),
    "dock_ir_emitter_channels": (
        "Two independently aimed 940 nm 38 kHz infrared LED emitter channels with rated transistor driver and current limiting per dock",
        "Vishay", "TSAL6200",
        "https://www.digikey.com/en/products/detail/vishay-semiconductor-opto-division/TSAL6200/1681339", 2, 0.35),
}

PILOT_PHYSICAL_SELECTION_HOLDS = frozenset({
    "stepper", "uln2003", "cap_power", "switch_power", "ina226",
    "max17048", "dock_contacts", "dock_fixture", "assembly",
    "as5600", "encoder_magnets", "haptic_driver", "dock_ir_beacon_controller",
})


def first_robot_pilot_samples(report: dict) -> dict:
    """Separate purchasing low-voltage bench samples from production release.

    An exact named module can be a test sample even before final acceptance.
    It must NOT be called fit, movement or charging qualified. Source-lock
    both ID and name so a substituted chip cannot inherit permission.
    """
    one = first_robot_projection(report)
    decisions = []
    for part in one["roles"]:
        ident, remaining = part["id"], part["conditional_remaining"]
        source = PILOT_SAMPLE_PRODUCTS.get(ident)
        if not remaining:
            action = ("VERIFY_OWNED_OR_INCOMING_STOCK" if part["prototype_target"]
                      else "EXCLUDED_MOTOR_ALTERNATIVE")
        elif ident in PILOT_PHYSICAL_SELECTION_HOLDS:
            action = "HOLD_POWER_MOTION_OR_FIT_SELECTION"
        elif source is not None:
            action = ("SAMPLE_ONLY_FOR_BENCH_VERIFICATION"
                      if part["name"] == source[0]
                      else "HOLD_CHANGED_PART_IDENTITY")
        else:
            action = "HOLD_EXACT_CARRIER_AND_VENDOR_SELECTION"
        source = (source if action == "SAMPLE_ONLY_FOR_BENCH_VERIFICATION"
                  else None)
        qty = min(remaining, source[4]) if source else 0
        decisions.append({
            "id": ident, "name": part["name"], "scope": part["scope"],
            "first_robot_target": part["prototype_target"],
            "possible_stock_not_verified": part["prototype_target"] - remaining,
            "conditional_remaining": remaining, "pilot_action": action,
            "pilot_sample_quantity": qty,
            "source_vendor": source[1] if source else None,
            "source_sku": source[2] if source else None,
            "source_url": source[3] if source else None,
            "historical_unit_quote_usd": source[5] if source else None,
            # TSAL6200 is a bare LED, not a driven 38 kHz dock channel.
            # Preserve this distinction in machine-readable pilot JSON too.
            "sample_is_complete_functional_channel": (
                False if ident == "dock_ir_emitter_channels" else None
            ),
            "missing_for_functional_channel": (
                ["rated_transistor_driver", "current_limiting",
                 "38khz_modulation_and_wiring_validation"]
                if ident == "dock_ir_emitter_channels" else []
            ),
        })
    return {
        "purpose": "First robot bench samples, not five robot release",
        "pilot_sample_count": sum(x["pilot_sample_quantity"] for x in decisions),
        "pilot_historical_quoted_subtotal_usd": round(sum(
            x["pilot_sample_quantity"] * x["historical_unit_quote_usd"]
            for x in decisions if x["pilot_sample_quantity"]
            and x["historical_unit_quote_usd"] is not None
        ), 2),
        "actual_current_landed_cost_verified": False,
        "whole_first_robot_purchase_approved": one["purchase_approved"],
        "lithium_charging_or_motor_motion_authorized": False,
        "unresolved_linked_decisions": [
            item["id"] for item in one["linked_decisions"] if not item["reviewed"]
        ],
        "roles": decisions,
    }



def pilot_supplier_cart(report: dict) -> dict:
    """Exact-source first-robot evaluation cart; never a whole robot release."""
    pilot = first_robot_pilot_samples(report)
    # Expose a real repository owner and test for each proposed sample. This
    # is traceability, not proof the test ran or the exact PCB works.
    ownership = json.loads((ROOT / "docs/hardware/full-63-role-source-ownership.json").read_text(encoding="utf-8"))
    pet_owners = ownership.get("pet_roles")
    if not isinstance(pet_owners, dict):
        raise ValueError("Missing first-robot implementation ownership")
    items = []
    seen = set()
    for role in pilot["roles"]:
        qty = role["pilot_sample_quantity"]
        if not qty:
            continue
        if role["pilot_action"] != "SAMPLE_ONLY_FOR_BENCH_VERIFICATION":
            raise ValueError("Unreviewed role in supplier cart")
        seller, sku, url = role["source_vendor"], role["source_sku"], role["source_url"]
        if not all(isinstance(x, str) and x.strip()
                   for x in (seller, sku, url)) or not _evidence_https_url(url):
            raise ValueError("Missing exact supplier and linked product")
        if (seller, sku) in seen:
            raise ValueError("Duplicate source SKU")
        seen.add((seller, sku))
        quote = role["historical_unit_quote_usd"]
        owner = pet_owners.get(role["id"])
        if not isinstance(owner, dict):
            raise ValueError("Sample has no implementation owner: " + role["id"])
        source_path = owner.get("source")
        test_path = owner.get("host_test")
        state = owner.get("source_state")
        if not (isinstance(source_path, str)
                and isinstance(test_path, str)
                and isinstance(state, str) and state.strip()):
            raise ValueError("Incomplete sample code trace: " + role["id"])
        for relative in (source_path, test_path):
            full = (ROOT / relative).resolve()
            if (not full.is_relative_to(ROOT.resolve()) or not full.is_file()):
                raise ValueError("Missing sample implementation file: " + relative)
        if not test_path.startswith("code/") or "/tests/" not in test_path:
            raise ValueError("Invalid sample test owner: " + role["id"])
        items.append({
            "implementation_source": source_path,
            "implementation_test": test_path,
            "implementation_state": state,
            "implementation_source_is_code": source_path.startswith("code/"),
            "tests_executed_on_this_checkout": False,
            "id": role["id"], "name": role["name"], "vendor": seller,
            "sku": sku, "product_url": url, "quantity": qty,
            "historical_unit_quote_usd": quote,
            "historical_line_quote_usd": round(qty * quote, 2)
            if quote is not None else None,
            "sample_is_complete_functional_channel":
                role["sample_is_complete_functional_channel"],
            "missing_for_functional_channel":
                role["missing_for_functional_channel"],
        })
    items.sort(key=lambda x: (x["vendor"].casefold(), x["sku"]))
    qty_sum = sum(x["quantity"] for x in items)
    known_subtotal = round(sum(x["historical_line_quote_usd"]
                               for x in items
                               if x["historical_line_quote_usd"] is not None), 2)
    if qty_sum != pilot["pilot_sample_count"] or (
            known_subtotal != pilot["pilot_historical_quoted_subtotal_usd"]):
        raise ValueError("Supplier cart differs from single authoritative plan")
    return {
        "source": "first_robot_pilot_samples",
        "exact_sku_count": len(items),
        "component_quantity": qty_sum,
        "historical_priced_partial_subtotal_usd": known_subtotal,
        "unpriced_skus": [x["sku"] for x in items
                          if x["historical_unit_quote_usd"] is None],
        "landed_total_verified": False,
        "complete_robot_purchase_approved": pilot[
            "whole_first_robot_purchase_approved"],
        "lithium_charging_or_motor_motion_authorized": False,
        "unresolved_roles": [
            x["id"] for x in pilot["roles"]
            if x["conditional_remaining"] > x["pilot_sample_quantity"]
        ],
        "items": items,
    }


def render_pilot_supplier_cart(report: dict) -> str:
    """A single copyable purchase worksheet for bench samples."""
    cart = pilot_supplier_cart(report)
    lines = [
        "# Source-locked first robot evaluation cart",
        "",
        "Not a ready-to-assemble robot or a fleet order. Historical prices are "
        "not live checkout quotes and exclude tax, shipping, conversion and "
        "stock checks. Source and test paths are real files, NOT executed tests "
        "or proof that optional firmware is enabled. No lithium charging or "
        "motor motion is authorized.",
        "",
        "| Seller | SKU | Part | Qty | Historical USD each | Link | Engineering source |",
        "| --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for x in cart["items"]:
        quote = ("$" + format(x["historical_unit_quote_usd"], ".2f")
                 if x["historical_unit_quote_usd"] is not None
                 else "not verified")
        lines.append(
            f"| {x['vendor']} | {x['sku']} | "
            f"{str(x['name']).replace('|', '/')} | "
            f"{x['quantity']} | {quote} | {x['product_url']} | "
            f"{x['implementation_source']} ({x['implementation_state']}) |"
        )
    lines += [
        "",
        f"{cart['exact_sku_count']} SKUs; {cart['component_quantity']} items.",
        "Priced-only historical subtotal USD "
        + format(cart["historical_priced_partial_subtotal_usd"], ".2f"),
        f"{len(cart['unpriced_skus'])} SKUs have unknown comparable USD price. "
        "There is no verified landed total.",
        "Bare TSAL6200 IR emitters are NOT complete driven dock channels. "
        "They need separate rated transistors and current limiting.",
        "Unlisted parts remain required in the canonical full-feature plan. "
        "Do not omit safety, power or fit requirements.",
        "",
    ]
    return "\n".join(lines)


def render_first_robot_pilot_samples(report: dict) -> str:
    """Two visible lists, with source-locked bench samples and all holds."""
    p = first_robot_pilot_samples(report)
    lines = [
        "# First robot: bench component purchase versus final release",
        "",
        "These exact samples are for low-energy bench experiments, not a "
        "physically qualified robot, motor drive, Li-ion battery or live dock. "
        "Every quote is historical and excludes shipping and tax. "
        "Bare dock IR emitters are NOT complete transistor drivers or "
        "current-limited channels.",
        "",
        "## 1. Reported owned or incoming, not yet inspected",
        "",
        "| Component | Possible first-unit stock |",
        "| --- | ---: |",
    ]
    for x in p["roles"]:
        if x["possible_stock_not_verified"]:
            lines.append(
                f"| {x['name']} | {x['possible_stock_not_verified']} |"
            )
    lines.extend([
        "",
        "## 2. Remaining: experimental samples versus unresolved physical choices",
        "",
        "| Component | Needed | Pilot sample quantity | Decision | Verified historical source candidate |",
        "| --- | ---: | ---: | --- | --- |",
    ])
    for x in p["roles"]:
        if not x["conditional_remaining"]:
            continue
        source = "Exact PCB, harness or mechanical selection still required"
        if x["pilot_sample_quantity"]:
            quote = (f"USD {x['historical_unit_quote_usd']:.2f} per unit, old quote"
                     if x["historical_unit_quote_usd"] is not None
                     else "currency or landed USD quote not verified")
            source = (f"{x['source_vendor']} {x['source_sku']}: "
                      f"{x['source_url']} ({quote})")
        lines.append(
            f"| {x['name']} | {x['conditional_remaining']} | "
            f"{x['pilot_sample_quantity']} | {x['pilot_action']} | {source} |"
        )
    lines.extend([
        "",
        "Pilot historical sample subtotal USD "
        + str(p["pilot_historical_quoted_subtotal_usd"])
        + " before tax and shipping.",
        "Do not add the 14 linked subassemblies as duplicate line items. "
        "Full one-robot or five-robot purchasing still requires receipt "
        "evidence and exact assembled electrical and mechanical decisions.",
        "",
    ])
    return "\n".join(lines)


def _checkout_money(value: object) -> str:
    if type(value) is not int:
        return "unknown"
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    return f"{sign}$" + str(absolute // 100) + f".{absolute % 100:02d}"


def _verified_checkout_summary(report: dict) -> list[str]:
    checkout = report.get("verified_checkout_cost")
    if not isinstance(checkout, dict):
        return []
    lines = [
        "**VERIFIED CHECKOUT EVIDENCE FOR THIS RELEASE:**",
        "Payable now: " + _checkout_money(checkout.get("payable_now_cents")),
        "Previously paid: " + _checkout_money(
            checkout.get("prior_paid_orders_cents")
        ),
        "Cumulative recorded spend: " + _checkout_money(
            checkout.get("prototype_cumulative_cents")
        ),
    ]
    if checkout.get("scope") == "first_robot":
        lines.append(
            "Remaining under prototype $50 cap: "
            + _checkout_money(checkout.get("remaining_under_cap_cents"))
        )
    for charge in checkout.get("seller_charges", []):
        if not isinstance(charge, dict):
            continue
        seller = str(charge.get("seller", "")).replace("\n", " ").strip()
        if not seller:
            continue
        lines.append(
            "Supplier charges "
            + seller
            + ": shipping "
            + str(charge.get("shipping_usd", "unknown"))
            + " USD, tax "
            + str(charge.get("tax_usd", "unknown"))
            + " USD, duties "
            + str(charge.get("duties_usd", "unknown"))
            + " USD, discount "
            + str(charge.get("discount_usd", "unknown"))
            + " USD."
        )
    lines.append("")
    return lines


def _power_reference_summary(row: dict) -> str:
    ref = row.get("power_reference")
    if not isinstance(ref, dict):
        return ""
    items = []
    rail = ref.get("rail_candidate_v")
    if isinstance(rail, (int, float)):
        items.append(f"{rail:g} V candidate rail")
    if isinstance(ref.get("regulator_3v3_peak_ma"), (int, float)):
        items.append(f"3.3 V regulator {ref['regulator_3v3_peak_ma']:g} mA peak")
    for key, label in (
        ("peak_ma_at_3v3_max", "peak max"),
        ("periodic_average_ma_at_3v3_max", "periodic average max"),
        ("custom_mode_current_ma_max", "custom mode max"),
        ("reference_current_ma_typ", "reference typical"),
        ("reference_average_current_ma", "reference average"),
    ):
        value = ref.get(key)
        if isinstance(value, (int, float)):
            items.append(f"{value:g} mA {label}")
    capacity = ref.get("supply_capacity_ma_must_exceed")
    if isinstance(capacity, (int, float)):
        items.append(f"supply capacity > {capacity:g} mA")
    if any(key.endswith("_qualified") and value is False
           for key, value in ref.items()):
        items.append("exact fitted current unqualified")
    return "; ".join(items)


def _verified_checkout_quote(row: dict) -> str:
    quotes = row.get("verified_checkout_quotes", [])
    if not isinstance(quotes, list):
        return ""
    rendered = []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        rendered.append(
            f"{quote['seller']} {quote['sku']} rev {quote['pcb_revision']}; "
            f"{quote['quantity_packages']} package(s) x "
            f"{quote['units_per_package']} unit(s) at "
            f"USD {quote['package_price_usd']}/package; quoted "
            f"{quote['quoted_at']}; stock {quote['stock_evidence_url']}"
        )
    return "; ".join(rendered)


def render_first_robot_markdown(report: dict) -> str:
    """Exactly two source-derived lists for the first complete robot."""
    projection = first_robot_projection(report)

    def cell(value: object) -> str:
        return str(value).replace("|", r"\|").replace("\n", " ").strip()

    lines = [
        "# First complete desk robot, one dock and one room station",
        "",
        ("**PROTOTYPE BUYING STATUS: APPROVED WITH VERIFIED RECEIPTS.**"
         if projection["purchase_approved"] else
         "**PROTOTYPE BUYING STATUS: HOLD.**")
        + " This is the exact quantity projection from the canonical "
        "five-pet source. Only actual physical system receipts can approve "
        "one complete unit. No new Adafruit hardware.",
        "",
    ]
    lines.extend(_verified_checkout_summary(report))
    lines += [
        "## 1. Reported owned or ordered, still unverified",
        "",
        "| Role | All reported on hand | All estimated on hand | All ordered, unreceived | Allocated to first unit |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in projection["roles"]:
        if any(row[k] for k in (
                "fleet_reported_owned_not_verified",
                "fleet_estimated_owned_not_verified",
                "fleet_ordered_unreceived_not_verified")):
            first_allocated = sum(row[k] for k in (
                "reported_owned_not_verified", "estimated_owned_not_verified",
                "ordered_unreceived_not_verified"))
            lines.append(
                f"| {cell(row['name'])} | "
                f"{row['fleet_reported_owned_not_verified']} | "
                f"{row['fleet_estimated_owned_not_verified']} | "
                f"{row['fleet_ordered_unreceived_not_verified']} | "
                f"{first_allocated} |"
            )
    lines += [
        "",
        "## 2. First-unit remaining slots and conditional alternatives",
        "",
        "| Scope | Role | One-unit target | Remaining if stock verified | Decision | Reviewed carrier | Power reference | Verified checkout quote |",
        "| --- | --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for row in projection["roles"]:
        selected = row.get("selected_carrier") or {}
        reviewed = ""
        if selected:
            reviewed = (
                f"{selected['vendor']} {selected['sku']}, "
                f"rev {selected['pcb_revision']}"
            )
            if selected.get("product_url"):
                reviewed += f": {selected['product_url']}"
        lines.append(
            f"| {cell(row['scope'])} | {cell(row['name'])} | "
            f"{row['prototype_target']} | {row['conditional_remaining']} | "
            f"{row['decision']} | {cell(reviewed)} | "
            f"{cell(_power_reference_summary(row))} | "
            f"{cell(_verified_checkout_quote(row))} |"
        )
    for item in projection["linked_decisions"]:
        lines.append(
            f"| linked detail, never additive | {cell(item['name'])} | "
            f"{item['conditional_one_robot_quantity']} if selected | "
            "not independently counted | "
            f"{'REVIEWED' if item['reviewed'] else 'HOLD DECISION'} | | | |"
        )
    lines += [
        "",
        "One unit is built and qualified before another four are ordered. "
        "A reported or estimated owned quantity is not physical stock proof. "
        "Linked parts are already owned by parent roles and must not be "
        "summed into a cart; unresolved motors and charger parts are not "
        "authorized purchases.",
        "",
        "First-unit physical and source evidence still required (not extra "
        "shopping lines): " + (
            ", ".join(projection["missing_first_robot_system_evidence"])
            if projection["missing_first_robot_system_evidence"] else "none"
        ),
        "",
    ]
    return "\n".join(lines)

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
            scope, part["id"], part["name"],
            0 if part.get("excluded_from_order_as_alternative") else part["per_robot"],
            part.get("effective_selected_fleet_total",
                     part.get("fleet_total", part.get("shared_total", 0))),
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
        "> **CANONICAL FIVE PET BUYING REGISTER (2026-11-16):** [42 required pet/dock roles plus 14 separately orderable DC motor, power and shared station parts](2026-11-16-five-pet-purchase-register.md). This is the only current full-fleet purchasing candidate table. It incorporates exact seller links, one incoming XIAO, estimated already owned MG90S/MAX30102, motor variant still unresolved and explicit first-pet qualification. This older checklist remains an engineering explanation, NOT an independently approved alternate cart. All power/contact/printing/loaded-drive hold conditions remain effective.",
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
    ]
    output.extend(_verified_checkout_summary(report))
    output += [
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
        "and assorted IR sensors. The reported-owned Feather nRF52840 "
        "still needs carrier inspection, firmware, power and USB qualification "
        "before it becomes the approved station controller.",
        "",
        "## 2. Remaining components or unqualified roles",
        "",
        "| Scope | Component | Fleet required | Conditional remaining | Status | Vendor reference or design blocker | Power reference | Verified checkout quote |",
        "| --- | --- | ---: | ---: | --- | --- | --- | --- |",
    ))
    for scope, part in _purchase_rows(report):
        total = part.get("effective_selected_fleet_total",
                         part.get("fleet_total", part.get("shared_total", 0)))
        remaining = part["remaining_if_reported_stock_works"]
        status = "APPROVED" if part["approved_for_fleet_purchase"] else "HOLD"
        if part.get("excluded_from_order_as_optional"):
            status = "OPTIONAL NOT SELECTED, DO NOT BUY"
        elif part.get("excluded_from_order_as_alternative"):
            status = "EXCLUDED MOTOR ALTERNATIVE, DO NOT BUY"
        elif part["shopping_decision"].startswith("hold_until_drivetrain"):
            status = "HOLD MOTOR CHOICE"
        selected = part.get("selected_carrier") or {}
        reference = part.get("reference_only") or {}
        if selected:
            note = (
                f"{selected['vendor']} {selected['sku']}, "
                f"rev {selected['pcb_revision']}"
            )
            if selected.get("product_url"):
                note += f": {selected['product_url']}"
        else:
            note = (f"{reference['vendor']} {reference['sku']}: {reference['url']}"
                    if reference else part["notes"])
        output.append(
            f"| {cell(scope)} | {cell(part['name'])} | {total} | "
            f"{remaining} | {status} | {cell(note)} | "
            f"{cell(_power_reference_summary(part))} | "
            f"{cell(_verified_checkout_quote(part))} |"
        )
    # These fourteen are alternatives or parts already covered by a parent
    # role. Expose all of them in the SAME remaining-components list without
    # double counting either physical quantities or automatic purchases.
    for detail in report["supplemental_decisions"]:
        name = detail["name"]
        # A reviewed choice to defer an optional module is not a reviewed
        # purchase. Keep its row on HOLD even if deferral was correctly recorded.
        status = (
            "REVIEWED DECISION, CHECK DISPOSITION"
            if detail["reviewed"] and detail["disposition"] != "deferred_optional"
            else "HOLD SUBASSEMBLY DECISION"
        )
        output.append(
            f"| linked detail (not additive) | {cell(name)} | "
            f"{detail['fleet_quantity']} if selected | not independently counted | "
            f"{status} | Linked parent {detail['parent_role']}; "
            f"disposition {detail['disposition'] or 'unresolved'}; "
            "see the canonical 14-row source register before buying | | |"
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


# The dock is included in one-unit parent roles; linked subassemblies are
# selected pieces of those roles, never additional automatic order quantities.
DOCK_COST_ROLES = frozenset({
    "dock_ir_receivers", "dock_ir_beacon_controller",
    "dock_ir_emitter_channels", "dock_contacts", "dock_fixture",
})


def cost_requirements(report: dict, scope: str) -> tuple[dict, dict]:
    """Derive payable part counts from the same canonical quantity owner."""
    if scope == "evaluation":
        keys = ("robot:cliff_obstacle", "robot:i2c_mux")
        return dict.fromkeys(keys, 1), dict.fromkeys(keys, "robot")
    if scope == "first_robot":
        entries = (
            (row["id"], row["prototype_target"], row["scope"])
            for row in first_robot_projection(report)["roles"]
        )
    elif scope == "fleet":
        entries = (
            (row["id"], row.get("effective_selected_fleet_total",
                               row.get("fleet_total", row.get("shared_total", 0))),
             origin)
            for origin, row in _purchase_rows(report)
        )
    else:
        raise ValueError("Unsupported quote scope")
    needed, categories = {}, {}
    for ident, quantity, origin in entries:
        category = ("station" if origin == "shared station"
                    else "dock" if ident in DOCK_COST_ROLES else "robot")
        key = category + ":" + ident
        needed[key] = _count(quantity, key)
        categories[key] = category
    return needed, categories



def quoted_carrier_matches_signed_role(line: dict, selected: dict) -> bool:
    """Strict release must bind the quoted *revision*, not merely chip/SKU.

    Bench sample price projections may have unknown board revisions, but
    irreversible orders must carry the exact revision from the inspected
    and signed part record. Distributors may differ from manufacturers.
    """
    if not isinstance(line, dict) or not isinstance(selected, dict):
        return False
    for key in ("sku", "pcb_revision"):
        quoted = line.get(key)
        if (not isinstance(quoted, str) or not quoted.strip()
                or quoted != selected.get(key)):
            return False
    retailer = selected.get("seller")
    return retailer is None or line.get("seller") == retailer


def cost_quote(report: dict, evidence: dict, scope: str) -> dict:
    required, categories = cost_requirements(report, scope)
    values = evidence.get("costs", {}) if isinstance(evidence, dict) else {}
    return account_landed_cost(values, required, categories,
                               expected_scope=scope)


def attach_verified_checkout_evidence(
    report: dict, cost: dict, cost_evidence: dict
) -> dict:
    """Attach already audited checkout facts to the existing two shopping lists."""
    if (not isinstance(report, dict) or not isinstance(cost, dict)
            or not isinstance(cost_evidence, dict)
            or cost.get("calculation_complete_not_physical_approval") is not True):
        raise ValueError("Verified complete checkout evidence required")
    quote_lines = cost_evidence.get("lines")
    charges = cost_evidence.get("seller_charges")
    if not isinstance(quote_lines, list) or not isinstance(charges, list):
        raise ValueError("Verified quote lines and seller charges required")
    output = copy.deepcopy(report)
    output["verified_checkout_cost"] = {
        "scope": cost.get("scope"),
        "payable_now_cents": cost.get("payable_now_cents"),
        "prior_paid_orders_cents": cost.get("prior_paid_orders_cents"),
        "prototype_cumulative_cents": cost.get("prototype_cumulative_cents"),
        "remaining_under_cap_cents": cost.get("remaining_under_cap_cents"),
        "seller_charges": copy.deepcopy(charges),
    }
    rows = {}
    for part in output["robots"]:
        prefix = "dock" if part["id"] in DOCK_COST_ROLES else "robot"
        rows[prefix + ":" + part["id"]] = part
    for part in output["room_pod"]:
        rows["station:" + part["id"]] = part
    for line in quote_lines:
        if not isinstance(line, dict):
            raise ValueError("Verified quote line must be an object")
        role = line.get("role_key")
        if role not in rows:
            raise ValueError("Verified quote references unknown shopping role")
        normalized = {}
        for key in (
            "role_key", "seller", "sku", "pcb_revision", "quantity_packages",
            "units_per_package", "package_price_usd", "quoted_at",
            "stock_evidence_url", "quote_reference",
        ):
            value = line.get(key)
            if value is None:
                raise ValueError("Verified quote line missing " + key)
            normalized[key] = value
        rows[role].setdefault("verified_checkout_quotes", []).append(normalized)
    return output


def cost_quote_markdown(cost: dict) -> str:
    """Show accurate totals only when all needed quote inputs are present."""
    def amount(value: int | None) -> str:
        if value is None:
            return "unknown"
        sign = "-" if value < 0 else ""
        absolute = abs(value)
        return f"{sign}\u0024{absolute // 100}.{absolute % 100:02d}"
    complete = cost["calculation_complete_not_physical_approval"]
    # Never let a partial or externally constructed report publish a payable
    # total or apparent remaining budget. The accountant returns None for
    # incomplete evidence; the presentation must independently fail closed.
    payable = cost["payable_now_cents"] if complete else None
    cumulative = cost["prototype_cumulative_cents"] if complete else None
    fleet_scope = cost["scope"] == "fleet"
    remaining = cost["remaining_under_cap_cents"] if complete else None
    lines = [
        "# Landed purchasing cost",
        "",
        "Scope: " + cost["scope"],
        "Quote calculation complete: " +
        ("yes, not purchase approval" if complete else "NO"),
        "Payable now: " + amount(payable),
        "Previously paid: " + amount(cost["prior_paid_orders_cents"]),
        ("Cumulative fleet spending: " if fleet_scope
         else "Cumulative prototype spending: ") + amount(cumulative),
        ("First-unit $50 cap does not apply to a five-robot fleet quote."
         if fleet_scope else
         "Remaining under prototype $50 cap: " + amount(remaining)),
        "These amounts are input calculations, not independently checked "
        "supplier stock, receipt, device fit or permission to buy.",
    ]
    for category, subtotal in cost["material_subtotals_cents"].items():
        # A missing quote can yield a numeric zero from an empty line list.
        # Never present that partial accounting as a fully priced category.
        shown = (amount(subtotal)
                 if complete
                 else "unknown (incomplete quote)")
        lines.append(category.capitalize() + " materials: " + shown)
    # A single category view, with exact seller charges included once.
    # Partial quotations cannot show a plausible complete delivered total.
    allocated = cost.get("allocated_landed_subtotals_cents")
    if allocated is None or not complete:
        lines.append("Allocated landed category costs: unknown (incomplete quote)")
    else:
        lines.append(
            "Allocated landed category costs apportion seller charges by "
            "material value, or unit count for free goods. They are not "
            "individual supplier checkout prices."
        )
        for category in ("robot", "dock", "station"):
            lines.append(
                category.capitalize() + " allocated landed cost: "
                + amount(allocated.get(category))
            )
    if (not fleet_scope and cumulative is not None
            and not cost["within_prototype_cap"]):
        lines.append("HOLD: cumulative prototype spending exceeds the "
                     + amount(cost["prototype_cap_cents"]) + " cap")
    for supplier, total in cost["seller_payable_cents"].items():
        # Seller strings are evidence inputs, not trusted Markdown.
        safe_name = str(supplier).replace("\n", " ").replace("\r", " ").strip()
        prefix = "Supplier " if complete else "Partial supplier quote "
        lines.append(prefix + safe_name + ": " + amount(total))
    for problem in cost["errors"]:
        lines.append("HOLD: " + problem)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--evidence", type=Path,
                        help="Operator-recorded measured qualification JSON, if any")
    releases = parser.add_mutually_exclusive_group()
    releases.add_argument("--require-release", action="store_true",
                          help="Fail closed unless full fleet physical evidence verifies")
    releases.add_argument("--require-first-robot", action="store_true",
                          help="Fail closed unless one complete robot and dock verify")
    parser.add_argument("--format", choices=(
        "json", "csv", "markdown", "first-robot-json", "first-robot-markdown",
        "pilot-samples-json", "pilot-samples-markdown",
        "pilot-cart-json", "pilot-cart-markdown",
        "landed-cost-json", "landed-cost-markdown"
    ), default="json", help="Project the canonical ledger without buying permits")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    evidence = (json.loads(args.evidence.read_text(encoding="utf-8"))
                if args.evidence else {})
    report = generate(plan, evidence)
    provided_costs = evidence.get("costs")
    requested_scope = (provided_costs.get("scope", "first_robot")
                       if isinstance(provided_costs, dict) else "first_robot")
    if args.require_release:
        pricing_scope = "fleet"
    elif args.require_first_robot:
        pricing_scope = "first_robot"
    else:
        pricing_scope = requested_scope
    if pricing_scope not in {"first_robot", "fleet", "evaluation"}:
        parser.error("Unknown cost quote scope")
    cost = cost_quote(report, evidence, pricing_scope)
    if args.require_first_robot and args.format not in (
        "first-robot-json", "first-robot-markdown"
    ):
        parser.error("First robot release may only print a first robot view")
    if args.require_release and args.format not in (
        "json", "csv", "markdown"
    ):
        parser.error("Fleet release may only print a full fleet view")
    if args.require_release or args.require_first_robot:
        # The pure projection intentionally accepts synthetic unit-test
        # receipts. A REAL purchase command must verify immutable, scoped
        # physical evidence against this exact clean source revision before
        # printing a potentially misleading APPROVED shopping view.
        purchase_ready = (first_robot_projection(report)["purchase_approved"]
                          if args.require_first_robot else report["order_released"])
        if not purchase_ready:
            print("HOLD: prerequisite component and system gates not qualified",
                  file=sys.stderr)
            return 2
        try:
            from verify_procurement_receipts import (
                audit_release, checkout_sha, verified_required_ci_jobs,
            )
            checked_sha = checkout_sha()
            # The same generator decision map owns optional station inclusion.
            # Deferred, reviewed shared-room options require no fabricated
            # purchase receipts; selected options still require every gate.
            deferred_optional_ids = frozenset(
                decision["id"] for decision in report["supplemental_decisions"]
                if decision["reviewed"]
                and decision["disposition"] == "deferred_optional"
                and decision["parent_role"] in CONDITIONAL_ROOM_PER_STATION
            )
            failures = audit_release(
                evidence, checked_sha, first_robot=args.require_first_robot,
                deferred_optional_ids=deferred_optional_ids,
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print("HOLD: cannot verify real purchasing evidence: " + str(exc),
                  file=sys.stderr)
            return 2
        if failures:
            for problem in failures[:20]:
                print("HOLD: " + problem, file=sys.stderr)
            if len(failures) > 20:
                print(f"HOLD: {len(failures) - 20} further evidence failures",
                      file=sys.stderr)
            return 2
        # A purchase receipt is not executable-source qualification. The
        # declared CI run must show all five required exact-revision jobs
        # completed successfully, not merely a successful workflow headline.
        if not verified_required_ci_jobs(
            evidence.get("source_ci_run_url"), checked_sha
        ):
            print("HOLD: exact-source Mac, Python, sanitizer, WROOM and Sense "
                  "CI jobs not all verified successful", file=sys.stderr)
            return 2
        if (not cost["calculation_complete_not_physical_approval"]
                or args.require_first_robot and not cost["within_prototype_cap"]
                or cost["awaiting_arrival_roles"]):
            print("HOLD: actual landed quotation, budget or received stock "
                  "has not cleared the purchase gates", file=sys.stderr)
            return 2
        # The approved system receipt for the costed exact carrier BOM must
        # separately attest that the supplier and SKU match every quote line.
        by_role = (evidence.get("room_pod", {}), evidence.get("parts", {}))
        for line in evidence["costs"]["lines"]:
            role = line["role_key"]
            kind, ident = role.split(":", 1)
            selected = by_role[0 if kind == "station" else 1].get(ident, {})
            # A supplier can be a distributor (for example, DigiKey)
            # rather than the carrier manufacturer. Match the exact
            # selected part SKU; verify retailer only when independently
            # named on the signed part record.
            if not quoted_carrier_matches_signed_role(line, selected):
                print("HOLD: quoted SKU, PCB revision or chosen retailer "
                      "differs from signed carrier: " + role, file=sys.stderr)
                return 2
        report = attach_verified_checkout_evidence(
            report, cost, evidence["costs"]
        )
        # Receipts, checkout and carrier matching can take time. The first
        # live PR read is not a lease: reject an approved cart if another
        # worker changed the canonical hardware or purchasing requirements.
        try:
            if checkout_sha() != checked_sha:
                print("HOLD: PR #17 advanced during purchasing verification",
                      file=sys.stderr)
                return 2
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print("HOLD: cannot recheck live purchasing revision: " + str(exc),
                  file=sys.stderr)
            return 2
    report = public_purchase_view(
        report, live_receipts_verified=(args.require_release or args.require_first_robot)
    )
    if args.format == "landed-cost-json":
        print(json.dumps(cost, indent=2))
    elif args.format == "landed-cost-markdown":
        print(cost_quote_markdown(cost), end="")
    elif args.format == "csv":
        print(render_csv(report), end="")
    elif args.format == "markdown":
        print(render_markdown(report), end="")
    elif args.format == "first-robot-json":
        print(json.dumps(first_robot_projection(report), indent=2))
    elif args.format == "first-robot-markdown":
        print(render_first_robot_markdown(report), end="")
    elif args.format == "pilot-samples-json":
        print(json.dumps(first_robot_pilot_samples(report), indent=2))
    elif args.format == "pilot-samples-markdown":
        print(render_first_robot_pilot_samples(report), end="")
    elif args.format == "pilot-cart-json":
        print(json.dumps(pilot_supplier_cart(report), indent=2))
    elif args.format == "pilot-cart-markdown":
        print(render_pilot_supplier_cart(report), end="")
    else:
        print(json.dumps(report, indent=2))
    return 2 if args.require_release and not report["order_released"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
