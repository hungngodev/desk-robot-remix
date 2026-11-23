"""Provisional A4 paper overlays at true millimetre scale, not drill releases.

All source dimensions come from the current OpenSCAD references. The actual
carriers, camera, mounting holes and charging hardware still require calipers.
"""
from __future__ import annotations

import argparse
import json
import re
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[3]
A4_WIDTH_MM = 210
A4_HEIGHT_MM = 297
SOURCES = {
    "ranger": "docs/cad/remixes/vl53l0x_gy530_fit_gauge.scad",
    "speaker": "docs/cad/remixes/speaker_rect_fit_gauge.scad",
    "dock": "docs/cad/remixes/dock/dock_passive_fit.scad",
    "power": "docs/cad/remixes/remaining_fit_gauges.scad",
}


def scad_mm(source: str, variable: str) -> float:
    """Read one literal millimetre dimension; never evaluate SCAD expressions."""
    matches = re.findall(
        rf"(?m)^\s*{re.escape(variable)}\s*=\s*(\d+(?:\.\d+)?)\s*;",
        source,
    )
    if len(matches) != 1:
        raise ValueError(f"Missing or ambiguous source dimension: {variable}")
    value = float(matches[0])
    if not 0 < value < A4_HEIGHT_MM:
        raise ValueError(f"Out-of-range source dimension: {variable}")
    return value


def values(root: Path) -> dict:
    data = {name: (root / path).read_text(encoding="utf-8")
            for name, path in SOURCES.items()}
    black = scad_mm(data["dock"], "tag_black_side_mm")
    quiet = scad_mm(data["dock"], "tag_white_margin_each_mm")
    slack = scad_mm(data["dock"], "tag_paper_slack_each_mm")
    paper = black + 2 * quiet
    pocket = paper + 2 * slack
    if not (0 < black < paper < pocket <= 120):
        raise ValueError("Invalid dock paper/pocket dimensions")
    power = data["power"]
    candidate_length = scad_mm(power, "candidate_pack_body_l_mm")
    pack_l = scad_mm(power, "power_l")
    pack_w = scad_mm(power, "power_w")
    fit_xy = scad_mm(power, "fit_xy")
    wall = scad_mm(power, "wall")
    if pack_l < candidate_length:
        raise ValueError("Power tray shorter than candidate protected pack body")
    tray_l = pack_l + 2 * (fit_xy + wall)
    tray_w = pack_w + 2 * (fit_xy + wall)
    return {
        "ranger": (scad_mm(data["ranger"], "board_x"),
                   scad_mm(data["ranger"], "board_y")),
        "speaker": (scad_mm(data["speaker"], "speaker_l"),
                    scad_mm(data["speaker"], "speaker_w")),
        "dock": (black, paper, pocket),
        "power": (pack_l, pack_w, tray_l, tray_w),
    }


def _num(value: float) -> str:
    return f"{value:g}"


def _rect(x: float, y: float, width: float, height: float,
          *, dash: bool = False) -> str:
    extra = ' stroke-dasharray="2 2"' if dash else ""
    return (f'<rect x="{_num(x)}" y="{_num(y)}" '
            f'width="{_num(width)}" height="{_num(height)}" '
            f'fill="none" stroke="black" stroke-width="0.3"{extra}/>')


def _text(x: float, y: float, value: str, *, size: int = 4) -> str:
    # Values passed here are fixed labels and numeric dimensions, not HTML.
    return (f'<text x="{_num(x)}" y="{_num(y)}" '
            f'font-family="sans-serif" font-size="{size}">{value}</text>')


def svg(name: str, dims: tuple[float, ...]) -> str:
    if name not in SOURCES:
        raise ValueError("Unknown 2D fit reference")
    if name == "dock":
        black, paper, pocket = dims
        x, y = (A4_WIDTH_MM-pocket)/2, 76
        # The first legend baseline is y=171 (4 mm text). Preserve at
        # least 4 mm whitespace after the nominal pocket outline; a wider
        # measured tag must use a redesigned layout, not overlapping ink.
        if x < 15 or y + pocket > 163:
            raise ValueError("Dock pocket outline exceeds A4 printable layout")
        features = (
            _rect(x, y, pocket, pocket, dash=True)
            + _rect(x+(pocket-paper)/2, y+(pocket-paper)/2, paper, paper)
            + _rect(x+(pocket-black)/2, y+(pocket-black)/2, black, black)
            + _text(20, 171, f"Tag black square: {_num(black)} mm (NOT an AprilTag)")
            + _text(20, 178, f"White-border paper: {_num(paper)} mm")
            + _text(20, 185, f"Nominal dock pocket: {_num(pocket)} mm (dashed)")
        )
        title = "Dock paper / passive pocket outline"
    elif name == "power":
        pack_l, pack_w, tray_l, tray_w = dims
        x, y = (A4_WIDTH_MM - tray_l) / 2, 88
        if x < 15 or y + tray_w > 157:
            raise ValueError("Power outline exceeds A4 printable layout")
        features = (
            _rect(x, y, tray_l, tray_w, dash=True)
            + _rect(x + (tray_l - pack_l) / 2,
                    y + (tray_w - pack_w) / 2, pack_l, pack_w)
            + _text(20, 169, f"Pack body only: {_num(pack_l)} x {_num(pack_w)} mm")
            + _text(20, 176, f"Nominal tray outside: {_num(tray_l)} x {_num(tray_w)} mm (dashed)")
            + _text(20, 183, "EXCLUDES leads, NTC, PCM overhang, charger, boost and fuses.")
            + _text(20, 190, "No mounting holes, complete pack fit or charging approved.")
        )
        title = "Protected 1S candidate body / nominal tray outline"
    else:
        width, height = dims
        x, y = (A4_WIDTH_MM-width)/2, 108
        # The fixed A4 layout reserves 15 mm side margins and a legend
        # starting at y=153. An oversized nominal body would print clipped
        # or over its dimension label while still claiming true scale.
        if x < 15 or y + height > 145:
            raise ValueError("Nominal outline exceeds A4 printable layout")
        features = (_rect(x, y, width, height)
                    + _text(20, 153, f"Nominal body outline: {_num(width)} x {_num(height)} mm")
                    + _text(20, 161, "NO drilling centers, pad positions or lens centers qualified"))
        title = ("GY-530 carrier reference" if name == "ranger"
                 else "Challenge speaker body reference")
    return ('<svg xmlns="http://www.w3.org/2000/svg" '
            'width="210mm" height="297mm" viewBox="0 0 210 297">'
            + _text(15, 20, title, size=6)
            + _text(15, 29, "FRONT / TOP of paper  ^  (not a PCB polarity mark)")
            + _text(15, 37, "PROVISIONAL / UNPOWERED / NOT FOR DRILLING")
            + features
            + _text(20, 218, "Print at 100% or actual size. Disable fit-to-page scaling.")
            + _text(20, 225, "Check BOTH reference lengths with a ruler before use.")
            + _rect(20, 239, 100, 8)
            + _text(20, 236, "100 mm horizontal print scale")
            + _rect(173, 229, 8, 25)
            + _text(146, 262, "25 mm vertical")
            + _text(15, 280, "BACK / BOTTOM of paper. Never mirror a mounting pattern blindly.")
            + '</svg>\n')


def _expected(root: Path) -> tuple[dict, dict[str, bytes]]:
    dimensions = values(root)
    pages = {f"{name}_reference_A4.svg": svg(name, dims).encode("utf-8")
             for name, dims in dimensions.items()}
    manifest = {
        "page": "A4", "physical_units": "mm", "scale": 1.0,
        "provisional_only": True, "approved_drill_holes": 0,
        "actual_fit_verified": False,
        "source_sha256": {
            path: sha256((root / path).read_bytes()).hexdigest()
            for path in SOURCES.values()
        },
        "pages": {file: sha256(data).hexdigest() for file, data in pages.items()},
        "source_dimensions_mm": {name: list(dims) for name, dims in dimensions.items()},
    }
    return manifest, pages


def _reject_output_aliases(output: Path) -> None:
    """Keep SVG templates and their manifest inside the selected output."""
    # macOS may expose root-owned /var or /tmp aliases; allow only system
    # links beneath a nonwritable parent, never mutable project links.
    for ancestor in (output, *output.parents):
        if not ancestor.is_symlink():
            continue
        if (ancestor.lstat().st_uid == 0
                and not (ancestor.parent.stat().st_mode & 0o022)):
            continue
        raise ValueError(f"Symlinked paper template output path: {ancestor}")
    names = ["paper_manifest.json"] + [
        f"{kind}_reference_A4.svg" for kind in SOURCES
    ]
    for name in names:
        path = output / name
        if path.is_symlink():
            raise ValueError(f"Symlinked paper template output path: {path}")
    # A stale source-unpinned SVG alongside verified pages can be mistaken
    # for an authorized, true-scale cut or drill template. Never delete it:
    # make the operator inspect and remove the unexpected artifact first.
    if output.is_dir():
        declared = set(names)
        for entry in output.iterdir():
            if entry.suffix.lower() == ".svg" and entry.name not in declared:
                raise ValueError(f"Undeclared A4 paper template: {entry}")


def export(root: Path, output: Path) -> dict:
    manifest, pages = _expected(root)
    _reject_output_aliases(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, data in pages.items():
        (output / name).write_bytes(data)
    (output / "paper_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def verify(root: Path, output: Path) -> dict:
    _reject_output_aliases(output)
    expected, pages = _expected(root)
    actual = json.loads((output / "paper_manifest.json").read_text(encoding="utf-8"))
    if actual != expected:
        raise ValueError("Paper source, dimensions or manifest changed")
    for name, expected_bytes in pages.items():
        if (output / name).read_bytes() != expected_bytes:
            raise ValueError(f"Scaled or altered paper page: {name}")
        doc = ElementTree.fromstring(expected_bytes)
        if (doc.attrib.get("width"), doc.attrib.get("height"),
                doc.attrib.get("viewBox")) != ("210mm", "297mm", "0 0 210 297"):
            raise ValueError(f"Invalid A4 physical scale: {name}")
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    print(json.dumps((verify if args.verify else export)(args.repo, args.output),
                     sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
