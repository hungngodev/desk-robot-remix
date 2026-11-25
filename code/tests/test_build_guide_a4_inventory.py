"""Builder must print every current source-backed provisional A4 reference."""

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAPER_SCRIPT = ROOT / "docs/cad/remixes/print_2d_fit_templates.py"
GUIDE = ROOT / "docs/guides/build.md"


def _validate_a4_scaling_prohibition(instructions: str) -> None:
    normalized = " ".join(instructions.split())
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
    for page in page_sources:
        assert f"`{page}_reference_A4.svg`" in instructions
    _validate_a4_scaling_prohibition(instructions)
    assert "**100% / actual size**" in instructions
    assert "100 mm and 25 mm scales" in instructions
    assert "provisional protected 1S pack" in instructions
    assert "not approved mounting holes or a qualified dock" in instructions


def test_a4_print_guard_rejects_fit_to_page_or_missing_stop():
    import pytest

    instructions = GUIDE.read_text(encoding="utf-8")
    for old, new in (
        ("Never fit-to-page.", "Always fit-to-page."),
        ("Never fit-to-page.", ""),
        ("is a **STOP**", "is advisory only"),
    ):
        with pytest.raises(ValueError):
            _validate_a4_scaling_prohibition(instructions.replace(old, new, 1))
