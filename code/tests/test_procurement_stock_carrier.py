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


@pytest.mark.parametrize("field,value", [
    ("sku", "GY-521-other"), ("pcb_revision", "rev-b"),
    ("vendor", "Different Manufacturer"), ("pcb_revision", None),
    ("sku", True),
])
def test_inspected_stock_cannot_substitute_a_similar_part(field, value):
    record = evidence()
    record["costs"]["inventory"][0][field] = value
    assert "stock vendor, model/SKU or PCB revision" in " ".join(
        release.stock_carrier_failures(record)
    )


def test_paid_in_flight_cannot_claim_different_board_revision():
    record = evidence()
    record["costs"]["paid_in_flight"] = [{
        "role_key": "robot:imu", **IMU, "pcb_revision": "uninspected",
        "quantity": 1, "order_reference": "paid-1",
    }]
    assert "paid_in_flight 0" in release.stock_carrier_failures(record)[0]


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
