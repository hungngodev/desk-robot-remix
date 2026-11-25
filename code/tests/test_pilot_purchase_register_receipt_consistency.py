"""Protect the first-unit XIAO paid amount from historical listing drift.

The November 16 fleet register is a dated candidate comparison, not an
independently maintained third cart or authorization to purchase hardware.
"""

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOM = ROOT / "docs/hardware/bom.json"
REGISTER = ROOT / "docs/hardware/2026-11-16-five-pet-purchase-register.md"


def _validate_xiao_sense_receipt(bom: dict, register: str) -> None:
    sense_rows = [
        item for item in bom["items"] if "XIAO ESP32S3 Sense" in item["item"]
    ]
    assert len(sense_rows) == 1
    sense = sense_rows[0]
    assert sense["quantity"] == 1
    assert sense["price_status"] == "reported_purchase"
    assert Decimal(str(sense["unit_usd"])) == Decimal("13.67")
    assert "November 22, 2026 first-unit payment and arrival correction" in register
    assert f"USD {sense['unit_usd']:.2f} actually paid" in register
    assert "carrier reported delivery November 7" in register
    assert "not been physically inspected" in register
    assert "historical seller quote, not the actual amount paid" in register
    assert "not a full prior-spend total or authorization to order" in register
    assert "[the historical BOM receipt record](bom.json)" in register
    assert "One XIAO is ordered; a carrier reports delivery" in register

    # Bind every field of the unique dated `xiao_sense` row so uninspected
    # stock or fleet-wide ordering cannot drift silently behind narrative prose.
    table_rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in register.splitlines()
        if re.match(r"^\|\s*`xiao_sense`\s*\|", line)
    ]
    assert len(table_rows) == 1
    row = table_rows[0]
    assert len(row) == 11
    assert (
        row[0], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10],
    ) == (
        "`xiao_sense`", "1", "5", "0", "0", "1", "4", "0", "$18.90", "ORDERED 1",
    )


def test_first_unit_xiao_payment_is_not_old_quote_or_received_stock():
    bom = json.loads(BOM.read_text(encoding="utf-8"))
    register = REGISTER.read_text(encoding="utf-8")
    _validate_xiao_sense_receipt(bom, register)


def test_xiao_sense_receipt_rejects_unverified_received_or_double_bom_qty():
    bom = json.loads(BOM.read_text(encoding="utf-8"))
    register = REGISTER.read_text(encoding="utf-8")

    double_bom = json.loads(json.dumps(bom))
    next(i for i in double_bom["items"] if "XIAO ESP32S3 Sense" in i["item"])["quantity"] = 2
    with pytest.raises(AssertionError):
        _validate_xiao_sense_receipt(double_bom, register)

    received_row = register.replace(
        "| 0 | 0 | 1 | 4 | 0 | $18.90 | ORDERED 1 |",
        "| 1 | 0 | 1 | 4 | 0 | $18.90 | RECEIVED 1 |",
        1,
    )
    assert received_row != register
    with pytest.raises(AssertionError):
        _validate_xiao_sense_receipt(bom, received_row)
