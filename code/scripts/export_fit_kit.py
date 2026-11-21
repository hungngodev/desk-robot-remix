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
from hashlib import sha256
from math import hypot, isfinite
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
SPEAKER_FITS = ("speaker_rect_fit_gauge",
                "speaker_rear_chamber_reference")
RANGER_FITS = ("vl53l0x_gy530_fit_gauge",)
DOCKS = ("dock_passive_fit", "dock_rail_entry_coupon",
         "dock_ir_pair_position_coupon")

POWER_FIT_SCOPE = {
    # Historical generated filename retained for compatibility.
    # The geometry currently represents the protected pack body only.
    "part": "battery_boost_tray",
    "protected_pack_body_only": True,
    "includes_connector_and_leads": False,
    "includes_charger": False,
    "includes_boost": False,
    "includes_fuse_switch": False,
    "whole_power_stack_fit_verified": False,
}


def binary_stl_triangles(path: Path) -> int:
    """Reject empty, truncated or malformed binary STL output."""
    blob = path.read_bytes()
    if len(blob) < 84:
        raise ValueError(f"Truncated STL: {path.name}")
    triangles = int.from_bytes(blob[80:84], "little")
    if triangles < 1 or len(blob) != 84 + 50 * triangles:
        raise ValueError(f"Invalid binary STL triangles: {path.name}")
    return triangles


def mesh_bounds_mm(path: Path) -> dict:
    """Read actual exported STL bounds in millimeters, never assumed CAD size.

    STL has no native unit metadata: millimeters are the declared OpenSCAD
    export convention. A bounding box is a print-layout aid, NOT component
    fit, internal clearance, mechanical assembly or strength certification.
    """
    blob = path.read_bytes()
    triangles = binary_stl_triangles(path)
    lows = [float("inf")] * 3
    highs = [float("-inf")] * 3
    for i in range(triangles):
        offset = 84 + 50 * i + 12
        for corner in range(3):
            point = unpack_from("<fff", blob, offset + 12 * corner)
            for axis, value in enumerate(point):
                if not isfinite(value):
                    raise ValueError(f"Nonfinite STL bounds: {path.name}")
                lows[axis] = min(lows[axis], value)
                highs[axis] = max(highs[axis], value)
    dimensions = [hi - lo for lo, hi in zip(lows, highs, strict=True)]
    if any(not isfinite(v) or v <= 0 for v in dimensions):
        raise ValueError(f"Degenerate STL bounds: {path.name}")
    return {
        "minimum_mm": [round(v, 3) for v in lows],
        "maximum_mm": [round(v, 3) for v in highs],
        "dimensions_mm": [round(v, 3) for v in dimensions],
    }


def closed_mesh_edges(path: Path) -> int:
    """Reject open, inverted-edge, nonfinite and degenerate STL geometry.

    Float32 coordinates are compared exactly as exported by OpenSCAD;
    this is a topological source check, not measured component fit.
    """
    blob = path.read_bytes()
    triangles = binary_stl_triangles(path)
    incidence: Counter = Counter()
    winding: Counter = Counter()
    # Closed shells that only touch at one vertex are still separate print
    # islands. Require triangle connectivity THROUGH SHARED EDGES, not merely
    # a common vertex coordinate.
    parents = list(range(triangles))
    first_face_for_edge = {}
    signed_six_volume = 0.0

    def root(face):
        while parents[face] != face:
            parents[face] = parents[parents[face]]
            face = parents[face]
        return face

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
        # Three different coordinates can still lie on one line. Such a
        # triangle has zero printable surface and is never a valid facet.
        a, b, c = points
        ab = tuple(b[k] - a[k] for k in range(3))
        ac = tuple(c[k] - a[k] for k in range(3))
        normal = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        if not all(isfinite(v) for v in normal) or not any(normal):
            raise ValueError(f"Degenerate or nonfinite STL triangle: {path.name}")
        # The dot of an oriented triangle's first vertex with its area
        # normal contributes six times signed enclosed volume.
        signed_six_volume += sum(a[k] * normal[k] for k in range(3))
        for corner in range(3):
            a, b = points[corner], points[(corner + 1) % 3]
            edge = (a, b) if a < b else (b, a)
            other_face = first_face_for_edge.setdefault(edge, index)
            parents[root(index)] = root(other_face)
            incidence[edge] += 1
            winding[edge] += 1 if a < b else -1
    if (not incidence
            or any(count != 2 for count in incidence.values())
            or any(direction != 0 for direction in winding.values())):
        raise ValueError(f"Open or inconsistent STL mesh: {path.name}")
    if len({root(index) for index in range(triangles)}) != 1:
        raise ValueError(f"Disconnected STL mesh: {path.name}")
    if not isfinite(signed_six_volume) or signed_six_volume <= 0:
        raise ValueError(f"Inverted or zero-volume STL mesh: {path.name}")
    return len(incidence)


def reference_body_footprint_screen(root: Path, output: Path) -> dict:
    """Screen flat tray orientation against a source chassis outer footprint.

    The original SMARS chassis mesh is an OUTER reference, not an interior
    cavity. A physical span longer than that outer XY diagonal cannot fit
    within its footprint at ANY flat yaw. This is necessary, not sufficient:
    no clearance, height, tilt, servo sweep or material strength is proven.
    """
    chassis = root / (
        "docs/cad/originals/smars-stepper/SMARS_2BJY8-Chassis.stl"
    )
    candidate = output / "fit_stls/battery_boost_tray.stl"
    result = {
        "source_mesh_only": True,
        "physical_interior_fit_verified": False,
        "reference_chassis_available": chassis.is_file(),
    }
    if not chassis.is_file():
        result["axis_aligned_packaging_possible"] = None
        result["flat_tray_any_yaw_impossible"] = None
        return result
    body = mesh_bounds_mm(chassis)["dimensions_mm"][:2]
    tray = mesh_bounds_mm(candidate)["dimensions_mm"][:2]
    fits = ((tray[0] <= body[0] and tray[1] <= body[1])
            or (tray[0] <= body[1] and tray[1] <= body[0]))
    # The longest actual XY extent connects two mesh vertices at least
    # this far apart. No pair of points inside the chassis outer XY
    # rectangle can be farther apart than its diagonal for any flat yaw.
    # This does not prove anything about 3D tilt or external mounting.
    outer_diagonal = hypot(*body)
    flat_yaw_impossible = max(tray) > outer_diagonal
    result.update({
        "chassis_original_mesh_sha256": sha256(chassis.read_bytes()).hexdigest(),
        "reference_chassis_xy_mm": body,
        "candidate_tray_xy_mm": tray,
        "chassis_outer_xy_diagonal_mm": round(outer_diagonal, 3),
        "flat_tray_any_yaw_impossible": flat_yaw_impossible,
        "axis_aligned_packaging_possible": fits,
    })
    return result


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
        ("fit_stls", source_dir / "speaker_rect_fit_gauge.scad", SPEAKER_FITS),
        ("fit_stls", source_dir / "vl53l0x_gy530_fit_gauge.scad", RANGER_FITS),
        ("dock_stls", source_dir / "dock/dock_passive_fit.scad", DOCKS),
    )
    for _, source, _ in sources:
        if not source.is_file():
            raise FileNotFoundError(f"Missing original parametric source: {source}")
    out.mkdir(parents=True, exist_ok=True)
    # Fail closed: a failed rebuild cannot retain an old success manifest.
    (out / "fit_kit_manifest.json").unlink(missing_ok=True)
    rendered: list[dict] = []
    # No incomplete candidate part gets published if any SCAD render fails.
    with tempfile.TemporaryDirectory(prefix="desk-fit-", dir=out) as folder:
        stage = Path(folder)
        for kind, source, parts in sources:
            scad_digest = sha256(source.read_bytes()).hexdigest()
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
                    "source": source.relative_to(root).as_posix(),
                    "source_sha256": scad_digest,
                    "mesh_sha256": sha256(target.read_bytes()).hexdigest(),
                    "units": "mm",
                    "triangles": triangles, "manifold_edges": edges,
                    "bbox_mm": mesh_bounds_mm(target),
                    # This number describes how many provisional candidates
                    # to export for layout, NOT approved installed inventory.
                    "quantity_per_robot": 8 if name == "tof_adjustable" else 1,
                    "installed_quantity_per_robot": 0,
                    "temporary_fit_coupon": name in (
                        *GAUGES, *SPEAKER_FITS, *RANGER_FITS,
                        "dock_rail_entry_coupon",
                        "dock_ir_pair_position_coupon",
                    ),
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
        "power_fit_scope": dict(POWER_FIT_SCOPE),
        "source_chassis_battery_footprint": reference_body_footprint_screen(
            root, out,
        ),
        "parts": rendered,
    }
    (out / "fit_kit_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8",
    )
    return report


def verify_fit_kit(root: Path = ROOT, *, output_dir: Path | None = None) -> dict:
    """Reject stale or changed print files; does not certify fit or power."""
    output = output_dir or root / "docs/cad/remixes"
    report = json.loads((output / "fit_kit_manifest.json").read_text(encoding="utf-8"))
    # Generated STLs are only reversible coupons. A hand-edited manifest
    # cannot turn any missing physical, assembly or licensing evidence into
    # a passing release claim without invalidating source verification.
    if (report.get("provisional_fit_parts_only") is not True
            or report.get("source_geometry_rendered") is not True
            or any(report.get(flag) is not False for flag in (
                "hardware_fit_verified",
                "full_printable_assembly_verified",
                "dock_charge_contacts_approved",
                "commercial_manufacture_authorized",
            ))):
        raise ValueError("Unsafe fit kit provenance flags")
    if report.get("power_fit_scope") != POWER_FIT_SCOPE:
        raise ValueError("Unsafe power fit scope")
    # A changed source chassis must invalidate an old packing screen.
    # Passing this reference-only screen can never authorize fit or charging.
    if report.get("source_chassis_battery_footprint") != (
        reference_body_footprint_screen(root, output)
    ):
        raise ValueError("Source chassis / battery tray footprint screen changed")
    expected = {}
    for folder, filename, names in (
        ("adapter_stls", "one_robot_adapter_kit.scad", ADAPTERS),
        ("fit_stls", "remaining_fit_gauges.scad", GAUGES),
        ("fit_stls", "speaker_rect_fit_gauge.scad", SPEAKER_FITS),
        ("fit_stls", "vl53l0x_gy530_fit_gauge.scad", RANGER_FITS),
        ("dock_stls", "dock/dock_passive_fit.scad", DOCKS),
    ):
        for name in names:
            expected[f"{folder}/{name}.stl"] = f"docs/cad/remixes/{filename}"
    items = report.get("parts")
    if (not isinstance(items, list) or len(items) != len(expected)
            or {item.get("location") for item in items} != set(expected)):
        raise ValueError("Missing or duplicate fit kit parts")
    for item in items:
        location = item["location"]
        # A manifest is not a release BOM. Even a syntactically valid edit
        # must never turn a test coupon into an installed robot component.
        name = Path(location).stem
        coupon = name in (*GAUGES, *SPEAKER_FITS, *RANGER_FITS,
                          "dock_rail_entry_coupon",
                          "dock_ir_pair_position_coupon")
        if (item.get("installed_quantity_per_robot") != 0
                or type(item.get("installed_quantity_per_robot")) is not int
                or item.get("temporary_fit_coupon") is not coupon):
            raise ValueError(f"Unqualified installed CAD part: {location}")
        if item.get("source") != expected[location]:
            raise ValueError(f"Wrong source for {location}")
        source = root / expected[location]
        mesh = output / location
        if sha256(source.read_bytes()).hexdigest() != item.get("source_sha256"):
            raise ValueError(f"SCAD source changed: {location}")
        if sha256(mesh.read_bytes()).hexdigest() != item.get("mesh_sha256"):
            raise ValueError(f"STL changed: {location}")
        if (binary_stl_triangles(mesh) != item.get("triangles")
                or closed_mesh_edges(mesh) != item.get("manifold_edges")):
            raise ValueError(f"Mesh geometry mismatch: {location}")
        if item.get("bbox_mm") != mesh_bounds_mm(mesh):
            raise ValueError(f"STL bounds changed: {location}")
    return report

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--openscad", default="openscad")
    parser.add_argument("--verify", action="store_true",
                        help="Validate existing mesh and source digests")
    args = parser.parse_args()
    if args.verify:
        report = verify_fit_kit(args.repo, output_dir=args.output)
    else:
        report = export_kit(
            args.repo, output_dir=args.output, openscad=args.openscad,
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
