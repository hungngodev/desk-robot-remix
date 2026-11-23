"""The provisional A4 paper manifest must preserve exact JSON scalar types."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docs/cad/remixes/print_2d_fit_templates.py"


def load():
    spec = importlib.util.spec_from_file_location("paper_fit_templates_strict", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("scale", True),
        ("provisional_only", 1),
        ("approved_drill_holes", False),
        ("actual_fit_verified", 0),
    ],
)
def test_a4_paper_manifest_rejects_equal_but_wrong_json_types(
    tmp_path, field, replacement,
):
    source = load()
    output = tmp_path / "paper"
    source.export(ROOT, output)
    assert source.verify(ROOT, output)["approved_drill_holes"] == 0
    path = output / "paper_manifest.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    previous = report[field]
    assert previous == replacement
    assert type(previous) is not type(replacement)
    report[field] = replacement
    path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    with pytest.raises(ValueError, match="Paper source, dimensions or manifest changed"):
        source.verify(ROOT, output)


def test_a4_paper_manifest_rejects_duplicate_keys(tmp_path):
    source = load()
    output = tmp_path / "paper"
    source.export(ROOT, output)
    path = output / "paper_manifest.json"
    contents = path.read_text(encoding="utf-8")
    assert '"scale": 1.0,' in contents
    path.write_text(contents.replace('"scale": 1.0,',
                                     '"scale": 1.0,\n  "scale": 1.0,', 1),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate A4 paper manifest key"):
        source.verify(ROOT, output)


def test_a4_paper_manifest_rejects_nonfinite_json_values(tmp_path):
    source = load()
    output = tmp_path / "paper"
    source.export(ROOT, output)
    path = output / "paper_manifest.json"
    contents = path.read_text(encoding="utf-8")
    assert '"scale": 1.0' in contents
    path.write_text(contents.replace('"scale": 1.0', '"scale": NaN', 1),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="Nonfinite A4 paper manifest number"):
        source.verify(ROOT, output)
