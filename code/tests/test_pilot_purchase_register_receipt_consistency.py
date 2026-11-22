"""Protect the first-unit XIAO paid amount from historical listing drift.

The November 16 fleet register is a dated candidate comparison, not an
independently maintained third cart or authorization to purchase hardware.
"""

import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOM = ROOT / "docs/hardware/bom.json"
REGISTER = ROOT / "docs/hardware/2026-11-16-five-pet-purchase-register.md"


def test_first_unit_xiao_payment_is_not_old_quote_or_received_stock():
    bom = json.loads(BOM.read_text(encoding="utf-8"))
    sense = next(item for item in bom["items"]
                 if "XIAO ESP32S3 Sense" in item["item"])
    assert sense["price_status"] == "reported_purchase"
    assert Decimal(str(sense["unit_usd"])) == Decimal("13.67")
    register = REGISTER.read_text(encoding="utf-8")
    assert "November 22, 2026 first-unit payment and arrival correction" in register
    assert f"USD {sense['unit_usd']:.2f} actually paid" in register
    assert "carrier reported delivery November 7" in register
    assert "not been physically inspected" in register
    assert "historical seller quote, not the actual amount paid" in register
    assert "not a full prior-spend total or authorization to order" in register
    assert "[the historical BOM receipt record](bom.json)" in register
    # Retain the November 16 candidate price as dated comparison only.
    assert any(
        line.startswith("| `xiao_sense` |") and "| $18.90 |" in line
        for line in register.splitlines()
    )
    assert "One XIAO is ordered; a carrier reports delivery" in register
