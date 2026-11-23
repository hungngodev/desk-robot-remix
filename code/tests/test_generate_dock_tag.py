"""Exact paper AprilTag 36h11 geometry and source provenance tests."""
import importlib.util
import json
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


@pytest.mark.parametrize("alias", ("parent", "ancestor", "leaf"))
def test_dock_tag_never_follows_mutable_output_symlinks(
    monkeypatch, tmp_path, alias,
):
    module = source()
    monkeypatch.setattr(module, "marker_bits", synthetic_bits)
    # Keep this a mutable alias even when the test runner uses root.
    tmp_path.chmod(0o777)
    outside = tmp_path / "unrelated"
    outside.mkdir()
    sentinel = outside / "private.svg"
    sentinel.write_text("unrelated evidence", encoding="utf-8")
    output = tmp_path / "dock_01.svg"
    if alias == "parent":
        pivot = tmp_path / "alias"
        pivot.symlink_to(outside, target_is_directory=True)
        output = pivot / "dock_01.svg"
    elif alias == "ancestor":
        (outside / "nested").mkdir()
        pivot = tmp_path / "alias"
        pivot.symlink_to(outside, target_is_directory=True)
        output = pivot / "nested/dock_01.svg"
    else:
        output.symlink_to(sentinel)

    with pytest.raises(ValueError, match="Symlinked dock tag output path"):
        module.save_or_verify(output, 1, 12, overwrite=True)
    with pytest.raises(ValueError, match="Symlinked dock tag output path"):
        module.save_or_verify(output, 1, 12, verify=True)
    assert sentinel.read_text(encoding="utf-8") == "unrelated evidence"
    assert not (outside / "dock_01.svg").exists()
    assert not (outside / "nested/dock_01.svg").exists()


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
    with pytest.raises(ValueError, match="requires marker 12"):
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
    # The whole codebook may be tested, but only the assigned dock pair
    # can produce printable artifacts for that real physical dock.
    svg = module.build_svg(1, 12)
    actual = module.marker_bits(12)
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


def test_print_guide_commands_are_unescaped_markdown():
    guide = (
        ROOT / "docs/cad/remixes/dock/README.md"
    ).read_text(encoding="utf-8")
    section = guide.split("## Source checked, print scale accurate AprilTag paper")[1]
    assert chr(92) + chr(96) not in section
    assert chr(96) * 3 + "sh" in section
    assert "--dock-id 1 --marker-id 12" in section
    assert "--verify" in section
    assert "100 percent actual size" in section


def test_real_open_cv_detector_reads_generated_vector_cells():
    """A printed marker design must be legible to the REAL 36h11 decoder."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    if not hasattr(cv2, "aruco"):
        pytest.skip("OpenCV aruco is optional")
    module = source()
    svg = module.build_svg(1, 12)
    _root, rectangles = svg_rectangles(svg)
    # Ten pixels/mm is an image space integration check, not evidence
    # of printed scale, real camera optics or actual dock seating.
    raster = np.full((700, 700), 255, dtype=np.uint8)
    for rect in rectangles[1:]:
        attrs = rect.attrib
        x = round(float(attrs["x"]) * 10)
        y = round(float(attrs["y"]) * 10)
        w = round(float(attrs["width"]) * 10)
        h = round(float(attrs["height"]) * 10)
        raster[y:y + h, x:x + w] = 0
    dictionary = cv2.aruco.getPredefinedDictionary(
        cv2.aruco.DICT_APRILTAG_36h11
    )
    corners, ids, _rejected = cv2.aruco.ArucoDetector(
        dictionary
    ).detectMarkers(raster)
    assert ids is not None and ids.ravel().tolist() == [12]
    assert len(corners) == 1
    assert module.build_svg(2, 13) != svg



def test_five_dock_marker_assignments_are_one_to_one(monkeypatch):
    module = source()
    monkeypatch.setattr(module, "marker_bits", synthetic_bits)
    assert module.read_marker_assignments() == {
        1: 12, 2: 13, 3: 14, 4: 15, 5: 16,
    }
    for dock_id, marker_id in module.read_marker_assignments().items():
        svg = module.build_svg(dock_id, marker_id)
        assert f"marker {marker_id} for dock {dock_id}" in svg
        assert "assignment sha256" in svg


def test_second_dock_cannot_print_first_docks_marker(monkeypatch, tmp_path):
    module = source()
    monkeypatch.setattr(module, "marker_bits", synthetic_bits)
    first = tmp_path / "dock01.svg"
    second = tmp_path / "dock02.svg"
    module.save_or_verify(first, 1, 12)
    with pytest.raises(ValueError, match="Dock 2 requires marker 13"):
        module.save_or_verify(second, 2, 12)
    assert first.exists()
    assert not second.exists()
    module.save_or_verify(second, 2, 13)
    module.save_or_verify(second, 2, 13, verify=True)


@pytest.mark.parametrize("mutation,reason", [
    (lambda records: records[1].update(marker_id=12), "Duplicate optical marker"),
    (lambda records: records[1].update(dock_id=1, beacon_id=1), "Duplicate dock"),
    (lambda records: records[1].update(beacon_id=1), "invalid dock/beacon"),
    (lambda records: records[1].update(marker_id=True), "invalid dock/beacon"),
    (lambda records: records.pop(), "invalid schema"),
])
def test_malformed_or_reused_assignment_rejected_before_print(
    monkeypatch, tmp_path, mutation, reason,
):
    module = source()
    monkeypatch.setattr(module, "marker_bits", synthetic_bits)
    manifest = json.loads(module.ASSIGNMENTS.read_text())
    mutation(manifest["docks"])
    path = tmp_path / "assignments.json"
    path.write_text(json.dumps(manifest))
    output = tmp_path / "dock01.svg"
    with pytest.raises(ValueError, match=reason):
        module.save_or_verify(output, 1, 12, assignments=path)
    assert not output.exists()


def test_old_print_fails_verification_after_manifest_revision(
    monkeypatch, tmp_path,
):
    module = source()
    monkeypatch.setattr(module, "marker_bits", synthetic_bits)
    manifest = tmp_path / "assignments.json"
    manifest.write_bytes(module.ASSIGNMENTS.read_bytes())
    output = tmp_path / "dock01.svg"
    module.save_or_verify(output, 1, 12, assignments=manifest)
    # Even an unobservable change in a different dock's allocation
    # invalidates previous print provenance until the full set is reviewed.
    record = json.loads(manifest.read_text())
    record["docks"][4]["marker_id"] = 17
    manifest.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="stale SCAD revision"):
        module.save_or_verify(
            output, 1, 12, assignments=manifest, verify=True,
        )


def test_missing_assignment_manifest_fails_closed(monkeypatch, tmp_path):
    module = source()
    monkeypatch.setattr(module, "marker_bits", synthetic_bits)
    with pytest.raises(ValueError, match="manifest missing"):
        module.build_svg(1, 12, assignments=tmp_path / "missing.json")

@pytest.mark.parametrize("before,after", [
    ('"marker_id": 12', '"marker_id": 13, "marker_id": 12'),
    ('"marker_id": 12', '"marker_id": 12, "marker_id": 12'),
    ('"beacon_id": 1', '"beacon_id": 2, "beacon_id": 1'),
    ('"dock_id": 1', '"dock_id": 2, "dock_id": 1'),
    ('"schema_version": 1', '"schema_version": 2, "schema_version": 1'),
])
def test_duplicate_json_keys_cannot_override_dock_marker_assignment(
    monkeypatch, tmp_path, before, after,
):
    """An apparently valid last field cannot hide a conflicting earlier ID."""
    module = source()
    monkeypatch.setattr(module, "marker_bits", synthetic_bits)
    manifest = module.ASSIGNMENTS.read_text()
    assert manifest.count(before) == 1
    forged = manifest.replace(before, after)
    path = tmp_path / "duplicated_assignments.json"
    path.write_text(forged, encoding="utf-8")
    output = tmp_path / "dock01.svg"
    with pytest.raises(ValueError, match="Duplicate dock marker assignment JSON field"):
        module.read_marker_assignments(path)
    with pytest.raises(ValueError, match="Duplicate dock marker assignment JSON field"):
        module.save_or_verify(output, 1, 12, assignments=path)
    assert not output.exists()
