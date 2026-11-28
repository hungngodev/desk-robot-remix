"""Prevent historical runner failures from being presented as current CI status."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_URL = (
    "https://github.com/hungngodev/desk-robot-remix/actions/workflows/host-verification.yml"
)


def _section(plan: str, heading: str) -> str:
    sections = []
    for section in re.split(r"(?m)^## ", plan)[1:]:
        title, _, body = section.partition("\n")
        if title == heading:
            sections.append(body)
    assert len(sections) == 1, f"Expected one {heading!r} section, got {len(sections)}"
    return sections[0]


def _link_targets(section: str) -> set[str]:
    return set(re.findall(r"\[[^\]]+\]\(([^()\s]+)\)", section))


def test_build_plan_directs_reader_to_exact_revision_ci_and_physical_gates():
    plan = (ROOT / "docs/PLAN.md").read_text(encoding="utf-8")
    checkpoint = _section(plan, "November 12 integration checkpoint")
    assert "**Historical CI context:**" in checkpoint
    assert WORKFLOW_URL in _link_targets(checkpoint)
    assert "exact PR #17 commit SHA" in checkpoint
    assert "each job's success, failure, cancellation, skip or queue status" in checkpoint
    assert "separate physical trial evidence" in checkpoint
    assert "records/verification.md" in _link_targets(checkpoint)
    assert "Passing software checks do not qualify physical" in checkpoint
    assert "Tests are added but currently not executed" not in checkpoint
    assert "all four GitHub Actions jobs fail before their first recorded step" not in checkpoint


def test_build_plan_current_evidence_requires_live_exact_sha_ci():
    plan = (ROOT / "docs/PLAN.md").read_text(encoding="utf-8")
    current = _section(plan, "Current evidence")
    assert WORKFLOW_URL in _link_targets(current)
    assert "exact PR #17 head SHA" in current
    assert "job logs and tests for that same commit" in current
    assert "executed failing test is not a pre-step runner failure" in current
    assert "before recording any steps, with unavailable logs" not in current
    assert "all five jobs must succeed on the same reviewed commit" in " ".join(current.split())
    assert "physical, assembly, charging and procurement HOLD" in current
    assert "bench stop margin remains unmeasured" in current


@pytest.mark.parametrize(
    "text",
    [
        WORKFLOW_URL,
        f"[{WORKFLOW_URL}](https://example.com)",
        "[workflow](https://github.com/wrong/repository/actions/workflows/host-verification.yml)",
    ],
)
def test_workflow_link_target_is_not_inferred_from_path_or_display_text(text):
    assert WORKFLOW_URL not in _link_targets(text)


def test_section_link_cannot_be_satisfied_by_neighboring_heading():
    plan = f"## Current evidence\nNo link\n## Other\n[workflow]({WORKFLOW_URL})\n"
    assert WORKFLOW_URL not in _link_targets(_section(plan, "Current evidence"))


@pytest.mark.parametrize(
    "plan",
    [
        "## Current evidence archive\n",
        "## Current evidence\nFirst\n## Current evidence\nSecond\n",
    ],
)
def test_section_requires_one_exact_heading(plan):
    with pytest.raises(AssertionError, match="Expected one"):
        _section(plan, "Current evidence")
