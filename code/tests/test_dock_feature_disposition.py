"""Keep the accepted first pet docking requirement separate from historical status.

No source-only test can qualify charging contacts or real physical docking.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_docking_original_expansion_history_and_new_required_scope_both_survive():
    register = (ROOT / "docs/source-map.md").read_text(encoding="utf-8")
    rows = register.splitlines()
    for feature_id in ("F037", "G029"):
        matches = [line for line in rows if line.startswith(f"| \`{feature_id}\` |")]
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
