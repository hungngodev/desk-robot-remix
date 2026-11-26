"""Keep the human print inventory aligned with the fit exporters."""

import re
import runpy
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REMIX = ROOT / "docs/cad/remixes"


def documented_stls(path):
    return Counter(re.findall(r"^\| `([^`]+\.stl)` \|", path.read_text(), re.MULTILINE))


def test_print_pack_manifest_matches_exporter():
    exporter = runpy.run_path(str(ROOT / "code/scripts/export_fit_kit.py"))
    groups = {
        "adapter_stls": exporter["ADAPTERS"],
        "fit_stls": (
            *exporter["GAUGES"], *exporter["SPEAKER_FITS"],
            *exporter["MG90S_FITS"], *exporter["RANGER_FITS"],
        ),
        "dock_stls": exporter["DOCKS"],
    }
    expected = Counter(
        f"{folder}/{part}.stl" for folder, parts in groups.items() for part in parts
    )
    assert all(count == 1 for count in expected.values())
    assert documented_stls(REMIX / "one_robot_adapter_kit_README.md") == expected
    dock = REMIX / "dock/README.md"
    assert documented_stls(dock) == Counter(
        f"dock_stls/{part}.stl" for part in groups["dock_stls"]
    )
    examples = re.findall(r"-o\s+(\w+\.stl)", dock.read_text())
    assert all(f"dock_stls/{name}" in expected for name in examples)


def test_paper_inventory_matches_template_sources():
    templates = runpy.run_path(str(REMIX / "print_2d_fit_templates.py"))
    readme = (REMIX / "one_robot_adapter_kit_README.md").read_text()
    actual = Counter(re.findall(r"^\| `([^`]+_reference_A4\.svg)` \|", readme, re.MULTILINE))
    assert actual == Counter(f"{name}_reference_A4.svg" for name in templates["SOURCES"])
