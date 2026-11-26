"""Cross-phase accounting regressions: exact cents are not purchase approval."""

import importlib.util
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/landed_cost.py"
spec = importlib.util.spec_from_file_location("landed_cost", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

REQUIRED = {"robot:pack": 2, "dock:contact": 1, "station:host": 1}
CATEGORIES = {"robot:pack": "robot", "dock:contact": "dock", "station:host": "station"}


def _quote(role, seller, price, units=1):
    today = date.today().isoformat()
    return {
        "role_key": role, "seller": seller, "sku": role,
        "quantity_packages": 1, "units_per_package": units,
        "package_price_usd": price, "quote_reference": "checkout",
        "quoted_at": today, "stock_checked_at": today,
        "stock_evidence_url": "https://supplier.example/stock",
    }


def _charges(seller, shipping, tax, duties, discount):
    return {
        "seller": seller, "shipping_usd": shipping, "tax_usd": tax,
        "duties_usd": duties, "discount_usd": discount,
    }


def _evidence():
    pack = _quote("robot:pack", "A", "10.00", 3)
    pack["minimum_pack_review"] = {
        "extra_units": 2, "reviewed": True,
        "seller_minimum_pack_url": "https://supplier.example/pack",
    }
    return {
        "scope": "first_robot", "currency": "USD", "paid_orders_complete": True,
        "lines": [pack, _quote("dock:contact", "A", "10.00"),
                  _quote("station:host", "B", "5.00")],
        "seller_charges": [_charges("A", "2.00", "0.91", "0.05", "0.93"),
                           _charges("B", "6.11", "0.42", "0.08", "0.14")],
        "paid_orders": [{"order_reference": "prior", "total_paid_usd": "16.50",
                         "allocations": [{"role_key": "robot:pack", "quantity": 1}]}],
        "inventory": [{"role_key": "robot:pack", "usable_allocated": 1,
                       "acquisition_kind": "paid_order", "order_reference": "prior",
                       "inspection_receipt_url": "https://supplier.example/inspection"}],
    }


@pytest.mark.parametrize("tax, cumulative, remaining, within", [
    ("0.41", 4999, 1, True),
    ("0.42", 5000, 0, True),
    ("0.43", 5001, -1, False),
])
def test_combined_pack_charges_and_prior_spend_at_exact_cap(tax, cumulative, remaining, within):
    ev = _evidence()
    ev["seller_charges"][1]["tax_usd"] = tax
    result = mod.account_landed_cost(ev, REQUIRED, CATEGORIES)
    assert result["errors"] == []
    assert result["calculation_complete_not_physical_approval"] is True
    assert result["material_subtotals_cents"] == {"robot": 1000, "dock": 1000, "station": 500}
    assert result["seller_payable_cents"] == {"A": 2203, "B": cumulative - 3853}
    assert result["allocated_landed_subtotals_cents"] == {
        "robot": 1101, "dock": 1102, "station": cumulative - 3853,
    }
    assert sum(result["allocated_landed_subtotals_cents"].values()) == cumulative - 1650
    assert result["payable_now_cents"] == cumulative - 1650
    assert result["prior_paid_orders_cents"] == 1650
    assert result["prototype_cumulative_cents"] == cumulative
    assert result["remaining_under_cap_cents"] == remaining
    assert result["within_prototype_cap"] is within
    assert result["reviewed_pack_surplus_units"] == {"robot:pack": 2}
    assert result["quoted_units_applied_to_roles"] == dict.fromkeys(REQUIRED, 1)
    assert result["landed_price_is_a_verified_supplier_checkout"] is False


@pytest.mark.parametrize("shipping, robot, dock", [("0.02", 1, 1), ("0.04", 3, 1)])
def test_free_goods_apportion_freight_by_actual_package_units(shipping, robot, dock):
    ev = _evidence()
    for line in ev["lines"]:
        line["package_price_usd"] = "0"
        line["free_package_evidence_url"] = "https://supplier.example/free"
    ev["seller_charges"] = [_charges("A", shipping, "0", "0", "0"),
                            _charges("B", "0.01", "0", "0", "0")]
    result = mod.account_landed_cost(ev, REQUIRED, CATEGORIES)
    assert result["errors"] == []
    # Three units versus one; the tied remainder goes to the dock by name.
    assert result["allocated_landed_subtotals_cents"] == {
        "robot": robot, "dock": dock, "station": 1,
    }
    assert result["payable_now_cents"] == robot + dock + 1


def test_cross_phase_errors_keep_order_and_hide_partial_totals():
    ev = _evidence()
    ev["currency"] = "EUR"
    ev["lines"].append(None)
    ev["paid_orders"].append({"order_reference": "prior", "total_paid_usd": "16.51"})
    ev["inventory"].append(dict(ev["inventory"][0]))
    ev["paid_in_flight"] = [{"role_key": "robot:pack", "quantity": 1,
                            "order_reference": "prior"}]
    ev["lines"][0]["minimum_pack_review"]["extra_units"] = 1
    ev["seller_charges"][0].pop("tax_usd")
    ev["seller_charges"].pop()
    result = mod.account_landed_cost(ev, REQUIRED, CATEGORIES)
    assert result["errors"] == [
        "Quote currency must be USD",
        "quote 3: invalid line",
        "paid order 1: conflicting duplicate paid reference",
        "inventory 1: duplicate inspection receipt for same role",
        "in-flight 0: paid allocation already consumed by inspected inventory",
        "robot:pack: over-order or minimum pack surplus lacks exact review",
        "seller charges 0: tax: use an exact USD dollar amount",
        "Shipping, taxes, duties or discounts unknown for one or more sellers",
    ]
    assert result["calculation_complete_not_physical_approval"] is False
    assert result["allocated_landed_subtotals_cents"] is None
    assert result["payable_now_cents"] is None
    assert result["prior_paid_orders_cents"] is None
    assert result["prototype_cumulative_cents"] is None
    assert result["within_prototype_cap"] is False
