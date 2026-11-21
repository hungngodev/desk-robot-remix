"""Current delivered quote must cover every exact first-unit pilot sample.

Synthetic fixtures exercise accounting, not real supplier or hardware release.
"""
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "code/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "pilot_landed_quote", SCRIPTS / "procurement_release.py"
)
procurement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(procurement)


@pytest.fixture
def pilot():
    plan = json.loads(procurement.PLAN.read_text(encoding="utf-8"))
    report = procurement.generate(plan, {})
    cart = procurement.pilot_supplier_cart(report)
    return report, cart


def quoted_evidence(cart):
    now = date.today().isoformat()
    lines = [{
        "role_key": "pilot:" + item["id"],
        "seller": item["checkout_seller_candidate"],
        "sku": item["sku"],
        "quantity_packages": item["quantity"],
        "units_per_package": 1,
        "package_price_usd": format(item["historical_unit_quote_usd"], ".2f"),
        "quote_reference": "synthetic quoted SKU " + item["sku"],
        "quoted_at": now,
        "stock_checked_at": now,
        "stock_evidence_url": item["product_url"],
    } for item in cart["items"]]
    sellers = sorted({item["checkout_seller_candidate"] for item in cart["items"]})
    charges = [{
        "seller": seller,
        "shipping_usd": "1.00" if index == 0 else "0.00",
        "tax_usd": "0.50" if index == 0 else "0.00",
        "duties_usd": "0.00",
        "discount_usd": "0.00",
    } for index, seller in enumerate(sellers)]
    return {"pilot_costs": {
        "scope": "pilot_samples", "currency": "USD",
        "paid_orders_complete": True,
        "paid_orders": [{
            "order_reference": "previous_spending",
            "total_paid_usd": "12.00",
            "allocations": [],
        }],
        "lines": lines,
        "seller_charges": charges,
        "inventory": [],
        "paid_in_flight": [],
    }}


def test_full_pilot_sample_landed_cost_accounts_for_sellers_and_prior_spend(pilot):
    report, cart = pilot
    assert cart["exact_sku_count"] == 13
    assert cart["component_quantity"] == 17
    result = procurement.pilot_landed_cost(report, quoted_evidence(cart))
    assert result["scope"] == "pilot_samples"
    assert result["exact_sample_skus"] == 13
    assert result["sample_component_quantity"] == 17
    assert result["calculation_complete_not_physical_approval"] is True
    assert result["payable_now_cents"] == 4191
    assert result["prior_paid_orders_cents"] == 1200
    assert result["prototype_cumulative_cents"] == 5391
    assert result["within_prototype_cap"] is False
    assert result["full_first_robot_purchase_approved"] is False
    assert result["motor_or_lithium_charge_authorized"] is False


@pytest.mark.parametrize("mutation", [
    "empty", "missing_seller_charge", "mismatched_sku",
    "wrong_storefront", "untrusted_stock_url",
    "stale_quote", "unknown_prior_spend", "unverified_inventory",
    "nonstring_role", "broken_url",
])
def test_pilot_quote_fails_closed_for_missing_or_wrong_evidence(pilot, mutation):
    report, cart = pilot
    evidence = quoted_evidence(cart)
    cost = evidence["pilot_costs"]
    if mutation == "empty":
        evidence = {}
    elif mutation == "missing_seller_charge":
        cost["seller_charges"].pop()
    elif mutation == "mismatched_sku":
        cost["lines"][0]["sku"] = "similar_other_revision"
    elif mutation == "wrong_storefront":
        cost["lines"][0]["seller"] = "another seller"
    elif mutation == "untrusted_stock_url":
        cost["lines"][0]["stock_evidence_url"] = "https://example.com/stock"
    elif mutation == "stale_quote":
        cost["lines"][0]["quoted_at"] = "2020-01-01"
        cost["lines"][0]["stock_checked_at"] = "2020-01-01"
    elif mutation == "unknown_prior_spend":
        del cost["paid_orders"]
    elif mutation == "nonstring_role":
        cost["lines"][0]["role_key"] = ["pilot:not-a-hashable-key"]
    elif mutation == "broken_url":
        cost["lines"][0]["stock_evidence_url"] = "https://[broken"
    elif mutation == "unverified_inventory":
        cost["inventory"] = [{
            "role_key": cost["lines"][0]["role_key"],
            "usable_allocated": 1,
            "inspection_receipt_url": "https://example.com/not-verified",
            "acquisition_kind": "already_owned",
        }]
    result = procurement.pilot_landed_cost(report, evidence)
    assert not result["calculation_complete_not_physical_approval"]
    assert result["payable_now_cents"] is None
    assert result["prototype_cumulative_cents"] is None
    assert result["full_first_robot_purchase_approved"] is False
    assert result["errors"]


def test_pilot_samples_do_not_relabel_or_release_original_evaluation(pilot):
    report, cart = pilot
    evidence = quoted_evidence(cart)
    result = procurement.pilot_landed_cost(report, evidence)
    assert result["scope"] == "pilot_samples"
    unrelated = procurement.cost_quote(report, {}, "evaluation")
    assert unrelated["scope"] == "evaluation"
    assert not unrelated["calculation_complete_not_physical_approval"]
    assert not report["order_released"]
