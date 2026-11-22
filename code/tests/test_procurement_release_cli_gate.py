"""The irreversible purchasing command must never print approval on a HOLD."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "code/scripts/procurement_release.py"


def test_full_fleet_release_holds_before_printing_order_without_real_evidence():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--require-release",
         "--format", "markdown"],
        cwd=ROOT / "code", text=True, capture_output=True,
        check=False, timeout=20,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "HOLD" in result.stderr
    assert "APPROVED" not in result.stdout


def test_unverified_pilot_projection_remains_available_without_release_flag():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--format", "pilot-samples-json"],
        cwd=ROOT / "code", text=True, capture_output=True,
        check=False, timeout=20,
    )
    assert result.returncode == 0
    import json
    pilot = json.loads(result.stdout)
    assert pilot["whole_first_robot_purchase_approved"] is False
    assert pilot["lithium_charging_or_motor_motion_authorized"] is False
    assert pilot["actual_current_landed_cost_verified"] is False


def test_one_robot_release_requires_real_first_unit_receipts_before_printing_cart():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--require-first-robot",
         "--format", "first-robot-markdown"],
        cwd=ROOT / "code", text=True, capture_output=True,
        check=False, timeout=20,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "HOLD" in result.stderr


def test_first_robot_release_refuses_fleet_or_pilot_output():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--require-first-robot",
         "--format", "markdown"],
        cwd=ROOT / "code", text=True, capture_output=True,
        check=False, timeout=20,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert "First robot release may only print a first robot view" in result.stderr

def test_fleet_release_refuses_nonfleet_views():
    for view in ("first-robot-json", "pilot-cart-json",
                 "landed-cost-json", "pilot-samples-markdown"):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--require-release",
             "--format", view],
            cwd=ROOT / "code", text=True, capture_output=True,
            check=False, timeout=20,
        )
        assert result.returncode != 0
        assert result.stdout == ""
        assert "Fleet release may only print a full fleet view" in result.stderr


def test_purchasing_release_rechecks_live_pr_after_receipts_before_output(
    monkeypatch, tmp_path, capsys,
):
    """A mid-audit branch advance must not print a once-approved cart."""
    import importlib.util
    import json
    import sys

    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    import verify_procurement_receipts as verifier

    spec = importlib.util.spec_from_file_location(
        "procurement_cli_race_test", SCRIPT,
    )
    assert spec and spec.loader
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)

    plan = tmp_path / "plan.json"
    evidence = tmp_path / "evidence.json"
    plan.write_text("{}", encoding="utf-8")
    valid_paid_evidence = {"costs": {"lines": [], "paid_orders": [
        {"order_reference": "synthetic-sense-payment", "total_paid_usd": "13.67",
         "allocations": [{"role_key": "robot:xiao_sense", "quantity": 1}]}
    ]}}
    evidence.write_text(json.dumps(valid_paid_evidence), encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--plan", str(plan),
                      "--evidence", str(evidence),
                      "--require-first-robot", "--format", "first-robot-markdown"],
    )
    # The strict gate now always requires the canonical optional-station
    # decision map before CI or source checkout. This synthetic checkout has
    # no selected options, not an absent or unverified decision map.
    monkeypatch.setattr(
        release, "generate", lambda *args: {"supplemental_decisions": []},
    )
    monkeypatch.setattr(
        release, "first_robot_projection",
        lambda *_: {"purchase_approved": True},
    )
    monkeypatch.setattr(
        release, "cost_quote",
        lambda *_: {"calculation_complete_not_physical_approval": True,
                    "within_prototype_cap": True, "awaiting_arrival_roles": [],
                    "prior_paid_orders_cents": 1367},
    )
    monkeypatch.setattr(verifier, "audit_release", lambda *args, **kwargs: [])
    # Isolate the head-moving race: successful job receipts are tested
    # separately and do not involve a live Actions request in this fixture.
    monkeypatch.setattr(
        verifier, "verified_required_ci_jobs", lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(release, "attach_verified_checkout_evidence",
                        lambda report, *args: report)
    monkeypatch.setattr(release, "public_purchase_view",
                        lambda report, **kwargs: report)
    monkeypatch.setattr(release, "render_first_robot_markdown",
                        lambda report: "synthetic cart, NOT approval")
    # The November 3 confirmed XIAO payment must survive all synthetic
    # receipt successes. Zero declared history or a missing role allocation
    # cannot make an over-budget cart appear affordable.
    evidence.write_text(
        json.dumps({"costs": {"lines": [], "paid_orders": []}}),
        encoding="utf-8",
    )
    assert release.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "confirmed Sense payment is absent" in captured.err
    evidence.write_text(json.dumps(valid_paid_evidence), encoding="utf-8")
    monkeypatch.setattr(
        release, "cost_quote",
        lambda *_: {"calculation_complete_not_physical_approval": True,
                    "within_prototype_cap": True, "awaiting_arrival_roles": [],
                    "prior_paid_orders_cents": 0},
    )
    assert release.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "confirmed Sense payment is absent" in captured.err
    monkeypatch.setattr(
        release, "cost_quote",
        lambda *_: {"calculation_complete_not_physical_approval": True,
                    "within_prototype_cap": True, "awaiting_arrival_roles": [],
                    "prior_paid_orders_cents": 1367},
    )

    revisions = iter(["a" * 40, "b" * 40])
    monkeypatch.setattr(verifier, "checkout_sha", lambda: next(revisions))
    assert release.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "PR #17 advanced during purchasing verification" in captured.err

    monkeypatch.setattr(verifier, "checkout_sha", lambda: "a" * 40)
    assert release.main() == 0
    assert "synthetic cart" in capsys.readouterr().out

    revisions = iter(["a" * 40, None])

    def offline_after_initial_receipt_check():
        revision = next(revisions)
        if revision is None:
            raise ValueError("network unavailable")
        return revision

    monkeypatch.setattr(
        verifier, "checkout_sha", offline_after_initial_receipt_check,
    )
    assert release.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot recheck live purchasing revision" in captured.err


def _run_projection_with_json(
    tmp_path, *, plan_text: str | None = None, evidence_text: str | None = None,
):
    command = [sys.executable, str(SCRIPT), "--format", "first-robot-json"]
    if plan_text is not None:
        plan = tmp_path / "plan.json"
        plan.write_text(plan_text, encoding="utf-8")
        command += ["--plan", str(plan)]
    if evidence_text is not None:
        evidence = tmp_path / "evidence.json"
        evidence.write_text(evidence_text, encoding="utf-8")
        command += ["--evidence", str(evidence)]
    return subprocess.run(
        command,
        cwd=ROOT / "code",
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def test_procurement_cli_accepts_unambiguous_finite_evidence(tmp_path):
    result = _run_projection_with_json(
        tmp_path,
        evidence_text='{"costs":{"scope":"evaluation","test_ratio":1.25}}',
    )
    assert result.returncode == 0
    assert result.stderr == ""

    import json

    projection = json.loads(result.stdout)
    assert projection["purchase_approved"] is False


def test_procurement_cli_rejects_duplicate_json_keys_before_projection(tmp_path):
    for raw in (
        '{"costs":{"scope":"evaluation","scope":"fleet"}}',
        '{"costs":{"scope":"evaluation","lines":['
        '{"role_key":"first","role_key":"second"}]}}',
    ):
        result = _run_projection_with_json(tmp_path, evidence_text=raw)
        assert result.returncode == 2
        assert result.stdout == ""
        assert "evidence JSON is invalid or ambiguous" in result.stderr
        assert "duplicate object key" in result.stderr

    result = _run_projection_with_json(
        tmp_path,
        plan_text='{"robots":[],"robots":[]}',
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "plan JSON is invalid or ambiguous" in result.stderr
    assert "duplicate object key" in result.stderr


def test_procurement_cli_rejects_nonfinite_json_numbers_before_projection(tmp_path):
    for token in ("NaN", "Infinity", "-Infinity", "1e9999"):
        result = _run_projection_with_json(
            tmp_path,
            evidence_text=(
                '{"costs":{"scope":"evaluation","claimed_value":'
                + token
                + "}}"
            ),
        )
        assert result.returncode == 2
        assert result.stdout == ""
        assert "evidence JSON is invalid or ambiguous" in result.stderr
        assert (
            "numeric constant" in result.stderr
            or "overflows finite range" in result.stderr
        )

