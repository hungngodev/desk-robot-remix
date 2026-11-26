import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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


def _side_cli_args(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/calibrate_side_ranges.py"
    source = tmp_path / "side.jsonl"
    target = tmp_path / "candidate.json"
    rows = []
    for channel, side in enumerate(("left", "right", "rear")):
        for index in range(1, 41):
            mm = [800] * 3
            mm[channel] = 100 if index <= 20 else 500
            rows.append({
                "robot_id": "robot-01", "direction": side,
                "label": "near" if index <= 20 else "far", "sample_id": index,
                "side_ranges": {
                    "mm": mm, "age_ms": [35] * 3, "sample_ms": [index * 20] * 3,
                    "boot_id": 73, "present_mask": 7, "valid_mask": 7,
                    "motion_certified": False,
                },
            })
    source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return script, source, target, ["--robot", "robot-01", "--input", str(source)]


@pytest.mark.parametrize("bad,diagnostic", [
    (b'{"broken":', "line 121"),
    (b'{"x": 1, "x": 2}\n', "Duplicate"),
    (b'{"x": 1e999}\n', "Nonfinite"),
    (b'[]\n', "identity"),
    (b'\xff', "utf-8"),
    (None, "No such file"),
])
@pytest.mark.parametrize("existing", [False, True])
def test_side_cli_invalid_input_preserves_candidate(tmp_path, bad, diagnostic, existing):
    script, source, target, args = _side_cli_args(tmp_path)
    if existing:
        target.write_bytes(b'{"previous": true}\n')
    if bad is None:
        source.unlink()
    else:
        with source.open("ab") as stream:
            stream.write(bad)
    result = subprocess.run(
        [sys.executable, str(script), *args, "--output", str(target)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 2
    assert diagnostic in result.stderr
    assert "Traceback" not in result.stderr
    assert not result.stdout
    if existing:
        assert target.read_bytes() == b'{"previous": true}\n'
    else:
        assert not target.exists()
    assert not list(tmp_path.glob(".desk-robot-*"))


@pytest.mark.parametrize("operation", ["fsync", "replace"])
@pytest.mark.parametrize("failure,exit_code", [(OSError, 2), (KeyboardInterrupt, 130)])
@pytest.mark.parametrize("existing", [False, True])
def test_side_cli_interrupted_publication(tmp_path, monkeypatch, capsys, operation,
                                          failure, exit_code, existing):
    import runpy

    script, source, target, args = _side_cli_args(tmp_path)
    if existing:
        target.write_bytes(b'{"previous": true}\n')

    def fail(*args):
        raise failure("injected failure")

    monkeypatch.setattr(os, operation, fail)
    monkeypatch.setattr(sys, "argv", [str(script), *args, "--output", str(target)])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(script), run_name="__main__")
    assert exc.value.code == exit_code
    captured = capsys.readouterr()
    assert not captured.out
    assert "injected failure" in captured.err or "interrupted" in captured.err
    if existing:
        assert target.read_bytes() == b'{"previous": true}\n'
    else:
        assert not target.exists()
    assert source.is_file()
    assert not list(tmp_path.glob(".desk-robot-*"))


def test_side_cli_success_matches_stdout_and_preserves_input(tmp_path):
    script, source, target, args = _side_cli_args(tmp_path)
    original = source.read_bytes()
    target.write_bytes(b'{"previous": true}\n')
    stdout = subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True,
        timeout=10, check=True,
    )
    result = subprocess.run(
        [sys.executable, str(script), *args, "--output", str(target)],
        capture_output=True, text=True, timeout=10, check=True,
    )
    assert not result.stdout and not result.stderr
    assert target.read_text() == stdout.stdout
    candidate = json.loads(stdout.stdout)
    assert candidate["samples_total"] == 120
    assert candidate["physical_acceptance_pass"] is False
    assert candidate["no_motion_authority"] is True
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert source.read_bytes() == original
    assert not list(tmp_path.glob(".desk-robot-*"))

    alias = tmp_path / "alias.json"
    alias.hardlink_to(source)
    for output in (source, alias):
        rejected = subprocess.run(
            [sys.executable, str(script), *args, "--output", str(output)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        assert rejected.returncode == 2
        assert "must not overwrite" in rejected.stderr
        assert source.read_bytes() == original
        assert alias.read_bytes() == original
