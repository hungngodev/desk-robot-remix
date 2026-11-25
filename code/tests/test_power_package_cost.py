"""A cap_power logical role must price actual complete physical subparts."""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/procurement_release.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("power_package_release", SCRIPT)
assert spec and spec.loader
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def quote(role, sku, packages=1, *, kit=None):
    line = {
        "role_key": role, "seller": "TestSupplier",
        "sku": sku, "pcb_revision": "revA",
        "quantity_packages": packages, "units_per_package": 1,
        "package_price_usd": "2.00",
        "quote_reference": "exact-cart-" + sku,
        "quoted_at": date.today().isoformat(),
        "stock_checked_at": date.today().isoformat(),
        "stock_evidence_url": "https://example.org/catalog/" + sku,
    }
    if kit is not None:
        line["kit_components"] = kit
    return line


def kit_contents():
    return [
        {"id": ident, "vendor": "MeasuredMaker",
         "sku": "selected-" + ident, "pcb_revision": "revA",
         "quantity_per_kit": 1}
        for ident in release.POWER_CHILDREN
    ]


def report_quote(monkeypatch, mode, lines, *, scope="first_robot", qty=1):
    monkeypatch.setattr(
        release, "cost_requirements",
        lambda _report, _scope: (
            {release.POWER_PARENT_ROLE: qty},
            {release.POWER_PARENT_ROLE: "robot"},
        ),
    )
    costs = {
        "scope": scope, "currency": "USD",
        "power_package_mode": mode,
        "lines": lines, "inventory": [],
        "paid_in_flight": [],
        "seller_charges": [{
            "seller": "TestSupplier", "shipping_usd": "0.00",
            "tax_usd": "0.00", "duties_usd": "0.00",
            "discount_usd": "0.00",
        }],
        "paid_orders_complete": True,
        "paid_orders": [{
            "order_reference": "test-sense-payment",
            "total_paid_usd": "13.67",
            "allocations": [{"role_key": "robot:xiao_sense", "quantity": 1}],
        }] if scope == "first_robot" else [],
    }
    return release.cost_quote({}, {"costs": costs}, scope)


def test_complete_power_kit_requires_exact_four_carriers():
    assert release.complete_power_kit_contents(kit_contents())
    incomplete = kit_contents()[:-1]
    assert not release.complete_power_kit_contents(incomplete)
    duplicate = kit_contents()
    duplicate[-1] = dict(duplicate[0])
    assert not release.complete_power_kit_contents(duplicate)
    overfilled = kit_contents()
    overfilled[0]["quantity_per_kit"] = True
    assert not release.complete_power_kit_contents(overfilled)
    wrong = kit_contents()
    wrong[0]["pcb_revision"] = " "
    assert not release.complete_power_kit_contents(wrong)


def test_first_robot_exact_complete_kit_charges_once(monkeypatch):
    cost = report_quote(
        monkeypatch, "complete_kit",
        [quote(release.POWER_PARENT_ROLE, "COMPLETE-PACK", kit=kit_contents())],
    )
    assert cost["errors"] == []
    assert cost["calculation_complete_not_physical_approval"]
    assert cost["payable_now_cents"] == 200
    assert cost["prototype_cumulative_cents"] == 1567


@pytest.mark.parametrize("mutation", [
    lambda lines: lines[0]["kit_components"].pop(),
    lambda lines: lines[0]["kit_components"][0].update(
        sku="",
    ),
    lambda lines: lines[0].pop("kit_components"),
    lambda lines: lines.append(quote(
        release.POWER_PARENT_ROLE + ":" + release.POWER_CHILDREN[0], "DUPLICATE"
    )),
    lambda lines: lines.append(quote(release.POWER_PARENT_ROLE, "SECOND-KIT")),
])
def test_partial_or_double_charged_power_kit_is_never_complete(
    monkeypatch, mutation,
):
    lines = [quote(release.POWER_PARENT_ROLE, "COMPLETE-PACK",
                   kit=kit_contents())]
    mutation(lines)
    cost = report_quote(monkeypatch, "complete_kit", lines)
    assert not cost["calculation_complete_not_physical_approval"]
    assert cost["payable_now_cents"] is None
    assert cost["prototype_cumulative_cents"] is None


def test_separate_power_parts_cost_four_real_lines(monkeypatch):
    lines = [
        quote(release.POWER_PARENT_ROLE + ":" + part, part)
        for part in release.POWER_CHILDREN
    ]
    cost = report_quote(monkeypatch, "separate_components", lines)
    assert cost["errors"] == []
    assert cost["calculation_complete_not_physical_approval"]
    assert cost["payable_now_cents"] == 800
    assert cost["quoted_units_applied_to_roles"] == {
        release.POWER_PARENT_ROLE + ":" + part: 1
        for part in release.POWER_CHILDREN
    }


@pytest.mark.parametrize("mutation", [
    lambda lines: lines.pop(),
    lambda lines: lines.append(
        quote(release.POWER_PARENT_ROLE, "UNJUSTIFIED-PARENT")
    ),
    lambda lines: lines.append(dict(lines[0])),
])
def test_separate_parts_reject_missing_child_parent_mix_or_duplicate(
    monkeypatch, mutation,
):
    lines = [
        quote(release.POWER_PARENT_ROLE + ":" + part, part)
        for part in release.POWER_CHILDREN
    ]
    mutation(lines)
    cost = report_quote(monkeypatch, "separate_components", lines)
    assert not cost["calculation_complete_not_physical_approval"]
    assert cost["payable_now_cents"] is None


def test_missing_selection_cannot_price_only_abstract_power_parent(monkeypatch):
    cost = report_quote(
        monkeypatch, None, [quote(release.POWER_PARENT_ROLE, "CHIP-ONLY")],
    )
    assert not cost["calculation_complete_not_physical_approval"]
    assert cost["payable_now_cents"] is None
    assert any("power kit or all separately purchased" in e
               for e in cost["errors"])


def test_fleet_power_parts_are_five_sets_without_first_unit_cap(monkeypatch):
    lines = [
        quote(release.POWER_PARENT_ROLE + ":" + part, part, packages=5)
        for part in release.POWER_CHILDREN
    ]
    cost = report_quote(
        monkeypatch, "separate_components", lines, scope="fleet", qty=5,
    )
    assert cost["errors"] == []
    assert cost["payable_now_cents"] == 4000
    assert cost["prototype_cap_cents"] is None
    assert cost["within_prototype_cap"] is None
