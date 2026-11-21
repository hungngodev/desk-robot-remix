"""Exact paper AprilTag 36h11 geometry and source provenance tests."""
import importlib.util
from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "code/scripts/generate_dock_tag.py"


def source():
    spec = importlib.util.spec_from_file_location("dock_tag_generator", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_bits(_marker):
    # Border must be dark; interior may contain both 0 and 1.
    return [
        [True if x in (0, 7) or y in (0, 7) else (x+y) % 2 == 0
         for x in range(8)]
        for y in range(8)
    ]


def svg_rectangles(document):
    root = ElementTree.fromstring(document)
    return root, list(root.findall("{*}rect"))


def test_dock_marker_svg_keeps_true_60mm_black_tag_and_5mm_quiet_margin(
    monkeypatch,
):
    module = source()
    monkeypatch.setattr(module, "marker_bits", synthetic_bits)
    svg = module.build_svg(1, 12)
    root, rectangles = svg_rectangles(svg)
    assert root.attrib["width"] == "70mm"
    assert root.attrib["height"] == "70mm"
    assert root.attrib["viewBox"] == "0 0 70 70"
    assert rectangles[0].attrib == {
        "x": "0", "y": "0", "width": "70",
        "height": "70", "fill": "#fff",
    }
    black = [rect.attrib for rect in rectangles[1:]]
    assert black
    assert all(5 <= float(r["x"]) <= 57.5 for r in black)
    assert all(5 <= float(r["y"]) <= 57.5 for r in black)
    assert all(r["width"] == r["height"] == "7.5"
               and r["fill"] == "#000" for r in black)
    dimensions = module.read_dock_geometry()
    assert dimensions["paper_mm"] == 70
    assert dimensions["pocket_mm"] == pytest.approx(71.2)
    assert "Print at 100 percent" in svg


def test_dock_marker_provenance_verifier_rejects_edits_and_stale_source(
    monkeypatch, tmp_path,
):
    module = source()
    monkeypatch.setattr(module, "marker_bits", synthetic_bits)
    marker = tmp_path / "dock_01.svg"
    module.save_or_verify(marker, 1, 12)
    module.save_or_verify(marker, 1, 12, verify=True)
    with pytest.raises(FileExistsError, match="overwrite"):
        module.save_or_verify(marker, 1, 12)
    with pytest.raises(ValueError, match="stale SCAD"):
        module.save_or_verify(marker, 1, 13, verify=True)
    marker.write_text(marker.read_text() + "<!-- modified -->")
    with pytest.raises(ValueError, match="stale SCAD"):
        module.save_or_verify(marker, 1, 12, verify=True)
    module.save_or_verify(marker, 1, 12, overwrite=True)
    module.save_or_verify(marker, 1, 12, verify=True)
    scad = tmp_path / "dock.scad"
    scad.write_bytes(module.SCAD.read_bytes() + b"\n// changed\n")
    with pytest.raises(ValueError, match="stale SCAD"):
        module.save_or_verify(marker, 1, 12, scad=scad, verify=True)


@pytest.mark.parametrize("dock_id,marker_id", [
    (0, 12), (6, 12), (True, 12), (1, -1), (1, 587), (1, True),
])
def test_invalid_dock_or_marker_id_cannot_produce_print(monkeypatch, dock_id, marker_id):
    module = source()
    monkeypatch.setattr(module, "marker_bits", lambda marker: (
        synthetic_bits(marker) if type(marker) is int and 0 <= marker <= 586
        else (_ for _ in ()).throw(ValueError("marker ID invalid"))
    ))
    with pytest.raises(ValueError):
        module.build_svg(dock_id, marker_id)


def test_source_dimensions_fail_closed_on_ambiguous_or_bad_scad(tmp_path):
    module = source()
    original = module.SCAD.read_text()
    duplicate = tmp_path / "duplicate.scad"
    duplicate.write_text(original + "\ntag_black_side_mm = 60;\n")
    with pytest.raises(ValueError, match="ambiguous"):
        module.read_dock_geometry(duplicate)
    undersized = tmp_path / "undersized.scad"
    undersized.write_text(original.replace(
        "tag_white_margin_each_mm = 5;",
        "tag_white_margin_each_mm = 1;",
    ))
    with pytest.raises(ValueError, match="violates"):
        module.read_dock_geometry(undersized)


def test_real_opencv_36h11_bits_match_vector_marker_exactly():
    cv2 = pytest.importorskip("cv2")
    if not hasattr(cv2, "aruco"):
        pytest.skip("OpenCV aruco support is an optional vision dependency")
    module = source()
    for marker_id in (0, 12, 13, 586):
        expected = cv2.aruco.generateImageMarker(
            cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11),
            marker_id, 8, borderBits=1,
        )
        actual = module.marker_bits(marker_id)
        assert actual == [[int(pixel) == 0 for pixel in row]
                          for row in expected]
        svg = module.build_svg(1, marker_id)
        _, rectangles = svg_rectangles(svg)
        for y in range(8):
            for x in range(8):
                location = (5 + 7.5*x, 5 + 7.5*y)
                painted_black = any(
                    float(r.attrib["x"]) == location[0]
                    and float(r.attrib["y"]) == location[1]
                    for r in rectangles[1:]
                )
                assert painted_black is actual[y][x]
