"""Regression coverage for historical budget row accounting."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def budget():
    """Load the standalone CLI without modifying global import paths permanently."""
    import sys

    spec = importlib.util.spec_from_file_location("check_budget", SCRIPTS / "check_budget.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
        spec.loader.exec_module(module)
    return module.budget


@pytest.mark.parametrize("status,known,ready", [("owned", True, True), ("verified", False, False)])
def test_zero_price_requires_owned_stock(budget, status, known, ready):
    data = {"cap_usd": "50", "fit_confirmed": True, "items": [
        {"item": "sample", "quantity": 1, "price_status": status, "unit_usd": "0"},
    ]}
    result = budget(data, "0", "0")
    assert result["unknown_price_items"] == ([] if known else ["sample"])
    assert result["purchase_ready"] is ready


def test_unknown_fees_do_not_authorize_purchase(budget):
    data = {"cap_usd": "50", "fit_confirmed": True, "items": [
        {"item": "sample", "quantity": 3, "price_status": "verified", "unit_usd": "0.01"},
    ]}
    result = budget(data, None, "0")
    assert result["known_landed_subtotal_usd"] == 0.03
    assert result["unknown_landed_fees"] == ["shipping"]
    assert result["planning_over_cap"] is None
    assert result["purchase_ready"] is False


@pytest.mark.parametrize("quantity", [True, 0, 10001])
def test_invalid_quantity_still_rejected(budget, quantity):
    data = {"cap_usd": "50", "items": [
        {"item": "sample", "quantity": quantity, "price_status": "verified", "unit_usd": "1"},
    ]}
    with pytest.raises(ValueError, match="quantity"):
        budget(data, "0", "0")


def test_empty_bom_cannot_be_a_complete_budget(budget):
    data = {"cap_usd": "50", "fit_confirmed": True, "items": []}
    with pytest.raises(ValueError, match="at least one item"):
        budget(data, "0", "0")


@pytest.mark.parametrize("robots,cap,subtotal,total,remaining,over", [
    (1, "50", 48.99, 50.01, -0.01, True),
    (5, "50", 116.99, 118.01, -68.01, True),
    (5, "250", 116.99, 118.01, 131.99, False),
])
def test_budget_charges_entire_retail_pack_and_scales_other_rows(
    budget, robots, cap, subtotal, total, remaining, over,
):
    # One sealed five-unit pack must be paid for even when only one unit
    # is needed. The legacy BOM represents the purchased pack as one row unit.
    data = {
        "cap_usd": cap, "fit_confirmed": True,
        "items": [
            {"item": "sealed five-unit pack", "quantity": 1,
             "price_status": "verified", "unit_usd": "31.99"},
            {"item": "other parts per robot", "quantity": robots,
             "price_status": "verified", "unit_usd": "17.00"},
        ],
    }
    result = budget(data, "0.510", "0.51")
    assert result["known_subtotal_usd"] == subtotal
    assert result["quoted_total_usd"] == total
    assert result["known_landed_subtotal_usd"] == total
    assert result["remaining_under_cap_usd"] == remaining
    assert result["planning_over_cap"] is over
    assert result["purchase_ready"] is (not over)


@pytest.mark.parametrize("robots", [1, 5])
@pytest.mark.parametrize("shipping,tax", [("0.005", "0.51"), ("0.51", "0.005")])
def test_budget_rejects_subcent_fees_at_each_quantity(budget, robots, shipping, tax):
    data = {"cap_usd": "50", "fit_confirmed": True, "items": [
        {"item": "sample", "quantity": robots, "price_status": "verified", "unit_usd": "9.90"},
    ]}
    with pytest.raises(ValueError, match="exact USD cents"):
        budget(data, shipping, tax)


@pytest.mark.parametrize("tax,total,remaining,over", [
    ("0.50", 49.99, 0.01, False),
    ("0.51", 50.00, 0.00, False),
    ("0.52", 50.01, -0.01, True),
])
def test_exact_landed_cap_boundary(budget, tax, total, remaining, over):
    data = {"cap_usd": "50", "fit_confirmed": True, "items": [
        {"item": "sample", "quantity": 1, "price_status": "verified", "unit_usd": "48.99"},
    ]}
    result = budget(data, "0.50", tax)
    assert result["quoted_total_usd"] == total
    assert result["remaining_under_cap_usd"] == remaining
    assert result["planning_over_cap"] is over
    assert result["purchase_ready"] is (not over)


@pytest.mark.parametrize("fit,checks,status,pending,unquoted,quote,ready", [
    (True, {"electrical": True}, "verified", [], [], 10.0, True),
    (False, {"electrical": True}, "verified", [], [], 10.0, False),
    (True, {"electrical": False}, "verified", ["electrical"], [], 10.0, False),
    (True, {"electrical": True}, "estimated", [], ["sample"], None, False),
])
def test_known_planning_cost_does_not_bypass_independent_readiness_gates(
    budget, fit, checks, status, pending, unquoted, quote, ready,
):
    data = {"cap_usd": "50", "fit_confirmed": fit, "readiness_checks": checks, "items": [
        {"item": "sample", "quantity": 2, "price_status": status, "unit_usd": "4.50"},
    ]}
    result = budget(data, "0.75", "0.25")
    assert result["known_subtotal_usd"] == 9.0
    assert result["planning_total_usd"] == 10.0
    assert result["remaining_under_cap_usd"] == 40.0
    assert result["planning_over_cap"] is False
    assert result["unknown_price_items"] == []
    assert result["unknown_landed_fees"] == []
    assert result["pending_checks"] == pending
    assert result["unquoted_items"] == unquoted
    assert result["quoted_total_usd"] == quote
    assert result["purchase_ready"] is ready


def test_known_cost_floor_over_cap_even_with_missing_prices_and_fees(budget):
    data = {"cap_usd": "50", "fit_confirmed": True, "items": [
        {"item": "known", "quantity": 2, "price_status": "verified", "unit_usd": "25.00"},
        {"item": "missing", "quantity": 1, "price_status": "verified", "unit_usd": None},
    ]}
    result = budget(data, "0.01", None)
    assert result["known_subtotal_usd"] == 50.0
    assert result["known_landed_subtotal_usd"] == 50.01
    assert result["unknown_price_items"] == ["missing"]
    assert result["unquoted_items"] == ["missing"]
    assert result["unknown_landed_fees"] == ["tax"]
    assert result["parts_estimate_usd"] is None
    assert result["planning_total_usd"] is None
    assert result["quoted_total_usd"] is None
    assert result["remaining_under_cap_usd"] is None
    assert result["planning_over_cap"] is True
    assert result["purchase_ready"] is False
