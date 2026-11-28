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


def _assert_docking_scope(product: str, decisions: str, register: str, guide: str) -> None:
    if (
        "includes its own independently qualified dock" not in product
        or "does not include" in product
    ):
        raise ValueError("product-definition.md weakened required first-unit dock")
    if (
        "requires physically safe self docking" not in decisions
        or "does not require physically safe self docking" in decisions
    ):
        raise ValueError("decision-log.md weakened required first-unit dock")
    f037 = [line for line in register.splitlines() if line.startswith("| `F037` |")]
    if (
        len(f037) != 1
        or "REQUIRED FIRST PET AND DOCK, PHYSICAL HOLD" not in f037[0]
        or "Accepted subsequent complete first-pet requirement supersedes original expansion timing" not in f037[0]
    ):
        raise ValueError("source-map.md F037 scope contract corrupted")
    if "its own dedicated dock" not in guide and "its dedicated dock" not in guide:
        raise ValueError("one-complete-robot.md dropped dedicated dock requirement")


def test_product_decision_and_register_agree_on_required_docking():
    product = (ROOT / "docs/product-definition.md").read_text(encoding="utf-8")
    decisions = (ROOT / "docs/decision-log.md").read_text(encoding="utf-8")
    register = (ROOT / "docs/source-map.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/guides/one-complete-robot.md").read_text(encoding="utf-8")
    _assert_docking_scope(product, decisions, register, guide)
    assert "Accepted docking scope revision, 2026-11-21" in product
    assert "2026-11-21 superseding scope decision" in decisions
    assert "five docks" in product
    assert "one shared room station" in product
    assert "PHYSICAL HOLD" in product and "PHYSICAL HOLD" in register
    assert "historically EXPANSION" in register


def test_docking_scope_contract_rejects_negation_and_reversed_supersession():
    import pytest

    product = (ROOT / "docs/product-definition.md").read_text(encoding="utf-8")
    decisions = (ROOT / "docs/decision-log.md").read_text(encoding="utf-8")
    register = (ROOT / "docs/source-map.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/guides/one-complete-robot.md").read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        _assert_docking_scope(
            product.replace("includes its own independently qualified dock", "does not include its own independently qualified dock"),
            decisions, register, guide,
        )
    with pytest.raises(ValueError):
        _assert_docking_scope(
            product,
            decisions.replace("requires physically safe self docking", "does not require physically safe self docking"),
            register, guide,
        )
    with pytest.raises(ValueError):
        _assert_docking_scope(
            product, decisions,
            register.replace(
                "Accepted subsequent complete first-pet requirement supersedes original expansion timing",
                "The original expansion timing supersedes the accepted subsequent complete first-pet requirement",
            ),
            guide,
        )
    with pytest.raises(ValueError):
        _assert_docking_scope(
            product, decisions, register,
            guide.replace("its dedicated dock", "its optional dedicated dock"),
        )
