"""Render candidate CAD parts reproducibly without claiming measured fit."""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "code/scripts/export_fit_kit.py"


def module():
    spec = importlib.util.spec_from_file_location("desk_fit_kit", SCRIPT)
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    return source


def test_binary_stl_geometry_rejects_truncation_and_zero_triangles(tmp_path):
    source = module()
    output = tmp_path / "part.stl"
    output.write_bytes(b"nothing")
    with pytest.raises(ValueError, match="Truncated"):
        source.binary_stl_triangles(output)
    output.write_bytes(bytes(80) + (0).to_bytes(4, "little"))
    with pytest.raises(ValueError, match="Invalid"):
        source.binary_stl_triangles(output)
    output.write_bytes(bytes(80) + (2).to_bytes(4, "little") + bytes(50))
    with pytest.raises(ValueError, match="Invalid"):
        source.binary_stl_triangles(output)
    output.write_bytes(bytes(80) + (1).to_bytes(4, "little") + bytes(50))
    assert source.binary_stl_triangles(output) == 1


def test_render_all_candidates_with_one_source_and_unqualified_output(monkeypatch, tmp_path):
    source = module()
    folder = tmp_path / "docs/cad/remixes"
    folder.mkdir(parents=True)
    for name in ("one_robot_adapter_kit.scad", "remaining_fit_gauges.scad"):
        (folder / name).write_text("cube([1,1,1]);\n")
    monkeypatch.setattr(source.shutil, "which", lambda _command: "/usr/bin/openscad")
    commands = []

    def fake_render(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] and kwargs["timeout"] <= 180
        assert "--export-format" in command and "binstl" in command
        out = Path(command[command.index("-o") + 1])
        out.write_bytes(bytes(80) + (1).to_bytes(4, "little") + bytes(50))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(source.subprocess, "run", fake_render)
    rendered = tmp_path / "rendered"
    report = source.export_kit(tmp_path, output_dir=rendered)
    assert len(commands) == len(source.ADAPTERS) + len(source.GAUGES) == 10
    assert len(report["parts"]) == 10
    assert (rendered / "adapter_stls/tof_adjustable.stl").is_file()
    assert (rendered / "fit_stls/dock_contact_recess_gauge.stl").is_file()
    assert (rendered / "fit_kit_manifest.json").is_file()
    assert report["parts"][1]["quantity_per_robot"] == 8
    for key in (
        "hardware_fit_verified", "full_printable_assembly_verified",
        "dock_charge_contacts_approved", "commercial_manufacture_authorized",
    ):
        assert report[key] is False


def test_failed_cad_render_never_publishes_partial_parts(monkeypatch, tmp_path):
    source = module()
    folder = tmp_path / "docs/cad/remixes"
    folder.mkdir(parents=True)
    for name in ("one_robot_adapter_kit.scad", "remaining_fit_gauges.scad"):
        (folder / name).write_text("cube([1,1,1]);\n")
    monkeypatch.setattr(source.shutil, "which", lambda _command: "/usr/bin/openscad")
    tries = 0

    def fail_after_one(command, **_kwargs):
        nonlocal tries
        tries += 1
        if tries == 2:
            raise subprocess.CalledProcessError(1, command)
        Path(command[command.index("-o") + 1]).write_bytes(
            bytes(80) + (1).to_bytes(4, "little") + bytes(50)
        )

    monkeypatch.setattr(source.subprocess, "run", fail_after_one)
    output = tmp_path / "rendered"
    with pytest.raises(subprocess.CalledProcessError):
        source.export_kit(tmp_path, output_dir=output)
    assert not list(output.rglob("*.stl"))
    assert not (output / "fit_kit_manifest.json").exists()


@pytest.mark.skipif(shutil.which("openscad") is None, reason="Needs real OpenSCAD CLI")
def test_real_openscad_renders_provisional_source_parts(tmp_path):
    source = module()
    output = tmp_path / "rendered"
    report = source.export_kit(ROOT, output_dir=output)
    assert len(report["parts"]) == 10
    for item in report["parts"]:
        assert source.binary_stl_triangles(output / item["location"]) > 0
    assert report["full_printable_assembly_verified"] is False
