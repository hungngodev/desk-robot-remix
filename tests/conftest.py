from pathlib import Path

import pytest
from desk_robot.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings():
    return load_settings(ROOT / "config/simulation.toml")


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
