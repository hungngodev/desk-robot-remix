"""A design slot, popular part, or fabricated boolean is not a purchase approval."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/procurement_release.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("procurement_release", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    return {
        "target_robots": 5, "qualified_assumptions": False,
        "physical_trial_count": 0, "prices_complete": False,
        "parts": [
            {"id": "cliff_obstacle", "name": "VL53L0X", "per_robot": 8,
             "reported_owned_total": 0, "group": "pet"},
            {"id": "stepper", "name": "28BYJ48", "per_robot": 2,
             "reported_owned_total": 5, "group": "pet"},
            {"id": "mg90s", "name": "MG90S", "per_robot": 2,
             "reported_owned_total": 0, "group": "pet"},
        ],
        "room_pod": {
            "power_reference": {
                "room_controller": {"exact_board_current_qualified": False},
                "scd40": {"exact_carrier_current_qualified": False},
                "bme688": {"exact_carrier_current_qualified": False},
                "amg8833": {"exact_carrier_current_qualified": False},
                "ld2410c": {"exact_carrier_current_qualified": False},
                "soil_probe": {"exact_carrier_current_qualified": False},
                "references": ["https://example.com/room-power-reference"],
            },
            "modules": [
                {"id": "scd40", "name": "SCD40", "quantity_per_room": 1}
            ],
        },
    }


def test_full_fleet_quantities_never_grant_purchase():
    r = mod.generate(fixture())
    assert (r["fleet_robots"], r["docks"], r["room_stations"]) == (5, 5, 1)
    d = {p["id"]: p for p in r["robots"]}
    assert d["cliff_obstacle"]["fleet_total"] == 40
    assert d["cliff_obstacle"]["reference_only"]["sku"] == "SEN-19-006"
    assert d["stepper"]["remaining_if_reported_stock_works"] == 5
    assert d["mg90s"]["remaining_if_reported_stock_works"] == 10
    assert not r["order_released"]
    assert "plan_unqualified_or_price_incomplete" in r["missing_system_evidence"]



def test_outdated_s3cam_c3_architecture_cannot_be_buy_approved():
    """A generic role ID cannot authorize a different board or GPIO budget."""
    import copy
    import json

    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    assert "unqualified_xiao_sense_wroom_architecture_substitution" not in (
        mod.generate(plan)["missing_system_evidence"]
    )
    cases = (
        ("architecture", "ESP32 S3CAM + ESP32 C3 two-sensor XSHUT"),
        ("xiao_sense", "Generic ESP32 S3CAM N16R8 OV2640"),
        ("wroom", "Generic ESP32 C3 SuperMini"),
        # Prior substring matching silently accepted these mixed labels.
        ("architecture", plan["architecture"] + " Also install ESP32 C3."),
        ("xiao_sense", "XIAO ESP32S3 Sense camera + microphone / "
                       "or generic ESP32 S3CAM"),
        ("wroom", "ESP32 WROOM32 development board / "
                  "or ESP32 C3 SuperMini"),
        ("architecture", "ESP32 C3 plus " + plan["architecture"]),
    )
    for ident, replacement in cases:
        altered = copy.deepcopy(plan)
        if ident == "architecture":
            altered["architecture"] = replacement
        else:
            next(p for p in altered["parts"] if p["id"] == ident)["name"] = replacement
        report = mod.generate(altered)
        assert not report["order_released"]
        assert "unqualified_xiao_sense_wroom_architecture_substitution" in (
            report["missing_system_evidence"]
        )



def test_no_expensive_sensor_substitution_in_canonical_order():
    p = fixture()
    p["parts"][0]["name"] = "VL53L4CD premium carrier"
    with pytest.raises(ValueError, match="approved low-cost VL53L0X"):
        mod.generate(p)



def test_missing_speaker_model_is_a_purchase_hold_not_a_crash():
    """An incomplete candidate listing cannot break the full cart audit."""
    p = fixture()
    p["parts"].append({
        "id": "speaker", "name": None, "per_robot": 1,
        "reported_owned_total": 0, "group": "pet",
    })
    p["audio_output_power_contract"] = {
        "amplifier_ic": "MAX98357A", "amplifier_vdd_v": 5.0,
        "speaker_nominal_impedance_ohm": 8,
        "speaker_nominal_rating_w": 2,
        "physical_release": "HOLD pending real speaker thermal measurement",
    }
    result = mod.generate(p)
    assert result["order_released"] is False
    assert "unresolved_current_two_watt_speaker_contract" in (
        result["missing_system_evidence"]
    )



def test_verification_requires_receipts_not_boolean_assertions():
    p = fixture()
    p["qualified_assumptions"] = True
    p["physical_trial_count"] = 1
    p["prices_complete"] = True
    ev = {"parts": {x["id"]: {"vendor": "X", "sku": "Y", "pcb_revision": "1",
                             **{k: True for k in mod.PART_GATES}}
                    for x in p["parts"]},
          "system": {k: True for k in mod.SYSTEM_GATES}}
    r = mod.generate(p, ev)
    assert not r["order_released"]
    assert "full_power_load_and_faults" in r["missing_system_evidence"]
    assert all(x["missing_part_evidence"] for x in r["robots"])


def test_missing_ownership_or_conflicting_parts_fail_fast():
    p = fixture()
    p["parts"].append(p["parts"][0].copy())
    with pytest.raises(ValueError, match="Duplicate part"):
        mod.generate(p)
    p = fixture()
    p["parts"][0]["reported_owned_total"] = True
    with pytest.raises(ValueError, match="nonnegative integer"):
        mod.generate(p)
    p = fixture()
    p["parts"][0]["reported_owned_total"] = 41
    with pytest.raises(ValueError, match="exceeds"):
        mod.generate(p)
    with pytest.raises(ValueError, match="nonexistent"):
        mod.generate(fixture(), {"parts": {"fake_part": {}}})


def test_bona_fide_receipts_are_operator_provided_not_inferred():
    p = fixture()
    p["qualified_assumptions"] = True
    p["physical_trial_count"] = 1
    p["prices_complete"] = True
    receipt = {"result": "pass", "evidence_url": "https://example.org/test-data",
               "tested_on": "sample board revision", "reviewer": "second reviewer"}
    ev = {"parts": {x["id"]: {"vendor": "X", "sku": "Y", "pcb_revision": "1",
                             **{k: receipt for k in mod.PART_GATES}}
                    for x in p["parts"]},
          "system": {k: receipt for k in mod.SYSTEM_GATES},
          "room_pod": {"scd40": {
              "vendor": "Sensirion", "sku": "SCD40", "pcb_revision": "1",
              **{k: receipt for k in mod.PART_GATES},
          }}}
    assert not mod.generate(p, ev)["order_released"]
    ev["system"]["protected_1s_charger_and_dock_contacts"] = {"result": "pass"}
    assert not mod.generate(p, ev)["order_released"]



@pytest.mark.parametrize("role,linked_id,total", [
    ("amg8833", "room_amg8833", 1),
    ("nfc_game_props", "room_nfc_game_tokens", 10),
])
def test_conditional_room_options_stay_visible_but_not_in_default_checkout(
    role, linked_id, total
):
    import json
    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    report = mod.generate(plan)
    optional = next(row for row in report["room_pod"]
                    if row["id"] == role)
    assert optional["shared_total"] == total
    assert optional["effective_selected_fleet_total"] == 0
    assert optional["excluded_from_order_as_optional"] is True
    assert optional["shopping_decision"] == "conditional_optional_not_selected"
    assert optional["approved_for_fleet_purchase"] is False
    assert optional["missing_part_evidence"]
    detail = next(item for item in report["supplemental_decisions"]
                  if item["id"] == linked_id)
    assert detail["reviewed"] is True
    assert detail["disposition"] == "deferred_optional"
    first = mod.first_robot_projection(report)
    projected = next(row for row in first["roles"]
                     if row["id"] == role)
    assert projected["prototype_target"] == 0
    assert projected["conditional_remaining"] == 0
    assert projected["decision"] == "OPTIONAL NOT SELECTED, DO NOT BUY"
    first_needed, _ = mod.cost_requirements(report, "first_robot")
    fleet_needed, _ = mod.cost_requirements(report, "fleet")
    assert first_needed["station:" + role] == 0
    assert fleet_needed["station:" + role] == 0
    shown = mod.render_markdown(report)
    assert "OPTIONAL NOT SELECTED, DO NOT BUY" in shown


def test_required_room_role_cannot_be_relabelled_optional():
    plan = fixture()
    plan["room_pod"]["modules"][0]["purchase_status"] = "conditional_optional"
    with pytest.raises(ValueError, match="Required room role cannot become optional"):
        mod.generate(plan)


def test_required_room_status_records_match_current_selected_plan():
    source = (mod.PLAN.parent.parent / "source-map.md").read_text(
        encoding="utf-8"
    )
    register = (
        mod.PLAN.parent / "2026-11-16-five-pet-purchase-register.md"
    ).read_text(encoding="utf-8")
    for feature in ("S027", "S043", "S045", "S062"):
        row = next(line for line in source.splitlines()
                   if line.startswith("| `" + feature + "` |"))
        assert "ACTIVE REQUIRED SHARED STATION ROLE, PHYSICAL HOLD" in row
    thermal = next(line for line in source.splitlines()
                   if line.startswith("| `S042` |"))
    assert "CONDITIONAL SHARED STATION OPTION, NOT SELECTED" in thermal
    assert "Required shared-station capacitive soil probe" in register
    assert "CONDITIONAL OPTIONAL, NOT SELECTED" in register


def test_room_power_reference_survives_builder_markdown():
    import json
    report = mod.generate(json.loads(mod.PLAN.read_text(encoding="utf-8")))
    room = next(row for row in report["room_pod"] if row["id"] == "scd40")
    assert room["power_reference"]["peak_ma_at_3v3_max"] == 205
    full = mod.render_markdown(report)
    first = mod.render_first_robot_markdown(report)
    for shown in (full, first):
        assert "Power reference" in shown
        assert "3.3 V candidate rail" in shown
        assert "205 mA peak max" in shown
        assert "18 mA periodic average max" in shown
        assert "exact fitted current unqualified" in shown


def test_partial_plan_preserves_linked_roles_as_visible_holds_not_fake_cart():
    # A reduced fixture never authorizes quantities for nonexistent parents.
    # The single shared station can still be shown without a generator crash.
    report = mod.generate(fixture())
    projected = mod.first_robot_projection(report)
    assert projected["purchase_approved"] is False
    assert projected["linked_decision_count"] == 14
    assert "linked_parent_missing:cap_power" in (
        projected["missing_first_robot_system_evidence"]
    )
    linked = next(row for row in projected["linked_decisions"]
                  if row["id"] == "protected_ntc_pack")
    assert linked["conditional_one_robot_quantity"] == 0
    assert linked["parent_present_in_plan"] is False
    assert linked["additive_purchase_authorized"] is False
    assert "HOLD" in mod.render_first_robot_markdown(report)


def test_reviewed_room_carrier_identity_survives_builder_projections():
    p = fixture()
    ev = {"room_pod": {"scd40": {
        "vendor": "Sensirion",
        "sku": "SCD40-CARRIER",
        "pcb_revision": "rev-A",
        "product_url": "https://supplier.example/scd40-carrier",
    }}}
    report = mod.generate(p, ev)
    room = report["room_pod"][0]
    assert room["selected_carrier"] == {
        "vendor": "Sensirion",
        "sku": "SCD40-CARRIER",
        "pcb_revision": "rev-A",
        "product_url": "https://supplier.example/scd40-carrier",
    }
    full = mod.render_markdown(report)
    assert "Sensirion SCD40-CARRIER, rev rev-A" in full
    assert "https://supplier.example/scd40-carrier" in full

    one = mod.render_first_robot_markdown(report)
    assert "Reviewed carrier" in one
    assert "Sensirion SCD40-CARRIER, rev rev-A" in one


def test_new_adafruit_hardware_is_never_approved_even_with_receipts():
    p = fixture()
    p["qualified_assumptions"] = True
    p["physical_trial_count"] = 1
    p["prices_complete"] = True
    receipt = {"result": "pass", "evidence_url": "https://example.org/real-trial",
               "tested_on": "sample A", "reviewer": "operator"}
    good = {"vendor": "generic", "sku": "tested", "pcb_revision": "A",
            **{gate: receipt for gate in mod.PART_GATES}}
    e = {"parts": {x["id"]: dict(good) for x in p["parts"]},
         "room_pod": {"scd40": dict(good)},
         "system": {gate: receipt for gate in mod.SYSTEM_GATES}}
    assert not mod.generate(p, e)["order_released"]
    e["parts"]["cliff_obstacle"]["vendor"] = "Adafruit Industries"
    r = mod.generate(p, e)
    assert not r["order_released"]
    assert "no_new_adafruit_hardware" in next(
        x for x in r["robots"] if x["id"] == "cliff_obstacle"
    )["missing_part_evidence"]
    e["parts"]["cliff_obstacle"]["vendor"] = "generic"
    e["room_pod"]["scd40"]["vendor"] = "Adafruit"
    assert not mod.generate(p, e)["order_released"]


@pytest.mark.parametrize("field, label", [
    ("brand", "Adafruit"),
    ("sku", "Adafruit 3317 VL53L0X breakout"),
    ("product_name", "Adafruit STEMMA QT carrier"),
    ("product_url", "https://www.adafruit.com/product/3317"),
    ("resolved_item", "Adafruit branded module"),
])
def test_adafruit_brand_hidden_behind_generic_reseller_is_still_blocked(field, label):
    candidate = {"vendor": "generic reseller", "sku": "GENERIC-SKU"}
    candidate[field] = label
    assert mod._ad_fruit_new_hardware(candidate, 1)
    assert not mod._ad_fruit_new_hardware(candidate, 0)  # already owned
    assert not mod._ad_fruit_new_hardware(
        {"vendor": "Generic", "sku": "VL53L0X"}, 1
    )
    plan = fixture()
    evidence = {"parts": {"stepper": dict(candidate)},
                "room_pod": {"scd40": dict(candidate)}}
    actual = mod.generate(plan, evidence)
    assert "no_new_adafruit_hardware" in next(
        item for item in actual["robots"] if item["id"] == "stepper"
    )["missing_part_evidence"]
    assert "no_new_adafruit_hardware" in next(
        item for item in actual["room_pod"] if item["id"] == "scd40"
    )["missing_part_evidence"]


def test_battery_babysitter_and_second_fuel_gauge_not_bought_together():
    p = fixture()
    p["parts"].extend([
        {"id": "cap_power", "name": "1S power module", "per_robot": 1,
         "reported_owned_total": 0, "group": "pet"},
        {"id": "max17048", "name": "MAX17048", "per_robot": 1,
         "reported_owned_total": 0, "group": "pet"}])
    evidence = {"parts": {"cap_power": {"vendor": "SparkFun",
              "sku": "PRT-13777", "pcb_revision": "A"}}}
    r = mod.generate(p, evidence)
    assert "duplicate_bq27441_and_max17048_gauges" in r["missing_system_evidence"]
    evidence["parts"]["cap_power"]["sku"] = "charger_without_gauge"
    assert "duplicate_bq27441_and_max17048_gauges" not in (
        mod.generate(p, evidence)["missing_system_evidence"])
    evidence["parts"]["cap_power"]["integrated_fuel_gauge_ic"] = "BQ27441"
    assert "duplicate_bq27441_and_max17048_gauges" in (
        mod.generate(p, evidence)["missing_system_evidence"])
    evidence["parts"]["cap_power"]["integrated_fuel_gauge_ic"] = "MAX17048"
    assert "duplicate_bq27441_and_max17048_gauges" in (
        mod.generate(p, evidence)["missing_system_evidence"])
    evidence["parts"]["cap_power"]["integrated_fuel_gauge_ic"] = "none"
    assert "duplicate_bq27441_and_max17048_gauges" not in (
        mod.generate(p, evidence)["missing_system_evidence"])
    evidence["parts"]["cap_power"]["integrated_fuel_gauge_ic"] = "mystery"
    assert "unrecognized_integrated_fuel_gauge" in (
        mod.generate(p, evidence)["missing_system_evidence"])



def test_detailed_charger_selection_cannot_hide_duplicate_battery_gauge():
    """A BQ27441 equipped charger is incompatible with a second MAX17048."""
    p = fixture()
    p["parts"].extend([
        {"id": "cap_power", "name": "1S power assembly", "per_robot": 1,
         "reported_owned_total": 0, "group": "pet"},
        {"id": "max17048", "name": "MAX17048", "per_robot": 1,
         "reported_owned_total": 0, "group": "pet"},
    ])
    e = {
        "parts": {"cap_power": {"vendor": "generic", "sku": "custom",
                                  "pcb_revision": "A",
                                  "integrated_fuel_gauge_ic": "none"}},
        "supplemental_decisions": {
            "bq24075_charger_candidate": {
                "parent_role": "cap_power", "fleet_quantity": 5,
                "disposition": "selected", "vendor": "SparkFun",
                "sku": "PRT-13777", "pcb_revision": "A",
            },
        },
    }
    assert "duplicate_bq27441_and_max17048_gauges" in (
        mod.generate(p, e)["missing_system_evidence"])
    # Removing a board from the actual purchasing selection is different
    # from selecting it and simply changing the primary power assembly name.
    e["supplemental_decisions"]["bq24075_charger_candidate"][
        "disposition"
    ] = "rejected_in_favor_of_qualified_alternative"
    assert "duplicate_bq27441_and_max17048_gauges" not in (
        mod.generate(p, e)["missing_system_evidence"])
    e["supplemental_decisions"]["bq24075_charger_candidate"].update(
        disposition="selected", sku="generic-1s-charger",
        integrated_fuel_gauge_ic="BQ27441",
    )
    assert "duplicate_bq27441_and_max17048_gauges" in (
        mod.generate(p, e)["missing_system_evidence"])


def test_shared_station_and_controller_must_be_in_release_scope():
    """Every listed room module is needed for the requested complete build."""
    p = fixture()
    p["qualified_assumptions"] = True
    p["physical_trial_count"] = 1
    p["prices_complete"] = True
    receipt = {"result": "pass", "evidence_url": "https://example.org/test",
               "tested_on": "bench trial", "reviewer": "operator"}
    passed = {"vendor": "specific vendor", "sku": "specific part",
              "pcb_revision": "1", **{k: receipt for k in mod.PART_GATES}}
    ev = {
        "parts": {x["id"]: passed for x in p["parts"]},
        "system": {k: receipt for k in mod.SYSTEM_GATES},
    }
    assert not mod.generate(p, ev)["order_released"]
    assert "exact_vendor_sku_and_pcb_revision" in (
        mod.generate(p, ev)["room_pod"][0]["missing_part_evidence"])
    ev["room_pod"] = {"scd40": passed}
    assert not mod.generate(p, ev)["order_released"]
    ev["room_pod"]["scd40"] = {"vendor": "X", "sku": "Y", "pcb_revision": "1"}
    assert not mod.generate(p, ev)["order_released"]


def test_shared_station_rejects_duplicate_and_phantom_modules():
    p = fixture()
    p["room_pod"]["modules"].append({"id": "scd40",
                                       "name": "Duplicate",
                                       "quantity_per_room": 1})
    with pytest.raises(ValueError, match="duplicate shared station"):
        mod.generate(p)
    p = fixture()
    with pytest.raises(ValueError, match="nonexistent shared station"):
        mod.generate(p, {"room_pod": {"invented_sensor": {}}})
    p = fixture()
    p["room_pod"]["modules"][0]["quantity_per_room"] = True
    with pytest.raises(ValueError, match="nonnegative integer"):
        mod.generate(p)




def test_candidate_buy_register_matches_exact_selected_bom_without_premium_pilots():
    """The hand-curated price comparison must not silently replace a chip.

    Candidate register is not a second quantity owner or purchase approval.
    """
    import json
    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    parts = {p["id"]: p for p in plan["parts"]}
    register = (mod.PLAN.parent / "2026-11-16-five-pet-purchase-register.md").read_text(
        encoding="utf-8")
    selected = {}
    for line in register.splitlines():
        if not line.startswith("| " + chr(96)):
            continue
        columns = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(columns) != 11:
            raise AssertionError("Incorrect buying register row: " + line)
        part_id = columns[0].strip("`")
        assert part_id not in selected, "Duplicate candidate component"
        selected[part_id] = columns
    assert set(selected) == set(parts), "Missing or invented selected purchasing role"
    machine = {row["id"]: row for row in mod.generate(plan)["robots"]}
    # Audit the *entire* hand-curated 42-role purchase table, not only its
    # headline totals. In particular HOLD or zero pilot does not erase a
    # physical fleet shortage (previously wrong for steppers and 1S power).
    for ident, _item in parts.items():
        cells = selected[ident]
        report = machine[ident]
        expected = (
            report["per_robot"], report["fleet_total"],
            report["reported_owned_not_verified"],
            report["estimated_owned_not_verified"],
            report["ordered_unreceived_not_verified"],
            report["remaining_if_reported_stock_works"],
        )
        actual = tuple(int(value) for value in cells[2:8])
        assert actual == expected, (
            f"{ident}: register per/total/owned/estimate/ordered/gap "
            f"{actual} disagrees with machine ledger {expected}"
        )
        assert int(cells[8]) >= 0, ident
        assert int(cells[8]) <= report["remaining_if_reported_stock_works"], (
            f"{ident}: pilot count cannot exceed recorded shortage"
        )
    assert machine["stepper"]["remaining_if_reported_stock_works"] == 5
    assert machine["uln2003"]["remaining_if_reported_stock_works"] == 5
    assert machine["cap_power"]["remaining_if_reported_stock_works"] == 5
    for ident in ("oled", "imu", "head_touch", "reed", "pir", "bmp280",
                  "haptic_motor"):
        assert selected[ident][8] == "0", "Do not rebuy reported owned " + ident
    assert "VL53L0X" in selected["cliff_obstacle"][1]
    # Historical rejection of the overpriced alternative is useful to
    # preserve; only the actual selected purchase row must exclude it.
    assert "VL53L4CD" not in selected["cliff_obstacle"][1]
    # The first unknown $2-style GY-530 carrier is for optical/electrical
    # qualification, NOT the complete 8-piece robot or 40-piece fleet.
    assert selected["cliff_obstacle"][8] == "1"
    assert "ONE SAMPLE OR BORROW ONLY" in selected["cliff_obstacle"][10]
    # The preferred low-cost CAP1188 is HOLD with zero pilot units, while
    # other premium comparison boards explicitly say NO PURCHASE. Do not
    # loosen either source quantity merely to satisfy an outdated phrase.
    assert selected["cap1188"][8] == "0"
    assert selected["cap1188"][10].startswith("HOLD CHEAP GENERIC")
    for ident in ("fsr", "ads1115", "as5600", "encoder_magnets",
                  "max17048", "ina226", "pn532", "sht41"):
        assert selected[ident][8] == "0", ident
        # Supplier comparison may say HOLD rather than NO PURCHASE, but
        # neither may authorize units. Preserve the explicitly unresolved
        # INA226 Kelvin shunt and exact-carrier fit decisions.
        decision = selected[ident][10]
        assert ("NO PURCHASE" in decision or decision.startswith(
            ("HOLD CHEAP GENERIC EXACT CARRIER",
             "SHUNT VALUE/SKU FIXED, BREAKOUT HOLD")
        ) or (ident == "max17048" and
              decision.startswith("ONE SoC GAUGE ONLY:") and
              "HOLD" in decision)), ident
    # Separate candidate subsystem is not a hidden second approved shopping list.
    assert "BQ24075 power-path source, NO second SoC gauge" in register
    assert "MAX17048" in register
    assert "SparkFun Battery Babysitter with BQ27441 is EXCLUDED" in register
    assert "Owned 28BYJ48 must be load tested first" in register

def test_canonical_full_fleet_plan_has_all_forty_nine_roles():
    import json
    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    report = mod.generate(plan)
    robots = {row["id"]: row for row in report["robots"]}
    room = {row["id"]: row for row in report["room_pod"]}
    assert len(robots) == 42 and len(room) == 7
    assert robots["cliff_obstacle"]["fleet_total"] == 40
    assert robots["i2c_mux"]["fleet_total"] == 10
    assert robots["dock_ir_receivers"]["fleet_total"] == 10
    assert robots["dock_ir_beacon_controller"]["fleet_total"] == 5
    assert robots["dock_ir_emitter_channels"]["fleet_total"] == 10
    assert robots["xiao_sense"]["ordered_unreceived_not_verified"] == 1
    assert robots["xiao_sense"]["remaining_if_reported_stock_works"] == 4
    assert robots["mg90s"]["estimated_owned_not_verified"] == 10
    assert robots["mg90s"]["remaining_if_reported_stock_works"] == 0
    assert robots["max30102"]["estimated_owned_not_verified"] == 5
    assert robots["max30102"]["remaining_if_reported_stock_works"] == 0
    assert room["room_controller"]["reported_owned_not_verified"] == 1
    assert room["room_controller"]["estimated_owned_not_verified"] == 0
    assert room["room_controller"]["remaining_if_reported_stock_works"] == 0
    assert robots["stepper"]["shopping_decision"].startswith("hold_until_drivetrain")
    assert not report["order_released"]


def test_requested_effects_and_soil_cannot_be_silently_excluded_from_release():
    """Preserved BOM slots are not the same as completed physical features."""
    import json

    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    report = mod.generate(plan)
    requirements = (
        "rgb_and_haptic_real_device_effects_and_power",
        "room_soil_probe_enabled_and_calibrated",
    )
    for requirement in requirements:
        assert requirement in mod.SYSTEM_GATES
        assert requirement in report["missing_system_evidence"]
    assert not report["order_released"]

    station_ini = (
        mod.PLAN.parents[2] / "code/firmware/room_station/platformio.ini"
    ).read_text(encoding="utf-8")
    # This is deliberately a guard on the CURRENT unqualified profile.
    # Replacing 0 with 1 alone would not make physical soil calibration pass.
    assert "-DROOM_SOIL_FITTED=0" in station_ini


def test_reviewed_optional_deferral_still_prints_shopping_hold():
    import json

    report = mod.generate(json.loads(mod.PLAN.read_text(encoding="utf-8")))
    deferred = {
        row["id"]: row for row in report["supplemental_decisions"]
        if row["disposition"] == "deferred_optional"
    }
    assert set(deferred) == {"room_amg8833", "room_nfc_game_tokens"}
    assert all(row["reviewed"] is True for row in deferred.values())
    rendered = mod.render_markdown(report)
    for row in deferred.values():
        expected = (
            f"| linked detail (not additive) | {row['name']} | "
            f"{row['fleet_quantity']} if selected | not independently counted | "
            "HOLD SUBASSEMBLY DECISION |"
        )
        assert expected in rendered
    assert "REVIEWED DECISION, CHECK DISPOSITION | Linked parent amg8833" not in rendered
    assert "REVIEWED DECISION, CHECK DISPOSITION | Linked parent nfc_game_props" not in rendered


def test_entire_shopping_csv_and_two_lists_match_authoritative_source():
    import csv
    import io
    import json
    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    report = mod.generate(plan)
    root = mod.PLAN.parents[2]
    expected_csv = mod.render_csv(report)
    expected_md = mod.render_markdown(report)
    assert (root / "docs/hardware/fleet-components.csv").read_text(
        encoding="utf-8"
    ) == expected_csv, "Do not edit fleet CSV independently of full feature plan"
    assert (root / "docs/hardware/complete-shopping-checklist.md").read_text(
        encoding="utf-8"
    ) == expected_md, "Do not edit shopping lists independently of plan"
    rows = list(csv.DictReader(io.StringIO(expected_csv)))
    assert len(rows) == 49
    assert {r["scope"] for r in rows} == {"pet or dock", "shared station"}
    assert all(row["purchase_approved"] == "NO" for row in rows)
    assert not any(
        "VL53L4CD" in row["component"] or "VL6180X" in row["component"]
        for row in rows
    )
    assert expected_md.count("## 1. Owned or ordered") == 1
    assert expected_md.count("## 2. Remaining components") == 1


@pytest.mark.parametrize("where,key", [
    ("parts", "estimated_owned_total"),
    ("parts", "ordered_unreceived_total"),
    ("room", "reported_owned_total"),
    ("room", "estimated_owned_total"),
    ("room", "ordered_unreceived_total"),
])
def test_fake_or_overcounted_reported_stock_cannot_erase_purchase_quantity(
    where, key
):
    plan = fixture()
    if where == "parts":
        target = plan["parts"][0]
        target[key] = True
    else:
        target = plan["room_pod"]["modules"][0]
        target[key] = True
    with pytest.raises(ValueError, match="nonnegative integer"):
        mod.generate(plan)
    if where == "parts":
        target[key] = 100
    else:
        target[key] = 3
    with pytest.raises(ValueError, match="exceeds"):
        mod.generate(plan)


def test_room_station_power_reference_cannot_disappear_from_buying_ledger():
    plan = fixture()
    del plan["room_pod"]["power_reference"]
    with pytest.raises(ValueError, match="room station power reference"):
        mod.generate(plan)


def test_room_station_power_reference_requires_every_powered_role():
    plan = fixture()
    del plan["room_pod"]["power_reference"]["ld2410c"]
    with pytest.raises(ValueError, match="room station power role: ld2410c"):
        mod.generate(plan)


@pytest.mark.parametrize("stock_key,output_key", [
    ("reported_owned_total", "reported_owned_not_verified"),
    ("ordered_unreceived_total", "ordered_unreceived_not_verified"),
])
def test_room_station_owned_or_ordered_stock_is_not_double_counted(
    stock_key, output_key
):
    plan = fixture()
    plan["room_pod"]["modules"][0][stock_key] = 1
    report = mod.generate(plan)
    room = report["room_pod"][0]
    assert room[output_key] == 1
    assert room["remaining_if_reported_stock_works"] == 0
    assert room["power_reference"]["exact_carrier_current_qualified"] is False

    projected = mod.first_robot_projection(report)
    room_role = next(
        row for row in projected["roles"]
        if row["scope"] == "shared station" and row["id"] == "scd40"
    )
    assert room_role[output_key] == 1
    assert room_role["conditional_remaining"] == 0
    assert room_role["power_reference"] == room["power_reference"]


def test_common_chip_reference_does_not_force_premium_breakout_purchase():
    """Selected IC/source is distinct from an expensive branded carrier."""
    for part_id, chip in (("i2c_mux", "TCA9548A"),
                          ("mcp23017", "MCP23017"),
                          ("amp", "MAX98357A")):
        assert mod.SOURCE_REFERENCES[part_id][0:2] == ("Generic", chip)
        register = (mod.PLAN.parent / "2026-11-16-five-pet-purchase-register.md").read_text()
        row = next(line for line in register.splitlines()
                   if line.startswith("| " + chr(96) + part_id + chr(96) + " |"))
        assert "Unquoted" in row
        assert "HOLD EXACT GENERIC PCB" in row

def test_extra_register_rows_are_known_alternatives_not_hidden_purchases():
    """Fourteen manual alternatives must map to machine-counted roles."""
    import json
    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    robot = {item["id"] for item in plan["parts"]}
    room = {item["id"] for item in plan["room_pod"]["modules"]}
    # One purchase row may describe a subpart of one counted assembly.
    role = {
        "N20 100:1 MP 6V motors": "stepper",
        "DRV8833 dual H bridge": "uln2003",
        "BQ24075 power-path source, NO second SoC gauge": "cap_power",
        "5V switching regulator": "cap_power",
        "Protected NTC 1S battery pack": "cap_power",
        "Independent 5V dock adapter": "dock_fixture",
        "Dock IR LED transistor/resistor driver channel": "dock_ir_emitter_channels",
        "Shared room controller": "room_controller",
        "True room CO2 sensor": "scd40",
        "Room gas/environment sensor": "bme688",
        "Room presence radar": "ld2410c",
        "Room thermal 8x8 array": "amg8833",
        "Required shared-station capacitive soil probe": "soil_probe",
        "Optional NFC toy stickers": "nfc_game_props",
    }
    register = (mod.PLAN.parent / "2026-11-16-five-pet-purchase-register.md").read_text()
    sub = register.split("## Explicit drivetrain, 1S power path and one shared station add-ons", 1)[1]
    sub = sub.split("## Price and source-first purchase overrides", 1)[0]
    # The same section also documents source owners in a different table.
    # Those are not additional order lines or duplicate components.
    sub = sub.split("## Actual source owner for every linked assembly detail", 1)[0]
    rows = {}
    for line in sub.splitlines():
        if not line.startswith("| ") or line.startswith("| Item ") or line.startswith("|---"):
            continue
        fields = [v.strip() for v in line.strip().strip("|").split("|")]
        if len(fields) != 7 or fields[0] in rows:
            raise AssertionError("Invalid or duplicate alternative: " + line)
        rows[fields[0]] = fields
    assert set(rows) == set(role), "New alternatives require source-role review"
    assert set(role.values()) <= robot | room
    # Fourteen subcomponent rows must have exact physical quantities. A
    # comparison table must not accidentally multiply ONE room station by
    # five pets or turn a half-pair driver into ten unnecessary purchases.
    expected = {
        "N20 100:1 MP 6V motors": (2, 10),
        "DRV8833 dual H bridge": (1, 5),
        "BQ24075 power-path source, NO second SoC gauge": (1, 5),
        "5V switching regulator": (1, 5),
        "Protected NTC 1S battery pack": (1, 5),
        "Independent 5V dock adapter": (1, 5),
        "Dock IR LED transistor/resistor driver channel": (2, 10),
        "Shared room controller": (1, 1),
        "True room CO2 sensor": (1, 1),
        "Room gas/environment sensor": (1, 1),
        "Room presence radar": (1, 1),
        "Room thermal 8x8 array": (1, 1),
        "Required shared-station capacitive soil probe": (1, 1),
        "Optional NFC toy stickers": (10, 10),
    }
    assert set(expected) == set(role)
    for name, values in rows.items():
        if name == "Room thermal 8x8 array":
            assert values[2:4] == ["1 if later selected", "1 visible option"]
            assert values[5] == "0"
            assert "CONDITIONAL OPTIONAL, NOT SELECTED" in values[6]
            actual = (1, 1)
        else:
            actual = tuple(int(v) for v in values[2:4])
        assert actual == expected[name], (
            f"{name}: subcomponent quantities {actual} do not match "
            f"the one robot or one shared station role {expected[name]}"
        )
        assert int(values[5]) >= 0
        assert int(values[5]) <= actual[1], name
    assert rows["N20 100:1 MP 6V motors"][5] == "0"
    assert rows["DRV8833 dual H bridge"][5] == "0"
    assert rows["BQ24075 power-path source, NO second SoC gauge"][5] == "0"
    assert "Reuse reportedly owned spare DRV8833" in rows["DRV8833 dual H bridge"][6]



def test_dock_uses_generic_nano_not_brand_premium():
    """Dock beacon must match the existing Arduino Nano firmware target."""
    register = (mod.PLAN.parent / "2026-11-16-five-pet-purchase-register.md").read_text()
    row = next(line for line in register.splitlines()
               if line.startswith("| " + chr(96) + "dock_ir_beacon_controller" +
                                  chr(96) + " |"))
    assert "Generic classic Arduino Nano" in row
    assert "Seeeduino Nano" not in row
    assert "Unquoted" in row
    firmware = (mod.PLAN.parents[2] / "code/firmware/dock/platformio.ini").read_text()
    assert "board = nanoatmega328" in firmware
    assert "Arduino-IRremote.git#v4.7.1" in firmware


def test_current_high_markup_sensor_rows_are_generic_and_unapproved():
    """Brand premiums are not our default cart just because their IC works."""
    data = (mod.PLAN.parent / "2026-11-16-five-pet-purchase-register.md").read_text()
    for part_id in ("cap1188", "fsr", "ads1115", "as5600"):
        row = next(line for line in data.splitlines()
                   if line.startswith("| " + chr(96) + part_id + chr(96) + " |"))
        assert "generic" in row.lower(), part_id
        assert "HOLD CHEAP GENERIC EXACT CARRIER" in row, part_id
        assert "Unquoted" in row, part_id
        fields = [x.strip() for x in row.strip().strip("|").split("|")]
        assert fields[8] == "0", part_id


def test_full_feature_scope_cannot_be_deleted_for_release():
    """Simulated receipts can release a COMPLETE plan, not a reduced cart.

    These are fabricated test fixtures, not electrical or physical proof.
    """
    import copy
    import json

    selected = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    selected["qualified_assumptions"] = True
    selected["physical_trial_count"] = 1
    selected["prices_complete"] = True
    receipt = {"result": "pass", "evidence_url": "https://example.org/simulated",
               "tested_on": "simulated", "reviewer": "fixture"}
    passed = {"vendor": "generic", "sku": "simulated", "pcb_revision": "1",
              **{gate: receipt for gate in mod.PART_GATES}}

    def evidence_for(plan):
        return {
            "parts": {
                part["id"]: {
                    **dict(passed),
                    **(dict(zip(("vendor", "sku"),
                                mod.FIXED_SOURCE_SKUS[part["id"]], strict=True))
                       if part["id"] in mod.FIXED_SOURCE_SKUS else {}),
                }
                for part in plan["parts"]
            },
            "room_pod": {item["id"]: dict(passed)
                         for item in plan["room_pod"]["modules"]},
            "system": {gate: receipt for gate in mod.SYSTEM_GATES},
            "supplemental_decisions": {
                ident: {
                    "parent_role": parent, "fleet_quantity": count,
                    "disposition": ("rejected_in_favor_of_qualified_alternative"
                                    if ident in ("n20_motor_candidate", "drv8833_driver_candidate")
                                    else "selected"),
                    "resolved_item": "simulated selected subpart",
                    "replacement_sku": "qualified legacy stepper assembly",
                    "alternative_or_parent_receipt": receipt,
                    "decision_receipt": receipt, **dict(passed),
                }
                for ident, (parent, count)
                in mod.SUPPLEMENTAL_DECISIONS.items()
                # Explicitly deferred optional thermal and NFC parts must
                # not appear as selected receipts in an otherwise complete
                # synthetic cart. The generator preserves both decisions.
                if ident not in ("room_amg8833", "room_nfc_game_tokens")
            },
        }

    synthetic_released = mod.generate(selected, evidence_for(selected))
    assert synthetic_released["order_released"]
    # The single-unit projection was previously permanently HOLD even when
    # all physical source receipts were synthetically present. Reuse the
    # original full evidence contract rather than inventing a second one.
    one = mod.first_robot_projection(synthetic_released)
    assert one["purchase_approved"] is True
    assert one["motor_variant"] == "stepper"
    assert "APPROVED WITH VERIFIED RECEIPTS" in (
        mod.render_first_robot_markdown(synthetic_released)
    )
    # A first complete unit MUST be qualifiable before the other four
    # exist. Synthetic receipts verify logic only and are never buy proof.
    single_evidence = evidence_for(selected)
    single_evidence["system"].pop("five_robot_integration")
    single_evidence["system"].pop(
        "room_pod_usb_serial_and_five_pet_observers"
    )
    single_evidence["system"][mod.FIRST_ROBOT_ROOM_GATE] = receipt
    first_only = mod.generate(selected, single_evidence)
    assert not first_only["order_released"]  # Fleet still unqualified.
    assert "five_robot_integration" in first_only["missing_system_evidence"]
    assert first_only["missing_first_robot_system_evidence"] == []
    assert mod.first_robot_projection(first_only)["purchase_approved"] is True

    # Neither a missing first-unit room station trial nor a missing shared
    # loaded stopping trial may slip through the independent release path.
    missing_observer = copy.deepcopy(single_evidence)
    missing_observer["system"].pop(mod.FIRST_ROBOT_ROOM_GATE)
    first_missing_observer = mod.generate(selected, missing_observer)
    assert mod.FIRST_ROBOT_ROOM_GATE in first_missing_observer[
        "missing_first_robot_system_evidence"]
    assert not mod.first_robot_projection(first_missing_observer)[
        "purchase_approved"]
    missing_stopping = copy.deepcopy(single_evidence)
    missing_stopping["system"].pop("loaded_drive_and_stopping")
    first_missing_stopping = mod.generate(selected, missing_stopping)
    assert "loaded_drive_and_stopping" in first_missing_stopping[
        "missing_first_robot_system_evidence"]
    assert not mod.first_robot_projection(first_missing_stopping)[
        "purchase_approved"]

    # WARNING: All the above receipts are TEST DATA, not an actual buy permit.
    attempts = []
    without_touch = copy.deepcopy(selected)
    without_touch["parts"] = [part for part in without_touch["parts"]
                              if part["id"] != "cap1188"]
    attempts.append((without_touch, "pet:cap1188"))

    fewer_cliffs = copy.deepcopy(selected)
    next(part for part in fewer_cliffs["parts"]
         if part["id"] == "cliff_obstacle")["per_robot"] = 7
    attempts.append((fewer_cliffs, "pet:cliff_obstacle"))

    without_station = copy.deepcopy(selected)
    without_station["room_pod"]["modules"] = [
        item for item in without_station["room_pod"]["modules"]
        if item["id"] != "room_controller"
    ]
    attempts.append((without_station, "room:room_controller"))

    fewer_game_tokens = copy.deepcopy(selected)
    next(item for item in fewer_game_tokens["room_pod"]["modules"]
         if item["id"] == "nfc_game_props")["quantity_per_room"] = 9
    attempts.append((fewer_game_tokens, "room:nfc_game_props"))

    for plan, expected in attempts:
        report = mod.generate(plan, evidence_for(plan))
        assert not report["order_released"]
        assert any(expected in gate for gate in report["missing_system_evidence"])


def test_all_fourteen_addon_quantities_match_one_fleet():
    """No motor, battery, dock, or shared-station add-on can drift in prose.

    These fourteen are candidate subparts or alternatives to the forty-nine
    machine-counted parent roles, not fourteen automatically approved purchases.
    The quantities are fixed here until the design is explicitly reviewed.
    """
    register = (mod.PLAN.parent / "2026-11-16-five-pet-purchase-register.md").read_text(
        encoding="utf-8")
    sub = register.split(
        "## Explicit drivetrain, 1S power path and one shared station add-ons", 1
    )[1].split("## Price and source-first purchase overrides", 1)[0]
    # The adjacent three-column source ownership table is not another
    # purchase table. The 14 physical alternatives must retain seven columns.
    sub = sub.split(
        "## Actual source owner for every linked assembly detail", 1
    )[0]
    expected = {
        "N20 100:1 MP 6V motors": (2, 10),
        "DRV8833 dual H bridge": (1, 5),
        "BQ24075 power-path source, NO second SoC gauge": (1, 5),
        "5V switching regulator": (1, 5),
        "Protected NTC 1S battery pack": (1, 5),
        "Independent 5V dock adapter": (1, 5),
        "Dock IR LED transistor/resistor driver channel": (2, 10),
        "Shared room controller": (1, 1),
        "True room CO2 sensor": (1, 1),
        "Room gas/environment sensor": (1, 1),
        "Room presence radar": (1, 1),
        "Room thermal 8x8 array": (1, 1),
        "Required shared-station capacitive soil probe": (1, 1),
        "Optional NFC toy stickers": (10, 10),
    }
    observed = {}
    for line in sub.splitlines():
        if not line.startswith("| ") or line.startswith(("| Item ", "|---")):
            continue
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        assert len(cells) == 7, line
        assert cells[0] not in observed, cells[0]
        if cells[0] == "Room thermal 8x8 array":
            assert cells[2:4] == ["1 if later selected", "1 visible option"]
            assert cells[5] == "0"
            assert "CONDITIONAL OPTIONAL, NOT SELECTED" in cells[6]
            observed[cells[0]] = (1, 1)
        else:
            observed[cells[0]] = (int(cells[2]), int(cells[3]))
        # A quoted source or candidate must never masquerade as approval.
        assert cells[6], cells[0]
    assert observed == expected, (
        "A hidden or miscounted motor, protected cell, charger, dock driver, "
        "or room station component would change the real shopping list"
    )


def test_motor_selection_requires_both_independent_qualified_decisions():
    # Frozen 28BYJ48 accounting rows are NOT positive evidence that a
    # physically qualified stepper drivetrain has been selected.
    import json
    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    undecided = mod.generate(plan)
    assert undecided["physical_motor_variant_in_cart"] == "unresolved"
    assert not undecided["order_released"]
    assert "motor_driver_variant_mismatch" in undecided["missing_system_evidence"]
    assert all(
        not row.get("excluded_from_order_as_alternative", False)
        for row in undecided["robots"]
        if row["id"] in ("stepper", "uln2003")
    )

    # Even selecting the new DC motor with a valid receipt cannot imply
    # a complete motor/driver pair while the actual driver is undecided.
    receipt = {"result": "pass", "evidence_url": "https://example.org/test-only",
               "tested_on": "synthetic", "reviewer": "test"}
    evidence = {"supplemental_decisions": {
        "n20_motor_candidate": {
            "parent_role": "stepper", "fleet_quantity": 10,
            "disposition": "selected", "resolved_item": "N20",
            "decision_receipt": receipt, "vendor": "generic", "sku": "N20",
            "pcb_revision": "1",
            **{gate: receipt for gate in mod.PART_GATES},
        }
    }}
    partial = mod.generate(plan, evidence)
    assert partial["physical_motor_variant_in_cart"] == "unresolved"
    assert not partial["order_released"]


def test_supplemental_decisions_reject_unresolved_real_subparts():
    """Selected linked hardware needs receipts; deferred thermal stays visible."""
    import copy
    import json

    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    plan["qualified_assumptions"] = True
    plan["prices_complete"] = True
    plan["physical_trial_count"] = 1
    receipt = {"result": "pass", "evidence_url": "https://example.org/fake",
               "tested_on": "test-only", "reviewer": "fixture"}
    approved_part = {"vendor": "generic", "sku": "test-only",
                     "pcb_revision": "1",
                     **{gate: receipt for gate in mod.PART_GATES}}
    evidence = {
        "parts": {
            p["id"]: {
                **dict(approved_part),
                **(dict(zip(("vendor", "sku"), mod.FIXED_SOURCE_SKUS[p["id"]], strict=True))
                   if p["id"] in mod.FIXED_SOURCE_SKUS else {}),
            }
            for p in plan["parts"]
        },
        "room_pod": {p["id"]: dict(approved_part)
                     for p in plan["room_pod"]["modules"]},
        "system": {gate: receipt for gate in mod.SYSTEM_GATES},
        "supplemental_decisions": {
            name: {"parent_role": parent, "fleet_quantity": qty,
                   "disposition": ("rejected_in_favor_of_qualified_alternative"
                                   if name in ("n20_motor_candidate", "drv8833_driver_candidate")
                                   else "selected"),
                   "resolved_item": "synthetic subcomponent",
                   "replacement_sku": "qualified 28BYJ48 and ULN2003",
                   "alternative_or_parent_receipt": receipt,
                   "decision_receipt": receipt,
                   **dict(approved_part)}
            for name, (parent, qty) in mod.SUPPLEMENTAL_DECISIONS.items()
            if name not in ("room_amg8833", "room_nfc_game_tokens")
        },
    }
    assert len(evidence["supplemental_decisions"]) == 12
    complete = mod.generate(plan, evidence)
    assert complete["order_released"]  # test fixture only
    assert len(complete["supplemental_decisions"]) == 14
    for linked_id in ("room_amg8833", "room_nfc_game_tokens"):
        deferred = next(
            item for item in complete["supplemental_decisions"]
            if item["id"] == linked_id
        )
        assert deferred["reviewed"] is True
        assert deferred["disposition"] == "deferred_optional"
    # Even a synthetic otherwise fully approved fleet MUST NOT contain a
    # renamed cheap sensor carrier or revert to the unsafe 1W speaker.
    for name, replacement in (
        ("cliff_obstacle", "OTHER_GY530_REVISION"),
        ("speaker", "COM-26553"),
    ):
        mismatch = copy.deepcopy(evidence)
        mismatch["parts"][name]["sku"] = replacement
        result = mod.generate(plan, mismatch)
        assert not result["order_released"]
        row = next(x for x in result["robots"] if x["id"] == name)
        assert "exact_frozen_vendor_and_sku_mismatch" in row["missing_part_evidence"]
    changed_vendor = copy.deepcopy(evidence)
    changed_vendor["parts"]["cliff_obstacle"]["vendor"] = "PremiumBoardCo"
    assert not mod.generate(plan, changed_vendor)["order_released"]

    for changed_name, mutator in (
        ("protected_ntc_pack", lambda e: e["supplemental_decisions"].pop(
            "protected_ntc_pack")),
        ("dock_ir_transistor_channels", lambda e: e["supplemental_decisions"]
            ["dock_ir_transistor_channels"].update(fleet_quantity=1)),
        ("boost_5v_candidate", lambda e: e["supplemental_decisions"]
            ["boost_5v_candidate"].update(disposition="not_selected")),
        ("drv8833_driver_candidate", lambda e: e["supplemental_decisions"]
            ["drv8833_driver_candidate"].update(
                disposition="selected", vendor="Adafruit")),
    ):
        altered = copy.deepcopy(evidence)
        mutator(altered)
        actual = mod.generate(plan, altered)
        assert not actual["order_released"], changed_name
        assert any("unresolved_supplemental_part:" + changed_name in issue
                   for issue in actual["missing_system_evidence"]), changed_name

    altered = copy.deepcopy(evidence)
    altered["supplemental_decisions"]["n20_motor_candidate"].update(
        disposition="rejected_in_favor_of_qualified_alternative",
        replacement_sku="already qualified STEP backend",
        alternative_or_parent_receipt=receipt,
    )
    # A qualified STEP motor combined with a selected DRV8833 DC driver is
    # still an impossible assembly. It must never release a mixed cart.
    altered["supplemental_decisions"]["drv8833_driver_candidate"][
        "disposition"] = "selected"
    mixed = mod.generate(plan, altered)
    assert not mixed["order_released"]
    assert "motor_driver_variant_mismatch" in mixed["missing_system_evidence"]
    altered["supplemental_decisions"]["drv8833_driver_candidate"].update(
        disposition="rejected_in_favor_of_qualified_alternative",
        replacement_sku="already qualified ULN2003 STEP driver",
        alternative_or_parent_receipt=receipt,
    )
    assert mod.generate(plan, altered)["order_released"]
    altered["supplemental_decisions"]["n20_motor_candidate"].pop(
        "alternative_or_parent_receipt")
    assert not mod.generate(plan, altered)["order_released"]

    # In the opposite direction, a selected DC motor cannot be authorized
    # with a legacy ULN2003 stepper driver merely because each has a receipt.
    motor_dc_driver_step = copy.deepcopy(evidence)
    motor_dc_driver_step["supplemental_decisions"]["n20_motor_candidate"][
        "disposition"] = "selected"
    motor_dc_driver_step["supplemental_decisions"]["drv8833_driver_candidate"].update(
        disposition="rejected_in_favor_of_qualified_alternative",
        replacement_sku="already qualified ULN2003 STEP driver",
        alternative_or_parent_receipt=receipt,
    )
    opposite = mod.generate(plan, motor_dc_driver_step)
    assert not opposite["order_released"]
    assert "motor_driver_variant_mismatch" in opposite["missing_system_evidence"]


    # The original frozen 42-role baseline keeps legacy STEP entries for
    # accounting, but a genuinely selected and reviewed N20+DRV8833
    # alternative must be orderable WITHOUT charging for ten unused
    # 28BYJ48 motors and ten unused ULN2003 drivers. Former code made
    # qualified DC procurement logically impossible forever.
    both_selected = copy.deepcopy(evidence)
    for ident in ("n20_motor_candidate", "drv8833_driver_candidate"):
        both_selected["supplemental_decisions"][ident]["disposition"] = "selected"
    dc_report = mod.generate(plan, both_selected)
    assert dc_report["order_released"]  # synthetic receipt fixture only
    assert dc_report["physical_motor_variant_in_cart"] == "dc"
    legacy = [row for row in dc_report["robots"]
              if row["id"] in ("stepper", "uln2003")]
    assert len(legacy) == 2
    for row in legacy:
        assert row["excluded_from_order_as_alternative"]
        assert row["effective_selected_fleet_total"] == 0
        assert row["remaining_if_reported_stock_works"] == 0
        assert row["shopping_decision"].startswith("do_not_buy")
    assert "EXCLUDED MOTOR ALTERNATIVE, DO NOT BUY" in (
        mod.render_markdown(dc_report))
    import csv
    import io
    csv_rows = {row["part_id"]: row for row in
                csv.DictReader(io.StringIO(mod.render_csv(dc_report)))}
    for ident in ("stepper", "uln2003"):
        assert csv_rows[ident]["per_robot"] == "0"
        assert csv_rows[ident]["fleet_total"] == "0"
        assert csv_rows[ident]["remaining_if_all_reported_stock_works"] == "0"
    assert mod.generate(plan, evidence)["physical_motor_variant_in_cart"] == "stepper"

    invalid = copy.deepcopy(evidence)
    invalid["supplemental_decisions"]["ghost_charger"] = {}
    with pytest.raises(ValueError, match="Unknown supplemental"):
        mod.generate(plan, invalid)


def test_linked_subassembly_plan_is_not_deletable():
    """The source JSON must carry all 14 details, not only the side register."""
    import copy
    import json

    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    linked = {item["id"]: item for item in plan["linked_subassemblies"]}
    assert set(linked) == set(mod.SUPPLEMENTAL_DECISIONS)
    assert len(linked) == 14
    assert linked["room_amg8833"]["disposition"] == "deferred_optional"
    assert linked["room_nfc_game_tokens"]["disposition"] == "deferred_optional"
    for ident, (parent, count) in mod.SUPPLEMENTAL_DECISIONS.items():
        assert linked[ident]["parent_role"] == parent
        assert linked[ident]["fleet_quantity"] == count
        assert linked[ident]["name"].strip()

    removed = copy.deepcopy(plan)
    removed["linked_subassemblies"] = [
        item for item in removed["linked_subassemblies"]
        if item["id"] != "protected_ntc_pack"
    ]
    report = mod.generate(removed)
    assert "missing_or_reduced_linked_subassembly:protected_ntc_pack" in (
        report["missing_system_evidence"])

    smaller = copy.deepcopy(plan)
    next(item for item in smaller["linked_subassemblies"]
         if item["id"] == "dock_ir_transistor_channels")["fleet_quantity"] = 1
    assert "missing_or_reduced_linked_subassembly:dock_ir_transistor_channels" in (
        mod.generate(smaller)["missing_system_evidence"])

    phantom = copy.deepcopy(plan)
    phantom["linked_subassemblies"].append({
        "id": "new_undocumented_charger", "parent_role": "cap_power",
        "fleet_quantity": 5, "name": "mystery charger",
    })
    with pytest.raises(ValueError, match="Unexpected linked subassembly"):
        mod.generate(phantom)

    duplicate = copy.deepcopy(plan)
    duplicate["linked_subassemblies"].append(
        copy.deepcopy(duplicate["linked_subassemblies"][0]))
    with pytest.raises(ValueError, match="Duplicate linked subassembly"):
        mod.generate(duplicate)


def test_noninteger_physical_trial_counts_cannot_release_cart():
    """A truthy bool or negative count is not evidence of any prototype trial."""
    for invalid in (True, False, -1, 0, 1.0, "tested", None, {}):
        p = fixture()
        p["physical_trial_count"] = invalid
        p["qualified_assumptions"] = True
        p["prices_complete"] = True
        result = mod.generate(p)
        assert "plan_unqualified_or_price_incomplete" in (
            result["missing_system_evidence"]), invalid
    p = fixture()
    p["physical_trial_count"] = 1
    p["qualified_assumptions"] = True
    p["prices_complete"] = True
    assert "plan_unqualified_or_price_incomplete" not in (
        mod.generate(p)["missing_system_evidence"])


def test_critical_physical_evidence_gates_are_independent():
    """One generic checklist receipt cannot stand in for safety proof."""
    system = set(mod.SYSTEM_GATES)
    parts = set(mod.PART_GATES)
    assert {
        "cliff_sensor_mount_height_and_stopping_geometry",
        "four_floor_sensor_reverse_pivot_arc_sweep",
        "sixteen_mux_channel_400khz_pullups_rise_and_sink_trials",
        "battery_pack_ntc_to_charger_ts_thermal_fault_trial",
        "battery_pack_actual_length_and_enclosure_clearance",
        "amplifier_speaker_power_limit_and_thermal_trial",
        "dock_contacts_recess_reverse_polarity_and_current_limit",
        "charger_out_full_voltage_range_to_fixed_5v_rail_physical_trial",
        "haptic_hc123_one_shot_stuck_i2c_and_motor_thermal_trial",
    } <= system
    assert "received_quantity_revision_and_owned_stock_inspection" in parts
    p = fixture()
    result = mod.generate(p)
    for gate in (
        "cliff_sensor_mount_height_and_stopping_geometry",
        "four_floor_sensor_reverse_pivot_arc_sweep",
        "sixteen_mux_channel_400khz_pullups_rise_and_sink_trials",
        "battery_pack_ntc_to_charger_ts_thermal_fault_trial",
        "battery_pack_actual_length_and_enclosure_clearance",
        "amplifier_speaker_power_limit_and_thermal_trial",
        "dock_contacts_recess_reverse_polarity_and_current_limit",
    ):
        assert gate in result["missing_system_evidence"]


def test_premium_or_malformed_eight_range_mux_cannot_be_approved():
    """No expensive or wrong-address chip can be hidden behind a cheap cart row."""
    import copy
    import json

    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    assert "invalid_selected_cheap_range_mux_layout" not in (
        mod.generate(plan)["missing_system_evidence"])
    mutants = []
    wrong_chip = copy.deepcopy(plan)
    wrong_chip["bus"]["mux_ranges"]["channels"][0]["devices"][0]["name"] = "VL53L4CD"
    mutants.append(wrong_chip)
    wrong_addr = copy.deepcopy(plan)
    wrong_addr["bus"]["mux_ranges"]["channels"][7]["devices"][0]["address"] = 0x52
    mutants.append(wrong_addr)
    dropped_lane = copy.deepcopy(plan)
    dropped_lane["bus"]["mux_ranges"]["channels"].pop()
    mutants.append(dropped_lane)
    duplicate_lane = copy.deepcopy(plan)
    duplicate_lane["bus"]["mux_ranges"]["channels"][1]["channel"] = 0
    mutants.append(duplicate_lane)
    wrong_mux = copy.deepcopy(plan)
    wrong_mux["bus"]["mux_ranges"]["address"] = 0x71
    mutants.append(wrong_mux)
    floating_address = copy.deepcopy(plan)
    floating_address["bus"]["mux_ranges"]["address"] = 112.0
    mutants.append(floating_address)
    for mutant in mutants:
        actual = mod.generate(mutant)
        assert "invalid_selected_cheap_range_mux_layout" in (
            actual["missing_system_evidence"])
        assert not actual["order_released"]


def test_inexpensive_gy530_power_and_mux_levels_are_fleet_purchase_invariant():
    """Never authorize 5V I2C/cheap sensor VIN on an ESP32 3.3V bus."""
    import copy
    import json

    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    good = mod.generate(plan)
    assert "unsafe_gy530_voltage_or_pin_contract" not in (
        good["missing_system_evidence"])
    mutations = (
        ("module_vin_v", 5),
        ("module_vin_v", True),
        ("upstream_pullup_target_v", 5),
        ("downstream_pullup_target_v", 5),
        ("tca9548a_vcc_v", 5),
        ("modules_per_robot", 7),
        ("selected_chip", "VL53L4CD"),
    )
    for field, value in mutations:
        candidate = copy.deepcopy(plan)
        candidate["range_breakout_power_contract"][field] = value
        report = mod.generate(candidate)
        assert "unsafe_gy530_voltage_or_pin_contract" in (
            report["missing_system_evidence"]), field
        assert not report["order_released"]


def test_current_speaker_sku_and_five_volt_amplifier_cannot_drift():
    """Old round 1W speaker and contradictory VDD must never pass the cart."""
    import copy
    import json

    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    assert "unresolved_current_two_watt_speaker_contract" not in (
        mod.generate(plan)["missing_system_evidence"])
    mutations = []
    old_round = copy.deepcopy(plan)
    next(x for x in old_round["parts"] if x["id"] == "speaker")[
        "name"] = "8 ohm 1 watt 20 mm round speaker"
    mutations.append(old_round)
    for field, value in (
        ("amplifier_vdd_v", 3.3),
        ("amplifier_vdd_v", True),
        ("speaker_nominal_rating_w", 1),
        ("speaker_nominal_impedance_ohm", 4),
        ("amplifier_ic", "unreviewed"),
        ("physical_release", ""),
    ):
        altered = copy.deepcopy(plan)
        altered["audio_output_power_contract"][field] = value
        mutations.append(altered)
    for altered in mutations:
        report = mod.generate(altered)
        assert "unresolved_current_two_watt_speaker_contract" in (
            report["missing_system_evidence"])
        assert not report["order_released"]


def test_one_robot_cart_projects_all_linked_quantities_without_order_approval():
    import json
    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    fleet = mod.generate(plan)
    one = mod.first_robot_projection(fleet)
    assert (one["robot_count"], one["dock_count"],
            one["shared_station_count"]) == (1, 1, 1)
    assert one["parent_role_count"] == 49
    assert one["linked_decision_count"] == 14
    assert one["motor_variant"] == "unresolved"
    assert one["purchase_approved"] is False
    assert mod.FIRST_ROBOT_ROOM_GATE in one["missing_first_robot_system_evidence"]
    assert "five_robot_integration" not in one[
        "missing_first_robot_system_evidence"]
    pet = {r["id"]: r for r in one["roles"] if r["scope"] == "pet or dock"}
    room = {r["id"]: r for r in one["roles"] if r["scope"] == "shared station"}
    assert pet["cliff_obstacle"]["prototype_target"] == 8
    assert pet["cliff_obstacle"]["conditional_remaining"] == 8
    assert pet["i2c_mux"]["prototype_target"] == 2
    assert pet["xiao_sense"]["prototype_target"] == 1
    # One ordered head is NOT delivered stock and must not be reordered
    # for the first unit while its actual arrival is checked.
    assert pet["xiao_sense"]["ordered_unreceived_not_verified"] == 1
    assert pet["xiao_sense"]["conditional_remaining"] == 0
    # Crucial motor decision: old available steppers are NOT automatically
    # selected and no new missing stepper motors appear as purchases.
    assert pet["stepper"]["prototype_target"] == 0
    assert pet["uln2003"]["prototype_target"] == 0
    # A motor decision cannot erase actual reported stock from owned list.
    assert pet["stepper"]["fleet_reported_owned_not_verified"] == 5
    assert pet["uln2003"]["fleet_reported_owned_not_verified"] == 5
    assert pet["stepper"]["reported_owned_not_verified"] == 0
    assert pet["stepper"]["decision"] == "HOLD MOTOR CHOICE"
    assert room["nfc_game_props"]["prototype_target"] == 0
    assert room["nfc_game_props"]["conditional_remaining"] == 0
    assert room["nfc_game_props"]["decision"] == "OPTIONAL NOT SELECTED, DO NOT BUY"
    linked = {item["id"]: item for item in one["linked_decisions"]}
    assert linked["n20_motor_candidate"]["conditional_one_robot_quantity"] == 2
    assert linked["drv8833_driver_candidate"]["conditional_one_robot_quantity"] == 1
    assert linked["protected_ntc_pack"]["conditional_one_robot_quantity"] == 1
    assert linked["dock_ir_transistor_channels"]["conditional_one_robot_quantity"] == 2
    assert linked["room_nfc_game_tokens"]["conditional_one_robot_quantity"] == 10
    assert not any(d["additive_purchase_authorized"] for d in one["linked_decisions"])
    text = mod.render_first_robot_markdown(fleet)
    assert text.count("## 1.") == 1
    assert text.count("## 2.") == 1
    assert "PROTOTYPE BUYING STATUS: HOLD" in text
    assert "VL53L0X" in text
    assert "First-unit physical and source evidence still required" in text
    assert mod.FIRST_ROBOT_ROOM_GATE in text
    assert "five_robot_integration" not in text


def test_first_robot_projection_rejects_wrong_scope_and_variant():
    import copy
    import json
    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    report = mod.generate(plan)
    different_fleet = copy.deepcopy(report)
    different_fleet["fleet_robots"] = 4
    with pytest.raises(ValueError):
        mod.first_robot_projection(different_fleet)
    unknown = copy.deepcopy(report)
    unknown["physical_motor_variant_in_cart"] = "fantasy"
    with pytest.raises(ValueError):
        mod.first_robot_projection(unknown)




def test_first_robot_bench_samples_do_not_require_completed_robot_first():
    """A sample procurement gate breaks the prototype acceptance deadlock."""
    import json
    report = mod.generate(json.loads(mod.PLAN.read_text(encoding="utf-8")))
    pilot = mod.first_robot_pilot_samples(report)
    rows = {item["id"]: item for item in pilot["roles"]}
    assert len(rows) == 49
    assert pilot["pilot_sample_count"] == 17
    assert pilot["pilot_historical_quoted_subtotal_usd"] == 40.41
    assert not pilot["whole_first_robot_purchase_approved"]
    assert not pilot["lithium_charging_or_motor_motion_authorized"]
    assert not pilot["actual_current_landed_cost_verified"]
    assert rows["cliff_obstacle"]["pilot_sample_quantity"] == 1
    assert rows["cliff_obstacle"]["source_sku"] == "SEN-19-006"
    assert rows["cliff_obstacle"]["historical_unit_quote_usd"] == 1.44
    assert rows["speaker"]["source_sku"] == "CS20-02P110-04-1X"
    # A bare TSAL6200 LED is not a safe functional dock emitter channel.
    ir = rows["dock_ir_emitter_channels"]
    assert ir["pilot_sample_quantity"] == 2
    assert ir["source_sku"] == "TSAL6200"
    assert ir["sample_is_complete_functional_channel"] is False
    assert ir["missing_for_functional_channel"] == [
        "rated_transistor_driver", "current_limiting",
        "38khz_modulation_and_wiring_validation",
    ]
    assert rows["cliff_obstacle"]["missing_for_functional_channel"] == []
    assert rows["i2c_mux"]["pilot_sample_quantity"] == 2
    assert rows["i2c_mux"]["source_sku"] == "COM-05-067"
    assert rows["i2c_mux"]["historical_unit_quote_usd"] == 0.47
    assert rows["cap1188"]["source_sku"] == "SEN-25-020"
    assert rows["apds9960"]["source_sku"] == "SEN-24-027"
    assert rows["ads1115"]["historical_unit_quote_usd"] == 1.50
    assert rows["mcp23017"]["source_sku"] == "COM-05-093"
    assert rows["amp"]["pilot_sample_quantity"] == 1
    assert rows["amp"]["source_sku"] == "DFR0954"
    assert rows["amp"]["historical_unit_quote_usd"] == 4.90
    assert rows["bumper"]["pilot_sample_quantity"] == 2
    assert rows["bumper"]["source_sku"] == "D2F-01L3"
    assert rows["bumper"]["historical_unit_quote_usd"] == 2.48


    assert rows["xiao_sense"]["pilot_sample_quantity"] == 0
    assert rows["xiao_sense"]["pilot_action"] == "VERIFY_OWNED_OR_INCOMING_STOCK"
    for ident in (
        "cap_power", "ina226", "max17048", "switch_power",
        "dock_contacts", "assembly", "as5600",
    ):
        assert rows[ident]["pilot_sample_quantity"] == 0
        assert rows[ident]["pilot_action"] == "HOLD_POWER_MOTION_OR_FIT_SELECTION"
    assert "protected_ntc_pack" in pilot["unresolved_linked_decisions"]
    text = mod.render_first_robot_pilot_samples(report)
    assert text.count("## 1.") == 1
    assert text.count("## 2.") == 1
    assert "SEN-19-006" in text
    assert "40.41" in text
    assert "not a physically qualified robot" in text


def test_pilot_sample_cannot_inherit_approved_sku_from_replaced_sensor():
    """A source-locked sample is never an automatic chip substitution permit."""
    import copy
    import json
    bad = copy.deepcopy(json.loads(mod.PLAN.read_text(encoding="utf-8")))
    next(x for x in bad["parts"] if x["id"] == "cliff_obstacle")[
        "name"
    ] = "VL53L0X unreviewed replacement PCB"
    pilot = mod.first_robot_pilot_samples(mod.generate(bad))
    range_row = next(x for x in pilot["roles"] if x["id"] == "cliff_obstacle")
    assert range_row["pilot_action"] == "HOLD_CHANGED_PART_IDENTITY"
    assert range_row["pilot_sample_quantity"] == 0
    assert range_row["source_url"] is None
    assert not pilot["whole_first_robot_purchase_approved"]



def test_pilot_supplier_rows_never_mutate_canonical_fleet_source_references():
    """Keep unit test samples distinct from production source references.

    A mistaken insertion of a 6-field candidate into SOURCE_REFERENCES
    rewrites every generated five-robot CSV source field. The first robot
    pilot cart must not invalidate the original full fleet register.
    """
    assert set(mod.SOURCE_REFERENCES) == {
        "cliff_obstacle", "i2c_mux", "mcp23017", "amp", "speaker"
    }
    assert all(len(candidate) == 3
               for candidate in mod.SOURCE_REFERENCES.values())
    assert all(len(candidate) == 6
               for candidate in mod.PILOT_SAMPLE_PRODUCTS.values())
    assert all(isinstance(candidate[4], int) and candidate[4] > 0
               for candidate in mod.PILOT_SAMPLE_PRODUCTS.values())
    assert all(candidate[5] is None or isinstance(candidate[5], float)
               for candidate in mod.PILOT_SAMPLE_PRODUCTS.values())
    assert mod.SOURCE_REFERENCES["i2c_mux"][0] == "Generic"
    assert mod.SOURCE_REFERENCES["mcp23017"][0] == "Generic"
    assert mod.PILOT_SAMPLE_PRODUCTS["i2c_mux"][2] == "COM-05-067"


def test_pilot_supplier_cart_exact_skus_prices_and_incomplete_channels():
    import json
    from collections import Counter

    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    cart = mod.pilot_supplier_cart(mod.generate(plan))
    assert cart["exact_sku_count"] == 13
    assert cart["component_quantity"] == 17
    assert cart["historical_priced_partial_subtotal_usd"] == 40.41
    assert not cart["landed_total_verified"]
    assert not cart["complete_robot_purchase_approved"]
    assert not cart["lithium_charging_or_motor_motion_authorized"]
    assert cart["unpriced_skus"] == []
    assert "COM-05-067" not in cart["unpriced_skus"]
    assert "COM-05-045" not in cart["unpriced_skus"]
    assert len(set((x["vendor"], x["sku"]) for x in cart["items"])) == 13
    assert Counter(x["vendor"] for x in cart["items"])["ElectroPeak"] == 6
    rows = {x["id"]: x for x in cart["items"]}
    assert rows["cliff_obstacle"]["quantity"] == 1
    assert rows["i2c_mux"]["quantity"] == 2
    assert rows["dock_ir_emitter_channels"]["quantity"] == 2
    assert rows["dock_ir_emitter_channels"][
        "sample_is_complete_functional_channel"] is False
    assert "rated_transistor_driver" in rows[
        "dock_ir_emitter_channels"]["missing_for_functional_channel"]
    assert "cliff_obstacle" in cart["unresolved_roles"]
    assert "i2c_mux" not in cart["unresolved_roles"]
    assert "cap_power" in cart["unresolved_roles"]
    assert "dock_contacts" in cart["unresolved_roles"]
    rendered = mod.render_pilot_supplier_cart(mod.generate(plan))
    assert "13 SKUs; 17 items." in rendered
    assert "Priced-only historical subtotal" in rendered
    assert "0 SKUs have unknown comparable USD price" in rendered
    assert "There is no verified landed total" in rendered
    assert "NOT complete driven dock channels" in rendered




def test_pilot_cart_exposes_actual_source_and_test_not_hardware_approval():
    import json

    report = mod.generate(json.loads(mod.PLAN.read_text(encoding="utf-8")))
    cart = mod.pilot_supplier_cart(report)
    assert cart["exact_sku_count"] == 13
    for item in cart["items"]:
        assert (mod.ROOT / item["implementation_source"]).is_file()
        assert (mod.ROOT / item["implementation_test"]).is_file()
        assert item["implementation_test"].startswith("code/")
        assert "/tests/" in item["implementation_test"]
        assert item["implementation_state"]
        assert item["tests_executed_on_this_checkout"] is False
    rows = {item["id"]: item for item in cart["items"]}
    assert rows["cliff_obstacle"]["implementation_source"].endswith(
        "TofBus/TofBus.cpp")
    assert rows["amp"]["implementation_source"].endswith(
        "sense_reference_codec.cc")
    # The speaker has a CAD coupon, not a compiled speaker driver. Do not
    # mislabel a physical fit reference as verified firmware.
    assert rows["speaker"]["implementation_source_is_code"] is False
    assert rows["speaker"]["implementation_state"] == "speaker_fit_reference_only"
    assert rows["dock_ir_emitter_channels"][
        "sample_is_complete_functional_channel"] is False
    rendered = mod.render_pilot_supplier_cart(report)
    assert "Engineering source" in rendered
    assert "NOT executed tests" in rendered


def test_pilot_cart_fails_closed_on_invented_implementation_owner(
        tmp_path, monkeypatch):
    import json

    report = mod.generate(json.loads(mod.PLAN.read_text(encoding="utf-8")))
    owners = json.loads((mod.ROOT / "docs/hardware/full-63-role-source-ownership.json")
                        .read_text(encoding="utf-8"))
    owners["pet_roles"]["cliff_obstacle"]["source"] = \
        "../../nonexistent/tof.cpp"
    target = tmp_path / "docs/hardware/full-63-role-source-ownership.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(owners), encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="Missing sample implementation file"):
        mod.pilot_supplier_cart(report)


def test_receipt_url_requires_real_https_host():
    """A URL scheme alone is not a real receipt address."""
    receipt = {"result": "pass", "tested_on": "bench sample",
               "reviewer": "operator", "evidence_url": ""}
    for bad in ("https://", "https:///no-host",
                "https://user@attacker.example/receipt",
                "https://example.org:0/receipt",
                "https://example.org:invalid/receipt",
                "https://example.org/space here"):
        receipt["evidence_url"] = bad
        assert not mod._receipt(receipt), bad
    receipt["evidence_url"] = "https://lab.example.org/receipt/42"
    assert mod._receipt(receipt)


def test_one_robot_power_register_excludes_duplicate_soc_board():
    """Keep a single SoC gauge choice distinct from raw INA226 current."""
    path = (Path(__file__).resolve().parents[2] /
            "docs/hardware/2026-11-16-five-pet-purchase-register.md")
    register = path.read_text(encoding="utf-8")
    bq_rows = [
        row for row in register.splitlines()
        if row.startswith("| BQ24075 power-path source, NO second SoC gauge |")
    ]
    assert len(bq_rows) == 1
    assert "SparkFun Battery Babysitter with BQ27441 is EXCLUDED" in bq_rows[0]
    gauge_rows = [
        row for row in register.splitlines()
        if row.startswith("| `max17048` |")
    ]
    assert len(gauge_rows) == 1
    assert "ONE SoC GAUGE ONLY" in gauge_rows[0]
    assert "separate INA226 is a signed current monitor" in gauge_rows[0]


def test_pilot_supplier_cart_rejects_malformed_source_url(monkeypatch):
    """An HTTPS prefix alone must not authorize a supplier cart link."""
    import json
    plan = json.loads(mod.PLAN.read_text(encoding="utf-8"))
    report = mod.generate(plan)
    original = mod.PILOT_SAMPLE_PRODUCTS["cliff_obstacle"]
    for invalid in ("https://", "https:///missing-host",
                    "https://user@vendor.example/part",
                    "https://vendor.example:invalid/part"):
        monkeypatch.setitem(mod.PILOT_SAMPLE_PRODUCTS, "cliff_obstacle",
                            (*original[:3], invalid, *original[4:]))
        with pytest.raises(ValueError, match="Missing exact supplier"):
            mod.pilot_supplier_cart(report)
    monkeypatch.setitem(mod.PILOT_SAMPLE_PRODUCTS, "cliff_obstacle", original)
    assert mod.pilot_supplier_cart(report)["exact_sku_count"] == 13

def test_public_view_hides_pure_synthetic_receipts():
    """Synthetic unit-test approvals cannot be printed as actual buying permits."""
    eligible = {
        "order_released": True,
        "missing_first_robot_system_evidence": [],
        "robots": [{"approved_for_fleet_purchase": True}],
        "room_pod": [{"approved_for_fleet_purchase": True}],
        "supplemental_decisions": [
            {"id": "linked_power", "reviewed": True, "disposition": "selected"}
        ],
    }
    visible = mod.public_purchase_view(eligible)
    assert visible["order_released"] is False
    assert all(not row["approved_for_fleet_purchase"]
               for row in (*visible["robots"], *visible["room_pod"]))
    assert "live_scoped_purchase_receipts_not_verified" in (
        visible["missing_first_robot_system_evidence"]
    )
    assert visible["supplemental_decisions"][0]["reviewed"] is False
    assert eligible["supplemental_decisions"][0]["reviewed"] is True
    assert eligible["order_released"] is True
    assert mod.public_purchase_view(
        eligible, live_receipts_verified=True
    ) is eligible


def test_regular_cli_json_never_claims_untested_receipts(monkeypatch, capsys):
    """Even supplied evidence cannot print approval without strict live audit."""
    import json
    import sys

    fake = {
        "order_released": True,
        "missing_first_robot_system_evidence": [],
        "robots": [{"approved_for_fleet_purchase": True}],
        "room_pod": [{"approved_for_fleet_purchase": True}],
    }
    monkeypatch.setattr(mod, "generate", lambda plan, evidence: fake)
    monkeypatch.setattr(mod, "cost_quote",
                        lambda report, evidence, scope: {})
    monkeypatch.setattr(sys, "argv", ["procurement_release.py", "--format", "json"])
    assert mod.main() == 0
    visible = json.loads(capsys.readouterr().out)
    assert visible["order_released"] is False
    assert visible["robots"][0]["approved_for_fleet_purchase"] is False


def test_verified_checkout_evidence_is_embedded_in_existing_shopping_lists():
    import json
    report = mod.generate(json.loads(mod.PLAN.read_text(encoding="utf-8")))
    quote = {
        "role_key": "robot:i2c_mux",
        "seller": "Example Seller",
        "sku": "MUX-REV-A",
        "pcb_revision": "A",
        "quantity_packages": 1,
        "units_per_package": 2,
        "package_price_usd": "3.25",
        "quote_reference": "checkout-2026-11-20",
        "quoted_at": "2026-11-20",
        "stock_evidence_url": "https://supplier.example/mux",
    }
    cost = {
        "scope": "first_robot",
        "calculation_complete_not_physical_approval": True,
        "payable_now_cents": 725,
        "prior_paid_orders_cents": 1250,
        "prototype_cumulative_cents": 1975,
        "remaining_under_cap_cents": 3025,
    }
    evidence = {
        "lines": [quote],
        "seller_charges": [{
            "seller": "Example Seller",
            "shipping_usd": "0.50",
            "tax_usd": "0.25",
            "duties_usd": "0.00",
            "discount_usd": "0.00",
        }],
    }
    shown_report = mod.attach_verified_checkout_evidence(report, cost, evidence)
    projected = mod.first_robot_projection(shown_report)
    assert projected["verified_checkout_cost"]["payable_now_cents"] == 725
    projected_mux = next(
        row for row in projected["roles"] if row["id"] == "i2c_mux"
    )
    assert projected_mux["verified_checkout_quotes"] == [quote]
    one = mod.render_first_robot_markdown(shown_report)
    full = mod.render_markdown(shown_report)
    for shown in (one, full):
        assert "VERIFIED CHECKOUT EVIDENCE FOR THIS RELEASE" in shown
        assert "Payable now: $7.25" in shown
        assert "Previously paid: $12.50" in shown
        assert "shipping 0.50 USD, tax 0.25 USD" in shown
        assert "Example Seller MUX-REV-A rev A" in shown
        assert "1 package(s) x 2 unit(s) at USD 3.25/package" in shown
        assert "quoted 2026-11-20" in shown
        assert "https://supplier.example/mux" in shown
    assert "Remaining under prototype $50 cap: $30.25" in one
    # The stored quote must preserve its validated role identity. It must
    # never let a different component inherit an unrelated seller receipt.
    bad = {**quote, "role_key": "station:unknown_sensor"}
    with pytest.raises(ValueError, match="unknown shopping role"):
        mod.attach_verified_checkout_evidence(
            report, cost, {**evidence, "lines": [bad]}
        )


def test_landed_cost_markdown_allocations_are_visible_and_not_checkout_prices():
    values = {
        "scope": "evaluation", "calculation_complete_not_physical_approval": True,
        "payable_now_cents": 755, "prior_paid_orders_cents": 1250,
        "prototype_cumulative_cents": 2005, "remaining_under_cap_cents": 2995,
        "material_subtotals_cents": {"robot": 223, "dock": 100, "station": 0},
        "allocated_landed_subtotals_cents": {
            "robot": 521, "dock": 234, "station": 0,
        },
        "within_prototype_cap": True, "prototype_cap_cents": 5000,
        "seller_payable_cents": {"Example": 755}, "errors": [],
    }
    shown = mod.cost_quote_markdown(values)
    assert "Robot materials: $2.23" in shown
    assert "Robot allocated landed cost: $5.21" in shown
    assert "Dock allocated landed cost: $2.34" in shown
    assert "Station allocated landed cost: $0.00" in shown
    assert "They are not individual supplier checkout prices." in shown
    values["calculation_complete_not_physical_approval"] = False
    values["allocated_landed_subtotals_cents"] = None
    shown = mod.cost_quote_markdown(values)
    assert "Allocated landed category costs: unknown (incomplete quote)" in shown
    assert "Robot allocated landed cost: $5.21" not in shown
    assert "Robot materials: unknown (incomplete quote)" in shown
    # Even synthetic inconsistent caller data must not make incomplete
    # evidence look like a confirmed supplier checkout or budget balance.
    assert "Payable now: unknown" in shown
    assert "Cumulative prototype spending: unknown" in shown
    assert "Remaining under prototype $50 cap: unknown" in shown
    assert "Partial supplier quote Example: $7.55" in shown


def test_strict_signed_quote_requires_exact_carrier_revision():
    signed = {
        "sku": "SEN-19-006", "pcb_revision": "rev-B",
        "seller": "ElectroPeak",
    }
    quote = {
        "sku": "SEN-19-006", "pcb_revision": "rev-B",
        "seller": "ElectroPeak",
    }
    assert mod.quoted_carrier_matches_signed_role(quote, signed)
    for changed in (
        {"pcb_revision": None},
        {"pcb_revision": ""},
        {"pcb_revision": "rev-A"},
        {"sku": "VL53L4CD-premium"},
        {"seller": "unknown"},
    ):
        altered = {**quote, **changed}
        assert not mod.quoted_carrier_matches_signed_role(altered, signed)

    # A distributor may sell the exact frozen carrier if the signed
    # selection did not separately freeze the retailer.
    manufacturer_signed = {
        "sku": "SEN-19-006", "pcb_revision": "rev-B",
    }
    assert mod.quoted_carrier_matches_signed_role(
        {**quote, "seller": "Distributor"}, manufacturer_signed,
    )
    assert not mod.quoted_carrier_matches_signed_role(
        {**quote, "pcb_revision": "unknown"}, manufacturer_signed,
    )
    assert not mod.quoted_carrier_matches_signed_role(None, signed)
    assert not mod.quoted_carrier_matches_signed_role(quote, None)
