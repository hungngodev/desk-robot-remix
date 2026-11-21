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


def test_build_plan_current_evidence_requires_live_exact_sha_ci():
    plan = (ROOT / "docs/PLAN.md").read_text(encoding="utf-8")
    current = plan.split("## Current evidence", 1)[1].split("\n## ", 1)[0]
    assert "actions/workflows/host-verification.yml" in current
    assert "exact PR #17 head SHA" in current
    assert "job logs and tests for that same commit" in current
    assert "executed failing test is not a pre-step runner failure" in current
    assert "before recording any steps, with unavailable logs" not in current
    assert "bench stop margin remains unmeasured" in current
