"""Protect the shared motion kernel from the vision/orchestration import cycle."""

import ast
from pathlib import Path

import pytest

from desk_robot.scene_motion import change_fraction, scene_change_mask


def _imports_multimodal(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if node.module in {"multimodal", "desk_robot.multimodal"}:
                return True
            if node.module in {None, "desk_robot"} and any(
                alias.name == "multimodal" for alias in node.names
            ):
                return True
        elif isinstance(node, ast.Import) and any(
            alias.name == "desk_robot.multimodal" for alias in node.names
        ):
            return True
    return False


def test_vision_does_not_import_multimodal_even_lazily():
    root = Path(__file__).resolve().parents[1] / "laptop/src/desk_robot"
    for name in ("vision.py", "scene_motion.py"):
        assert not _imports_multimodal((root / name).read_text()), name


@pytest.mark.parametrize("source", [
    "def f():\n    from .multimodal import scene_change_mask",
    "from . import multimodal",
    "from desk_robot import multimodal",
    "import desk_robot.multimodal as mm",
])
def test_cycle_guard_detects_reverse_import(source):
    assert _imports_multimodal(source)


def test_motion_kernel_ignores_exposure_but_retains_signed_local_changes():
    baseline = bytes([80]) * (64 * 48)
    exposed = bytes([100]) * len(baseline)
    assert change_fraction(baseline, exposed) == 0
    altered = bytearray(exposed)
    altered[0], altered[1] = 140, 60
    mask = scene_change_mask(baseline, bytes(altered))
    assert mask[:2] == bytes([1, 2])
    assert mask[2:] == bytes(len(baseline) - 2)
    assert change_fraction(baseline, bytes(altered)) == 2 / len(baseline)
