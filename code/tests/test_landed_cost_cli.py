"""Use the actual procurement CLI to distinguish quotes from purchase approval."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "code/scripts/procurement_release.py"


def run_cost(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT / "code", text=True, capture_output=True,
        check=False, timeout=20,
    )


def sample_quote():
    from test_landed_cost import sample

    return {"costs": sample()}


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
    assert data["prototype_cumulative_cents"] == 1905
    assert not data["landed_price_is_a_verified_supplier_checkout"]
    assert data["material_subtotals_cents"]["robot"] == 223


def test_cli_keeps_supplier_quote_distinct_from_irreversible_cart(tmp_path):
    path = tmp_path / "quote.json"
    path.write_text(json.dumps(sample_quote()), encoding="utf-8")
    result = run_cost("--evidence", str(path),
                      "--require-first-robot",
                      "--format", "first-robot-markdown")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "HOLD" in result.stderr
