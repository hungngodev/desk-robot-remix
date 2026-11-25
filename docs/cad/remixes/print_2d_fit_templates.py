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
    "dock_guide": "docs/cad/remixes/dock/dock_passive_fit.scad",
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
    pack_h = scad_mm(power, "power_h")
    if not (25 < pack_l < 150 and 12 < pack_w < 100 and 4 < pack_h < 60):
        raise ValueError("Power tray dimensions exceed OpenSCAD limits")
    fit_xy = scad_mm(power, "fit_xy")
    wall = scad_mm(power, "wall")
    base = scad_mm(power, "base")
    strap_slot = scad_mm(power, "tray_strap_slot_w")
    if fit_xy < 0.2 or wall < 2 or base < 2:
        raise ValueError("Power tray clearance, wall or floor below printable minimum")
    if pack_l < candidate_length:
        raise ValueError("Power tray shorter than candidate protected pack body")
    tray_l = pack_l + 2 * (fit_xy + wall)
    tray_w = pack_w + 2 * (fit_xy + wall)
    tab_l = scad_mm(power, "tray_tab_l_mm")
    tab_w = scad_mm(power, "tray_tab_w_mm")
    tab_offset = scad_mm(power, "tray_tab_offset_mm")
    mounting_bore = scad_mm(power, "m3_clearance")
    if mounting_bore < 3 or tab_l <= mounting_bore or tab_w <= mounting_bore:
        raise ValueError("Power tab must exceed mounting bore")
    if min(tab_l, tab_w) - mounting_bore < 4:
        raise ValueError("Power tab leaves insufficient M3 web")
    if strap_slot < 2 or tray_l / 3 - strap_slot < 2:
        raise ValueError("Power tray strap openings missing or intersecting")
    if tab_offset + tab_w > tray_w:
        raise ValueError("Power tab exceeds tray body width")
    dock = data["dock"]
    track_w = scad_mm(dock, "track_outer_width_mm")
    each_side = scad_mm(dock, "side_clearance_each_mm")
    base_l = scad_mm(dock, "base_length_mm")
    guide_run = scad_mm(dock, "guide_run_mm")
    backstop_thickness = scad_mm(dock, "backstop_thickness_mm")
    entry_coupon = scad_mm(dock, "entry_coupon_length_mm")
    # A zero-height rail has no printable guide even if its footprint fits.
    guide_height = scad_mm(dock, "guide_height_mm")
    base_thickness = scad_mm(dock, "base_thickness_mm")
    brace_depth = scad_mm(dock, "backstop_brace_depth_mm")
    brace_height = scad_mm(dock, "backstop_brace_height_mm")
    backstop_height = scad_mm(dock, "backstop_height_mm")
    rail_wall = scad_mm(dock, "guide_wall_mm")
    if min(guide_height, base_thickness, rail_wall) < 2:
        raise ValueError("Dock base or guide below printable minimum")
    rail_margin = scad_mm(dock, "wall_outside_margin_mm")
    entry_flare = scad_mm(dock, "entry_flare_each_mm")
    channel_w = track_w + 2 * each_side
    outer_w = channel_w + 2 * (rail_wall + rail_margin)
    # The physical OpenSCAD dock rejects any tag pocket that cannot fit
    # strictly inside its rail channel. A paper overlay must reject the
    # same impossible source instead of signing a misleading A4 template.
    if pocket >= channel_w:
        raise ValueError("Dock tag pocket exceeds nominal rail channel")
    if (guide_run <= 37 or guide_run >= base_l
            or entry_flare >= rail_wall + rail_margin
            or entry_flare > rail_margin
            or channel_w <= 0 or outer_w <= channel_w):
        raise ValueError("Invalid nominal dock guide rail dimensions")
    # Mirror the full dock and entry coupon OpenSCAD assertions. A paper
    # layout for non-renderable source geometry must fail before export.
    if (base_l <= guide_run + backstop_thickness
            or not 37 < entry_coupon < guide_run):
        raise ValueError("Invalid dock backstop or entry coupon dimensions")
    if (base_l - backstop_thickness - brace_depth <= guide_run
            or brace_height > backstop_height):
        raise ValueError("Invalid dock brace or guide geometry")
    return {
        "ranger": (scad_mm(data["ranger"], "board_x"),
                   scad_mm(data["ranger"], "board_y")),
        "speaker": (scad_mm(data["speaker"], "speaker_l"),
                    scad_mm(data["speaker"], "speaker_w")),
        "dock": (black, paper, pocket),
        "dock_guide": (outer_w, base_l, guide_run, rail_wall,
                       rail_margin, entry_flare, channel_w),
        "power": (pack_l, pack_w, tray_l, tray_w, tab_l, tab_w, tab_offset),
    }


def _num(value: float) -> str:
    return f"{value:g}"


def _rect(x: float, y: float, width: float, height: float,
          *, dash: bool = False) -> str:
    extra = ' stroke-dasharray="2 2"' if dash else ""
    return (f'<rect x="{_num(x)}" y="{_num(y)}" '
            f'width="{_num(width)}" height="{_num(height)}" '
            f'fill="none" stroke="black" stroke-width="0.3"{extra}/>')


def _polygon(points: tuple[tuple[float, float], ...]) -> str:
    coordinates = " ".join(f"{_num(x)},{_num(y)}" for x, y in points)
    return ('<polygon points="' + coordinates
            + '" fill="none" stroke="black" stroke-width="0.3"/>')


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
    elif name == "dock_guide":
        outer_w, base_l, run_l, wall_w, margin_w, flare_w, channel_w = dims
        x, y = (A4_WIDTH_MM - outer_w) / 2, 51
        if x < 15 or y + base_l > 196 or run_l < 37:
            raise ValueError("Dock guide outline exceeds A4 printable layout")
        # The two footprints use the EXACT 37 mm flared-entry polygons
        # from dock_passive_fit.scad, translated onto an A4 sheet.
        left_inner = wall_w + margin_w
        left = (
            (x + left_inner - wall_w - flare_w, y),
            (x + left_inner - flare_w, y),
            (x + left_inner, y + 37),
            (x + left_inner, y + run_l),
            (x + left_inner - wall_w, y + run_l),
            (x + left_inner - wall_w, y + 37),
        )
        right = tuple((2*x + outer_w - px, py) for px, py in left)
        features = (
            _rect(x, y, outer_w, base_l, dash=True)
            + _polygon(left) + _polygon(right)
            + _text(20, 203, f"Nominal base: {_num(outer_w)} x {_num(base_l)} mm; channel: {_num(channel_w)} mm")
            + _text(20, 210, "ENTRY at TOP, BACKSTOP at BOTTOM; no contact or drill marks.")
        )
        title = "Passive dock base and exact nominal flared rail footprints"
    elif name == "power":
        pack_l, pack_w, tray_l, tray_w, tab_l, tab_w, tab_offset = dims
        full_l = tray_l + 2 * tab_l
        x, y = (A4_WIDTH_MM - full_l) / 2 + tab_l, 88
        if x - tab_l < 15 or y + tray_w > 157:
            raise ValueError("Power outline exceeds A4 printable layout")
        # Show the exact nominal external tab silhouettes, not their holes.
        # This footprint must agree with battery_boost_tray() in OpenSCAD.
        features = (
            _rect(x, y, tray_l, tray_w, dash=True)
            + _rect(x-tab_l, y+tab_offset, tab_l, tab_w, dash=True)
            + _rect(x+tray_l, y+tray_w-tab_offset-tab_w, tab_l, tab_w, dash=True)
            + _rect(x + (tray_l - pack_l) / 2,
                    y + (tray_w - pack_w) / 2, pack_l, pack_w)
            + _text(20, 169, f"Pack body only: {_num(pack_l)} x {_num(pack_w)} mm")
            + _text(20, 176, f"Nominal tray body: {_num(tray_l)} x {_num(tray_w)} mm (dashed)")
            + _text(20, 183, f"Overall span including tabs: {_num(full_l)} x {_num(tray_w)} mm")
            + _text(20, 190, "EXCLUDES leads, NTC, PCM overhang, charger, boost and fuses.")
            + _text(20, 197, "No mounting holes, complete pack fit or charging approved.")
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


def _unique_manifest_keys(pairs: list[tuple[str, object]]) -> dict:
    """Duplicate keys can hide contradictory paper release evidence."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate A4 paper manifest key")
        result[key] = value
    return result


def _reject_nonfinite_number(token: str) -> None:
    raise ValueError("Nonfinite A4 paper manifest number: " + token)


def verify(root: Path, output: Path) -> dict:
    _reject_output_aliases(output)
    expected, pages = _expected(root)
    actual = json.loads(
        (output / "paper_manifest.json").read_text(encoding="utf-8"),
        object_pairs_hook=_unique_manifest_keys,
        parse_constant=_reject_nonfinite_number,
    )
    # Python's ordinary dict equality considers true == 1 and false == 0.
    # Preserve actual JSON scalar types for scale and safety flags instead.
    if (json.dumps(actual, sort_keys=True, allow_nan=False)
            != json.dumps(expected, sort_keys=True, allow_nan=False)):
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
