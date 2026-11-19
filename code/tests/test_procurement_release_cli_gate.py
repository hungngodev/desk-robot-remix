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
