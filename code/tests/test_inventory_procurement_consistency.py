"""Cross-check reported inventory without promoting historical quotes to orders."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

HARDWARE = Path(__file__).resolve().parents[2] / "docs/hardware"


@pytest.fixture
def registers():
    def load(name):
        return json.loads((HARDWARE / name).read_text(), parse_float=Decimal)

    return (
        load("fleet-inventory.json"),
        load("full-feature-plan.json"),
        load("bom.json"),
        (HARDWARE / "complete-shopping-checklist.md").read_text(),
    )


@pytest.mark.parametrize(
    "role, inventory_name",
    [
        ("bmp280", "Adafruit BMP280 pressure/temperature breakout"),
        ("pir", "PIR motion detector, SB00622A-2-V1.3"),
        ("reed", "Magnetic reed-switch comparator, KY-025-style"),
        ("haptic_motor", "DFRobot FIT0774 coin vibration motor"),
        ("max30102", "MAX30102 optical heartbeat paw pad breakout"),
    ],
)
def test_reported_accessory_counts_agree(registers, role, inventory_name):
    inventory, plan, _, checklist = registers
    part = next(p for p in plan["parts"] if p["id"] == role)
    stock = next(p for p in inventory["components"] if p["component"] == inventory_name)
    assert inventory["robot_count"] == plan["target_robots"]
    assert stock["owned_count"] is None
    reported = stock.get("minimum_reported", 0)
    estimated = stock.get("estimated_owned_count", 0)
    required = part["per_robot"] * plan["target_robots"]
    assert stock["needed_per_robot"] == part["per_robot"]
    assert stock["needed_for_five"] == required
    assert reported == part["reported_owned_total"]
    assert estimated == part.get("estimated_owned_total", 0)
    remaining = max(0, required - max(reported, estimated))
    assert f"| {part['name']} | {reported} | {estimated} | 0 |" in checklist
    assert f"| pet or dock | {part['name']} | {required} | {remaining} | HOLD |" in checklist


def test_historical_payment_and_range_candidate_agree(registers):
    inventory, plan, bom, checklist = registers
    payment = inventory["s3_purchase"]
    head = next(p for p in bom["items"] if p["price_status"] == "reported_purchase")
    assert payment["paid_order_quantity"] == head["quantity"] == 1
    assert payment["source_url"] == head["url"]
    assert payment["payment_total_usd"] == head["quantity"] * head["unit_usd"]
    assert payment["payment_total_usd"] == bom["reported_already_purchased_usd"]
    assert payment["payment_total_usd"] == bom["paid_reconciliation"]["payment_total_usd"]
    assert bom["procurement_authority"] is False
    range_part = next(p for p in plan["parts"] if p["id"] == "cliff_obstacle")
    rows = [p for p in bom["items"] if p.get("candidate_seller_sku") == "SEN-19-006"]
    assert sum(p["quantity"] for p in rows) == range_part["per_robot"] == 8
    assert {p["reference_unit_usd"] for p in rows} == {Decimal("1.44")}
    assert all(p["unit_usd"] is None for p in rows)
    assert "SEN-19-006" in range_part["name"]
    required = range_part["per_robot"] * plan["target_robots"]
    assert f"| pet or dock | {range_part['name']} | {required} | {required} | HOLD |" in checklist
