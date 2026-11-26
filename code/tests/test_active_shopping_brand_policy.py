"""Active shopping identities must not introduce new Adafruit hardware."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code/scripts"))
import procurement_release as release  # noqa: E402
from procurement_policy import adafruit_new_hardware  # noqa: E402


def test_active_catalogs_do_not_reference_new_adafruit_parts():
    for role, (vendor, sku, url) in release.SOURCE_REFERENCES.items():
        assert not adafruit_new_hardware(
            {"vendor": vendor, "sku": sku, "product_url": url}, 1
        ), role
    for role, (name, vendor, sku, url, qty, _) in release.PILOT_SAMPLE_PRODUCTS.items():
        assert not adafruit_new_hardware(
            {"name": name, "vendor": vendor, "sku": sku, "product_url": url,
             "brand": release.PILOT_IDENTIFIED_BRANDS.get(role)}, qty
        ), role


def test_active_plan_rejects_new_brand_but_preserves_owned_station():
    plan = json.loads(release.PLAN.read_text(encoding="utf-8"))
    for role in plan["parts"]:
        quantity = plan["target_robots"] * role["per_robot"] - role["reported_owned_total"]
        assert not adafruit_new_hardware(role, quantity), role["id"]
    for role in plan["room_pod"]["modules"]:
        quantity = role["quantity_per_room"] - role.get("reported_owned_total", 0)
        assert not adafruit_new_hardware(role, quantity), role["id"]
    for role in plan["linked_subassemblies"]:
        assert not adafruit_new_hardware(role, role["fleet_quantity"]), role["id"]
    controller = next(r for r in plan["room_pod"]["modules"] if r["id"] == "room_controller")
    assert controller["quantity_per_room"] == controller["reported_owned_total"] == 1
    assert "Feather nRF52840" in controller["name"]
    owned = dict(controller, brand="Adafruit")
    assert not adafruit_new_hardware(owned, 0)
    assert adafruit_new_hardware(owned, 1)


@pytest.mark.parametrize("field", [0, 1, 2, 3, "brand"])
def test_pilot_catalog_brand_mutation_is_held(monkeypatch, field):
    role = "cliff_obstacle"
    original = release.PILOT_SAMPLE_PRODUCTS[role]
    if field == "brand":
        monkeypatch.setitem(release.PILOT_IDENTIFIED_BRANDS, role, "aDaFrUiT")
    else:
        changed = list(original)
        changed[field] += " Adafruit"
        monkeypatch.setitem(release.PILOT_SAMPLE_PRODUCTS, role, tuple(changed))
    monkeypatch.setattr(release, "first_robot_projection", lambda report: {
        "roles": [{"id": role, "name": original[0], "scope": "pet or dock",
                   "conditional_remaining": 1, "prototype_target": 8,
                   "fleet_reported_owned_not_verified": 0, "missing_part_evidence": []}],
        "purchase_approved": False, "linked_decisions": [],
    })
    monkeypatch.setattr(release, "_historical_pilot_budget", lambda subtotal: {})
    row = release.first_robot_pilot_samples({})["roles"][0]
    assert row["pilot_action"] == "HOLD_UNAPPROVED_NEW_HARDWARE"
    assert row["pilot_sample_quantity"] == 0
    assert row["source_url"] is None
