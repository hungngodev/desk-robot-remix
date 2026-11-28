"""Use the actual procurement CLI to distinguish quotes from purchase approval."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "code/scripts/procurement_release.py"


def run_cost(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT / "code", text=True, capture_output=True,
        check=False, timeout=20,
    )


def sample_quote():
    """Self-contained quoted two-piece fixture for CLI subprocess tests."""
    lines = []
    for role, sku, price in (
        ("robot:cliff_obstacle", "SEN-19-006", "1.76"),
        ("robot:i2c_mux", "COM-05-067", "0.47"),
    ):
        lines.append({
            "role_key": role,
            "seller": "ElectroPeak",
            "sku": sku,
            "quantity_packages": 1,
            "units_per_package": 1,
            "package_price_usd": price,
            "quote_reference": "fixture-quote",
            "quoted_at": "2026-11-18",
            "stock_evidence_url": "https://electropeak.com/quoted-fixture",
        })
    return {"costs": {
        "scope": "evaluation",
        "currency": "USD",
        "paid_orders_complete": True,
        "lines": lines,
        "seller_charges": [{
            "seller": "ElectroPeak",
            "shipping_usd": "4.00",
            "tax_usd": "0.32",
            "duties_usd": "0.00",
            "discount_usd": "0.00",
        }],
        "paid_orders": [{
            "order_reference": "already-paid",
            "total_paid_usd": "13.67",
            "allocations": [{"role_key": "robot:xiao_sense", "quantity": 1}],
        }],
    }}


def test_cli_without_supplier_quotation_shows_unknown_not_zero():
    result = run_cost("--format", "landed-cost-json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["scope"] == "first_robot"
    assert not data["calculation_complete_not_physical_approval"]
    assert data["payable_now_cents"] is None
    assert data["prototype_cumulative_cents"] is None
    assert data["unaccounted_roles"]
    assert not data["within_prototype_cap"]


def test_cli_reports_only_evaluation_cart_delivered_amount(tmp_path):
    path = tmp_path / "operator_quote.json"
    path.write_text(json.dumps(sample_quote()), encoding="utf-8")
    result = run_cost("--evidence", str(path),
                      "--format", "landed-cost-json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["scope"] == "evaluation"
    assert data["payable_now_cents"] == 655
    assert data["prototype_cumulative_cents"] == 2022
    assert not data["landed_price_is_a_verified_supplier_checkout"]
    assert data["material_subtotals_cents"]["robot"] == 223


@pytest.mark.parametrize("mutation", ["empty", "underpaid", "wrong_role"])
def test_evaluation_quote_cannot_erase_confirmed_payment(tmp_path, mutation):
    quote = sample_quote()
    orders = quote["costs"]["paid_orders"]
    if mutation == "empty":
        orders.clear()
    elif mutation == "underpaid":
        orders[0]["total_paid_usd"] = "13.66"
    else:
        orders[0]["allocations"][0]["role_key"] = "robot:oled"
    path = tmp_path / "unreconciled.json"
    path.write_text(json.dumps(quote), encoding="utf-8")
    result = run_cost("--evidence", str(path), "--format", "landed-cost-json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert not data["calculation_complete_not_physical_approval"]
    assert data["prior_paid_orders_cents"] is None
    assert data["documented_prior_paid_minimum_cents"] == 1367
    assert data["prototype_cumulative_cents"] is None
    assert data["payable_now_cents"] is None
    assert not data["within_prototype_cap"]
    assert any("Sense" in error for error in data["errors"])
    markdown = run_cost("--evidence", str(path), "--format", "landed-cost-markdown")
    assert markdown.returncode == 0, markdown.stderr
    assert "Previously paid: unknown (confirmed minimum $13.67)" in markdown.stdout


def test_cli_keeps_supplier_quote_distinct_from_irreversible_cart(tmp_path):
    path = tmp_path / "quote.json"
    path.write_text(json.dumps(sample_quote()), encoding="utf-8")
    result = run_cost("--evidence", str(path),
                      "--require-first-robot",
                      "--format", "first-robot-markdown")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "HOLD" in result.stderr


def test_markdown_missing_quotes_never_claims_zero_material_totals():
    result = run_cost("--format", "landed-cost-markdown")
    assert result.returncode == 0, result.stderr
    assert "Payable now: unknown" in result.stdout
    for category in ("Robot", "Dock", "Station"):
        assert f"{category} materials: unknown (incomplete quote)" in result.stdout
        assert f"{category} materials: $0.00" not in result.stdout


def test_markdown_budget_overrun_is_explicit_hold(tmp_path):
    quote = sample_quote()
    quote["costs"]["paid_orders"][0]["total_paid_usd"] = "49.00"
    path = tmp_path / "over_budget_quote.json"
    path.write_text(json.dumps(quote), encoding="utf-8")
    result = run_cost("--evidence", str(path), "--format", "landed-cost-markdown")
    assert result.returncode == 0, result.stderr
    assert "Cumulative prototype spending: $55.55" in result.stdout
    assert "HOLD: cumulative prototype spending exceeds the $50.00 cap" in result.stdout


def test_landed_cost_markdown_reports_delivered_category_allocation(tmp_path):
    path = tmp_path / "quote_with_delivery.json"
    path.write_text(json.dumps(sample_quote()), encoding="utf-8")
    result = run_cost("--evidence", str(path), "--format", "landed-cost-markdown")
    assert result.returncode == 0, result.stderr
    assert "Payable now: $6.55" in result.stdout
    assert "Robot materials: $2.23" in result.stdout
    assert "Robot allocated landed cost: $6.55" in result.stdout
    assert "Dock allocated landed cost: $0.00" in result.stdout
    assert "Station allocated landed cost: $0.00" in result.stdout
    assert "not individual supplier checkout prices" in result.stdout


def test_incomplete_quote_never_displays_fake_delivered_allocation():
    result = run_cost("--format", "landed-cost-markdown")
    assert result.returncode == 0, result.stderr
    assert "Allocated landed category costs: unknown (incomplete quote)" in result.stdout
    assert "Robot allocated landed cost: $0.00" not in result.stdout


def test_partial_supplier_total_is_explicitly_not_full_cart(tmp_path):
    quote = sample_quote()
    quote["costs"]["lines"].pop()
    path = tmp_path / "partial_seller_quote.json"
    path.write_text(json.dumps(quote), encoding="utf-8")
    result = run_cost("--evidence", str(path), "--format", "landed-cost-markdown")
    assert result.returncode == 0, result.stderr
    assert "Payable now: unknown" in result.stdout
    assert "Partial supplier quote ElectroPeak:" in result.stdout
    assert "Supplier ElectroPeak:" not in result.stdout
    assert "Allocated landed category costs: unknown (incomplete quote)" in result.stdout


@pytest.mark.parametrize("bad_scope", [[], {}, ["first_robot"], {"scope": "fleet"}])
def test_unhashable_quote_scope_is_rejected_without_traceback(tmp_path, bad_scope):
    path = tmp_path / "invalid-scope.json"
    path.write_text(json.dumps({"costs": {"scope": bad_scope}}), encoding="utf-8")
    result = run_cost("--evidence", str(path), "--format", "landed-cost-json")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "Unknown cost quote scope" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("bad_mode", [[], {}, ["complete_kit"], {"mode": "complete_kit"}])
def test_unhashable_power_mode_preserves_unknown_cost(tmp_path, bad_mode):
    path = tmp_path / "invalid-power-mode.json"
    path.write_text(json.dumps({"costs": {
        "scope": "first_robot", "power_package_mode": bad_mode,
    }}), encoding="utf-8")
    result = run_cost("--evidence", str(path), "--format", "landed-cost-json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert not data["calculation_complete_not_physical_approval"]
    assert data["payable_now_cents"] is None
    assert not data["within_prototype_cap"]
    assert any("one complete power kit" in error for error in data["errors"])


@pytest.mark.parametrize("evidence", [[], None, True, "not an object"])
def test_nonobject_evidence_is_rejected_without_traceback(tmp_path, evidence):
    path = tmp_path / "invalid-evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    result = run_cost("--evidence", str(path), "--format", "landed-cost-json")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "Evidence must be a JSON object" in result.stderr
    assert "Traceback" not in result.stderr

@pytest.mark.parametrize("invalid_plan, message", [
    ([], "Missing hardware plan"),
    ({"target_robots": 5, "parts": []}, "Missing part ledger"),
])
def test_invalid_plan_schema_reports_cli_error(tmp_path, invalid_plan, message):
    path = tmp_path / "invalid-plan.json"
    path.write_text(json.dumps(invalid_plan), encoding="utf-8")
    result = run_cost("--plan", str(path))
    assert result.returncode == 2
    assert result.stdout == ""
    assert message in result.stderr
    assert "Traceback" not in result.stderr


def test_invalid_parts_evidence_reports_cli_error(tmp_path):
    path = tmp_path / "invalid-parts.json"
    path.write_text(json.dumps({"parts": []}), encoding="utf-8")
    result = run_cost("--evidence", str(path))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "Invalid parts evidence" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("flag, fmt, message", [
    ("--require-first-robot", "json", "First robot release"),
    ("--require-first-robot", "pilot-samples-json", "First robot release"),
    ("--require-first-robot", "pilot-cart-markdown", "First robot release"),
    ("--require-release", "first-robot-json", "Fleet release"),
    ("--require-release", "pilot-landed-cost-json", "Fleet release"),
    ("--require-release", "landed-cost-markdown", "Fleet release"),
])
def test_incompatible_release_format_is_rejected_before_input_io(
    tmp_path, flag, fmt, message,
):
    result = run_cost("--plan", str(tmp_path / "absent.json"), flag, "--format", fmt)
    assert result.returncode == 2
    assert result.stdout == ""
    assert message in result.stderr
    assert "Traceback" not in result.stderr
