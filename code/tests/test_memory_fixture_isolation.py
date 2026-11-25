from pathlib import Path

import pytest
from desk_robot.config import Settings


@pytest.mark.parametrize("attempt", [1, 2])
def test_settings_fixture_isolates_writable_state(
    settings: Settings, tmp_path: Path, attempt: int,
) -> None:
    # Assert containment before writing so a regression cannot touch repo data.
    assert settings.memory_dir == tmp_path / "memory"
    assert settings.trials_file == tmp_path / "physical-trials.jsonl"
    assert not settings.memory_dir.exists()
    assert not settings.trials_file.exists()
    settings.memory_dir.mkdir()
    (settings.memory_dir / "sentinel").write_text(str(attempt), encoding="utf-8")
    settings.trials_file.write_text(str(attempt), encoding="utf-8")
