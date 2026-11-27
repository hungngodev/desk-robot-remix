import os
from pathlib import Path

import pytest
from desk_robot.config import Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]


def _isolated_settings(filename: str, tmp_path: Path) -> Settings:
    # A fresh model alone does not isolate the SQLite and trial file paths.
    return load_settings(
        ROOT / "config" / filename,
        overrides={
            "memory_dir": tmp_path / "memory",
            "trials_file": tmp_path / "physical-trials.csv",
        },
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return _isolated_settings("simulation.toml", tmp_path)


@pytest.fixture
def fleet(tmp_path: Path) -> Settings:
    return _isolated_settings("fleet.simulation.toml", tmp_path)


@pytest.fixture(autouse=True)
def restore_robot_environment():
    """Restore project environment even when a test bypasses monkeypatch."""
    original = {key: value for key, value in os.environ.items() if key.startswith("DESK_ROBOT_")}
    try:
        yield
    finally:
        for key in tuple(os.environ):
            if key.startswith("DESK_ROBOT_") and key not in original:
                del os.environ[key]
        for key, value in original.items():
            if os.environ.get(key) != value:
                os.environ[key] = value


@pytest.fixture
def tokens(monkeypatch):
    values = {
        "DESK_ROBOT_API_TOKEN": "a" * 40,
        "DESK_ROBOT_TOOL_TOKEN": "b" * 40,
        "DESK_ROBOT_HEAD_01_TOKEN": "c" * 40,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values
