"""Real A4 page scale and failure on changed source, never fictitious holes."""
import importlib.util
from pathlib import Path
from xml.etree import ElementTree

import pytest

SCRIPT = (Path(__file__).resolve().parents[2] /
          "docs/cad/remixes/print_2d_fit_templates.py")


def load():
    spec = importlib.util.spec_from_file_location("paper_fit_templates", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def setup_sources(tmp_path):
    data = {
        "docs/cad/remixes/vl53l0x_gy530_fit_gauge.scad":
            "board_x = 10.5;\nboard_y = 13.3;\n",
        "docs/cad/remixes/speaker_rect_fit_gauge.scad":
            "speaker_l=20;\nspeaker_w=16;\n",
        "docs/cad/remixes/dock/dock_passive_fit.scad":
            "tag_black_side_mm = 60;\ntag_white_margin_each_mm=5;\n"
            "tag_paper_slack_each_mm=0.6;\n",
    }
    for name, contents in data.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")


@pytest.mark.parametrize("alias", ("output", "ancestor", "manifest", "page"))
def test_a4_export_and_verify_reject_symlink_aliases_before_writes(
    tmp_path, alias,
):
    source = load()
    setup_sources(tmp_path)
    # A fixture may run as root: make the parent explicitly mutable so an
    # accidental root-owned test symlink is not a trusted system /var alias.
    tmp_path.chmod(0o777)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "private.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    output = tmp_path / "paper"
    if alias == "output":
        output.symlink_to(outside, target_is_directory=True)
    elif alias == "ancestor":
        (outside / "nested").mkdir()
        pivot = tmp_path / "pivot"
        pivot.symlink_to(outside, target_is_directory=True)
        output = pivot / "nested"
    else:
        output.mkdir()
        target_name = ("paper_manifest.json" if alias == "manifest"
                       else "ranger_reference_A4.svg")
        (output / target_name).symlink_to(sentinel)

    with pytest.raises(ValueError, match="Symlinked paper template output"):
        source.export(tmp_path, output)
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    assert not (outside / "speaker_reference_A4.svg").exists()
    with pytest.raises(ValueError, match="Symlinked paper template output"):
        source.verify(tmp_path, output)


def test_a4_real_scale_and_source_dimensions(tmp_path):
    source = load()
    setup_sources(tmp_path)
    output = tmp_path / "paper"
    report = source.export(tmp_path, output)
    assert report["source_dimensions_mm"] == {
        "ranger": [10.5, 13.3], "speaker": [20, 16],
        "dock": [60, 70, 71.2],
    }
    assert len(report["pages"]) == 3
    assert report["approved_drill_holes"] == 0
    assert report["actual_fit_verified"] is False
    for filename in report["pages"]:
        data = (output / filename).read_text()
        root = ElementTree.fromstring(data)
        assert root.attrib["width"] == "210mm"
        assert root.attrib["height"] == "297mm"
        assert root.attrib["viewBox"] == "0 0 210 297"
        assert 'width="100" height="8"' in data
        assert 'width="8" height="25"' in data
        assert "FRONT / TOP" in data and "BACK / BOTTOM" in data
        assert "NOT FOR DRILLING" in data
    assert 'width="71.2" height="71.2"' in (
        output / "dock_reference_A4.svg").read_text()
    assert source.verify(tmp_path, output) == report


def test_changed_source_and_tampered_svg_refuse_verification(tmp_path):
    source = load()
    setup_sources(tmp_path)
    output = tmp_path / "paper"
    source.export(tmp_path, output)
    page = output / "speaker_reference_A4.svg"
    page.write_bytes(page.read_bytes().replace(b'width="20"', b'width="21"'))
    with pytest.raises(ValueError, match="altered paper page"):
        source.verify(tmp_path, output)
    source.export(tmp_path, output)
    scad = tmp_path / "docs/cad/remixes/speaker_rect_fit_gauge.scad"
    scad.write_text(scad.read_text().replace("speaker_l=20", "speaker_l=21"))
    with pytest.raises(ValueError, match="source, dimensions or manifest changed"):
        source.verify(tmp_path, output)


def test_missing_or_ambiguous_measurement_fails_closed(tmp_path):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/dock/dock_passive_fit.scad"
    scad.write_text(scad.read_text().replace("tag_black_side_mm = 60;", ""))
    with pytest.raises(ValueError, match="Missing or ambiguous"):
        source.export(tmp_path, tmp_path / "paper")
    assert not (tmp_path / "paper").exists()


@pytest.mark.parametrize(("filename", "before", "after"), [
    ("docs/cad/remixes/vl53l0x_gy530_fit_gauge.scad",
     "board_x = 10.5;", "board_x = 250;"),
    ("docs/cad/remixes/vl53l0x_gy530_fit_gauge.scad",
     "board_x = 10.5;", "board_x = 200;"),
    ("docs/cad/remixes/speaker_rect_fit_gauge.scad",
     "speaker_w=16;", "speaker_w=90;"),
])
def test_a4_nominal_outline_cannot_clip_or_overlap_legend(
    tmp_path, filename, before, after,
):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / filename
    scad.write_text(scad.read_text().replace(before, after), encoding="utf-8")
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match="exceeds A4 printable layout"):
        source.export(tmp_path, output)
    assert not output.exists()
