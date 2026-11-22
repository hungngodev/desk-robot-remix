"""Builder index must not present historical sensor source as live acceptance."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_dated_source_snapshot_cannot_claim_current_verification() -> None:
    index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    marker = (
        "**Historical source snapshot "
        "(November 16, 2026; not live verification).**"
    )
    assert marker in index
    assert "**Current status, 2026-11-16.**" not in index
    snapshot = index.split(marker, 1)[1].split(
        "**Not assembled or certified.**", 1
    )[0]
    assert "The code then" in snapshot
    assert "PR #17" in snapshot
    assert "Physical sensor events could request" in snapshot
    workflow = (
        "https://github.com/hungngodev/desk-robot-remix/actions/"
        "workflows/host-verification.yml"
    )
    assert workflow in index
    assert "Keep bulk purchases, loaded robot movement and" in index
    assert "powered charging on HOLD" in index
