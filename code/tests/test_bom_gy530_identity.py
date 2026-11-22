"""Keep the historical GY-530 alternative separate from the exact pilot carrier."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_historical_budget_carrier_matches_first_unit_sample_identity():
    plan = json.loads(
        (ROOT / "docs/hardware/full-feature-plan.json").read_text(encoding="utf-8")
    )
    bom = json.loads(
        (ROOT / "docs/hardware/bom.json").read_text(encoding="utf-8")
    )
    selected = next(part for part in plan["parts"] if part["id"] == "cliff_obstacle")
    assert "SEN-19-006" in selected["name"]
    rows = [
        item for item in bom["items"]
        if "VL53L0X" in item["item"] and "GY-530" in item["item"]
    ]
    assert len(rows) == 3
    assert [row["quantity"] for row in rows] == [4, 1, 3]
    assert sum(row["quantity"] for row in rows) == selected["per_robot"] == 8
    for row in rows:
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
