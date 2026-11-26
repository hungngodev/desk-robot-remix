"""DRX-1451: reject invalid CLI evidence before publishing a calibration trial."""
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("columns,images,error", [
    (3, 0, "measured board/dock geometry"),
    (9, 11, "at least 12 original checkerboard JPEGs"),
    (9, 12, "12+ independent real views"),
])
@pytest.mark.parametrize("existing", [False, True])
def test_camera_cli_rejects_invalid_counts_without_publication(
    monkeypatch, tmp_path, capsys, columns, images, error, existing,
):
    camera = load_script("calibrate_dock_camera")
    folder = tmp_path / "images"
    folder.mkdir()
    for index in range(images):
        Image.new("L", (320, 240), 128).save(folder / f"{index}.jpg")
    target = tmp_path / "candidate.json"
    if existing:
        target.write_bytes(b"prior candidate\n")
    monkeypatch.setattr(sys, "argv", [
        "calibrate_dock_camera.py", "--images", str(folder), "--output", str(target),
        "--robot-id", "robot-01", "--head-device-id", "head-01", "--columns", str(columns),
        "--rows", "6", "--square-mm", "10", "--tag-side-mm", "60", "--marker-id", "2",
        "--target-distance-mm", "200", "--camera-sensor-pid", "OV3660",
    ])
    with pytest.raises(SystemExit) as exc:
        camera.main()
    assert exc.value.code == 2
    assert error in capsys.readouterr().err
    if existing:
        assert target.read_bytes() == b"prior candidate\n"
    else:
        assert not target.exists()
    assert not list(tmp_path.glob(".dock-candidate-*.tmp"))


def ir_reading(sequence, *, valid=True):
    return {
        "robot_id": "robot-01", "left_valid": valid, "right_valid": False,
        "match": False, "left_seq": sequence, "right_seq": 0,
        "left_age_ms": 20 if valid else 0xffffffff, "right_age_ms": 0xffffffff,
        "code": 0, "left_code": 0xCB34ED12 if valid else 0, "right_code": 0,
        "motor_authorized": False, "charging_authorized": False, "physical_qualified": False,
    }


def configure_ir_cli(monkeypatch, module, target, sequences, *, valid=True):
    calls = []

    async def fast_sleep(_seconds):
        return None

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=ir_reading(sequences[len(calls) - 1], valid=valid))

    original_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return original_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    monkeypatch.setattr(module.asyncio, "sleep", fast_sleep)
    monkeypatch.setenv("DESK_ROBOT_OPERATOR_TOKEN", "T" * 32)
    monkeypatch.setattr(sys, "argv", [
        "calibrate_terminal_ir.py", "--robot", "robot-01", "--dock-id", "4",
        "--label", "left", "--out", str(target), "--samples", "20",
    ])
    return calls


@pytest.mark.parametrize("second,error", [(10, "Replayed"), (9, "Reboot or out-of-order")])
@pytest.mark.parametrize("existing", [False, True])
def test_ir_cli_aborts_invalid_capture_before_appending(
    monkeypatch, tmp_path, capsys, second, error, existing,
):
    module = load_script("calibrate_terminal_ir")
    target = tmp_path / "trial.jsonl"
    if existing:
        module.append_trial_rows(target, [{
            "schema_version": 1, "label": "left", "received_monotonic": 1.0,
            "ir": ir_reading(1),
        }])
        before = target.read_bytes()
    calls = configure_ir_cli(monkeypatch, module, target, [10, second] + list(range(11, 29)))
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert error in capsys.readouterr().err
    assert len(calls) == 2
    if existing:
        assert target.read_bytes() == before
    else:
        assert not target.exists()
    assert not list(tmp_path.glob(".terminal-ir-*.tmp"))


@pytest.mark.parametrize("start,error", [(100, "Replayed"), (99, "Reboot or out-of-order")])
def test_ir_cli_rejects_invalid_batch_boundary_under_writer_lock(
    monkeypatch, tmp_path, capsys, start, error,
):
    module = load_script("calibrate_terminal_ir")
    target = tmp_path / "trial.jsonl"
    module.append_trial_rows(target, [{
        "schema_version": 1, "label": "left", "received_monotonic": 0.0,
        "ir": ir_reading(100),
    }])
    before = target.read_bytes()
    calls = configure_ir_cli(monkeypatch, module, target, list(range(start, start + 20)))
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert error in capsys.readouterr().err
    assert len(calls) == 20
    assert target.read_bytes() == before
    assert not list(tmp_path.glob(".terminal-ir-*.tmp"))


@pytest.mark.parametrize("valid", [True, False])
def test_ir_cli_preserves_real_negative_observations_and_fresh_receipts(
    monkeypatch, tmp_path, capsys, valid,
):
    module = load_script("calibrate_terminal_ir")
    target = tmp_path / "trial.jsonl"
    sequences = list(range(1, 21)) if valid else [0] * 20
    configure_ir_cli(monkeypatch, module, target, sequences, valid=valid)
    module.main()
    rows = module.load_trial_rows(target)
    assert len(rows) == 20
    assert all(row["ir"]["left_valid"] is valid for row in rows)
    assert '"physical_acceptance_pass": false' in capsys.readouterr().out
