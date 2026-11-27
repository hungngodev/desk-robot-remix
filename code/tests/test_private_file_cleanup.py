"""Private text replacement preserves the primary failure during cleanup."""

import asyncio
import os
from pathlib import Path

import pytest
from desk_robot.private_files import replace_private_text


@pytest.mark.parametrize("failure_type", [OSError, asyncio.CancelledError])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_failed_replacement_preserves_primary_error(tmp_path, monkeypatch, failure_type, cleanup_fails):
    destination = tmp_path / "credentials.env"
    destination.write_text("old", encoding="utf-8")
    failure = failure_type("original failure")
    real_unlink = Path.unlink

    def fail_replace(source, target):
        assert Path(source).stat().st_mode & 0o777 == 0o600
        assert target == destination
        raise failure

    def unlink(path, *args, **kwargs):
        if cleanup_fails and path.name.startswith(".desk-robot-"):
            raise PermissionError("private cleanup path")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(failure_type) as caught:
        replace_private_text(destination, "new")
    assert caught.value is failure
    assert destination.read_text(encoding="utf-8") == "old"
    leftovers = list(tmp_path.glob(".desk-robot-*"))
    if cleanup_fails:
        assert caught.value.__notes__ == ["Private temporary file cleanup failed"]
        assert len(leftovers) == 1
        assert leftovers[0].stat().st_mode & 0o777 == 0o600
    else:
        assert not leftovers
        assert not getattr(caught.value, "__notes__", [])
