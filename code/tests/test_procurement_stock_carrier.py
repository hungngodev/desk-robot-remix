"""Strict buy release binds previously owned and paid units to signed hardware."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/procurement_release.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("procurement_stock_test", SCRIPT)
assert spec and spec.loader
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

IMU = {"vendor": "Generic", "sku": "GY-521", "pcb_revision": "rev-a"}


def evidence():
    return {
        "parts": {"imu": dict(IMU), "cap_power": {
            "vendor": "CompleteKit", "sku": "POWER-KIT", "pcb_revision": "1",
            "connector_selected_carrier": {
                "vendor": "Generic", "sku": "JST-PH-2", "pcb_revision": "2",
            },
        }},
        "room_pod": {"scd40": {
            "vendor": "Generic", "sku": "SCD40-MOD", "pcb_revision": "3",
        }},
        "supplemental_decisions": {
            "bq24075_charger_candidate": {
                "disposition": "selected", "vendor": "Generic",
                "sku": "BQ24075-MOD", "pcb_revision": "4",
            },
        },
        "costs": {"power_package_mode": "complete_kit", "inventory": [{
            "role_key": "robot:imu", **IMU,
            "acquisition_kind": "already_owned",
            "inspection_receipt_url": "https://example.org/receipt",
        }], "paid_in_flight": []},
    }


def test_exact_inspected_and_paid_stock_identity_matches_signed_carrier():
    record = evidence()
    record["costs"]["inventory"].append({
        "role_key": "station:scd40", **record["room_pod"]["scd40"],
    })
    record["costs"]["paid_in_flight"].append({
        "role_key": "robot:imu", **IMU,
        "quantity": 1, "order_reference": "real-paid-reference",
    })
    assert release.stock_carrier_failures(record) == []


@pytest.mark.parametrize("group", ["inventory", "paid_in_flight"])
@pytest.mark.parametrize("field,value", [
    ("sku", "GY-521-other"),
    ("sku", None),
    ("sku", True),
    ("sku", "__MISSING__"),
    ("pcb_revision", "rev-b"),
    ("pcb_revision", None),
    ("pcb_revision", True),
    ("pcb_revision", "__MISSING__"),
    ("vendor", "Different Manufacturer"),
    ("vendor", None),
    ("vendor", True),
    ("vendor", "__MISSING__"),
    ("model", "wrong-model"),
    ("model", None),
    ("model", True),
    ("model", "__MISSING__"),
])
def test_inspected_and_paid_stock_cannot_substitute_carrier_identity(group, field, value):
    signed = {**IMU, "model": "MPU6050-GY521"}
    record = evidence()
    record["parts"]["imu"] = dict(signed)
    valid_row = {
        "role_key": "robot:imu",
        **signed,
        **(
            {"acquisition_kind": "already_owned", "inspection_receipt_url": "https://example.org/receipt"}
            if group == "inventory"
            else {"quantity": 1, "order_reference": "paid-1"}
        ),
    }
    other_group = "paid_in_flight" if group == "inventory" else "inventory"
    record["costs"][other_group] = []
    record["costs"][group] = [dict(valid_row)]
    assert release.stock_carrier_failures(record) == []

    bad_row = dict(valid_row)
    if value == "__MISSING__":
        bad_row.pop(field)
    else:
        bad_row[field] = value
    record["costs"][group] = [bad_row]
    failures = release.stock_carrier_failures(record)
    assert failures and any(f"{group} 0" in msg and "robot:imu" in msg for msg in failures)


def test_stock_role_must_be_selected_and_well_formed():
    record = evidence()
    record["costs"]["inventory"][0]["role_key"] = "robot:unknown"
    assert release.stock_carrier_failures(record)
    record["costs"]["inventory"][0]["role_key"] = "unqualified"
    assert "invalid role identity" in release.stock_carrier_failures(record)[0]


def test_separate_power_components_require_selection_and_exact_identity():
    record = evidence()
    row = {"role_key": "robot:cap_power:bq24075_charger_candidate",
           "vendor": "Generic", "sku": "BQ24075-MOD", "pcb_revision": "4"}
    record["costs"]["inventory"] = [row]
    assert "unselected power component" in release.stock_carrier_failures(record)[0]
    record["costs"]["power_package_mode"] = "separate_components"
    assert release.stock_carrier_failures(record) == []
    row["pcb_revision"] = "5"
    assert "PCB revision" in release.stock_carrier_failures(record)[0]
    row["pcb_revision"] = "4"
    record["supplemental_decisions"]["bq24075_charger_candidate"][
        "disposition"
    ] = "deferred_optional"
    assert "unselected power component" in release.stock_carrier_failures(record)[0]


def test_connector_stock_matches_signed_power_parent_connector():
    record = evidence()
    record["costs"]["power_package_mode"] = "separate_components"
    record["costs"]["inventory"] = [{
        "role_key": "robot:cap_power:polarized_battery_connector",
        **record["parts"]["cap_power"]["connector_selected_carrier"],
    }]
    assert release.stock_carrier_failures(record) == []
    record["costs"]["inventory"][0]["sku"] = "JST-PH-3"
    assert release.stock_carrier_failures(record)


def test_unqualified_model_variant_cannot_count_as_selected_stock():
    record = evidence()
    record["parts"]["imu"]["model"] = "MPU6050"
    assert release.stock_carrier_failures(record)
    record["costs"]["inventory"][0]["model"] = "MPU6050"
    assert release.stock_carrier_failures(record) == []
    record["costs"]["inventory"][0]["model"] = "another sensor"
    assert release.stock_carrier_failures(record)


def test_empty_stock_evidence_preserves_existing_quote_only_release_fixture():
    record = evidence()
    record["costs"]["inventory"] = []
    assert release.stock_carrier_failures(record) == []
    record["costs"]["inventory"] = {}
    assert "expected an evidence list" in release.stock_carrier_failures(record)[0]


def test_legacy_parts_buying_guidance_retains_current_cap_and_head_status():
    """Old parts history must not undo the accepted budget or receipt state."""
    import json

    root = Path(__file__).resolve().parents[2]
    bom = json.loads((root / "docs/hardware/bom.json").read_text())
    parts = (root / "docs/hardware/parts.md").read_text()
    assert bom["cap_usd"] == 50
    assert any(item["unit_usd"] == 13.67
               and "XIAO ESP32S3 Sense" in item["item"]
               for item in bom["items"])
    assert "The $50 delivered cap still applies" in parts
    assert "historical cap is not established" not in parts
    assert "One paid, carrier-reported delivered; board uninspected" in parts
    assert "quantity/arrival unknown" not in parts


def test_inspected_first_unit_inventory_is_separate_from_reported_stock():
    """Strict checkout attachment must show real units without guessing ownership."""
    import json

    plan = json.loads(release.PLAN.read_text(encoding="utf-8"))
    source = release.generate(plan)
    original = release.first_robot_projection(source)
    assert all(x["verified_inspected_first_unit"] == 0 for x in original["roles"])
    assert original["verified_linked_power_stock"] == []

    cost = {
        "calculation_complete_not_physical_approval": True,
        "scope": "first_robot",
        "payable_now_cents": 0,
        "prior_paid_orders_cents": 1367,
        "prototype_cumulative_cents": 1367,
        "remaining_under_cap_cents": 3633,
    }
    checkout = {
        "power_package_mode": "separate_components",
        "inventory": [
            {"role_key": "robot:imu", "usable_allocated": 1},
            {"role_key": "station:room_controller", "usable_allocated": 1},
            {"role_key": "robot:cap_power:bq24075_charger_candidate",
             "usable_allocated": 1},
        ],
        "lines": [],
        "seller_charges": [],
    }
    attached = release.attach_verified_checkout_evidence(source, cost, checkout)
    projection = release.first_robot_projection(attached)
    by_id = {x["id"]: x for x in projection["roles"]}
    assert by_id["imu"]["verified_inspected_first_unit"] == 1
    assert by_id["imu"]["fleet_reported_owned_not_verified"] == 1
    assert by_id["room_controller"]["verified_inspected_first_unit"] == 1
    assert by_id["cap_power"]["verified_inspected_first_unit"] == 0
    assert projection["verified_linked_power_stock"] == [{
        "role_key": "robot:cap_power:bq24075_charger_candidate",
        "name": next(x["name"] for x in source["supplemental_decisions"]
                     if x["id"] == "bq24075_charger_candidate"),
        "usable_allocated": 1,
    }]
    output = release.render_first_robot_markdown(attached)
    first_list = output.split("## 2. First-unit remaining slots")[0]
    assert "Inspected usable for first unit" in first_list
    assert f"| {by_id['imu']['name']} | 1 | 1 |" in first_list
    assert f"| {by_id['room_controller']['name']} | 1 |" in first_list
    assert projection["verified_linked_power_stock"][0]["name"] in first_list

    # Reported stock is not silently upgraded for the normal preview.
    preview = release.render_first_robot_markdown(source)
    assert "Inspected usable for first unit" in preview
    assert f"| {by_id['imu']['name']} | 0 | 1 |" in preview


def test_checkout_attachment_rejects_bad_inspected_quantities():
    import json

    plan = json.loads(release.PLAN.read_text(encoding="utf-8"))
    source = release.generate(plan)
    cost = {"calculation_complete_not_physical_approval": True}
    checkout = {"inventory": [
        {"role_key": "robot:imu", "usable_allocated": True}
    ], "lines": [], "seller_charges": []}
    with pytest.raises(ValueError, match="quantity must be positive"):
        release.attach_verified_checkout_evidence(source, cost, checkout)
    checkout["inventory"][0]["usable_allocated"] = 1
    checkout["inventory"][0]["role_key"] = "robot:unselected_role"
    with pytest.raises(ValueError, match="unknown shopping role"):
        release.attach_verified_checkout_evidence(source, cost, checkout)


def test_strict_cli_rejects_mismatched_stock_carrier_under_mocked_audit(
    tmp_path, monkeypatch, capsys,
):
    import json
    import sys
    from types import SimpleNamespace

    record = evidence()
    record["costs"]["paid_in_flight"] = [{
        "role_key": "robot:imu",
        **IMU,
        "vendor": "Counterfeit",
        "quantity": 1,
        "order_reference": "paid-cli-1",
    }]
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setitem(
        sys.modules,
        "verify_procurement_receipts",
        SimpleNamespace(
            audit_release=lambda *_a, **_kw: [],
            checkout_sha=lambda: "0" * 40,
            verified_required_ci_jobs=lambda *_a, **_kw: True,
        ),
    )
    monkeypatch.setattr(release, "generate", lambda _p, _e=None: {"supplemental_decisions": [], "room_pod": []})
    monkeypatch.setattr(release, "first_robot_projection", lambda _r: {"purchase_approved": True})
    monkeypatch.setattr(release, "cost_quote", lambda *_a, **_kw: {"calculation_complete_not_physical_approval": True, "within_prototype_cap": True, "awaiting_arrival_roles": []})
    monkeypatch.setattr(release, "_confirmed_first_unit_prior_payment_missing", lambda *_a, **_kw: False)
    monkeypatch.setattr(release, "_first_unit_paid_history_review_missing", lambda *_a, **_kw: False)
    monkeypatch.setattr(
        sys, "argv",
        ["procurement_release.py", "--evidence", str(evidence_path),
         "--require-first-robot", "--format", "first-robot-json"],
    )
    assert release.main() == 2
    assert "paid_in_flight 0" in capsys.readouterr().err
