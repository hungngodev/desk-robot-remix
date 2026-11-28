"""Reproducibly render ORIGINAL provisional robot adapters and fit gauges.

This builds mesh candidates only. It does not approve actual measured
component fit, batteries, dock contacts, commercial licenses or assembly.
Run from the repository checkout with a locally installed OpenSCAD binary.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from collections import Counter
from hashlib import sha256
from math import hypot, isfinite, ldexp
from pathlib import Path
from stat import S_ISDIR, S_ISREG
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
RANGER_FITS = (
    "vl53l0x_gy530_fit_gauge",
    "vl53l0x_gy530_height_trial_035",
    "vl53l0x_gy530_height_trial_045",
    "vl53l0x_gy530_height_trial_055",
)
MG90S_FITS = ("mg90s_fit_015", "mg90s_fit_030",
              "mg90s_fit_045", "mg90s_fit_060")
DOCKS = ("dock_passive_fit", "dock_rail_entry_coupon",
         "dock_ir_pair_position_coupon")

FDM_PRINT_GUIDANCE = {
    "starting_layer_height_mm": 0.2,
    "nozzle_diameter_mm": None,
    "xy_clearance_mm": None,
    "instruction": "Select nozzle in slicer; measure a printed fit coupon with calipers.",
}


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


# These are explicit leading source comments, not a grant inferred from
# the repository MIT license (which expressly excludes CAD).
CC0_SOURCE_NOTICES = frozenset({
    "// ONE desk robot adapter kit. CC0 original code. Units mm.",
    "// Desk robot remaining mechanical FIT TESTS. Units mm, original CC0 source.",
    "// Challenge Electronics CS20-02P110-04-1X. Original CC0 adapter.",
    "// Original CC0 source. Print a coupon and measure the ACTUAL part.",
    "// CC0 original part. Nominal dimensions are an example, not measured robot fit.",
    "// SPDX-License-Identifier: CC0-1.0",
})


def source_license_evidence(source: bytes) -> dict:
    """Record explicit source declarations, never infer CAD rights from MIT."""
    for line in source.decode("utf-8").splitlines():
        if not line.startswith("//"):
            break
        if line in CC0_SOURCE_NOTICES:
            return {"declared_spdx": "CC0-1.0", "source_notice": line[3:]}
    return {"declared_spdx": None, "source_notice": None}


def binary_stl_triangles(path: Path) -> int:
    """Reject empty, truncated or malformed binary STL output."""
    blob = path.read_bytes()
    if len(blob) < 84:
        raise ValueError(f"Truncated STL: {path.name}")
    triangles = int.from_bytes(blob[80:84], "little")
    if triangles < 1 or len(blob) != 84 + 50 * triangles:
        raise ValueError(f"Invalid binary STL triangles: {path.name}")
    return triangles


def mesh_bounds_mm(path: Path, *, rounded: bool = True) -> dict:
    """Read actual exported STL bounds in millimeters, never assumed CAD size.

    STL has no native unit metadata: millimeters are the declared OpenSCAD
    export convention. A bounding box is a print-layout aid, NOT component
    fit, internal clearance, mechanical assembly or strength certification.
    Use unrounded dimensions for geometric comparisons; rounding is for display.
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
        "minimum_mm": [round(v, 3) for v in lows] if rounded else lows,
        "maximum_mm": [round(v, 3) for v in highs] if rounded else highs,
        "dimensions_mm": [round(v, 3) for v in dimensions] if rounded else dimensions,
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
    vertex_links: dict = {}
    # Closed shells that only touch at one vertex are still separate print
    # islands. Require triangle connectivity THROUGH SHARED EDGES, not merely
    # a common vertex coordinate.
    parents = list(range(triangles))
    first_face_for_edge = {}
    signed_six_volume = 0

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
        # Every finite binary32 coordinate is an exact multiple of 2**-149.
        # Scaling by that power of two fits in binary64 without rounding,
        # then integer cross products and volume sums avoid cancellation.
        # Keep the original float tuples for exact shared-edge identities.
        a, b, c = (
            tuple(int(ldexp(value, 149)) for value in point)
            for point in points
        )
        ab = tuple(b[k] - a[k] for k in range(3))
        ac = tuple(c[k] - a[k] for k in range(3))
        normal = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        if not any(normal):
            raise ValueError(f"Degenerate or nonfinite STL triangle: {path.name}")
        # The dot of an oriented triangle's first vertex with its area
        # normal contributes six times signed enclosed volume in the
        # scaled integer lattice. Its sign is unchanged by the scaling.
        signed_six_volume += sum(a[k] * normal[k] for k in range(3))
        for corner in range(3):
            a, b, c = (points[corner], points[(corner + 1) % 3],
                       points[(corner + 2) % 3])
            link = vertex_links.setdefault(a, {})
            link.setdefault(b, set()).add(c)
            link.setdefault(c, set()).add(b)
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
    # Edge pairing and whole-mesh connectivity do not rule out a vertex
    # where two disjoint triangle fans touch. A manifold vertex link is
    # one connected cycle (the incident triangles form one local surface).
    for link in vertex_links.values():
        if any(len(neighbors) != 2 for neighbors in link.values()):
            raise ValueError(f"Nonmanifold STL vertex: {path.name}")
        seen = set()
        pending = [next(iter(link))]
        while pending:
            neighbor = pending.pop()
            if neighbor not in seen:
                seen.add(neighbor)
                pending.extend(link[neighbor] - seen)
        if len(seen) != len(link):
            raise ValueError(f"Nonmanifold STL vertex: {path.name}")
    if signed_six_volume <= 0:
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
    # Rounded report dimensions can reverse near-boundary comparisons.
    body = mesh_bounds_mm(chassis, rounded=False)["dimensions_mm"][:2]
    tray = mesh_bounds_mm(candidate, rounded=False)["dimensions_mm"][:2]
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
        "reference_chassis_xy_mm": [round(v, 3) for v in body],
        "candidate_tray_xy_mm": [round(v, 3) for v in tray],
        "chassis_outer_xy_diagonal_mm": round(outer_diagonal, 3),
        "flat_tray_any_yaw_impossible": flat_yaw_impossible,
        "axis_aligned_packaging_possible": fits,
    })
    return result


def _reject_fit_kit_output_aliases(output: Path) -> None:
    """Never read or publish generated CAD through symlinked artifact paths.

    The candidate output is user selected, but its three generated part
    directories and manifest must remain inside that selected directory.
    Check before deleting a prior manifest or starting any mesh render.
    """
    # The default macOS temp tree can traverse root-owned /var or /tmp
    # aliases. Trust only system-owned links beneath nonwritable parents.
    # A user-controlled ancestor could otherwise redirect an entire output.
    for ancestor in (output, *output.parents):
        if not ancestor.is_symlink():
            continue
        if (ancestor.lstat().st_uid == 0
                and not (ancestor.parent.stat().st_mode & 0o022)):
            continue
        raise ValueError(f"Symlinked fit kit output path: {ancestor}")
    paths = [output / "fit_kit_manifest.json"]
    groups = (
        ("adapter_stls", ADAPTERS),
        ("fit_stls", (*GAUGES, *SPEAKER_FITS, *RANGER_FITS, *MG90S_FITS)),
        ("dock_stls", DOCKS),
    )
    for folder, names in groups:
        root = output / folder
        if root.is_symlink():
            raise ValueError(f"Symlinked fit kit output path: {root}")
        try:
            info = root.lstat()
        except FileNotFoundError:
            pass
        else:
            if not S_ISDIR(info.st_mode):
                raise ValueError(f"Non-directory fit kit output path: {root}")
        paths.extend(root / f"{name}.stl" for name in names)
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"Symlinked fit kit output path: {path}")
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        # Special files can block reads; hardlinks can alias unrelated data.
        if not S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(f"Nonregular or hardlinked fit kit output: {path}")
    # A passing manifest must describe the entire generated STL inventory.
    # Earlier candidate names can otherwise remain beside the current 23
    # signed parts and be mistaken for printable/installed assembly files.
    for folder, names in groups:
        part_dir = output / folder
        if not part_dir.is_dir():
            continue
        declared = {f"{name}.stl" for name in names}
        for entry in part_dir.iterdir():
            if entry.suffix.lower() == ".stl" and entry.name not in declared:
                raise ValueError(f"Undeclared fit kit STL: {entry}")


def _read_scad_source(root: Path, source: Path) -> tuple[bytes, tuple[int, ...]]:
    """Read one regular checkout source without following internal aliases."""
    parts = source.relative_to(root).parts
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory,
            )
            os.close(directory)
            directory = child
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory,
        )
        try:
            before = os.fstat(fd)
            if not S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError(f"Nonregular or hardlinked SCAD source: {source}")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read()
            after = os.fstat(fd)
        finally:
            os.close(fd)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ValueError(f"Unsafe SCAD source path: {source}") from exc
    finally:
        os.close(directory)

    def identity(info: os.stat_result) -> tuple[int, ...]:
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_ctime_ns, info.st_nlink)

    if identity(before) != identity(after):
        raise ValueError(f"SCAD source changed during read: {source}")
    return data, identity(after)


def export_kit(
    root: Path = ROOT, *, output_dir: Path | None = None,
    openscad: str = "openscad",
) -> dict:
    source_dir = root / "docs/cad/remixes"
    out = output_dir or source_dir
    sources = (
        ("adapter_stls", source_dir / "one_robot_adapter_kit.scad", ADAPTERS),
        ("fit_stls", source_dir / "remaining_fit_gauges.scad", GAUGES),
        ("fit_stls", source_dir / "speaker_rect_fit_gauge.scad", SPEAKER_FITS),
        ("fit_stls", source_dir / "mg90s_pocket_fit_gauges.scad", MG90S_FITS),
        ("fit_stls", source_dir / "vl53l0x_gy530_fit_gauge.scad", RANGER_FITS),
        ("dock_stls", source_dir / "dock/dock_passive_fit.scad", DOCKS),
    )
    _reject_fit_kit_output_aliases(out)
    # Fail closed: a failed rebuild cannot retain an old success manifest.
    (out / "fit_kit_manifest.json").unlink(missing_ok=True)
    if not shutil.which(openscad):
        raise FileNotFoundError(f"OpenSCAD is not installed: {openscad}")
    out.mkdir(parents=True, exist_ok=True)
    rendered: list[dict] = []
    # No incomplete candidate part gets published if any SCAD render fails.
    with tempfile.TemporaryDirectory(prefix="desk-fit-", dir=out) as folder:
        stage = Path(folder)
        # Render only the bytes whose digest is recorded. The six current
        # SCAD sources are standalone (no external includes/imports).
        snapshots = {source: _read_scad_source(root, source) for _, source, _ in sources}
        for kind, source, parts in sources:
            source_bytes, _ = snapshots[source]
            staged_source = stage / "source_snapshot" / source.relative_to(source_dir)
            staged_source.parent.mkdir(parents=True, exist_ok=True)
            staged_source.write_bytes(source_bytes)
            scad_digest = sha256(source_bytes).hexdigest()
            license_evidence = source_license_evidence(source_bytes)
            for name in parts:
                target = stage / kind / (name + ".stl")
                target.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    [
                        openscad, "--hardwarnings", "--export-format", "binstl", "-o",
                        str(target), "-D", f'part="{name}"', str(staged_source),
                    ],
                    check=True, capture_output=True, text=True, timeout=180,
                )
                triangles = binary_stl_triangles(target)
                edges = closed_mesh_edges(target)
                rendered.append({
                    "part": name, "location": f"{kind}/{name}.stl",
                    "source": source.relative_to(root).as_posix(),
                    "source_sha256": scad_digest,
                    "source_license": dict(license_evidence),
                    "mesh_sha256": sha256(target.read_bytes()).hexdigest(),
                    "units": "mm",
                    "triangles": triangles, "manifold_edges": edges,
                    "bbox_mm": mesh_bounds_mm(target),
                    # This number describes how many provisional candidates
                    # to export for layout, NOT approved installed inventory.
                    "quantity_per_robot": 8 if name == "tof_adjustable" else 1,
                    "installed_quantity_per_robot": 0,
                    "temporary_fit_coupon": name in (
                        *GAUGES, *SPEAKER_FITS, *RANGER_FITS, *MG90S_FITS,
                        *DOCKS,
                    ),
                })
        # Recheck before publishing meshes AND again after footprint screening
        # before atomically publishing fit_kit_manifest.json last.
        for source, snapshot in snapshots.items():
            if _read_scad_source(root, source) != snapshot:
                raise ValueError(f"SCAD source changed during export: {source.name}")
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
            "fdm_print_guidance": dict(FDM_PRINT_GUIDANCE),
            "power_fit_scope": dict(POWER_FIT_SCOPE),
            "source_chassis_battery_footprint": reference_body_footprint_screen(
                root, out,
            ),
            "parts": rendered,
        }
        staged_manifest = stage / "fit_kit_manifest.json"
        staged_manifest.write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        for source, snapshot in snapshots.items():
            if _read_scad_source(root, source) != snapshot:
                raise ValueError(f"SCAD source changed during export: {source.name}")
        os.replace(staged_manifest, out / "fit_kit_manifest.json")
    return report


def screen_print_bed_fit(
    report: dict,
    bed_xyz_mm: tuple[float, float, float],
    *,
    output_dir: Path | None = None,
) -> dict:
    """Conservative source-mesh screen for a user supplied printer volume.

    Flat orientation means keeping the exported STL's Z axis vertical.
    A source XY bounding box fitting at 0 or 90 degrees is only a necessary
    plate envelope check. Unknown orientations are NOT cleared; a physical
    span longer than the plate diagonal rules out every in-plane yaw.
    Do not treat the result as print strength, support, material or fit proof.
    """
    if (not isinstance(bed_xyz_mm, (list, tuple))
            or len(bed_xyz_mm) != 3
            or any(type(v) not in (float, int)
                   or not 1 <= v <= 5000 or not isfinite(v)
                   for v in bed_xyz_mm)):
        raise ValueError("Printer X/Y/Z build dimensions must be finite positive mm")
    if not isinstance(report, dict) or not isinstance(report.get("parts"), list):
        raise ValueError("Printer screen requires a candidate mesh manifest")
    x_bed, y_bed, z_bed = bed_xyz_mm
    diagonal = hypot(x_bed, y_bed)
    output = []
    for item in report["parts"]:
        if not isinstance(item, dict):
            raise ValueError("Missing candidate part")
        bounds = item.get("bbox_mm")
        dims = bounds.get("dimensions_mm") if isinstance(bounds, dict) else None
        if (not isinstance(dims, list) or len(dims) != 3
                or any(type(v) not in (float, int)
                       or not 0 < v <= 1_000_000 or not isfinite(v)
                       for v in dims)
                or not isinstance(item.get("location"), str)):
            raise ValueError("Missing or invalid exported STL build envelope")
        decision_dims = (
            mesh_bounds_mm(Path(output_dir) / item["location"], rounded=False)["dimensions_mm"]
            if output_dir is not None else dims
        )
        sx, sy, sz = decision_dims
        fits_flat = (sz <= z_bed and (
            (sx <= x_bed and sy <= y_bed)
            or (sx <= y_bed and sy <= x_bed)))
        excluded_by_span = max(sx, sy) > diagonal
        output.append({
            "part": item["location"],
            "mesh_xyz_mm": list(dims),
            "fits_source_bounds_flat_at_zero_or_ninety_deg": fits_flat,
            "flat_yaw_impossible_by_plate_diagonal": excluded_by_span,
            "flat_height_exceeds_build_volume": sz > z_bed,
            "other_orientation_or_support_fit_qualified": False,
        })
    return {
        "printer_xyz_mm": list(bed_xyz_mm),
        "printer_bed_diagonal_mm": round(diagonal, 3),
        "source_mesh_screen_only": True,
        "physical_printer_or_material_qualified": False,
        "parts": output,
    }


def strict_fit_kit_manifest_object(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicated JSON keys that conceal contradictory CAD evidence."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate fit kit manifest key")
        result[key] = value
    return result


def reject_nonfinite_fit_kit_number(token: str) -> None:
    raise ValueError("Nonfinite fit kit manifest number: " + token)


def same_json_evidence(left: object, right: object) -> bool:
    """Preserve exact JSON scalar types when checking immutable CAD evidence.

    Like the procurement receipt comparison, numeric equivalence is not
    evidence equivalence: JSON true must not replace 1.0 or zero. Canonical
    serialization also ignores irrelevant object key ordering.
    """
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False
    )


def verify_fit_kit(root: Path = ROOT, *, output_dir: Path | None = None) -> dict:
    """Reject stale or changed print files; does not certify fit or power."""
    output = output_dir or root / "docs/cad/remixes"
    _reject_fit_kit_output_aliases(output)
    manifest = output / "fit_kit_manifest.json"
    if not manifest.is_file():
        # Fresh clones deliberately do not ship generated, unqualified STLs.
        # Tell the builder how to render the SAME candidate and verify it,
        # rather than surfacing a raw FileNotFoundError with no next step.
        command = (
            "python code/scripts/export_fit_kit.py --repo "
            + shlex.quote(str(root))
            + " --output " + shlex.quote(str(output))
        )
        raise ValueError(
            f"Candidate fit kit manifest missing: {manifest}. "
            "Install OpenSCAD and run: " + command + ". "
            "Then rerun with --verify using the same --repo and --output. "
            "Exported gauges are provisional and do not prove fitted production "
            "assembly, power safety or dock charging."
        )
    report = json.loads(
        manifest.read_text(encoding="utf-8"),
        object_pairs_hook=strict_fit_kit_manifest_object,
        parse_constant=reject_nonfinite_fit_kit_number,
    )
    if not isinstance(report, dict):
        raise ValueError("Invalid fit kit manifest root")
    # This is a provisional mesh receipt, not an extensible release record.
    # Unknown fields must not smuggle physical fit or charge approval into
    # a verified result even when the known safety flags remain false.
    if set(report) != {
        "provisional_fit_parts_only", "source_geometry_rendered",
        "hardware_fit_verified", "full_printable_assembly_verified",
        "dock_charge_contacts_approved", "commercial_manufacture_authorized",
        "fdm_print_guidance", "power_fit_scope", "source_chassis_battery_footprint", "parts",
    }:
        raise ValueError("Unexpected fit kit manifest fields")
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
    if not same_json_evidence(report.get("fdm_print_guidance"), FDM_PRINT_GUIDANCE):
        raise ValueError("Altered FDM print guidance")
    if not same_json_evidence(report.get("power_fit_scope"), POWER_FIT_SCOPE):
        raise ValueError("Unsafe power fit scope")
    # A changed source chassis must invalidate an old packing screen.
    # Passing this reference-only screen can never authorize fit or charging.
    if not same_json_evidence(
        report.get("source_chassis_battery_footprint"),
        reference_body_footprint_screen(root, output),
    ):
        raise ValueError("Source chassis / battery tray footprint screen changed")
    expected = {}
    for folder, filename, names in (
        ("adapter_stls", "one_robot_adapter_kit.scad", ADAPTERS),
        ("fit_stls", "remaining_fit_gauges.scad", GAUGES),
        ("fit_stls", "speaker_rect_fit_gauge.scad", SPEAKER_FITS),
        ("fit_stls", "mg90s_pocket_fit_gauges.scad", MG90S_FITS),
        ("fit_stls", "vl53l0x_gy530_fit_gauge.scad", RANGER_FITS),
        ("dock_stls", "dock/dock_passive_fit.scad", DOCKS),
    ):
        for name in names:
            expected[f"{folder}/{name}.stl"] = f"docs/cad/remixes/{filename}"
    items = report.get("parts")
    if (not isinstance(items, list) or len(items) != len(expected)
            or any(not isinstance(item, dict)
                   or type(item.get("location")) is not str
                   for item in items)
            or {item["location"] for item in items} != set(expected)):
        raise ValueError("Missing or duplicate fit kit parts")
    for item in items:
        if set(item) != {
            "part", "location", "source", "source_sha256", "source_license",
            "mesh_sha256",
            "units", "triangles", "manifold_edges", "bbox_mm",
            "quantity_per_robot", "installed_quantity_per_robot",
            "temporary_fit_coupon",
        }:
            raise ValueError("Unexpected fit kit part fields")
        location = item["location"]
        # A manifest is not a release BOM. Even a syntactically valid edit
        # must never turn a test coupon into an installed robot component.
        name = Path(location).stem
        coupon = name in (
            *GAUGES, *SPEAKER_FITS, *RANGER_FITS, *MG90S_FITS, *DOCKS
        )
        # Sources and mesh bytes cannot validate a hand-edited label, unit
        # system or quoted build quantity. Keep source-first prototypes
        # from being mistaken for final install or procurement instructions.
        quantity = 8 if name == "tof_adjustable" else 1
        if (item.get("part") != name or item.get("units") != "mm"
                or type(item.get("quantity_per_robot")) is not int
                or item["quantity_per_robot"] != quantity):
            raise ValueError(f"Altered CAD part identity/quantity/units: {location}")
        if (item.get("installed_quantity_per_robot") != 0
                or type(item.get("installed_quantity_per_robot")) is not int
                or item.get("temporary_fit_coupon") is not coupon):
            raise ValueError(f"Unqualified installed CAD part: {location}")
        if item.get("source") != expected[location]:
            raise ValueError(f"Wrong source for {location}")
        source = root / expected[location]
        mesh = output / location
        source_bytes, _ = _read_scad_source(root, source)
        if sha256(source_bytes).hexdigest() != item.get("source_sha256"):
            raise ValueError(f"SCAD source changed: {location}")
        if not same_json_evidence(
            item.get("source_license"), source_license_evidence(source_bytes),
        ):
            raise ValueError(f"SCAD source license evidence changed: {location}")
        if sha256(mesh.read_bytes()).hexdigest() != item.get("mesh_sha256"):
            raise ValueError(f"STL changed: {location}")
        if (type(item.get("triangles")) is not int
                or type(item.get("manifold_edges")) is not int
                or binary_stl_triangles(mesh) != item["triangles"]
                or closed_mesh_edges(mesh) != item["manifold_edges"]):
            raise ValueError(f"Mesh geometry mismatch: {location}")
        if not same_json_evidence(item.get("bbox_mm"), mesh_bounds_mm(mesh)):
            raise ValueError(f"STL bounds changed: {location}")
    return report

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--openscad", default="openscad")
    parser.add_argument("--verify", action="store_true",
                        help="Validate existing mesh and source digests")
    parser.add_argument("--build-volume-mm", nargs=3, type=float,
                        metavar=("X", "Y", "Z"),
                        help="Source STL bounding screen for your measured printer X Y Z mm")
    args = parser.parse_args()
    if args.verify:
        report = verify_fit_kit(args.repo, output_dir=args.output)
    else:
        report = export_kit(
            args.repo, output_dir=args.output, openscad=args.openscad,
        )
    if args.build_volume_mm is not None:
        output_dir = args.output or (args.repo / "docs/cad/remixes")
        report = dict(report)
        report["print_bed_screen"] = screen_print_bed_fit(
            report, tuple(args.build_volume_mm), output_dir=output_dir,
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
