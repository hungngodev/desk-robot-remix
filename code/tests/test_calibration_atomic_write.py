import os
import stat
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from desk_robot.calibration import Calibration
from desk_robot.private_files import replace_private_text


def _calibration(measured: bool) -> Calibration:
    return Calibration.model_validate({
        "measured": measured,
        "image_width": 200,
        "image_height": 200,
        "pixel_points": [[0, 0], [199, 0], [199, 199], [0, 199]],
        "ground_points_mm": [[0, 0], [199, 0], [199, 199], [0, 199]],
        "work_area_mm": [20, 90, 180, 180],
        "grip_ground_mm": [100, 100],
        "lifted_roi_px": [75, 40, 125, 80],
    })


@pytest.mark.parametrize("operation", ["fsync", "replace"])
@pytest.mark.parametrize("existing", [False, True])
def test_failed_publication_preserves_old_file(tmp_path, monkeypatch, operation, existing):
    path = tmp_path / "calibration.json"
    if existing:
        _calibration(True).save(path)
        old = path.read_bytes()

    def fail(*args):
        raise OSError("injected publication failure")

    monkeypatch.setattr(os, operation, fail)
    with pytest.raises(OSError, match="injected publication failure"):
        _calibration(False).save(path)
    if existing:
        assert path.read_bytes() == old
        assert Calibration.load(path).measured is True
        assert list(tmp_path.iterdir()) == [path]
    else:
        assert not list(tmp_path.iterdir())


def test_encoding_failure_cleans_temporary_file(tmp_path):
    path = tmp_path / "private.txt"
    path.write_text("old", encoding="utf-8")
    with pytest.raises(UnicodeEncodeError):
        replace_private_text(path, "\ud800")
    assert path.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [path]


def test_sync_and_private_mode_precede_publication(tmp_path, monkeypatch):
    path = tmp_path / "calibration.json"
    old = _calibration(True)
    new = _calibration(False)
    old.save(path)
    path.chmod(0o644)
    sync = os.fsync
    replace = os.replace
    calls = []

    def inspect_sync(fd):
        assert stat.S_IMODE(os.fstat(fd).st_mode) == 0o600
        assert Calibration.load(path) == old
        calls.append("sync")
        sync(fd)

    def inspect_replace(source, destination):
        assert calls == ["sync"]
        assert source.parent == path.parent
        assert destination == path
        assert Calibration.load(source) == new
        assert Calibration.load(path) == old
        calls.append("replace")
        replace(source, destination)

    monkeypatch.setattr(os, "fsync", inspect_sync)
    monkeypatch.setattr(os, "replace", inspect_replace)
    new.save(path)
    assert calls == ["sync", "replace"]
    assert Calibration.load(path) == new
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]


def test_concurrent_writers_stage_distinct_complete_files(tmp_path, monkeypatch):
    path = tmp_path / "calibration.json"
    first, second = _calibration(True), _calibration(False)
    first.save(path)
    barrier = Barrier(2, timeout=5)
    replace = os.replace

    def concurrent_replace(source, destination):
        assert source.parent == path.parent
        assert Calibration.load(source) in (first, second)
        barrier.wait()
        assert len(list(tmp_path.glob(".desk-robot-*"))) == 2
        barrier.wait()
        replace(source, destination)

    monkeypatch.setattr(os, "replace", concurrent_replace)
    with ThreadPoolExecutor(max_workers=2) as executor:
        writes = [executor.submit(model.save, path) for model in (first, second)]
        for write in writes:
            write.result(timeout=10)
    assert Calibration.load(path) in (first, second)
    assert list(tmp_path.iterdir()) == [path]
