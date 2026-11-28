"""A paid Sense order is not an inspected physical board or a new quote."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _record(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text())


def _reconcile_sense_purchase(inventory: dict, bom: dict) -> dict:
    sense_rows = [
        item for item in bom["items"]
        if "Purchased XIAO ESP32S3 Sense" in item["item"]
    ]
    paid_rows = [
        item for item in bom["items"]
        if item.get("price_status") == "reported_purchase"
    ]
    if len(sense_rows) != 1 or len(paid_rows) != 1 or sense_rows[0] is not paid_rows[0]:
        raise ValueError("Expected exactly one reconciled Sense paid row")
    paid_item = sense_rows[0]
    purchase = inventory["s3_purchase"]
    receipt = bom["paid_reconciliation"]
    if (
        paid_item["quantity"] != 1
        or purchase["paid_order_quantity"] != 1
        or paid_item["unit_usd"] != receipt["payment_total_usd"]
        or paid_item["unit_usd"] != 13.67
    ):
        raise ValueError("Sense paid row does not match single receipt total")
    return paid_item


def test_sense_purchase_reconciles_payment_without_inventing_bench_stock():
    inventory = _record("docs/hardware/fleet-inventory.json")
    bom = _record("docs/hardware/bom.json")
    purchase = inventory["s3_purchase"]
    receipt = bom["paid_reconciliation"]
    paid_item = _reconcile_sense_purchase(inventory, bom)
    assert receipt["item_scope"] == "one XIAO ESP32S3 Sense only"
    assert purchase["paid_order_quantity"] == paid_item["quantity"] == 1
    assert purchase["minimum_ordered"] == 1
    assert purchase["payment_total_usd"] == receipt["payment_total_usd"]
    assert purchase["payment_total_usd"] == bom["reported_already_purchased_usd"]
    assert purchase["payment_total_usd"] == paid_item["unit_usd"] == 13.67
    assert purchase["payment_total_verified"] is True
    assert purchase["payment_reconciled_at"] == receipt["reviewed_at"]
    assert purchase["carrier_delivery_notice_date"] == (
        receipt["carrier_delivery_notice_date"]
    )
    assert purchase["purchase_evidence_record"] == "bom.json:paid_reconciliation"

    # Neither a payment nor a delivery notice establishes the bench count,
    # board condition, or physical qualification of a 3.3 V/audio path.
    assert inventory["s3_owned_count"] is None
    assert purchase["quantity"] is None
    assert purchase["received_and_markings_verified"] is False
    assert receipt["inspected_usable_hardware"] is False
    assert purchase["all_project_prior_spend_reconciled"] is False
    assert receipt["all_project_prior_spend_reconciled"] is False


def test_duplicate_sense_paid_row_is_rejected_without_blocking_other_quotes():
    inventory = _record("docs/hardware/fleet-inventory.json")
    bom = _record("docs/hardware/bom.json")

    duplicate_bom = copy.deepcopy(bom)
    duplicate_bom["items"].append(copy.deepcopy(bom["items"][0]))
    with pytest.raises(ValueError, match="exactly one reconciled Sense paid row"):
        _reconcile_sense_purchase(inventory, duplicate_bom)

    other_quote_bom = copy.deepcopy(bom)
    other_quote_bom["items"].append({
        "item": "Unrelated quoted part matching amount",
        "quantity": 1,
        "unit_usd": 13.67,
        "price_status": "quote_pending",
    })
    assert _reconcile_sense_purchase(inventory, other_quote_bom)["unit_usd"] == 13.67


def test_historical_sense_display_price_cannot_replace_paid_total():
    purchase = _record("docs/hardware/fleet-inventory.json")["s3_purchase"]
    assert purchase["display_price_historical_only"] is True
    assert purchase["pasted_display_price_usd"] == 18.87
    assert purchase["pasted_display_price_usd"] != purchase["payment_total_usd"]
    assert purchase["delivered_receipt_total_verified"] is False
