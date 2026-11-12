"""Reproducibly render ORIGINAL provisional robot adapters and fit gauges.

This builds mesh candidates only. It does not approve actual measured
component fit, batteries, dock contacts, commercial licenses or assembly.
Run from the repository checkout with a locally installed OpenSCAD binary.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from math import isfinite
from pathlib import Path
from struct import unpack_from

ROOT = Path(__file__).resolve().parents[2]
ADAPTERS = (
    "head_bridge", "tof_adjustable", "oled_bezel", "speaker_grille",
    "fsr_jaw_pocket", "dock_tag_backplate", "wire_clip",
)
GAUGES = (
    "battery_boost_tray", "dock_contact_recess_gauge",
    "jaw_calibration_coupon",
)


def binary_stl_triangles(path: Path) -> int:
    """Reject empty, truncated or malformed binary STL output."""
    blob = path.read_bytes()
    if len(blob) < 84:
        raise ValueError(f"Truncated STL: {path.name}")
    triangles = int.from_bytes(blob[80:84], "little")
    if triangles < 1 or len(blob) != 84 + 50 * triangles:
        raise ValueError(f"Invalid binary STL triangles: {path.name}")
    return triangles


def closed_mesh_edges(path: Path) -> int:
    """Reject open, inverted-edge, nonfinite and degenerate STL geometry.

    Float32 coordinates are compared exactly as exported by OpenSCAD;
    this is a topological source check, not measured component fit.
    """
    blob = path.read_bytes()
    triangles = binary_stl_triangles(path)
    incidence: Counter = Counter()
    winding: Counter = Counter()
    for index in range(triangles):
        offset = 84 + 50 * index + 12  # skip the STL facet normal
        points = tuple(
            unpack_from("<fff", blob, offset + 12 * corner)
            for corner in range(3)
        )
        if len(set(points)) != 3 or not all(
            isfinite(value) for point in points for value in point
        ):
            raise ValueError(f"Degenerate or nonfinite STL triangle: {path.name}")
        for corner in range(3):
            a, b = points[corner], points[(corner + 1) % 3]
            edge = (a, b) if a < b else (b, a)
            incidence[edge] += 1
            winding[edge] += 1 if a < b else -1
    if (not incidence
            or any(count != 2 for count in incidence.values())
            or any(direction != 0 for direction in winding.values())):
        raise ValueError(f"Open or inconsistent STL mesh: {path.name}")
    return len(incidence)


def export_kit(
    root: Path = ROOT, *, output_dir: Path | None = None,
    openscad: str = "openscad",
) -> dict:
    source_dir = root / "docs/cad/remixes"
    out = output_dir or source_dir
    if not shutil.which(openscad):
        raise FileNotFoundError(f"OpenSCAD is not installed: {openscad}")
    sources = (
        ("adapter_stls", source_dir / "one_robot_adapter_kit.scad", ADAPTERS),
        ("fit_stls", source_dir / "remaining_fit_gauges.scad", GAUGES),
    )
    for _, source, _ in sources:
        if not source.is_file():
            raise FileNotFoundError(f"Missing original parametric source: {source}")
    out.mkdir(parents=True, exist_ok=True)
    rendered: list[dict] = []
    # No incomplete candidate part gets published if any SCAD render fails.
    with tempfile.TemporaryDirectory(prefix="desk-fit-", dir=out) as folder:
        stage = Path(folder)
        for kind, source, parts in sources:
            for name in parts:
                target = stage / kind / (name + ".stl")
                target.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    [
                        openscad, "--export-format", "binstl", "-o",
                        str(target), "-D", f'part="{name}"', str(source),
                    ],
                    check=True, capture_output=True, text=True, timeout=180,
                )
                triangles = binary_stl_triangles(target)
                edges = closed_mesh_edges(target)
                rendered.append({
                    "part": name, "location": f"{kind}/{name}.stl",
                    "triangles": triangles, "manifold_edges": edges,
                    "quantity_per_robot": 8 if name == "tof_adjustable" else 1,
                })
        for entry in rendered:
            relative = Path(entry["location"])
            destination = out / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / relative, destination)
    report = {
        "provisional_fit_parts_only": True,
        "source_geometry_rendered": True,
        "hardware_fit_verified": False,
        "full_printable_assembly_verified": False,
        "dock_charge_contacts_approved": False,
        "commercial_manufacture_authorized": False,
        "parts": rendered,
    }
    (out / "fit_kit_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--openscad", default="openscad")
    args = parser.parse_args()
    report = export_kit(
        args.repo, output_dir=args.output, openscad=args.openscad,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
