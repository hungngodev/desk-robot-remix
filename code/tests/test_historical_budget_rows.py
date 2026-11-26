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
