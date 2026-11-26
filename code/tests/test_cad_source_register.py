"""CAD builder register must distinguish source files from fitted hardware."""

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CAD = ROOT / "docs/cad"
REGISTER = CAD / "README.md"

CURRENT_SOURCE_LINKS = (
    "FUSION_ONE_ROBOT_ASSEMBLY.md",
    "remixes/one_robot_adapter_kit_README.md",
    "remixes/one_robot_adapter_kit.scad",
    "remixes/dock/dock_passive_fit.scad",
    "remixes/remaining_fit_gauges.scad",
    "remixes/fusion_one_robot_scaffold.py",
)

# These are recorded upstream terms, not a blanket permission to redistribute
# a combined assembly. In particular, the stepper remix has an NC-SA ancestor.
ORIGINAL_SOURCES = {
    "eva-head": ("Ksirailway-Base", "CC-BY-SA-4.0", "thing:7319190"),
    "forklift": ("tristomietitoredeituit", "CC-BY-NC-SA-4.0", "thing:3027255"),
    "gripper": ("bluino", "CC-BY-4.0", "thing:4253681"),
    "smars": ("tristomietitoredeituit", "CC-BY-NC-SA-4.0", "thing:2662828"),
    "smars-stepper": ("unclejeff", "CC-BY-4.0", "thing:2778904"),
    "sparky-head": ("Sparky by Siddhartha Lahiri", "CC-BY-SA-4.0", "slahiri/sparky"),
    "tiny-engineer-head": ("Krzysztof Jamroz", "CERN-OHL-S-2.0", "jamro/tiny-engineer"),
}
CAD_SUFFIXES = {".stl", ".3mf", ".scad"}


def test_cad_builder_entrypoint_names_real_current_sources_and_holds_fit():
    register = REGISTER.read_text(encoding="utf-8")
    for path in CURRENT_SOURCE_LINKS:
        assert (CAD / path).is_file(), f"Missing advertised CAD source: {path}"
        assert f"]({path})" in register

    assert "Saved upstream models remain unmodified" in register
    assert "Locally\nauthored, provisional geometry now exists" in register
    assert "No geometry has been edited or sliced" not in register
    assert "not a dimensionally qualified" in register
    assert "no complete robot\nor powered dock has been assembled" in register
    assert "not**\napproved permanent installation quantities" in register
    assert "protected contact charging before release" in register


def _check_original_assets(directory, manifest):
    entries = manifest["files"] if "files" in manifest else [manifest]
    registered = {}
    for entry in entries:
        name = entry["file"]
        if Path(name).suffix.lower() not in CAD_SUFFIXES:
            continue
        assert name not in registered, f"Duplicate CAD registration: {name}"
        registered[name] = entry
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in CAD_SUFFIXES
    }
    assert actual == registered.keys(), f"CAD inventory mismatch: {directory}"
    for name, entry in registered.items():
        data = (directory / name).read_bytes()
        assert len(data) == entry["bytes"], f"CAD size mismatch: {name}"
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], f"CAD hash mismatch: {name}"


def _check_original_license(manifest, expected, attribution):
    author, license_id, source = expected
    assert manifest["author"] == author
    assert manifest["license"] == license_id
    assert source in manifest["source_url"]
    records = [record for record in _attribution_records(attribution) if source in record]
    assert any(
        author in record and _license_token(license_id) in _license_token(record)
        for record in records
    ), f"Missing attribution for {source}: {license_id}"
    assert not any(re.search(r"\bGPL", record, re.IGNORECASE) for record in records), (
        f"Conflicting GPL attribution for {source}"
    )


def _attribution_records(attribution):
    """Read one Markdown table row or bullet, never borrow a neighbor's terms."""
    bullet = []
    for line in attribution.splitlines():
        if bullet and (not line.strip() or not line.startswith("  ")):
            yield "\n".join(bullet)
            bullet = []
        if line.startswith("|"):
            yield line
        elif line.startswith("- ") or bullet:
            bullet.append(line)
    if bullet:
        yield "\n".join(bullet)


def _license_token(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _load_original_manifest(directory):
    path = directory / "source.json"
    assert path.is_file(), f"Missing CAD source manifest: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _check_stepper_ancestor(manifest, attribution):
    author, license_id, source = ORIGINAL_SOURCES["smars"]
    ancestor = manifest["ancestor"]
    assert ancestor["recorded_license"] == license_id
    assert ancestor["author"] == author
    assert source in ancestor["source_url"]
    stepper_source = ORIGINAL_SOURCES["smars-stepper"][2]
    assert any(
        stepper_source in record
        and "ncsa40" in _license_token(record)
        and "no commercial grant inferred" in record
        for record in _attribution_records(attribution)
    ), "Missing stepper noncommercial ancestor warning"


def test_original_cad_inventory_and_license_provenance():
    originals = CAD / "originals"
    attribution = (ROOT / "docs/ATTRIBUTION.md").read_text(encoding="utf-8")
    assert {p.name for p in originals.iterdir() if p.is_dir()} == ORIGINAL_SOURCES.keys()
    assert not any(
        p.is_file() and p.suffix.lower() in CAD_SUFFIXES for p in originals.iterdir()
    )
    for directory, expected in ORIGINAL_SOURCES.items():
        source = originals / directory
        manifest = _load_original_manifest(source)
        _check_original_license(manifest, expected, attribution)
        _check_original_assets(source, manifest)
        if directory == "smars-stepper":
            _check_stepper_ancestor(manifest, attribution)


@pytest.mark.parametrize("fault", ["unregistered", "missing", "duplicate", "changed", "size"])
def test_original_cad_inventory_rejects_drift(tmp_path, fault):
    data = b"cube(1);\n"
    asset = tmp_path / "model.scad"
    asset.write_bytes(data)
    entry = {"file": asset.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    entries = [entry]
    _check_original_assets(tmp_path, {"files": entries})
    if fault == "unregistered":
        (tmp_path / "extra.STL").write_bytes(data)
    elif fault == "missing":
        asset.unlink()
    elif fault == "duplicate":
        entries.append(entry)
    elif fault == "changed":
        asset.write_bytes(data.replace(b"1", b"2"))
    else:
        entry["bytes"] += 1
    with pytest.raises(AssertionError):
        _check_original_assets(tmp_path, {"files": entries})


def test_original_cad_license_rejects_relabeling():
    expected = ORIGINAL_SOURCES["smars"]
    author, license_id, source = expected
    manifest = {"author": author, "license": license_id, "source_url": source}
    attribution = f"| {source} | {author} | {license_id} |"
    _check_original_license(manifest, expected, attribution)
    with pytest.raises(AssertionError):
        _check_original_license(manifest, expected, attribution.replace(license_id, "MIT"))
    manifest["license"] = "MIT"
    with pytest.raises(AssertionError):
        _check_original_license(manifest, expected, attribution)


@pytest.mark.parametrize("style", ["table", "bullet"])
def test_original_cad_attribution_cannot_borrow_neighbor_license(style):
    expected = ORIGINAL_SOURCES["smars"]
    author, license_id, source = expected
    manifest = {"author": author, "license": license_id, "source_url": source}
    if style == "table":
        attribution = f"| {source} | {author} | MIT |\n| neighbor | {author} | {license_id} |"
    else:
        attribution = f"- {source}\n  {author}: MIT\n- neighbor\n  {author}: {license_id}"
    with pytest.raises(AssertionError, match="Missing attribution"):
        _check_original_license(manifest, expected, attribution)


@pytest.mark.parametrize("tag", ["GPLv3", "GPL-3.0-only", "GPL3"])
def test_original_cad_attribution_rejects_conflicting_gpl(tag):
    expected = ORIGINAL_SOURCES["smars"]
    author, license_id, source = expected
    manifest = {"author": author, "license": license_id, "source_url": source}
    attribution = f"| {source} | {author} | {license_id} |"
    _check_original_license(manifest, expected, attribution + f"\n- Unrelated reference: {tag}")
    with pytest.raises(AssertionError, match="Conflicting GPL attribution"):
        _check_original_license(manifest, expected, attribution + f" {tag}")
    manifest["license"] = tag
    with pytest.raises(AssertionError):
        _check_original_license(manifest, expected, attribution)


def test_original_cad_missing_source_manifest(tmp_path):
    path = tmp_path / "source.json"
    path.write_text('{"license": "CC-BY-4.0"}', encoding="utf-8")
    assert _load_original_manifest(tmp_path) == {"license": "CC-BY-4.0"}
    path.unlink()
    with pytest.raises(AssertionError, match="Missing CAD source manifest"):
        _load_original_manifest(tmp_path)


@pytest.mark.parametrize("fault", ["license", "author", "source_url", "warning", "neighbor", "nc"])
def test_stepper_ancestor_rejects_provenance_drift(fault):
    author, license_id, source = ORIGINAL_SOURCES["smars"]
    ancestor = {"author": author, "recorded_license": license_id, "source_url": source}
    manifest = {"ancestor": ancestor}
    attribution = "- thing:2778904; ancestor NC-SA4.0; no commercial grant inferred."
    _check_stepper_ancestor(manifest, attribution)
    if fault == "license":
        ancestor["recorded_license"] = "CC-BY-4.0"
    elif fault in {"author", "source_url"}:
        ancestor[fault] = "unrelated"
    elif fault == "warning":
        attribution = attribution.replace("no commercial grant inferred", "commercial use allowed")
    elif fault == "neighbor":
        attribution = attribution.replace("; no commercial", "\n- neighbor: no commercial")
    else:
        attribution = attribution.replace("NC-SA4.0", "BY4.0")
    with pytest.raises(AssertionError):
        _check_stepper_ancestor(manifest, attribution)
