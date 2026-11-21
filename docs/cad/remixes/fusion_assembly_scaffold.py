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


def build_manifest(root: Path):
    return _load()["build_manifest"](root)


def run(context):
    return _load()["run"](context)
