"""The paper screen must not silently ignore overriding CAD datums."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "dock_seat_assignment_screen", ROOT / "code/scripts/screen_dock_seat_mechanics.py"
)
assert SPEC is not None and SPEC.loader is not None
SCREEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCREEN)


@pytest.mark.parametrize(
    ("name", "override"),
    [
        ("entry_flare_each_mm", "  entry_flare_each_mm = 1;"),
        ("entry_flare_run_mm", "\tentry_flare_run_mm = 20;"),
        ("side_clearance_each_mm", "side_clearance_each_mm = 1+1;"),
    ],
)
def test_duplicate_dock_datum_rejected(tmp_path, name, override):
    source = tmp_path / "duplicate.scad"
    source.write_text(SCREEN.CAD.read_text() + "\n" + override + "\n")
    with pytest.raises(ValueError, match=f"Missing or ambiguous dock CAD datum: {name}"):
        SCREEN.dock_constants(source)


def test_indented_unique_dock_datum_accepted(tmp_path):
    source = tmp_path / "indented.scad"
    original = SCREEN.CAD.read_text()
    source.write_text(original.replace("\nentry_flare_each_mm =", "\n  entry_flare_each_mm ="))
    expected = SCREEN.dock_constants()
    actual = SCREEN.dock_constants(source)
    assert actual.pop("source_sha256") != expected.pop("source_sha256")
    assert actual == expected
