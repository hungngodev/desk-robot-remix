from pathlib import Path

import pytest
from desk_robot.config import Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # A fresh model alone does not isolate the SQLite and trial file paths.
    return load_settings(
        ROOT / "config/simulation.toml",
        overrides={
            "memory_dir": tmp_path / "memory",
            "trials_file": tmp_path / "physical-trials.jsonl",
        },
    )


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
