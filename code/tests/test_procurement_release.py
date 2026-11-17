"""A design slot, popular part, or fabricated boolean is not a purchase approval."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/procurement_release.py"
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
        "room_pod": {"modules": [
            {"id": "scd40", "name": "SCD40", "quantity_per_room": 1}
        ]},
    }


def test_full_fleet_quantities_never_grant_purchase():
    r = mod.generate(fixture())
    assert (r["fleet_robots"], r["docks"], r["room_stations"]) == (5, 5, 1)
    d = {p["id"]: p for p in r["robots"]}
    assert d["cliff_obstacle"]["fleet_total"] == 40
    assert d["cliff_obstacle"]["reference_only"]["sku"] == "GY-530 VL53L0X"
    assert d["stepper"]["remaining_if_reported_stock_works"] == 5
    assert d["mg90s"]["remaining_if_reported_stock_works"] == 10
    assert not r["order_released"]
    assert "plan_unqualified_or_price_incomplete" in r["missing_system_evidence"]


def test_no_expensive_sensor_substitution_in_canonical_order():
    p = fixture()
    p["parts"][0]["name"] = "VL53L4CD premium carrier"
    with pytest.raises(ValueError, match="approved low-cost VL53L0X"):
        mod.generate(p)


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
    assert mod.generate(p, ev)["order_released"]
    ev["system"]["protected_1s_charger_and_dock_contacts"] = {"result": "pass"}
    assert not mod.generate(p, ev)["order_released"]



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
    assert mod.generate(p, e)["order_released"]
    e["parts"]["cliff_obstacle"]["vendor"] = "Adafruit Industries"
    r = mod.generate(p, e)
    assert not r["order_released"]
    assert "no_new_adafruit_hardware" in next(
        x for x in r["robots"] if x["id"] == "cliff_obstacle"
    )["missing_part_evidence"]
    e["parts"]["cliff_obstacle"]["vendor"] = "generic"
    e["room_pod"]["scd40"]["vendor"] = "Adafruit"
    assert not mod.generate(p, e)["order_released"]


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
    assert mod.generate(p, ev)["order_released"]
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
        if not line.startswith("| \`"):
            continue
        columns = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(columns) != 11:
            raise AssertionError("Incorrect buying register row: " + line)
        part_id = columns[0].strip("`")
        assert part_id not in selected, "Duplicate candidate component"
        selected[part_id] = columns
    assert set(selected) == set(parts), "Missing or invented selected purchasing role"
    for ident, item in parts.items():
        cells = selected[ident]
        assert int(cells[2]) == item["per_robot"], ident
        assert int(cells[3]) == 5 * item["per_robot"], ident
        assert int(cells[8]) >= 0, ident
    assert "VL53L0X" in selected["cliff_obstacle"][1]
    assert "VL53L4CD" not in register
    # An expensive comparison board is not an authorized pilot purchase.
    for ident in ("cap1188", "fsr", "ads1115", "as5600", "encoder_magnets",
                  "max17048", "ina226", "pn532", "sht41"):
        assert selected[ident][8] == "0", ident
        assert "NO PURCHASE" in selected[ident][10], ident
    assert "NO NEW ADAFRUIT HARDWARE" not in register.upper() or (
        "Adafruit hardware purchases are not required" in register)
    # Separate candidate subsystem is not a hidden second approved shopping list.
    assert "BQ27441" in register and "MAX17048" in register
    assert "Duplicate with separate MAX17048" in register
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
    assert room["room_controller"]["estimated_owned_not_verified"] == 1
    assert room["room_controller"]["remaining_if_reported_stock_works"] == 0
    assert robots["stepper"]["shopping_decision"].startswith("hold_until_drivetrain")
    assert not report["order_released"]


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
    ("room", "estimated_owned_total"),
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
