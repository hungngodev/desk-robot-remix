"""Builder index must not present historical sensor source as live acceptance."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = "**Historical source snapshot (November 16, 2026; not live verification).**"
GATE = "**Not assembled or certified.**"
WORKFLOW = (
    "https://github.com/hungngodev/desk-robot-remix/actions/"
    "workflows/host-verification.yml"
)
HOLD = "Keep bulk purchases, loaded robot movement and powered charging on HOLD"


def assert_snapshot_contract(index: str) -> None:
    assert index.count("\n## Start here\n") == index.count("\n## Reference\n") == 1
    start = index.split("\n## Start here\n", 1)[1].split("\n## Reference\n", 1)[0]
    assert index.count(SNAPSHOT) == index.count(GATE) == 1
    assert "**Current status, 2026-11-16.**" not in index
    assert SNAPSHOT in start and GATE in start
    assert start.index(SNAPSHOT) < start.index(GATE)
    snapshot, gate = start.split(SNAPSHOT, 1)[1].split(GATE, 1)
    assert "The code then" in snapshot
    assert "[PR #17](https://github.com/hungngodev/desk-robot-remix/pull/17)" in snapshot
    assert "Physical sensor events could request" in snapshot
    gate = " ".join(gate.split())
    assert f"[live host verification workflow]({WORKFLOW})" in gate
    assert "CI must be assessed at the exact PR head" in gate
    assert "A passed host job cannot qualify" in gate
    assert HOLD + " until their independent physical gates pass." in gate


def test_dated_source_snapshot_cannot_claim_current_verification() -> None:
    assert_snapshot_contract((ROOT / "docs/README.md").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (GATE, "**Assembled and certified.**"),
        (SNAPSHOT, SNAPSHOT + "\n" + SNAPSHOT),
        ("[live host verification workflow]", "[historical verification workflow]"),
        ("CI must be assessed at the exact PR head", "CI may use any earlier green run"),
        ("A passed host job cannot", "A passed host job can"),
        ("powered charging on HOLD", "powered charging on RELEASE"),
    ],
)
def test_snapshot_contract_rejects_regressions(old: str, new: str) -> None:
    index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    assert old in index
    with pytest.raises(AssertionError):
        assert_snapshot_contract(index.replace(old, new, 1))
