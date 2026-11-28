"""Builder must print every current source-backed provisional A4 reference."""

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAPER_SCRIPT = ROOT / "docs/cad/remixes/print_2d_fit_templates.py"
GUIDE = ROOT / "docs/guides/build.md"


def _paper_step(instructions: str) -> str:
    return instructions.split("3. **Print reversible fit pieces first.**", 1)[1].split(
        "4. **Assemble and inspect mechanically.**", 1
    )[0]


def _validate_a4_page_inventory(instructions, page_sources):
    step = _paper_step(instructions)
    for page in page_sources:
        marker = f"`{page}_reference_A4.svg`"
        assert step.count(marker) == 1, marker


def _validate_a4_scaling_prohibition(instructions: str) -> None:
    normalized = " ".join(_paper_step(instructions).split())
    if (
        "Print **all five** source-derived A4 SVGs at **100% / actual size**:" not in normalized
        or "Never fit-to-page." not in normalized
        or "Always fit-to-page." in normalized
        or "A clipped, scaled or mismatched paper reference is a **STOP**" not in normalized
    ):
        raise ValueError("A4 print guide missing mandatory 100%/never-fit-to-page STOP guard")


def test_builder_instructions_cover_all_provisional_a4_paper_pages():
    # The generator owns page inventory. A newly added sheet cannot silently
    # disappear from the first-unit builder route after the source changes.
    page_sources = runpy.run_path(str(PAPER_SCRIPT))["SOURCES"]
    assert set(page_sources) == {
        "ranger", "speaker", "dock", "dock_guide", "power",
    }
    instructions = GUIDE.read_text(encoding="utf-8")
    _validate_a4_page_inventory(instructions, page_sources)
    _validate_a4_scaling_prohibition(instructions)
    assert "**100% / actual size**" in instructions
    assert "100 mm, 50 mm and 25 mm scales" in instructions
    assert "provisional protected 1S pack" in instructions
    assert "not approved mounting holes or a qualified dock" in instructions


def test_a4_print_guard_rejects_fit_to_page_or_missing_stop():
    instructions = GUIDE.read_text(encoding="utf-8")
    for old, new in (
        ("Never fit-to-page.", "Always fit-to-page."),
        ("Never fit-to-page.", ""),
        ("is a **STOP**", "is advisory only"),
    ):
        with pytest.raises(ValueError):
            _validate_a4_scaling_prohibition(instructions.replace(old, new, 1))


def test_a4_inventory_rejects_misplaced_page_mentions():
    instructions = GUIDE.read_text(encoding="utf-8")
    page_sources = runpy.run_path(str(PAPER_SCRIPT))["SOURCES"]
    for page in page_sources:
        marker = f"`{page}_reference_A4.svg`"
        mutant = instructions.replace(marker, "", 1) + "\n" + marker
        with pytest.raises(AssertionError):
            _validate_a4_page_inventory(mutant, page_sources)
