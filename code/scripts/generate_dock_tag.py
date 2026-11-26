"""Print-scale AprilTag 36h11 SVG for the existing passive dock registration.

The bits come directly from installed OpenCV aruco, not an invented codebook.
This tool creates paper ART only, never a calibrated camera, powered dock,
seat confirmation or permission to move a robot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
SCAD = ROOT / "docs/cad/remixes/dock/dock_passive_fit.scad"
ASSIGNMENTS = ROOT / "docs/cad/remixes/dock/tag_assignments.json"
FAMILY = "AprilTag 36h11"
MODULES_PER_SIDE = 8
MAX_MARKER_ID = 586



def read_marker_assignments(path: Path = ASSIGNMENTS, *,
                            raw: bytes | None = None) -> dict[int, int]:
    """One reviewed optical identity per physical NEC dock beacon.

    This is a candidate print manifest, not camera pose or motion approval.
    Validate the entire five-dock set before printing any single marker.
    """
    def reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        fields: dict[str, object] = {}
        for key, value in pairs:
            if key in fields:
                raise ValueError(
                    "Duplicate dock marker assignment JSON field: " + key
                )
            fields[key] = value
        return fields

    try:
        if raw is None:
            raw = path.read_bytes()
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=reject_duplicate_fields,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Dock marker assignment manifest missing or unreadable") from exc
    if (type(document) is not dict
            or set(document) != {"schema_version", "status", "family", "docks"}
            or type(document["schema_version"]) is not int
            or document["schema_version"] != 1
            or document["status"] != "candidate_only"
            or document["family"] != FAMILY
            or type(document["docks"]) is not list
            or len(document["docks"]) != 5):
        raise ValueError("Dock marker assignment manifest has invalid schema or scope")
    selected: dict[int, int] = {}
    beacons: set[int] = set()
    markers: set[int] = set()
    for row in document["docks"]:
        if type(row) is not dict or set(row) != {"dock_id", "beacon_id", "marker_id"}:
            raise ValueError("Dock marker assignment row is invalid")
        dock_id, beacon_id, marker_id = (
            row["dock_id"], row["beacon_id"], row["marker_id"]
        )
        if (type(dock_id) is not int or type(beacon_id) is not int
                or type(marker_id) is not int
                or not 1 <= dock_id <= 5
                or not 1 <= beacon_id <= 5
                or not 0 <= marker_id <= MAX_MARKER_ID
                or beacon_id != dock_id):
            raise ValueError("Dock marker assignment has invalid dock/beacon/marker identity")
        if dock_id in selected or beacon_id in beacons:
            raise ValueError("Duplicate dock or NEC beacon assignment")
        if marker_id in markers:
            raise ValueError("Duplicate optical marker across docks")
        selected[dock_id] = marker_id
        beacons.add(beacon_id)
        markers.add(marker_id)
    if set(selected) != set(range(1, 6)):
        raise ValueError("Missing dock assignment: exactly docks 1 through 5 required")
    return selected


def read_dock_geometry(path: Path = SCAD) -> dict:
    """Read printer dimensions from the SAME SCAD source as the pocket."""
    data = path.read_bytes()
    # Ignore inactive SCAD comments and quoted text before counting assignments.
    # Keep strings nonnumeric so a quoted dimension cannot become a literal.
    source = re.sub(
        r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"',
        lambda match: '""' if match[0].startswith('"') else " ",
        data.decode("utf-8"),
    )
    values = {}
    for name in (
        "tag_black_side_mm", "tag_white_margin_each_mm",
        "tag_paper_slack_each_mm",
    ):
        # Count every assignment before parsing its value. An expression or
        # indented override must not hide behind an earlier numeric literal.
        assignments = list(re.finditer(rf"\b{re.escape(name)}\s*=(?!=)", source))
        if len(assignments) != 1:
            raise ValueError("Dock marker dimension missing or ambiguous: " + name)
        literal = re.match(r"\s*(\d+(?:\.\d+)?)\s*;", source[assignments[0].end():])
        if literal is None:
            raise ValueError("Dock marker dimension must be a numeric literal: " + name)
        values[name] = float(literal[1])
    black = values["tag_black_side_mm"]
    margin = values["tag_white_margin_each_mm"]
    slack = values["tag_paper_slack_each_mm"]
    if not (10 <= black <= 75 and 4 <= margin <= 10
            and 0.25 <= slack <= 1.5):
        raise ValueError("Dock marker geometry violates its printed SCAD bounds")
    return {
        "black_mm": black,
        "white_margin_mm": margin,
        "paper_mm": black + 2 * margin,
        "pocket_mm": black + 2 * (margin + slack),
        "source_sha256": hashlib.sha256(data).hexdigest(),
    }


def marker_bits(marker_id: int) -> list[list[bool]]:
    if type(marker_id) is not int or not 0 <= marker_id <= MAX_MARKER_ID:
        raise ValueError("AprilTag 36h11 marker ID must be 0 through 586")
    import cv2

    if not hasattr(cv2, "aruco"):
        raise RuntimeError("OpenCV aruco is required; install the vision extra")
    dictionary = cv2.aruco.getPredefinedDictionary(
        cv2.aruco.DICT_APRILTAG_36h11
    )
    # 6 data bits plus 1 dark border bit on EACH side. 8 pixels means
    # one exact module per pixel, with no interpolation or antialiasing.
    image = cv2.aruco.generateImageMarker(
        dictionary, marker_id, MODULES_PER_SIDE, borderBits=1
    )
    if image.shape != (MODULES_PER_SIDE, MODULES_PER_SIDE):
        raise ValueError("OpenCV returned wrong AprilTag module count")
    bits = [[int(pixel) == 0 for pixel in row] for row in image]
    if not all(
        bits[0][i] and bits[-1][i] and bits[i][0] and bits[i][-1]
        for i in range(MODULES_PER_SIDE)
    ):
        raise ValueError("OpenCV output missing AprilTag dark border")
    return bits


def build_svg(dock_id: int, marker_id: int, *, scad: Path = SCAD,
              assignments: Path = ASSIGNMENTS) -> str:
    if type(dock_id) is not int or not 1 <= dock_id <= 5:
        raise ValueError("Dock ID must be 1 through 5")
    try:
        assignment_bytes = assignments.read_bytes()
    except OSError as exc:
        raise ValueError("Dock marker assignment manifest missing or unreadable") from exc
    mapping = read_marker_assignments(assignments, raw=assignment_bytes)
    if type(marker_id) is not int or marker_id != mapping[dock_id]:
        raise ValueError(
            f"Dock {dock_id} requires marker {mapping[dock_id]} from the "
            "reviewed five-dock assignment manifest; regenerate tag and calibration"
        )
    dimensions = read_dock_geometry(scad)
    bits = marker_bits(marker_id)
    margin = dimensions["white_margin_mm"]
    paper = dimensions["paper_mm"]
    module = dimensions["black_mm"] / MODULES_PER_SIDE
    svg = ElementTree.Element("svg", attrib={
        "xmlns": "http://www.w3.org/2000/svg",
        "width": f"{paper:g}mm",
        "height": f"{paper:g}mm",
        "viewBox": f"0 0 {paper:g} {paper:g}",
    })
    desc = ElementTree.SubElement(svg, "desc")
    desc.text = (
        f"{FAMILY} marker {marker_id} for dock {dock_id}; "
        f"black side {dimensions['black_mm']:g} mm; "
        f"white quiet margin {margin:g} mm each side; "
        f"source sha256 {dimensions['source_sha256']}; "
        f"assignment sha256 {hashlib.sha256(assignment_bytes).hexdigest()}. "
        "Print at 100 percent actual size. Measure physical black square."
    )
    ElementTree.SubElement(svg, "rect", attrib={
        "x": "0", "y": "0", "width": f"{paper:g}",
        "height": f"{paper:g}", "fill": "#fff",
    })
    for y, row in enumerate(bits):
        for x, black in enumerate(row):
            if black:
                ElementTree.SubElement(svg, "rect", attrib={
                    "x": f"{margin + x * module:g}",
                    "y": f"{margin + y * module:g}",
                    "width": f"{module:g}",
                    "height": f"{module:g}",
                    "fill": "#000",
                })
    return ElementTree.tostring(svg, encoding="unicode") + "\n"


def _reject_dock_tag_output_aliases(output: Path) -> None:
    """Never stage, read or replace a marker through mutable path aliases."""
    if output.is_symlink():
        raise ValueError(f"Symlinked dock tag output path: {output}")
    for parent in output.parents:
        if not parent.is_symlink():
            continue
        # Root-owned /var or /tmp aliases under a nonwritable parent are
        # normal on macOS. A mutable project or temp-directory alias is not.
        if (parent.lstat().st_uid == 0
                and not (parent.parent.stat().st_mode & 0o022)):
            continue
        raise ValueError(f"Symlinked dock tag output path: {parent}")


def save_or_verify(
    output: Path, dock_id: int, marker_id: int, *,
    scad: Path = SCAD, assignments: Path = ASSIGNMENTS,
    verify: bool = False, overwrite: bool = False,
) -> None:
    if output.suffix.lower() != ".svg":
        raise ValueError("Printed marker must be a vector .svg file")
    _reject_dock_tag_output_aliases(output)
    if verify and overwrite:
        raise ValueError("Verification cannot overwrite the source artifact")
    expected = build_svg(dock_id, marker_id, scad=scad, assignments=assignments)
    if verify:
        if output.read_text(encoding="utf-8") != expected:
            raise ValueError("Dock tag changed, wrong marker ID or stale SCAD revision")
        return
    if output.exists() and not overwrite:
        raise FileExistsError("Existing dock tag requires --overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent,
        prefix=".dock-tag-", suffix=".svg", delete=False,
    ) as staged:
        path = Path(staged.name)
        try:
            staged.write(expected)
            staged.flush()
            os.fsync(staged.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    os.replace(path, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dock-id", type=int, required=True)
    parser.add_argument("--marker-id", type=int, required=True)
    parser.add_argument("--assignments", type=Path, default=ASSIGNMENTS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    save_or_verify(
        args.output, args.dock_id, args.marker_id,
        assignments=args.assignments, verify=args.verify,
        overwrite=args.overwrite,
    )
    print(
        "SVG source geometry verified. Physical print scale, "
        "camera calibration and real docking remain unqualified."
    )


if __name__ == "__main__":
    main()
