"""Keep the implementation inventory aligned with live source files."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADING = "## Implementation source inventory\n"
PATTERNS = (
    "code/laptop/src/desk_robot/*.py",
    "code/scripts/*.py",
    "code/scripts/*.sh",
    "code/firmware/body/*",
    "code/firmware/body/cmake/*",
    "code/firmware/body/include/*",
    "code/firmware/body/lib/*/*",
    "code/firmware/body/src/*",
    "code/firmware/dock/*",
    "code/firmware/dock/src/*",
    "code/firmware/head/*",
    "code/firmware/head/modular/*",
    "code/firmware/head/overlay/*",
    "code/firmware/head/sense/*",
    "code/firmware/head/waveshare/*",
    "code/firmware/room_station/*",
    "code/firmware/room_station/src/*",
)
SUFFIXES = {".py", ".sh", ".h", ".hpp", ".cpp", ".cc", ".inc", ".ini", ".json", ".cmake", ".lock"}


def _source_paths(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for pattern in PATTERNS
        for path in root.glob(pattern)
        if path.is_file() and (path.suffix in SUFFIXES or path.name == "CMakeLists.txt")
    }


def _inventory_paths(document: str) -> list[str]:
    section = document.split(HEADING, 1)[1].split("\n## ", 1)[0]
    return re.findall(r"\]\(\.\./(code/[^)\s]+)\)", section)


def test_implementation_inventory_matches_sources() -> None:
    document = (ROOT / "docs/source-map.md").read_text(encoding="utf-8")
    listed = _inventory_paths(document)
    assert len(listed) == len(set(listed)), "Duplicate implementation inventory links"
    assert set(listed) == _source_paths(ROOT)


def test_inventory_does_not_count_historical_links() -> None:
    document = (
        "[old](../code/scripts/old.py)\n" + HEADING
        + "[new](../code/scripts/new.py)\n## Historical\n"
        "[other](../code/scripts/other.py)\n"
    )
    assert _inventory_paths(document) == ["code/scripts/new.py"]


def test_source_discovery_excludes_tests_and_generated_builds(tmp_path: Path) -> None:
    included = {
        "code/laptop/src/desk_robot/new.py",
        "code/scripts/new.sh",
        "code/firmware/body/lib/New/New.h",
        "code/firmware/head/sense/new.hpp",
        "code/firmware/room_station/src/new.cpp",
    }
    excluded = {
        "code/firmware/body/tests/new.cpp",
        "code/firmware/head/.build/new.cc",
        "code/firmware/head/sense/README.md",
        "code/scripts/__pycache__/new.py",
    }
    for name in included | excluded:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    assert _source_paths(tmp_path) == included

def test_review_reconciliation_preserves_evidence_boundaries() -> None:
    document = (ROOT / "docs/source-map.md").read_text(encoding="utf-8")
    ledger = (ROOT / "docs/records/verification.md").read_text(encoding="utf-8")
    heading = "### November 26 DRR-003 scoped inline-thread reconciliation"
    section = ledger.split(heading, 1)[1].split("\n### ", 1)[0]
    counts = re.search(
        r"(\d+) inline threads,\s+(\d+) resolved, (\d+) unresolved, "
        r"including (\d+) outdated and unresolved",
        section,
    )
    assert counts is not None
    total, resolved, unresolved, outdated_open = map(int, counts.groups())
    assert total == resolved + unresolved
    assert 0 <= outdated_open <= unresolved
    assert "Outdated is a diff-anchor property, not a closure verdict" in section
    assert "not its manual acceptance receipt" in section
    assert "physical and procurement HOLD" in section
    assert "records/verification.md#november-26-drr-003-scoped-inline-thread-reconciliation" in document
    row = next(line for line in document.splitlines() if line.startswith("| `G010` |"))
    assert "EXPANSION SOFTWARE; BACKLOG, NOT IMPLEMENTED" in row
    assert "due versus audible delivery" in row
