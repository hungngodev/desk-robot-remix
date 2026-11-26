"""Fleet-wide optical identity and literal CAD dimension regression tests."""
import importlib.util
import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/generate_dock_tag.py"


@pytest.fixture
def generator():
    spec = importlib.util.spec_from_file_location("dock_tag_generator_boundaries", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("extra", [
    "\ntag_black_side_mm = 50 + 5;\n",
    "\n  tag_black_side_mm = 55;\n",
    " tag_black_side_mm = 55;\n",
])
def test_cad_override_cannot_hide_behind_literal(generator, tmp_path, extra):
    scad = tmp_path / "dock.scad"
    scad.write_text(generator.SCAD.read_text().rstrip() + extra, encoding="utf-8")
    with pytest.raises(ValueError, match="ambiguous"):
        generator.read_dock_geometry(scad)


@pytest.mark.parametrize("marker", [-1, 587, 12.0, "12", None, False])
def test_invalid_peer_marker_blocks_even_valid_dock(generator, tmp_path, marker):
    manifest = json.loads(generator.ASSIGNMENTS.read_text())
    manifest["docks"][4]["marker_id"] = marker
    path = tmp_path / "assignments.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "dock.svg"
    with pytest.raises(ValueError, match="invalid dock/beacon/marker"):
        generator.save_or_verify(output, 1, 12, assignments=path)
    assert not output.exists()


def test_room_station_is_not_sixth_dock(generator, tmp_path):
    manifest = json.loads(generator.ASSIGNMENTS.read_text())
    manifest["docks"].append({"dock_id": 6, "beacon_id": 6, "marker_id": 17})
    path = tmp_path / "assignments.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="schema or scope"):
        generator.read_marker_assignments(path)
    with pytest.raises(ValueError, match="Dock ID"):
        generator.build_svg(6, 17)


def test_all_five_generated_tags_decode_together(generator):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    if not hasattr(cv2, "aruco"):
        pytest.skip("OpenCV aruco is optional")
    mapping = generator.read_marker_assignments()
    canvas = np.full((740, 3700), 255, dtype=np.uint8)
    for dock_id, marker_id in mapping.items():
        svg = ElementTree.fromstring(generator.build_svg(dock_id, marker_id))
        assert svg.attrib["width"] == svg.attrib["height"] == "70mm"
        for rect in svg.findall("{*}rect")[1:]:
            attrs = rect.attrib
            x = (dock_id - 1) * 740 + 20 + round(float(attrs["x"]) * 10)
            y = 20 + round(float(attrs["y"]) * 10)
            w = round(float(attrs["width"]) * 10)
            h = round(float(attrs["height"]) * 10)
            canvas[y:y + h, x:x + w] = 0
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    corners, ids, _ = cv2.aruco.ArucoDetector(dictionary).detectMarkers(canvas)
    assert ids is not None
    assert len(corners) == len(mapping) == 5
    assert sorted(ids.ravel().tolist()) == sorted(mapping.values())
