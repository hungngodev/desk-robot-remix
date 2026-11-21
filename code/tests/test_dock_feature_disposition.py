"""Keep the accepted first pet docking requirement separate from historical status.

No source-only test can qualify charging contacts or real physical docking.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_docking_original_expansion_history_and_new_required_scope_both_survive():
    register = (ROOT / "docs/source-map.md").read_text(encoding="utf-8")
    rows = register.splitlines()
    for feature_id in ("F037", "G029"):
        matches = [line for line in rows if line.startswith(f"| `{feature_id}` |")]
        assert len(matches) == 1
        line = matches[0]
        assert "REQUIRED FIRST PET AND DOCK, PHYSICAL HOLD" in line
        assert "historically EXPANSION" in line
        assert "supersedes" in line
    guide = (ROOT / "docs/guides/one-complete-robot.md").read_text(
        encoding="utf-8"
    )
    assert "dedicated dock" in guide
    assert "qualified charger" in guide
    assert "normally unpowered" in guide or "unpowered dock" in guide


def test_product_decision_and_register_agree_on_required_docking():
    product = (ROOT / "docs/product-definition.md").read_text(encoding="utf-8")
    decisions = (ROOT / "docs/decision-log.md").read_text(encoding="utf-8")
    register = (ROOT / "docs/source-map.md").read_text(encoding="utf-8")
    assert "Accepted docking scope revision, 2026-11-21" in product
    assert "2026-11-21 superseding scope decision" in decisions
    assert "five docks" in product
    assert "one shared room station" in product
    assert "PHYSICAL HOLD" in product and "PHYSICAL HOLD" in register
    assert "historically EXPANSION" in register
