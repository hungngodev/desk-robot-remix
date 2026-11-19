"""Regression coverage for cumulative first-unit delivered cost, not cart approval."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/landed_cost.py"
spec = importlib.util.spec_from_file_location("landed_cost", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

REQUIRED = {"robot:cliff_obstacle": 1, "robot:i2c_mux": 1}
CATEGORIES = {"robot:cliff_obstacle": "robot", "robot:i2c_mux": "robot"}


def sample():
    return {
        "scope": "evaluation", "currency": "USD",
        "paid_orders_complete": True,
        "lines": [
            {"role_key": "robot:cliff_obstacle", "seller": "ElectroPeak",
             "sku": "SEN-19-006", "quantity_packages": 1,
             "units_per_package": 1, "package_price_usd": "1.76",
             "quote_reference": "quote-one", "quoted_at": "2026-11-18",
             "stock_evidence_url": "https://electropeak.com/gy-530-vl53l0x"},
            {"role_key": "robot:i2c_mux", "seller": "ElectroPeak",
             "sku": "COM-05-067", "quantity_packages": 1,
             "units_per_package": 1, "package_price_usd": "0.47",
             "quote_reference": "quote-one", "quoted_at": "2026-11-18",
             "stock_evidence_url": "https://electropeak.com/tca9548a"},
        ],
        "seller_charges": [
            {"seller": "ElectroPeak", "shipping_usd": "4.00",
             "tax_usd": "0.32", "duties_usd": "0.00",
             "discount_usd": "0.00"},
        ],
        "paid_orders": [{"order_reference": "already-paid",
                         "total_paid_usd": "12.50"}],
    }


def calculate(evidence):
    return mod.account_landed_cost(evidence, REQUIRED, CATEGORIES,
                                   expected_scope="evaluation")


def test_exact_landed_cost_includes_shipping_tax_and_paid_spend_once():
    ev = sample()
    ev["paid_orders"].append(dict(ev["paid_orders"][0]))
    out = calculate(ev)
    assert out["errors"] == []
    assert out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] == 655
    assert out["prior_paid_orders_cents"] == 1250
    assert out["prototype_cumulative_cents"] == 1905
    assert out["remaining_under_cap_cents"] == 3095
    assert out["within_prototype_cap"]
    assert not out["landed_price_is_a_verified_supplier_checkout"]


def test_missing_is_not_zero_and_partial_amount_is_not_a_landed_total():
    ev = sample()
    del ev["seller_charges"][0]["tax_usd"]
    out = calculate(ev)
    assert not out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] is None
    assert any("seller charges" in x for x in out["errors"])


def test_partial_cart_cannot_satisfy_required_role():
    ev = sample()
    ev["lines"].pop()
    out = calculate(ev)
    assert "robot:i2c_mux" in out["unaccounted_roles"]
    assert out["payable_now_cents"] is None


def test_explicit_inventory_and_in_flight_are_distinct():
    ev = sample()
    ev["lines"].pop()
    ev["inventory"] = [{"role_key": "robot:i2c_mux",
                        "usable_allocated": 1,
                        "inspection_receipt_url": "https://github.com/org/record"}]
    out = calculate(ev)
    assert out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] == 608
    ev["inventory"] = []
    ev["paid_in_flight"] = [{"role_key": "robot:i2c_mux",
                            "quantity": 1, "order_reference": "already-paid"}]
    out = calculate(ev)
    assert out["calculation_complete_not_physical_approval"]
    assert out["awaiting_arrival_roles"] == ["robot:i2c_mux"]


def test_duplicate_buying_covered_stock_fails_closed():
    ev = sample()
    ev["inventory"] = [{"role_key": "robot:i2c_mux",
                        "usable_allocated": 1,
                        "inspection_receipt_url": "https://github.com/org/record"}]
    out = calculate(ev)
    assert not out["calculation_complete_not_physical_approval"]
    assert any("duplicated purchase" in x for x in out["errors"])


@pytest.mark.parametrize("bad", [
    "0.001", "-1", "Infinity", "not-number", 1.23, True,
])
def test_money_rejects_inexact_or_invalid_values(bad):
    with pytest.raises(ValueError):
        mod.cents(bad, "test")


def test_conflicting_reused_order_reference_fails():
    ev = sample()
    ev["paid_orders"].append({"order_reference": "already-paid",
                              "total_paid_usd": "50.00"})
    out = calculate(ev)
    assert not out["calculation_complete_not_physical_approval"]


def test_unknown_stock_quote_url_and_wrong_scope_fail():
    ev = sample()
    ev["lines"][0]["stock_evidence_url"] = "https://user@invalid.example/x"
    ev["scope"] = "first_robot"
    out = calculate(ev)
    assert not out["calculation_complete_not_physical_approval"]
    assert any("mismatched quote scope" in x for x in out["errors"])
    assert any("stock evidence" in x for x in out["errors"])


def test_budget_overflow_remains_visible():
    ev = sample()
    ev["paid_orders"][0]["total_paid_usd"] = "49.00"
    out = calculate(ev)
    assert out["calculation_complete_not_physical_approval"]
    assert out["prototype_cumulative_cents"] == 5555
    assert not out["within_prototype_cap"]
    assert out["remaining_under_cap_cents"] == -555


def test_missing_prior_spend_confirmation_hides_cumulative_cost():
    ev = sample()
    del ev["paid_orders_complete"]
    out = calculate(ev)
    assert out["payable_now_cents"] is None
    assert out["prior_paid_orders_cents"] is None
    assert out["prototype_cumulative_cents"] is None
    assert not out["calculation_complete_not_physical_approval"]
    assert any("Prior paid spending" in err for err in out["errors"])


def test_absent_paid_order_register_never_means_zero_spend():
    ev = sample()
    del ev["paid_orders"]
    out = calculate(ev)
    assert not out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] is None
    assert out["prior_paid_orders_cents"] is None
    assert out["prototype_cumulative_cents"] is None
    assert out["remaining_under_cap_cents"] is None
    assert any("paid orders register missing" in error for error in out["errors"])


def test_explicit_verified_empty_paid_order_register_can_mean_zero():
    ev = sample()
    ev["paid_orders"] = []
    out = calculate(ev)
    assert out["calculation_complete_not_physical_approval"]
    assert out["prior_paid_orders_cents"] == 0
    assert out["prototype_cumulative_cents"] == out["payable_now_cents"]


def test_wrong_input_types_do_not_crash_or_approve():
    ev = sample()
    ev["lines"] = None
    ev["inventory"] = None
    ev["paid_in_flight"] = None
    ev["paid_orders"] = None
    ev["seller_charges"] = None
    out = calculate(ev)
    assert out["payable_now_cents"] is None
    assert out["errors"]

def test_trailing_zero_supplier_decimal_is_valid():
    assert mod.cents("5.950", "supplier price") == 595
    assert mod.cents("0.4700", "supplier price") == 47
    with pytest.raises(ValueError, match="subcent"):
        mod.cents("5.951", "supplier price")
