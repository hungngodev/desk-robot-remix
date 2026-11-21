"""Print-scale AprilTag 36h11 SVG for the existing passive dock registration.

The bits come directly from installed OpenCV aruco, not an invented codebook.
This tool creates paper ART only, never a calibrated camera, powered dock,
seat confirmation or permission to move a robot.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
SCAD = ROOT / "docs/cad/remixes/dock/dock_passive_fit.scad"
FAMILY = "AprilTag 36h11"
MODULES_PER_SIDE = 8
MAX_MARKER_ID = 586


def read_dock_geometry(path: Path = SCAD) -> dict:
    """Read printer dimensions from the SAME SCAD source as the pocket."""
    data = path.read_bytes()
    source = data.decode("utf-8")
    values = {}
    for name in (
        "tag_black_side_mm", "tag_white_margin_each_mm",
        "tag_paper_slack_each_mm",
    ):
        matches = re.findall(
            rf"^{re.escape(name)}\s*=\s*(\d+(?:\.\d+)?)\s*;",
            source, flags=re.M,
        )
        if len(matches) != 1:
            raise ValueError("Dock marker dimension missing or ambiguous: " + name)
        values[name] = float(matches[0])
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


def build_svg(dock_id: int, marker_id: int, *, scad: Path = SCAD) -> str:
    if type(dock_id) is not int or not 1 <= dock_id <= 5:
        raise ValueError("Dock ID must be 1 through 5")
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
        f"source sha256 {dimensions['source_sha256']}. "
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


def save_or_verify(
    output: Path, dock_id: int, marker_id: int, *,
    scad: Path = SCAD, verify: bool = False, overwrite: bool = False,
) -> None:
    if output.suffix.lower() != ".svg":
        raise ValueError("Printed marker must be a vector .svg file")
    if verify and overwrite:
        raise ValueError("Verification cannot overwrite the source artifact")
    expected = build_svg(dock_id, marker_id, scad=scad)
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    save_or_verify(
        args.output, args.dock_id, args.marker_id,
        verify=args.verify, overwrite=args.overwrite,
    )
    print(
        "SVG source geometry verified. Physical print scale, "
        "camera calibration and real docking remain unqualified."
    )


if __name__ == "__main__":
    main()
