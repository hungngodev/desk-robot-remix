"""Prevent historical runner failures from being presented as current CI status."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_build_plan_directs_reader_to_exact_revision_ci_and_physical_gates():
    plan = (ROOT / "docs/PLAN.md").read_text(encoding="utf-8")
    checkpoint = plan.split("## November 12 integration checkpoint", 1)[1].split(
        "## Build order", 1
    )[0]
    assert "**Historical CI context:**" in checkpoint
    assert "actions/workflows/host-verification.yml" in checkpoint
    assert "exact PR #17 commit SHA" in checkpoint
    assert "each job's success, failure, cancellation, skip or queue status" in checkpoint
    assert "separate physical trial evidence" in checkpoint
    assert "Tests are added but currently not executed" not in checkpoint
    assert "all four GitHub Actions jobs fail before their first recorded step" not in checkpoint
