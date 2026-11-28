"""Regress split power accounting through the first unit checkout presentation.

Records are synthetic and prevalidated for this presentation boundary only.
They do not authorize physical hardware or purchases.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/procurement_release.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("power_checkout_presentation", SCRIPT)
assert spec and spec.loader
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def _report():
    return release.generate(json.loads(release.PLAN.read_text(encoding="utf-8")))


def _cost():
    return {
        "scope": "first_robot",
        "calculation_complete_not_physical_approval": True,
        "payable_now_cents": 400,
        "prior_paid_orders_cents": 0,
        "prototype_cumulative_cents": 400,
        "remaining_under_cap_cents": 4600,
    }


def _quote(role, index=0):
    return {
        "role_key": role,
        "seller": f"Supplier-{index}",
        "sku": "SKU-" + role.rsplit(":", 1)[-1],
        "pcb_revision": f"rev-{index}",
        "quantity_packages": index + 1,
        "units_per_package": 1,
        "package_price_usd": f"{index + 1}.25",
        "quoted_at": "2026-11-22",
        "stock_evidence_url": f"https://example.org/parts/{index}",
        "quote_reference": f"example-{index}",
    }


def _power_row(report):
    return next(row for row in report["robots"] if row["id"] == "cap_power")


def test_split_power_checkout_preserves_child_quotes_in_builder_view():
    roles = [release.POWER_PARENT_ROLE + ":" + child
             for child in release.POWER_CHILDREN]
    expected_quotes = [_quote(role, idx) for idx, role in enumerate(roles)]
    report = release.attach_verified_checkout_evidence(
        _report(), _cost(),
        {"power_package_mode": "separate_components",
         "lines": expected_quotes,
         "seller_charges": []},
    )
    recorded = _power_row(report)["verified_checkout_quotes"]
    assert recorded == expected_quotes
    markdown = release.render_first_robot_markdown(report)
    list_two = markdown.split("## 2. First-unit remaining slots", 1)[1]
    cap_power_row = next(
        line for line in list_two.splitlines()
        if line.startswith("| ") and "robot:cap_power:" in line
    )
    for quote in expected_quotes:
        expected_fragment = (
            f"{quote['role_key']} {quote['seller']} {quote['sku']} "
            f"rev {quote['pcb_revision']}; "
            f"{quote['quantity_packages']} package(s) x "
            f"{quote['units_per_package']} unit(s) at "
            f"USD {quote['package_price_usd']}/package"
        )
        assert expected_fragment in cap_power_row


def test_complete_kit_still_attaches_one_parent_quote_only():
    report = release.attach_verified_checkout_evidence(
        _report(), _cost(),
        {"power_package_mode": "complete_kit",
         "lines": [_quote(release.POWER_PARENT_ROLE)],
         "seller_charges": []},
    )
    assert [item["role_key"] for item in
            _power_row(report)["verified_checkout_quotes"]] == [
                release.POWER_PARENT_ROLE,
            ]


@pytest.mark.parametrize("role,mode", [
    ("robot:cap_power:unknown_part", "separate_components"),
    ("robot:cap_power:bq24075_charger_candidate", "complete_kit"),
    ("robot:does_not_exist", "separate_components"),
])
def test_unrelated_or_unselected_power_line_still_fails_closed(role, mode):
    with pytest.raises(ValueError, match="unknown shopping role"):
        release.attach_verified_checkout_evidence(
            _report(), _cost(),
            {"power_package_mode": mode, "lines": [_quote(role)],
             "seller_charges": []},
        )
