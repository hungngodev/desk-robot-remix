"""Private memory path admission preserves ordinary directories and rejects aliases."""

import pytest
from desk_robot.private_files import is_private_robot_id, validate_private_directory_ancestry


@pytest.mark.parametrize("robot_id", ["CON", "nul", "Lpt9", "COM1", "aux", "PRN"])
def test_reserved_database_stems(robot_id):
    assert not is_private_robot_id(robot_id)


@pytest.mark.parametrize("robot_id", ["robot_01", "pet-2", "COM10", "normal"])
def test_ordinary_database_stems(robot_id):
    assert is_private_robot_id(robot_id)


@pytest.mark.parametrize("robot_id", ["", "a/b", "a\\b", "a\x00b", ".", "..", None])
def test_nonportable_database_stems(robot_id):
    assert not is_private_robot_id(robot_id)


def test_regular_existing_directory_retained(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    existing = root / "existing.txt"
    existing.write_text("retain", encoding="utf-8")
    validate_private_directory_ancestry(root)
    validate_private_directory_ancestry(root / "new" / "nested")
    assert existing.read_text(encoding="utf-8") == "retain"
    assert not (root / "new").exists()


def test_ancestry_rejects_non_directory(tmp_path):
    leaf = tmp_path / "file"
    leaf.touch()
    with pytest.raises(ValueError, match="only directories"):
        validate_private_directory_ancestry(leaf / "memory")


def test_ancestry_rejects_null(tmp_path):
    with pytest.raises(ValueError, match="null bytes"):
        validate_private_directory_ancestry(tmp_path / "bad\x00name")


def test_existing_ordinary_parent_reference(tmp_path):
    child = tmp_path / "config"
    child.mkdir()
    validate_private_directory_ancestry(child / ".." / "memory")
