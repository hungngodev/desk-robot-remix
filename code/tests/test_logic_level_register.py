"""Structural checks for the optional RGB buffer sourcing record."""
import re
from pathlib import Path

REGISTER = (Path(__file__).resolve().parents[2] / "docs/hardware/"
            "2026-11-16-five-pet-purchase-register.md")


def test_logic_level_candidate_has_exact_orderable_sku_and_hold():
    text = REGISTER.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| `logic_level` |")]
    assert len(rows) == 1
    cells = [cell.strip() for cell in rows[0].strip("|").split("|")]
    assert len(cells) == 11
    assert "SN74AHCT1G125DBVR" in cells[1]
    assert "SOT-23-5 (DBV)" in cells[1]
    assert "296-4708-1-ND" in cells[1]
    assert "digikey.com/" in cells[1]
    assert cells[2:9] == ["1", "5", "0", "0", "0", "5", "1"]
    assert re.search(r"\$\d+\.\d{2}", cells[9])
    assert "bare IC" in cells[9] and "before shipping" in cells[9]
    assert "HOLD" in cells[10] and "NO PURCHASE" in cells[10]
    assert "optional" in cells[10].lower()
    notes = [line for line in text.splitlines() if line.startswith("* **`logic_level`")]
    assert len(notes) == 1
    assert re.search(r"\d{4}-\d{2}-\d{2}", notes[0])
    assert "in stock" in notes[0].lower()
    assert "cached" in notes[0].lower()
    assert "recheck" in notes[0].lower()
    assert "physical HOLD" in notes[0]
