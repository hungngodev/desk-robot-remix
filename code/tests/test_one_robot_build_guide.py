"""The one complete robot builder entry stays discoverable and fail closed.

This verifies navigation and critical release language, not electrical fit.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs/guides/one-complete-robot.md"


def test_one_complete_robot_guide_is_discoverable_and_links_real_files():
    text = GUIDE.read_text(encoding="utf-8")
    assert "one-complete-robot.md" in (ROOT / "README.md").read_text()
    assert "guides/one-complete-robot.md" in (ROOT / "docs/README.md").read_text()
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("https://", "http://")):
            continue
        path = target.split("#", 1)[0]
        assert path and (GUIDE.parent / path).is_file(), target


def test_builder_guide_does_not_claim_unqualified_power_or_print_release():
    text = GUIDE.read_text()
    assert "HOLD" in text
    assert "USD 50 delivered cap" in text
    assert "including previously paid items" in text
    assert "first-robot-markdown" in text
    assert "five-pet fleet projection" in text
    assert "NOT a one-unit checkout" in text
    assert "Do not order fleet quantities" in text
    assert "only two builder facing lists" in text
    assert "pilot-cart-markdown" in text
    assert "only two builder facing lists" in text
    assert "one shared room station" in text
    assert "read-only" in text
    assert "signed net battery current" in text
    assert "86 mm" in text and "68 mm" in text
    assert "independent external motor cutoff" in text
    assert "Digital I2S acceptance does not establish acoustic playback completion" in text


def test_builder_guide_exposes_real_quiet_control_without_motion_authority():
    text = GUIDE.read_text()
    assert "POST /v1/pet/{robot_id}/quiet" in text
    assert '{"quiet": true}' in text
    assert '{"quiet": false}' in text
    assert "operator-only" in text
    assert "tool token is intentionally not authorized" in text
    assert "does not arm movement" in text
