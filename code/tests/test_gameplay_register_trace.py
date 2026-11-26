"""Prevent silent loss or scope promotion of gameplay and historical ideas.

This checks documentation traceability, not execution or physical acceptance.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_IDS = {f"G{i:03d}" for i in range(1, 47)} | {f"H{i:03d}" for i in range(1, 11)}
REQUIRED = {
    "G001": "REQUIRED",
    "G004": "REQUIRED",
    "G028": "REQUIRED",
    "G029": "REQUIRED FIRST PET AND DOCK, PHYSICAL HOLD (historically EXPANSION HARDWARE)",
    "G031": "REQUIRED",
    "G040": "REQUIRED EXPERIENCE",
    "G043": "REQUIRED + EXPANSION",
    "G044": "REQUIRED",
    "G045": "REQUIRED",
    "G046": "REQUIRED EXPERIENCE",
}
HISTORICAL = {
    "H001": "REFERENCE",
    "H002": "REFERENCE",
    "H003": "PRESERVE",
    "H004": "PRESERVE",
    "H005": "PRESERVE",
    "H006": "RESEARCH",
    "H007": "PRESERVE",
    "H008": "INSPIRATION",
    "H009": "REVIEW",
    "H010": "SOURCE CHECK",
}


def _rows(document: str, *, coverage: bool) -> dict[str, tuple[str, str]]:
    pattern = (
        r'^\| <a id="feature-([gh]\d{3})"></a>\[([GH]\d{3})\]\([^)]*\) \|'
        if coverage else r'^\| `([GH]\d{3})` \|'
    )
    rows = {}
    for line in document.splitlines():
        match = re.match(pattern, line)
        if match is None:
            continue
        identifier = match[2] if coverage else match[1]
        if coverage:
            assert match[1] == identifier.lower(), identifier
        assert identifier not in rows, f"duplicate {identifier}"
        _, _, title, scope, *_ = (part.strip() for part in line.split("|"))
        assert title and scope, identifier
        scope = scope.replace(
            "; historically EXPANSION HARDWARE", " (historically EXPANSION HARDWARE)"
        )
        rows[identifier] = (title, scope)
    assert rows.keys() == EXPECTED_IDS, EXPECTED_IDS.symmetric_difference(rows)
    return rows


def _assert_trace(register: str, coverage: str) -> None:
    source_rows = _rows(register, coverage=False)
    coverage_rows = _rows(coverage, coverage=True)
    assert source_rows == coverage_rows, "gameplay register and coverage ledger disagree"
    scopes = {key: scope for key, (_, scope) in source_rows.items()}
    assert {key: scope for key, scope in scopes.items() if scope.startswith("REQUIRED")} == REQUIRED
    assert {key: scopes[key] for key in HISTORICAL} == HISTORICAL


@pytest.fixture
def documents() -> tuple[str, str]:
    return (
        (ROOT / "docs/source-map.md").read_text(encoding="utf-8"),
        (ROOT / "agents/coverage.md").read_text(encoding="utf-8"),
    )


def test_gameplay_and_historical_register_trace(documents):
    _assert_trace(*documents)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "downgrade", "promote", "title"])
def test_gameplay_trace_rejects_scope_and_identity_drift(documents, mutation):
    register, coverage = documents
    row = next(line for line in register.splitlines() if line.startswith("| `G001` |"))
    if mutation == "missing":
        register = register.replace(row, "", 1)
    elif mutation == "duplicate":
        register = register.replace(row, f"{row}\n{row}", 1)
    elif mutation == "downgrade":
        # Even coordinated edits to both documents must not silently weaken required scope.
        phrase = "| Blink, gaze, 20-expression face and sleepy rest | REQUIRED |"
        replacement = phrase.replace("REQUIRED", "EXPANSION")
        register = register.replace(phrase, replacement)
        coverage = coverage.replace(phrase, replacement)
    elif mutation == "promote":
        phrase = "| Projects with no confirmed source/license | REVIEW |"
        replacement = phrase.replace("REVIEW", "REQUIRED")
        register = register.replace(phrase, replacement)
        coverage = coverage.replace(phrase, replacement)
    else:
        coverage = coverage.replace("Blink, gaze, 20-expression face and sleepy rest", "Blink only")
    with pytest.raises(AssertionError):
        _assert_trace(register, coverage)
