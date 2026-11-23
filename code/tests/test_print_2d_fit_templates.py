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
            "tag_paper_slack_each_mm=0.6;\n"
            "track_outer_width_mm=96;\nside_clearance_each_mm=2;\n"
            "base_length_mm=138;\nguide_run_mm=107;\n"
            "guide_wall_mm=5;\nwall_outside_margin_mm=8;\n"
            "entry_flare_each_mm=7;\n",
        "docs/cad/remixes/remaining_fit_gauges.scad":
            "candidate_pack_body_l_mm = 86;\npower_l = 86;\n"
            "power_w = 35;\nfit_xy = 0.4;\nwall = 2.4;\n",
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
        "dock_guide": [126, 138, 107, 5, 8, 7, 100],
        "power": [86, 35, 91.6, 40.6],
    }
    assert len(report["pages"]) == 5
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
    power = (output / "power_reference_A4.svg").read_text()
    assert 'width="86" height="35"' in power
    assert 'width="91.6" height="40.6"' in power
    assert "EXCLUDES leads, NTC, PCM overhang" in power
    assert "No mounting holes, complete pack fit or charging approved." in power
    rail = (output / "dock_guide_reference_A4.svg").read_text()
    assert 'width="126" height="138"' in rail
    assert '<polygon points="43,51 48,51 55,88 55,158 50,158 50,88"' in rail
    assert '<polygon points="167,51 162,51 155,88 155,158 160,158 160,88"' in rail
    assert "channel: 100 mm" in rail
    assert "ENTRY at TOP, BACKSTOP at BOTTOM" in rail
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


def test_larger_dock_pocket_must_not_overprint_a4_captions(tmp_path):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/dock/dock_passive_fit.scad"
    modified = scad.read_text(encoding="utf-8")
    modified = modified.replace("tag_black_side_mm = 60;",
                                "tag_black_side_mm = 75;")
    modified = modified.replace("tag_white_margin_each_mm=5;",
                                "tag_white_margin_each_mm=10;")
    scad.write_text(modified, encoding="utf-8")
    # Pocket 96.2 mm ends at y=172.2, crossing the first caption at 171.
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match="Dock pocket outline exceeds A4"):
        source.export(tmp_path, output)
    assert not output.exists()


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

def test_power_overlay_rejects_undersized_candidate_pack_layout(tmp_path):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/remaining_fit_gauges.scad"
    scad.write_text(scad.read_text().replace("power_l = 86;", "power_l = 68;"))
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match="shorter than candidate protected pack"):
        source.export(tmp_path, output)
    assert not output.exists()


def test_power_overlay_rejects_a4_label_collision(tmp_path):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/remaining_fit_gauges.scad"
    scad.write_text(scad.read_text().replace("power_w = 35;", "power_w = 90;"))
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match="Power outline exceeds A4 printable layout"):
        source.export(tmp_path, output)
    assert not output.exists()


@pytest.mark.parametrize("stale_name", [
    "obsolete_holes_reference_A4.svg",
    "old_layout.SVG",
])
def test_a4_export_verify_refuse_undeclared_stale_svg_before_writes(
    tmp_path, stale_name,
):
    source = load()
    setup_sources(tmp_path)
    output = tmp_path / "paper"
    output.mkdir()
    stale = output / stale_name
    sentinel = b"STALE UNVERIFIED DRILL ARTIFACT MUST NOT BE PUBLISHED"
    stale.write_bytes(sentinel)
    with pytest.raises(ValueError, match="Undeclared A4 paper template"):
        source.export(tmp_path, output)
    assert stale.read_bytes() == sentinel
    assert not (output / "paper_manifest.json").exists()
    assert not (output / "power_reference_A4.svg").exists()
    with pytest.raises(ValueError, match="Undeclared A4 paper template"):
        source.verify(tmp_path, output)


@pytest.mark.parametrize((old, replacement, message), [
    ("track_outer_width_mm=96;", "track_outer_width_mm=190;",
     "Dock guide outline exceeds A4 printable layout"),
    ("base_length_mm=138;", "base_length_mm=240;",
     "Dock guide outline exceeds A4 printable layout"),
    ("entry_flare_each_mm=7;", "entry_flare_each_mm=9;",
     "Invalid nominal dock guide rail dimensions"),
])
def test_a4_dock_guide_refuses_impossible_or_clipped_source_layout(
    tmp_path, old, replacement, message,
):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/dock/dock_passive_fit.scad"
    scad.write_text(scad.read_text().replace(old, replacement))
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match=message):
        source.export(tmp_path, output)
    assert not output.exists()
