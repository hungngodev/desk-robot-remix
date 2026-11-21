"""Docking is a first robot release gate, not an optional fleet expansion."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/PLAN.md"


def _stages(markdown):
    lines = markdown.splitlines()
    table = [line for line in lines if line.startswith("| ") and " | " in line]
    return {
        int(line.split("|")[1].strip().split(".")[0]): line.casefold()
        for line in table
        if line.split("|")[1].strip().split(".")[0].isdigit()
    }


def test_first_robot_plan_requires_dock_before_qualification():
    stages = _stages(PLAN.read_text())
    assert len(stages) >= 13
    assert "first dock" in stages[2]
    assert "protected 1s charging" in stages[2]
    assert "eight-sensor vl53l0x" in stages[3]
    assert "supervised terminal dock approach" in stages[8]
    assert "first dock" in stages[9]
    for phrase in ("measured net cell current", "departure", "recovery"):
        assert phrase in stages[9]
    assert "five" in stages[10] and "docks" in stages[10]
    assert "five independently qualified docks" in stages[11]
    assert "one approved shared station" in stages[11]
    assert "already mandatory" in stages[12]


def test_optional_research_row_cannot_qualify_or_defer_required_dock():
    rows = _stages(PLAN.read_text())
    assert "alternate experimental docking methods" in rows[12]
    assert "advanced games/docking/navigation" not in rows[12]
    assert "first assigned dock" in rows[9]
    fake = PLAN.read_text().replace(
        "alternate experimental docking methods", "advanced games/docking/navigation",
    )
    assert "advanced games/docking/navigation" in _stages(fake)[12]
    assert "advanced games/docking/navigation" not in rows[12]
