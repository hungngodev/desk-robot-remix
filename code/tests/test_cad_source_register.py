"""CAD builder register must distinguish source files from fitted hardware."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAD = ROOT / "docs/cad"
REGISTER = CAD / "README.md"

CURRENT_SOURCE_LINKS = (
    "FUSION_ONE_ROBOT_ASSEMBLY.md",
    "remixes/one_robot_adapter_kit_README.md",
    "remixes/one_robot_adapter_kit.scad",
    "remixes/dock/dock_passive_fit.scad",
    "remixes/remaining_fit_gauges.scad",
    "remixes/fusion_one_robot_scaffold.py",
)


def test_cad_builder_entrypoint_names_real_current_sources_and_holds_fit():
    register = REGISTER.read_text(encoding="utf-8")
    for path in CURRENT_SOURCE_LINKS:
        assert (CAD / path).is_file(), f"Missing advertised CAD source: {path}"
        assert f"]({path})" in register

    assert "Saved upstream models remain unmodified" in register
    assert "Locally\nauthored, provisional geometry now exists" in register
    assert "No geometry has been edited or sliced" not in register
    assert "not a dimensionally qualified" in register
    assert "no complete robot\nor powered dock has been assembled" in register
    assert "not**\napproved permanent installation quantities" in register
    assert "protected contact charging before release" in register
