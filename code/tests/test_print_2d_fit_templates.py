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
            "base_length_mm=138;\nguide_run_mm=107;\nbase_thickness_mm=3;\n"
            "backstop_thickness_mm=5;\nentry_coupon_length_mm=48;\n"
            "guide_wall_mm=5;\nwall_outside_margin_mm=8;\n"
            "entry_flare_each_mm=7;\nguide_height_mm=12;\n"
            "backstop_brace_depth_mm=8;\nbackstop_brace_height_mm=10;\n"
            "backstop_height_mm=90;\n",
        "docs/cad/remixes/remaining_fit_gauges.scad":
            "candidate_pack_body_l_mm = 86;\npower_l = 86;\n"
            "power_w = 35;\npower_h = 14;\nfit_xy = 0.4;\nwall = 2.4;\n"
            "m3_clearance = 3.4;\n"
            "tray_tab_l_mm = 8;\ntray_tab_w_mm = 9;\ntray_tab_offset_mm = 5;\n",
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
        "power": [86, 35, 91.6, 40.6, 8, 9, 5],
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
    assert '<rect x="51.2" y="93" width="8" height="9"' in power
    assert '<rect x="150.8" y="114.6" width="8" height="9"' in power
    assert "Overall span including tabs: 107.6 x 40.6 mm" in power
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


@pytest.mark.parametrize("old, replacement, message", [
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


@pytest.mark.parametrize("track_width", [60, 67.2])
def test_a4_tag_pocket_must_fit_strictly_inside_dock_rail_channel(
    tmp_path, track_width,
):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/dock/dock_passive_fit.scad"
    scad.write_text(
        scad.read_text(encoding="utf-8").replace(
            "track_outer_width_mm=96;", f"track_outer_width_mm={track_width};"
        ),
        encoding="utf-8",
    )
    # The source pocket is 71.2 mm. These channels are 64 and 71.2 mm,
    # both rejected by dock_passive_fit.scad's strict channel assertion.
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match="Dock tag pocket exceeds nominal rail channel"):
        source.export(tmp_path, output)
    assert not output.exists()


@pytest.mark.parametrize(("before", "after"), [
    ("base_length_mm=138;", "base_length_mm=110;"),
    ("base_length_mm=138;", "base_length_mm=112;"),
    ("guide_run_mm=107;", "guide_run_mm=45;"),
    ("entry_coupon_length_mm=48;", "entry_coupon_length_mm=107;"),
])
def test_a4_dock_rejects_impossible_backstop_or_entry_coupon(
    tmp_path, before, after,
):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/dock/dock_passive_fit.scad"
    scad.write_text(
        scad.read_text(encoding="utf-8").replace(before, after),
        encoding="utf-8",
    )
    output = tmp_path / "paper"
    with pytest.raises(
        ValueError, match="Invalid dock backstop or entry coupon dimensions"
    ):
        source.export(tmp_path, output)
    assert not output.exists()

@pytest.mark.parametrize(("old", "new", "message"), [
    ("tray_tab_l_mm = 8;", "tray_tab_l_mm = 60;",
     "Power outline exceeds A4 printable layout"),
    ("tray_tab_offset_mm = 5;", "tray_tab_offset_mm = 40;",
     "Power tab exceeds tray body width"),
])
def test_a4_power_tabs_cannot_clip_or_leave_tray_body(tmp_path, old, new, message):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/remaining_fit_gauges.scad"
    scad.write_text(scad.read_text().replace(old, new))
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match=message):
        source.export(tmp_path, output)
    assert not output.exists()


@pytest.mark.parametrize(("old", "new"), [
    ("tray_tab_l_mm = 8;", "tray_tab_l_mm = 3.4;"),
    ("tray_tab_l_mm = 8;", "tray_tab_l_mm = 3;"),
    ("tray_tab_w_mm = 9;", "tray_tab_w_mm = 3.4;"),
    ("tray_tab_w_mm = 9;", "tray_tab_w_mm = 3;"),
    ("m3_clearance = 3.4;", "m3_clearance = 8;"),
])
def test_a4_power_tabs_must_exceed_mounting_bore(tmp_path, old, new):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/remaining_fit_gauges.scad"
    scad.write_text(scad.read_text().replace(old, new), encoding="utf-8")
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match="Power tab must exceed mounting bore"):
        source.export(tmp_path, output)
    assert not output.exists()


def test_a4_power_tabs_strictly_above_bore_remain_provisional(tmp_path):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/remaining_fit_gauges.scad"
    scad.write_text(
        scad.read_text().replace("tray_tab_l_mm = 8;", "tray_tab_l_mm = 3.5;")
        .replace("tray_tab_w_mm = 9;", "tray_tab_w_mm = 3.5;"),
        encoding="utf-8",
    )
    manifest = source.export(tmp_path, tmp_path / "paper")
    assert manifest["source_dimensions_mm"]["power"][4:6] == [3.5, 3.5]
    assert manifest["approved_drill_holes"] == 0
    assert manifest["actual_fit_verified"] is False


@pytest.mark.parametrize(("old", "new"), [
    ("candidate_pack_body_l_mm = 86;\npower_l = 86;",
     "candidate_pack_body_l_mm = 20;\npower_l = 25;"),
    ("power_l = 86;", "power_l = 150;"),
    ("power_w = 35;", "power_w = 12;"),
    ("power_w = 35;", "power_w = 100;"),
    ("power_h = 14;", "power_h = 4;"),
    ("power_h = 14;", "power_h = 60;"),
])
def test_a4_power_tray_requires_renderable_envelope(tmp_path, old, new):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/remaining_fit_gauges.scad"
    scad.write_text(scad.read_text().replace(old, new), encoding="utf-8")
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match="Power tray dimensions exceed OpenSCAD limits"):
        source.export(tmp_path, output)
    assert not output.exists()


def test_a4_power_tray_rejects_missing_height(tmp_path):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/remaining_fit_gauges.scad"
    scad.write_text(scad.read_text().replace("power_h = 14;", ""), encoding="utf-8")
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match="Missing or ambiguous source dimension: power_h"):
        source.export(tmp_path, output)
    assert not output.exists()


def test_a4_power_tray_inside_envelope_remains_provisional(tmp_path):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/remaining_fit_gauges.scad"
    scad.write_text(
        scad.read_text().replace("power_w = 35;", "power_w = 12.1;")
        .replace("power_h = 14;", "power_h = 4.1;"),
        encoding="utf-8",
    )
    manifest = source.export(tmp_path, tmp_path / "paper")
    assert manifest["source_dimensions_mm"]["power"][1] == 12.1
    assert manifest["provisional_only"] is True
    assert manifest["actual_fit_verified"] is False


@pytest.mark.parametrize(("before", "after", "message"), [
    ("backstop_brace_depth_mm=8;", "backstop_brace_depth_mm=30;",
     "Invalid dock brace or guide geometry"),
    ("backstop_brace_depth_mm=8;", "backstop_brace_depth_mm=26;",
     "Invalid dock brace or guide geometry"),
    ("backstop_brace_height_mm=10;", "backstop_brace_height_mm=100;",
     "Invalid dock brace or guide geometry"),
    ("guide_height_mm=12;", "guide_height_mm=0;",
     "Out-of-range source dimension: guide_height_mm"),
    ("guide_height_mm=12;", "",
     "Missing or ambiguous source dimension: guide_height_mm"),
])
def test_a4_dock_requires_printable_brace_and_guide_height(
    tmp_path, before, after, message,
):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/dock/dock_passive_fit.scad"
    original = scad.read_text(encoding="utf-8")
    assert original.count(before) == 1
    scad.write_text(original.replace(before, after), encoding="utf-8")
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match=message):
        source.export(tmp_path, output)
    assert not output.exists()

@pytest.mark.parametrize(("old", "new"), [
    ("guide_height_mm=12;", "guide_height_mm=0.5;"),
    ("guide_wall_mm=5;", "guide_wall_mm=0.5;"),
    ("base_thickness_mm=3;", "base_thickness_mm=0.5;"),
])
def test_a4_dock_rejects_thin_base_or_guides(tmp_path, old, new):
    source = load()
    setup_sources(tmp_path)
    scad = tmp_path / "docs/cad/remixes/dock/dock_passive_fit.scad"
    original = scad.read_text(encoding="utf-8")
    assert old in original
    scad.write_text(original.replace(old, new), encoding="utf-8")
    output = tmp_path / "paper"
    with pytest.raises(ValueError, match="Dock base or guide below printable minimum"):
        source.export(tmp_path, output)
    assert not output.exists()
