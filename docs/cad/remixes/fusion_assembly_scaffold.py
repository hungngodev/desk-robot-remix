"""Backwards compatible Fusion entrypoint for the single robot scaffold.

The builder guide historically named this script. Importing it must use the
same complete, source verified, provisional reference list as the canonical
fusion_one_robot_scaffold.py. Do not maintain two diverging import sequences.
"""
from pathlib import Path
import runpy

_IMPLEMENTATION = Path(__file__).with_name("fusion_one_robot_scaffold.py")


def _load():
    return runpy.run_path(str(_IMPLEMENTATION))


# Retain the old importable names for existing builder scripts while sharing
# a single canonical source of mesh selections.
SOURCE_MESHES = _load()["SOURCE_MESHES"]
ADAPTER_NAMES = _load()["ADAPTER_NAMES"]
FIT_REFERENCES = _load()["FIT_REFERENCES"]


def find_repository(script_path: Path) -> Path:
    return _load()["find_repo"](script_path)


def build_manifest(root: Path):
    return _load()["build_manifest"](root)


def run(context):
    return _load()["run"](context)
