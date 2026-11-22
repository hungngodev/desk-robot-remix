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


def _quote(role):
    return {
        "role_key": role,
        "seller": "Example supplier",
        "sku": "SKU-" + role.rsplit(":", 1)[-1],
        "pcb_revision": "1",
        "quantity_packages": 1,
        "units_per_package": 1,
        "package_price_usd": "1.00",
        "quoted_at": "2026-11-22",
        "stock_evidence_url": "https://example.org/parts",
        "quote_reference": "example",
    }


def _power_row(report):
    return next(row for row in report["robots"] if row["id"] == "cap_power")


def test_split_power_checkout_preserves_child_quotes_in_builder_view():
    roles = [release.POWER_PARENT_ROLE + ":" + child
             for child in release.POWER_CHILDREN]
    report = release.attach_verified_checkout_evidence(
        _report(), _cost(),
        {"power_package_mode": "separate_components",
         "lines": [_quote(role) for role in roles],
         "seller_charges": []},
    )
    recorded = _power_row(report)["verified_checkout_quotes"]
    assert [quote["role_key"] for quote in recorded] == roles
    assert len({quote["sku"] for quote in recorded}) == len(roles)
    markdown = release.render_first_robot_markdown(report)
    for role in roles:
        assert role in markdown
        assert "SKU-" + role.rsplit(":", 1)[-1] in markdown


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
