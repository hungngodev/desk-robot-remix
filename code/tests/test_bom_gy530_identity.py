"""Keep the historical GY-530 alternative separate from the exact pilot carrier."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _validate_gy530_identity(plan: dict, bom: dict) -> None:
    selected = next(part for part in plan["parts"] if part["id"] == "cliff_obstacle")
    assert "VL53L0X" in selected["name"] and "GY-530" in selected["name"]
    assert "SEN-19-006" in selected["name"]
    rows = [
        item for item in bom["items"]
        if item.get("candidate_seller_sku") == "SEN-19-006"
        or "VL53L" in item["item"]
        or "GY-530" in item["item"]
    ]
    assert len(rows) == 3
    role_quantities = {}
    for role in ("downward", "forward", "side and rear"):
        matched = [row for row in rows if role in row["item"]]
        assert len(matched) == 1, role
        role_quantities[role] = matched[0]["quantity"]
    assert role_quantities == {
        "downward": 4,
        "forward": 1,
        "side and rear": 3,
    }
    assert sum(role_quantities.values()) == selected["per_robot"] == 8
    for row in rows:
        assert "VL53L0X GY-530" in row["item"]
        assert "VL53L4CD" not in row["item"]
        assert row["candidate_seller_sku"] == "SEN-19-006"
        assert row["url"] == (
            "https://electropeak.com/gy-530-vl53l0x-laser-range-finder"
        )
        assert row["unit_usd"] is None
        assert row["price_status"] == "sample_quote_only"
        assert row["reference_unit_usd"] == 1.44
        assert "SEN-19-018" in row["fit"]
    alt = bom["unselected_gy530_carrier_reference"]
    assert alt["seller_sku"] == "SEN-19-018"
    assert alt["reference_unit_usd"] == 1.75
    assert alt["url"].endswith("laser-ranging-sensor-module-double-hole")
    assert alt["intended_status"] == "historical_alternative_not_selected_for_first_unit"
    assert bom["qualification_checks"]["sensor_mount_surface_latency_and_stops_qualified"] is False


def test_historical_budget_carrier_matches_first_unit_sample_identity():
    plan = json.loads(
        (ROOT / "docs/hardware/full-feature-plan.json").read_text(encoding="utf-8")
    )
    bom = json.loads(
        (ROOT / "docs/hardware/bom.json").read_text(encoding="utf-8")
    )
    _validate_gy530_identity(plan, bom)


def test_gy530_identity_rejects_vl53l4cd_label_and_swapped_role_counts():
    plan = json.loads(
        (ROOT / "docs/hardware/full-feature-plan.json").read_text(encoding="utf-8")
    )
    bom = json.loads(
        (ROOT / "docs/hardware/bom.json").read_text(encoding="utf-8")
    )

    contradictory = json.loads(json.dumps(bom))
    down_row = next(
        item for item in contradictory["items"]
        if item.get("candidate_seller_sku") == "SEN-19-006" and "downward" in item["item"]
    )
    down_row["item"] = down_row["item"].replace("VL53L0X GY-530", "VL53L4CD")
    with pytest.raises(AssertionError):
        _validate_gy530_identity(plan, contradictory)

    swapped = json.loads(json.dumps(bom))
    for item in swapped["items"]:
        if item.get("candidate_seller_sku") == "SEN-19-006":
            if "downward" in item["item"]:
                item["quantity"] = 1
            elif "forward" in item["item"]:
                item["quantity"] = 4
    with pytest.raises(AssertionError):
        _validate_gy530_identity(plan, swapped)
