"""Keep the builder's stated spending ceiling tied to the canonical ledger."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

HARDWARE = Path(__file__).resolve().parents[2] / "docs/hardware"


def _validate_budget_guidance(ledger: dict, guide: str) -> None:
    cap = ledger["cap_usd"]
    paid = ledger["reported_already_purchased_usd"]
    receipt = ledger["paid_reconciliation"]
    assert ledger["currency"] == "USD"
    assert cap == Decimal("50.00")
    assert paid == receipt["payment_total_usd"]
    assert receipt["payment_total_verified"] is True
    assert ledger["all_project_prior_spend_reconciled"] is False
    assert receipt["all_project_prior_spend_reconciled"] is False
    normalized = " ".join(guide.split())
    assert (
        f"The USD {cap:.2f} cap minus the known USD {paid:.2f} payment "
        f"leaves at most USD {cap - paid:.2f}"
    ) in normalized
    assert "not a verified remaining allowance" in normalized
    assert "[prior-paid-ledger.json](prior-paid-ledger.json)" in normalized
    for field in ("shipping_usd", "tax_usd", "duties_usd", "discount_usd"):
        assert f"`{field}`" in normalized
    assert "missing charges are not zero" in normalized
    assert "an unknown landed total stays HOLD" in normalized
    assert "not incurred spending or a verified minimum shortfall" in normalized


@pytest.fixture
def guidance():
    ledger = json.loads(
        (HARDWARE / "prior-paid-ledger.json").read_text(encoding="utf-8"),
        parse_float=Decimal,
    )
    guide = (HARDWARE / "one-robot-inventory-and-shopping.md").read_text(encoding="utf-8")
    return ledger, guide


def test_first_unit_budget_guidance_matches_ledger(guidance):
    _validate_budget_guidance(*guidance)


@pytest.mark.parametrize(
    "old,new",
    [
        ("USD 50.00 cap", "USD 55.00 cap"),
        ("known USD 13.67 payment", "known USD 13.66 payment"),
        ("at most USD 36.33", "at most USD 36.34"),
        ("not a verified remaining allowance", "a verified remaining allowance"),
        ("`shipping_usd`", "estimated shipping"),
        ("`tax_usd`", "estimated tax"),
        ("`duties_usd`", "estimated duties"),
        ("`discount_usd`", "estimated discount"),
        ("missing charges are not zero", "missing charges are zero"),
        ("an unknown landed total stays HOLD", "an unknown landed total is approved"),
        ("not incurred spending or a verified minimum shortfall", "incurred spending"),
    ],
)
def test_first_unit_budget_guidance_rejects_drift(guidance, old, new):
    ledger, guide = guidance
    assert old in guide
    with pytest.raises(AssertionError):
        _validate_budget_guidance(ledger, guide.replace(old, new, 1))
