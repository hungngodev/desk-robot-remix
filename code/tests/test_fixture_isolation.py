"""Test storage and environment isolation without relying on collection order."""

import os
import sqlite3
from contextlib import closing

import pytest


@pytest.mark.parametrize("fixture_name", ["settings", "fleet"])
@pytest.mark.parametrize("iteration", [1, 2])
def test_simulation_fixture_storage_is_private(request, tmp_path, fixture_name, iteration):
    config = request.getfixturevalue(fixture_name)
    assert config.memory_dir == tmp_path / "memory"
    assert config.trials_file == tmp_path / "physical-trials.csv"
    assert not config.memory_dir.exists()
    assert not config.trials_file.exists()

    config.memory_dir.mkdir()
    with closing(sqlite3.connect(config.memory_dir / "isolation.sqlite3")) as db:
        db.execute("CREATE TABLE evidence (value INTEGER)")
        db.execute("INSERT INTO evidence VALUES (?)", (iteration,))
        db.commit()
    config.trials_file.write_text(f"{iteration}\n", encoding="utf-8")


@pytest.mark.parametrize("iteration", [1, 2])
def test_direct_robot_environment_change_does_not_leak(iteration):
    key = "DESK_ROBOT_DRX1011_TEST_ISOLATION_SENTINEL"
    previous = os.environ.get(key)
    assert previous is None
    os.environ[key] = str(iteration)
