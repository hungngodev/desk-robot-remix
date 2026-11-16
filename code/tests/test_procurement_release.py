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
            {"id": "cliff_obstacle", "name": "VL53L4CD", "per_robot": 8,
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
    assert d["cliff_obstacle"]["reference_only"]["sku"] == "3692"
    assert d["stepper"]["remaining_if_reported_stock_works"] == 5
    assert d["mg90s"]["remaining_if_reported_stock_works"] == 10
    assert not r["order_released"]
    assert "plan_unqualified_or_price_incomplete" in r["missing_system_evidence"]


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
