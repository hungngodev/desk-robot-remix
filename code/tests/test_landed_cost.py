"""Regression coverage for cumulative first-unit delivered cost, not cart approval."""
import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/landed_cost.py"
spec = importlib.util.spec_from_file_location("landed_cost", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def test_shared_integer_cost_arithmetic():
    subtotal = mod.sum_line_cost_cents([(3, 1666), (2, 11)])
    assert subtotal == 5020
    assert mod.landed_total_cents(
        subtotal, shipping=21, tax=10, duties=4, discount=15,
    ) == 5040
    with pytest.raises(ValueError, match="discount exceeds"):
        mod.landed_total_cents(1, shipping=0, tax=0, duties=0, discount=2)


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


def test_unavoidable_single_retail_pack_surplus_is_charged_once_and_reported():
    ev = sample()
    line = ev["lines"][0]
    line["sku"] = "SEALED-FIVE"
    line["units_per_package"] = 5
    line["package_price_usd"] = "3.00"
    line["minimum_pack_review"] = {
        "extra_units": 4,
        "seller_minimum_pack_url": "https://supplier.example/pack-five",
        "reviewed": True,
    }
    out = calculate(ev)
    assert out["errors"] == []
    assert out["calculation_complete_not_physical_approval"]
    assert out["reviewed_pack_surplus_units"] == {
        "robot:cliff_obstacle": 4
    }
    assert out["quoted_units_applied_to_roles"] == {
        "robot:cliff_obstacle": 1, "robot:i2c_mux": 1
    }
    assert out["payable_now_cents"] == 779
    assert out["prototype_cumulative_cents"] == 2029
    assert not out["landed_price_is_a_verified_supplier_checkout"]


@pytest.mark.parametrize("mutation", [
    lambda line: line.pop("minimum_pack_review"),
    lambda line: line["minimum_pack_review"].update(extra_units=3),
    lambda line: line["minimum_pack_review"].update(reviewed=False),
    lambda line: line["minimum_pack_review"].update(
        seller_minimum_pack_url="http://unsafe.example/pack-five"
    ),
    lambda line: line.update(quantity_packages=2),
    lambda line: line["minimum_pack_review"].update(extra_units=True),
    lambda line: line["minimum_pack_review"].update(extra_units="4"),
])
def test_minimum_pack_never_waives_unreviewed_or_unnecessary_excess(mutation):
    ev = sample()
    line = ev["lines"][0]
    line["units_per_package"] = 5
    line["minimum_pack_review"] = {
        "extra_units": 4,
        "seller_minimum_pack_url": "https://supplier.example/pack-five",
        "reviewed": True,
    }
    mutation(line)
    out = calculate(ev)
    assert out["payable_now_cents"] is None
    assert any("minimum pack surplus lacks exact review" in e for e in out["errors"])


def test_pack_review_requires_actual_excess_and_single_supplier_line():
    ev = sample()
    line = ev["lines"][0]
    line["minimum_pack_review"] = {
        "extra_units": 4,
        "seller_minimum_pack_url": "https://supplier.example/pack-five",
        "reviewed": True,
    }
    no_surplus = calculate(ev)
    assert no_surplus["payable_now_cents"] is None
    assert any("without genuine surplus" in e for e in no_surplus["errors"])
    line["units_per_package"] = 5
    ev["lines"].append({
        **line, "sku": "ANOTHER-PACK", "quote_reference": "other-quote",
        "minimum_pack_review": None,
    })
    duplicate_surplus = calculate(ev)
    assert duplicate_surplus["payable_now_cents"] is None
    assert any("surplus lacks exact review" in e for e in duplicate_surplus["errors"])


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
                        "acquisition_kind": "already_owned",
                         "inspection_receipt_url": "https://github.com/org/record"}]
    out = calculate(ev)
    assert out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] == 608
    ev["inventory"] = []
    ev["paid_orders"][0]["allocations"] = [
        {"role_key": "robot:i2c_mux", "quantity": 1}
    ]
    ev["paid_in_flight"] = [{"role_key": "robot:i2c_mux",
                            "quantity": 1, "order_reference": "already-paid"}]
    out = calculate(ev)
    assert out["calculation_complete_not_physical_approval"]
    assert out["awaiting_arrival_roles"] == ["robot:i2c_mux"]



def test_excluded_zero_target_paid_item_is_not_marked_awaiting_arrival():
    # A paid order for a deferred role must not silently enter the two-list
    # incoming stock view, even though the overall cost gate already holds.
    ev = sample()
    ev["lines"].pop()  # no new purchase for the excluded mux
    ev["paid_orders"][0]["allocations"] = [
        {"role_key": "robot:i2c_mux", "quantity": 1},
    ]
    ev["paid_in_flight"] = [{
        "role_key": "robot:i2c_mux", "quantity": 1,
        "order_reference": "already-paid",
    }]
    required = {"robot:cliff_obstacle": 1, "robot:i2c_mux": 0}
    excluded = mod.account_landed_cost(
        ev, required, CATEGORIES, expected_scope="evaluation",
    )
    assert not excluded["calculation_complete_not_physical_approval"]
    assert excluded["payable_now_cents"] is None
    assert any("unknown or excluded in-flight role" in error
               for error in excluded["errors"])
    assert "robot:i2c_mux" not in excluded["awaiting_arrival_roles"]

    # The same inspected allocation is legitimate when the role is selected.
    allowed = calculate(ev)
    assert allowed["errors"] == []
    assert allowed["calculation_complete_not_physical_approval"]
    assert allowed["awaiting_arrival_roles"] == ["robot:i2c_mux"]


def test_paid_delivered_inventory_and_in_flight_share_one_order_allocation():
    """One paid mux cannot cover both received and in-transit requirements."""
    ev = sample()
    ev["lines"].pop()  # no new mux quote, all muxes need genuine paid coverage
    ev["paid_orders"][0]["allocations"] = [
        {"role_key": "robot:i2c_mux", "quantity": 1},
    ]
    ev["inventory"] = [{
        "role_key": "robot:i2c_mux", "usable_allocated": 1,
        "acquisition_kind": "paid_order",
        "order_reference": "already-paid",
        "inspection_receipt_url": "https://github.com/org/mux-inspected",
    }]
    ev["paid_in_flight"] = [{
        "role_key": "robot:i2c_mux", "quantity": 1,
        "order_reference": "already-paid",
    }]
    need_two = {**REQUIRED, "robot:i2c_mux": 2}
    def run():
        return mod.account_landed_cost(
            ev, need_two, CATEGORIES, expected_scope="evaluation",
        )

    duplicate = run()
    assert not duplicate["calculation_complete_not_physical_approval"]
    assert "robot:i2c_mux" in duplicate["unaccounted_roles"]
    assert any("already consumed by inspected inventory" in e
               for e in duplicate["errors"])
    assert duplicate["payable_now_cents"] is None
    assert duplicate["within_prototype_cap"] is False

    # Two paid physical units, one with its own inspection and one still
    # awaiting arrival, genuinely cover the same role without buying twice.
    ev["paid_orders"][0]["allocations"][0]["quantity"] = 2
    distinct = run()
    assert distinct["errors"] == []
    assert distinct["calculation_complete_not_physical_approval"]
    assert distinct["awaiting_arrival_roles"] == ["robot:i2c_mux"]
    assert distinct["payable_now_cents"] == 608

    ev["inventory"][0]["usable_allocated"] = 2
    overclaimed = run()
    assert not overclaimed["calculation_complete_not_physical_approval"]
    assert any("already consumed" in e for e in overclaimed["errors"])


def test_inspected_stock_requires_explicit_origin_and_paid_reference():
    ev = sample()
    ev["lines"].pop()
    stock = {
        "role_key": "robot:i2c_mux", "usable_allocated": 1,
        "inspection_receipt_url": "https://github.com/org/mux-inspected",
    }
    ev["inventory"] = [stock]
    result = calculate(ev)
    assert not result["calculation_complete_not_physical_approval"]
    assert any("acquisition_kind" in error for error in result["errors"])

    stock["acquisition_kind"] = "paid_order"
    result = calculate(ev)
    assert any("inspected order" in error for error in result["errors"])
    stock["order_reference"] = "not-registered"
    result = calculate(ev)
    assert any("lacks an order record" in error for error in result["errors"])
    stock["acquisition_kind"] = "already_owned"
    result = calculate(ev)
    assert any("already owned stock cannot claim" in error
               for error in result["errors"])


def test_duplicate_buying_covered_stock_fails_closed():
    ev = sample()
    ev["inventory"] = [{"role_key": "robot:i2c_mux",
                        "usable_allocated": 1,
                        "acquisition_kind": "already_owned",
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


@pytest.mark.parametrize("invalid", [
    "1e999999", "1e-999999", "1.0000000000000000000000000001",
    "0.0000000000000000000000000001", "1000000000001",
])
def test_extreme_supplier_decimals_fail_closed_without_overflow_or_underflow(
    invalid,
):
    with pytest.raises(ValueError):
        mod.cents(invalid, "supplier USD")


@pytest.mark.parametrize("field,location", [
    ("package_price_usd", "lines"),
    ("shipping_usd", "seller_charges"),
    ("total_paid_usd", "paid_orders"),
])
def test_extreme_money_in_any_receipt_bucket_does_not_crash_or_approve(
    field, location,
):
    ev = sample()
    ev[location][0][field] = "1e999999"
    out = calculate(ev)
    assert out["payable_now_cents"] is None
    assert out["prototype_cumulative_cents"] is None
    assert not out["calculation_complete_not_physical_approval"]
    assert out["errors"]


def test_exact_cents_with_arbitrarily_long_trailing_zeros_remain_valid():
    assert mod.cents("5.950000000000000000000000000000", "USD") == 595
    assert mod.cents("0e-999999", "USD") == 0
    with pytest.raises(ValueError, match="subcent"):
        mod.cents("0.0000000000000000000000000001", "USD")


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


def test_shared_delivery_charges_are_allocated_in_exact_cents():
    ev = sample()
    ev["lines"].append({
        **ev["lines"][0], "role_key": "dock:cradle", "sku": "CRADLE",
        "package_price_usd": "1.00",
    })
    required = {**REQUIRED, "dock:cradle": 1}
    categories = {**CATEGORIES, "dock:cradle": "dock"}
    out = mod.account_landed_cost(
        ev, required, categories, expected_scope="evaluation"
    )
    assert out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] == 755
    assert out["material_subtotals_cents"] == {
        "robot": 223, "dock": 100, "station": 0,
    }
    assert out["allocated_landed_subtotals_cents"] == {
        "robot": 521, "dock": 234, "station": 0,
    }
    assert sum(out["allocated_landed_subtotals_cents"].values()) == 755
    assert out["prototype_cumulative_cents"] == 2005
    assert not out["landed_price_is_a_verified_supplier_checkout"]


def test_incomplete_quote_hides_landed_category_allocation():
    ev = sample()
    del ev["seller_charges"][0]["shipping_usd"]
    out = calculate(ev)
    assert out["payable_now_cents"] is None
    assert out["allocated_landed_subtotals_cents"] is None


def test_free_items_split_shipping_by_units_without_dividing_by_zero():
    ev = sample()
    for line in ev["lines"]:
        line["package_price_usd"] = "0.00"
    ev["seller_charges"][0]["tax_usd"] = "0.00"
    categories = {
        "robot:cliff_obstacle": "robot",
        "robot:i2c_mux": "station",
    }
    out = mod.account_landed_cost(
        ev, REQUIRED, categories, expected_scope="evaluation"
    )
    assert out["payable_now_cents"] == 400
    assert out["allocated_landed_subtotals_cents"] == {
        "robot": 200, "dock": 0, "station": 200,
    }


def test_invalid_canonical_cost_category_fails_closed():
    ev = sample()
    categories = {**CATEGORIES, "robot:i2c_mux": "unknown"}
    out = mod.account_landed_cost(
        ev, REQUIRED, categories, expected_scope="evaluation"
    )
    assert out["payable_now_cents"] is None
    assert out["allocated_landed_subtotals_cents"] is None
    assert any("unknown robot, dock or station" in error for error in out["errors"])


def test_one_inspection_receipt_cannot_create_two_allocations():
    ev = sample()
    ev["lines"].pop(0)
    stock = {
        "role_key": "robot:cliff_obstacle", "usable_allocated": 1,
        "acquisition_kind": "already_owned",
        "inspection_receipt_url": "https://github.com/org/real-inspection",
    }
    ev["inventory"] = [stock.copy(), stock.copy()]
    requirements = {**REQUIRED, "robot:cliff_obstacle": 2}
    out = mod.account_landed_cost(ev, requirements, CATEGORIES,
                                  expected_scope="evaluation")
    assert out["payable_now_cents"] is None
    assert not out["calculation_complete_not_physical_approval"]
    assert any("duplicate inspection receipt" in err for err in out["errors"])
    # Separate physical inspections are valid even for the same part role.
    ev["inventory"][1]["inspection_receipt_url"] += "-second"
    out = mod.account_landed_cost(ev, requirements, CATEGORIES,
                                  expected_scope="evaluation")
    assert out["errors"] == []
    assert out["calculation_complete_not_physical_approval"]


def test_one_paid_order_cannot_be_counted_twice_for_one_role():
    ev = sample()
    ev["lines"].pop(0)
    claim = {
        "role_key": "robot:cliff_obstacle", "quantity": 1,
        "order_reference": "already-paid",
    }
    ev["paid_orders"][0]["allocations"] = [
        {"role_key": "robot:cliff_obstacle", "quantity": 1}
    ]
    ev["paid_in_flight"] = [claim.copy(), claim.copy()]
    requirements = {**REQUIRED, "robot:cliff_obstacle": 2}
    out = mod.account_landed_cost(ev, requirements, CATEGORIES,
                                  expected_scope="evaluation")
    assert out["payable_now_cents"] is None
    assert any("duplicate in-flight order allocation" in err
               for err in out["errors"])
    ev["paid_orders"].append({
        "order_reference": "second-paid", "total_paid_usd": "2.00",
        "allocations": [{"role_key": "robot:cliff_obstacle", "quantity": 1}],
    })
    ev["paid_in_flight"][1]["order_reference"] = "second-paid"
    out = mod.account_landed_cost(ev, requirements, CATEGORIES,
                                  expected_scope="evaluation")
    assert out["errors"] == []
    assert out["awaiting_arrival_roles"] == ["robot:cliff_obstacle"]


def test_paid_reference_cannot_cover_an_unrelated_in_flight_role():
    ev = sample()
    ev["lines"].pop()
    ev["paid_orders"][0]["allocations"] = [
        {"role_key": "robot:cliff_obstacle", "quantity": 1}
    ]
    ev["paid_in_flight"] = [{
        "role_key": "robot:i2c_mux", "quantity": 1,
        "order_reference": "already-paid",
    }]
    out = calculate(ev)
    assert not out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] is None
    assert "robot:i2c_mux" in out["unaccounted_roles"]
    assert any(
        "does not allocate claimed role and quantity" in err
        for err in out["errors"]
    )


def test_paid_order_allocation_cannot_be_overclaimed():
    ev = sample()
    ev["lines"].pop()
    ev["paid_orders"][0]["allocations"] = [
        {"role_key": "robot:i2c_mux", "quantity": 1}
    ]
    ev["paid_in_flight"] = [{
        "role_key": "robot:i2c_mux", "quantity": 2,
        "order_reference": "already-paid",
    }]
    out = calculate(ev)
    assert not out["calculation_complete_not_physical_approval"]
    assert any(
        "does not allocate claimed role and quantity" in err
        for err in out["errors"]
    )


def test_one_inspection_can_cover_distinct_roles_without_double_counting():
    ev = sample()
    ev["lines"] = []
    ev["seller_charges"] = []
    receipt = "https://github.com/org/combined-inspection"
    ev["inventory"] = [
        {"role_key": role, "usable_allocated": 1,
         "acquisition_kind": "already_owned",
         "inspection_receipt_url": receipt}
        for role in REQUIRED
    ]
    out = calculate(ev)
    assert out["errors"] == []
    assert out["payable_now_cents"] == 0
    assert out["prototype_cumulative_cents"] == 1250


def test_duplicate_quote_row_cannot_fake_two_sku_units():
    ev = sample()
    cliff = dict(ev["lines"][0])
    ev["lines"].insert(1, cliff)
    required = {**REQUIRED, "robot:cliff_obstacle": 2}
    out = mod.account_landed_cost(ev, required, CATEGORIES,
                                  expected_scope="evaluation")
    assert not out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] is None
    assert any("duplicate quoted SKU" in err for err in out["errors"])
    # Two independently identified supplier quotes may each cover one
    # package, and the common seller freight is still charged just once.
    ev["lines"][1]["quote_reference"] = "second-separate-quote"
    out = mod.account_landed_cost(ev, required, CATEGORIES,
                                  expected_scope="evaluation")
    assert out["errors"] == []
    assert out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] == 831


def test_one_quote_can_legitimately_cover_distinct_skus():
    ev = sample()  # Both quoted items share one supplier quote reference.
    out = calculate(ev)
    assert out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] == 655


@pytest.mark.parametrize("quoted_at", [
    "2026-02-30", "20261118", "not-a-date", "2026-W47-3",
    "2026-11-18T12:00:00", 20261118, None,
])
def test_quote_requires_an_actual_iso_calendar_date(quoted_at):
    ev = sample()
    ev["lines"][0]["quoted_at"] = quoted_at
    out = calculate(ev)
    assert not out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] is None
    assert any("quote date must be a YYYY-MM-DD calendar date" in error
               for error in out["errors"])


def test_future_supplier_quote_is_not_valid_checkout_evidence():
    ev = sample()
    ev["lines"][0]["quoted_at"] = "2099-01-01"
    out = calculate(ev)
    assert not out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] is None
    assert any("supplier quote date cannot be in the future" in error
               for error in out["errors"])


def test_actual_leap_day_quote_remains_valid():
    ev = sample()
    ev["lines"][0]["quoted_at"] = "2024-02-29"
    out = calculate(ev)
    assert out["calculation_complete_not_physical_approval"]
    assert out["payable_now_cents"] == 655


def test_fleet_total_is_not_rejected_by_first_unit_prototype_cap():
    ev = sample()
    ev["scope"] = "fleet"
    for line in ev["lines"]:
        line["quoted_at"] = date.today().isoformat()
        line["stock_checked_at"] = date.today().isoformat()
    ev["paid_orders"][0]["total_paid_usd"] = "49.00"
    fleet = mod.account_landed_cost(
        ev, REQUIRED, CATEGORIES, expected_scope="fleet"
    )
    assert fleet["calculation_complete_not_physical_approval"]
    assert fleet["errors"] == []
    assert fleet["prototype_cumulative_cents"] == 5555
    assert fleet["payable_now_cents"] == 655
    assert fleet["prototype_cap_cents"] is None
    assert fleet["remaining_under_cap_cents"] is None
    assert fleet["within_prototype_cap"] is None

    ev["scope"] = "first_robot"
    first = mod.account_landed_cost(
        ev, REQUIRED, CATEGORIES, expected_scope="first_robot"
    )
    assert first["calculation_complete_not_physical_approval"]
    assert first["prototype_cap_cents"] == 5000
    assert first["remaining_under_cap_cents"] == -555
    assert first["within_prototype_cap"] is False


def _current_checkout_sample():
    evidence = sample()
    evidence["scope"] = "first_robot"
    for line in evidence["lines"]:
        line["quoted_at"] = date.today().isoformat()
        line["stock_checked_at"] = date.today().isoformat()
    return evidence


def test_buy07_strict_quote_requires_recent_stock_confirmation():
    ev = _current_checkout_sample()
    assert mod.account_landed_cost(ev, REQUIRED, CATEGORIES)["errors"] == []
    del ev["lines"][0]["stock_checked_at"]
    result = mod.account_landed_cost(ev, REQUIRED, CATEGORIES)
    assert result["payable_now_cents"] is None
    assert any("stock_checked_at" in e for e in result["errors"])
    ev["lines"][0]["stock_checked_at"] = (
        date.today() - timedelta(days=8)
    ).isoformat()
    result = mod.account_landed_cost(ev, REQUIRED, CATEGORIES)
    assert any("stock check predates" in e for e in result["errors"])


def test_buy07_stale_price_needs_bounded_validity_or_new_seller_proof():
    ev = _current_checkout_sample()
    line = ev["lines"][0]
    line["quoted_at"] = (date.today() - timedelta(days=20)).isoformat()
    result = mod.account_landed_cost(ev, REQUIRED, CATEGORIES)
    assert result["payable_now_cents"] is None
    assert any("supplier quote is stale" in e for e in result["errors"])
    line["quote_valid_through"] = (
        date.today() + timedelta(days=5)
    ).isoformat()
    assert mod.account_landed_cost(ev, REQUIRED, CATEGORIES)["errors"] == []
    line["quote_valid_through"] = (
        date.today() + timedelta(days=15)
    ).isoformat()
    assert any("30-day validity" in e for e in
               mod.account_landed_cost(ev, REQUIRED, CATEGORIES)["errors"])
    line["quote_valid_through"] = (
        date.today() - timedelta(days=1)
    ).isoformat()
    assert any("has expired" in e for e in
               mod.account_landed_cost(ev, REQUIRED, CATEGORIES)["errors"])
    del line["quote_valid_through"]
    line["price_reconfirmed_at"] = date.today().isoformat()
    assert any("supplier evidence" in e for e in
               mod.account_landed_cost(ev, REQUIRED, CATEGORIES)["errors"])
    line["price_reconfirmation_url"] = "https://seller.example/quote-confirmation"
    assert mod.account_landed_cost(ev, REQUIRED, CATEGORIES)["errors"] == []
    line["price_reconfirmed_at"] = (
        date.today() - timedelta(days=8)
    ).isoformat()
    assert any("price reconfirmation is stale" in e for e in
               mod.account_landed_cost(ev, REQUIRED, CATEGORIES)["errors"])


def test_buy07_future_or_invalid_date_cannot_qualify_checkout():
    for field, value in (
        ("stock_checked_at", (date.today() + timedelta(days=1)).isoformat()),
        ("stock_checked_at", "2026-02-30"),
        ("quote_valid_through", "bad-date"),
        ("price_reconfirmed_at", True),
    ):
        ev = _current_checkout_sample()
        ev["lines"][0][field] = value
        result = mod.account_landed_cost(ev, REQUIRED, CATEGORIES)
        assert result["payable_now_cents"] is None, (field, value)
        assert result["errors"], (field, value)


def test_buy07_historical_evaluation_preserves_nonapproving_cost_math():
    ev = sample()
    ev["lines"][0]["quoted_at"] = "2024-02-29"
    result = calculate(ev)
    assert result["calculation_complete_not_physical_approval"]
    assert not result["landed_price_is_a_verified_supplier_checkout"]


@pytest.mark.parametrize("field", ["quantity_packages", "units_per_package"])
def test_enormous_supplier_quantity_fails_before_cost_arithmetic(field):
    ev = sample()
    ev["lines"][0][field] = 10**1200
    result = calculate(ev)
    assert result["payable_now_cents"] is None
    assert any("quantity exceeds 10000 unit bound" in e for e in result["errors"])


@pytest.mark.parametrize("source", ["inventory", "paid_order", "in_flight"])
def test_enormous_stock_allocation_fails_closed(source):
    ev = sample()
    huge = 10**1200
    if source == "inventory":
        ev["inventory"] = [{
            "role_key": "robot:cliff_obstacle",
            "usable_allocated": huge,
            "acquisition_kind": "already_owned",
            "inspection_receipt_url": "https://supplier.example/inspection",
        }]
    elif source == "paid_order":
        ev["paid_orders"][0]["allocations"] = [{
            "role_key": "robot:cliff_obstacle", "quantity": huge
        }]
    else:
        ev["paid_orders"][0]["allocations"] = [{
            "role_key": "robot:cliff_obstacle", "quantity": 1
        }]
        ev["paid_in_flight"] = [{
            "role_key": "robot:cliff_obstacle",
            "quantity": huge, "order_reference": "already-paid",
        }]
    result = calculate(ev)
    assert result["payable_now_cents"] is None
    assert any("quantity exceeds 10000 unit bound" in e for e in result["errors"])


def test_canonical_role_count_is_bounded_before_accounting():
    huge_required = dict(REQUIRED)
    huge_required["robot:cliff_obstacle"] = 10**1200
    with pytest.raises(ValueError, match="Invalid canonical requirement count"):
        mod.account_landed_cost(
            sample(), huge_required, CATEGORIES, expected_scope="evaluation"
        )
    assert mod.positive_count(mod.MAX_ACCOUNTING_UNITS, "units") == 10000

@pytest.mark.parametrize("url", [
    "https://@example.org/receipt",
    "https://:@example.org/receipt",
    "\x00https://example.org/receipt",
    "https://example.org/\x00receipt",
    "https://example.org/\x7freceipt",
])
def test_ambiguous_supplier_evidence_url_cannot_qualify_cost(url):
    ev = sample()
    assert calculate(ev)["errors"] == []
    ev["lines"][0]["stock_evidence_url"] = url
    result = calculate(ev)
    assert result["payable_now_cents"] is None
    assert not result["calculation_complete_not_physical_approval"]
    assert any("stock evidence" in error for error in result["errors"])


def test_two_seller_duties_discounts_and_independent_freight_exact_cents():
    """Exercise nonzero duties/discounts across two sellers with missing/excess rejections."""
    ev = {
        "scope": "evaluation",
        "currency": "USD",
        "paid_orders_complete": True,
        "lines": [
            {
                "role_key": "robot:cliff_obstacle",
                "seller": "ElectroPeak",
                "sku": "SEN-19-006",
                "quantity_packages": 1,
                "units_per_package": 1,
                "package_price_usd": "3.00",
                "quote_reference": "ep-quote-1",
                "quoted_at": "2026-11-22",
                "stock_evidence_url": "https://electropeak.com/gy-530-vl53l0x",
            },
            {
                "role_key": "robot:i2c_mux",
                "seller": "DigiKey",
                "sku": "COM-05-067",
                "quantity_packages": 1,
                "units_per_package": 1,
                "package_price_usd": "5.00",
                "quote_reference": "dk-quote-1",
                "quoted_at": "2026-11-22",
                "stock_evidence_url": "https://www.digikey.com/tca9548a",
            },
        ],
        "seller_charges": [
            {
                "seller": "ElectroPeak",
                "shipping_usd": "1.50",
                "tax_usd": "0.24",
                "duties_usd": "1.25",
                "discount_usd": "0.67",
            },
            {
                "seller": "DigiKey",
                "shipping_usd": "2.00",
                "tax_usd": "0.45",
                "duties_usd": "0.80",
                "discount_usd": "1.10",
            },
        ],
        "paid_orders": [
            {"order_reference": "sense-paid", "total_paid_usd": "13.67"},
        ],
    }
    out = mod.account_landed_cost(
        ev, REQUIRED, CATEGORIES, expected_scope="evaluation",
    )
    assert out["errors"] == []
    assert out["calculation_complete_not_physical_approval"] is True
    # ElectroPeak: 300 + 150 + 24 + 125 - 67 = 532; DigiKey: 500 + 200 + 45 + 80 - 110 = 715
    assert out["seller_payable_cents"] == {"ElectroPeak": 532, "DigiKey": 715}
    assert out["payable_now_cents"] == 1247
    assert out["prior_paid_orders_cents"] == 1367
    assert out["prototype_cumulative_cents"] == 2614
    assert out["remaining_under_cap_cents"] == 2386

    for missing_field in ("shipping_usd", "tax_usd", "duties_usd", "discount_usd"):
        bad = {**ev, "seller_charges": [dict(ev["seller_charges"][0]), dict(ev["seller_charges"][1])]}
        del bad["seller_charges"][0][missing_field]
        res = mod.account_landed_cost(
            bad, REQUIRED, CATEGORIES, expected_scope="evaluation",
        )
        assert res["payable_now_cents"] is None, missing_field

    over_discount = {
        **ev,
        "seller_charges": [
            {**ev["seller_charges"][0], "discount_usd": "6.00"},
            dict(ev["seller_charges"][1]),
        ],
    }
    excess = mod.account_landed_cost(
        over_discount, REQUIRED, CATEGORIES, expected_scope="evaluation",
    )
    assert excess["payable_now_cents"] is None
    assert any("discount exceeds seller total" in err for err in excess["errors"])
