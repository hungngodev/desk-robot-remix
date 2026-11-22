"""Raw FSR qualification must follow the real WROOM nonzero uint32 sequence."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/calibrate_jaw_fsr.py"
spec = importlib.util.spec_from_file_location("jaw_fsr_trial", SCRIPT)
assert spec is not None and spec.loader is not None
jaw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jaw)


def measured_phases(sequences: list[int]) -> dict[str, list[tuple[int, int]]]:
    assert len(sequences) == 15
    return {
        "free": [(100, seq) for seq in sequences[:5]],
        "contact": [(600, seq) for seq in sequences[5:10]],
        "upper": [(1300, seq) for seq in sequences[10:]],
    }


def test_jaw_calibration_accepts_genuine_uint32_rollover_between_phases():
    sequences = list(range(0xfffffff9, 0x100000000)) + list(range(1, 9))
    assert len(sequences) == 15
    result = jaw.propose_force_limits(measured_phases(sequences))
    assert result["grip_force_sign"] == 1
    assert 0 < result["grip_force_delta_raw"] < result["grip_force_limit_raw"]
    assert result["newtons_measured"] is False
    assert result["physical_force_safety_qualified"] is False


@pytest.mark.parametrize("replacement", [0xffffffff, 0, 4])
def test_jaw_calibration_rejects_duplicate_zero_or_replayed_conversion(replacement):
    sequences = list(range(1, 16))
    sequences[8] = replacement
    with pytest.raises(ValueError, match="forward hardware conversions|Untrusted"):
        jaw.propose_force_limits(measured_phases(sequences))


async def test_jaw_capture_skips_duplicate_and_accepts_wrapped_hardware_sample():
    observations = iter([
        0xfffffffd, 0xfffffffe, 0xffffffff, 0xffffffff, 1, 2,
    ])
    calls = []

    def device(request):
        calls.append(str(request.url))
        seq = next(observations)
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "force": {
                "valid": True, "calibrated": False,
                "jaw_seq": seq, "adc": [0, 350],
            }
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(device)) as client:
        sampled = await jaw.capture(
            client, base_url="http://127.0.0.1:8008",
            robot="robot-01", token="t" * 24,
            count=5, interval=0.12,
        )
    assert [seq for _, seq in sampled] == [
        0xfffffffd, 0xfffffffe, 0xffffffff, 1, 2
    ]
    assert len(calls) == 6
    assert all("/v1/robots/robot-01/aux" in call for call in calls)


async def test_jaw_capture_rejects_cross_robot_auxiliary_telemetry():
    """A valid ADC conversion from another pet cannot calibrate this jaw."""
    def wrong_robot(_request):
        return httpx.Response(200, json={
            "robot_id": "robot-02",
            "force": {
                "valid": True, "calibrated": False,
                "jaw_seq": 1, "adc": [0, 350],
            },
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(wrong_robot)) as client:
        with pytest.raises(ValueError, match="robot identity mismatch"):
            await jaw.capture(
                client, base_url="http://127.0.0.1:8008",
                robot="robot-01", token="t" * 24,
                count=5, interval=0.12,
            )


async def test_jaw_physical_capture_rejects_zero_boot():
    def read(_request):
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "force": {"jaw_valid": True, "valid": True, "calibrated": False,
                      "jaw_seq": 1, "jaw_age_ms": 10, "boot_id": 0,
                      "adc": [0, 350]},
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(read)) as client:
        with pytest.raises(ValueError, match="WROOM boot and jaw age"):
            await jaw.capture(
                client, base_url="http://127.0.0.1:8008",
                robot="robot-01", token="t" * 24,
                count=5, interval=0.12, boot_state={},
            )


async def test_jaw_physical_capture_rejects_changed_boot_after_valid_phase():
    sample_number = 0
    boot = 4242
    def read(_request):
        nonlocal sample_number
        sample_number += 1
        return httpx.Response(200, json={
            "robot_id": "robot-01",
            "force": {"jaw_valid": True, "valid": True, "calibrated": False,
                      "jaw_seq": sample_number, "jaw_age_ms": 10,
                      "boot_id": boot, "adc": [0, 350]},
        })
    state = {}
    async with httpx.AsyncClient(transport=httpx.MockTransport(read)) as client:
        samples = await jaw.capture(
            client, base_url="http://127.0.0.1:8008",
            robot="robot-01", token="t" * 24,
            count=5, interval=0.12, boot_state=state,
        )
        assert len(samples) == 5
        assert state["boot_id"] == 4242
        boot = 4243
        with pytest.raises(ValueError, match="WROOM reboot"):
            await jaw.capture(
                client, base_url="http://127.0.0.1:8008",
                robot="robot-01", token="t" * 24,
                count=5, interval=0.12, boot_state=state,
            )

@pytest.mark.parametrize("payload,expected", [
    ('{"robot_id":"robot-01","robot_id":"robot-02"}', "robot_id"),
    ('{"measured":false,"measured":true}', "measured"),
    ('{"force":{"boot_id":17,"boot_id":18}}', "boot_id"),
    ('{"grip_force_limit_raw":50,"grip_force_limit_raw":10000}',
     "grip_force_limit_raw"),
    ('{"noise":NaN}', "Nonfinite"),
    ('{"noise":Infinity}', "Nonfinite"),
    ('{"noise":-Infinity}', "Nonfinite"),
])
def test_existing_jaw_source_rejects_ambiguous_json_before_capture(
    tmp_path, payload, expected,
):
    source = tmp_path / "untrusted.json"
    source.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match=expected):
        jaw.load_source_calibration(source)


def test_existing_jaw_source_keeps_valid_builder_fields(tmp_path):
    source = tmp_path / "valid.json"
    source.write_text(
        '{"measured":false,"robot_id":"robot-01",'
        '"head_device_id":"xiaozhi-01","grip_force_limit_raw":500,'
        '"extra":{"raw":[1,2,3]}}', encoding="utf-8",
    )
    assert jaw.load_source_calibration(source) == {
        "measured": False, "robot_id": "robot-01",
        "head_device_id": "xiaozhi-01", "grip_force_limit_raw": 500,
        "extra": {"raw": [1, 2, 3]},
    }


async def test_jaw_cli_rejects_conflicted_identity_before_hardware_sampling(
    tmp_path, monkeypatch,
):
    source = tmp_path / "wrong-identity.json"
    source.write_text(
        '{"robot_id":"robot-01","robot_id":"robot-02"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("DESK_ROBOT_OPERATOR_TOKEN", "t" * 24)
    monkeypatch.setattr(
        "sys.argv",
        ["calibrate_jaw_fsr.py", "--calibration", str(source)],
    )

    def no_prompt(*_args, **_kwargs):
        pytest.fail("Rejected provenance must not enter operator calibration")

    async def no_hardware_capture(*_args, **_kwargs):
        pytest.fail("Rejected provenance must not sample physical FSR")

    monkeypatch.setattr("builtins.input", no_prompt)
    monkeypatch.setattr(jaw, "capture", no_hardware_capture)
    with pytest.raises(ValueError, match="Repeated jaw calibration JSON field"):
        await jaw.main()
    assert not (tmp_path / "wrong-identity.jaw_candidate.json").exists()


def test_jaw_candidate_file_is_exclusive_private_and_stays_unqualified(tmp_path):
    import json
    import os
    import stat

    target = tmp_path / "physical.jaw_candidate.json"
    payload = {"measured": False, "grip_force_limit_raw": 1200}
    previous_umask = os.umask(0)
    try:
        jaw.write_jaw_candidate(target, payload)
    finally:
        os.umask(previous_umask)
    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        jaw.write_jaw_candidate(target, {"measured": False, "new": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_jaw_candidate_rejects_symlink_to_existing_provenance(tmp_path):
    actual = tmp_path / "approved.json"
    actual.write_text("SAFE", encoding="utf-8")
    candidate = tmp_path / "trial.jaw_candidate.json"
    candidate.symlink_to(actual)
    with pytest.raises(OSError):
        jaw.write_jaw_candidate(candidate, {"measured": False})
    assert actual.read_text(encoding="utf-8") == "SAFE"


def test_jaw_candidate_rejects_parent_alias_and_traversal(tmp_path):
    actual = tmp_path / "real"
    actual.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="alias"):
        jaw.write_jaw_candidate(
            alias / "trial.jaw_candidate.json", {"measured": False},
        )
    with pytest.raises(ValueError, match="path"):
        jaw.write_jaw_candidate(
            tmp_path / "missing" / ".." / "real" / "trial.jaw_candidate.json",
            {"measured": False},
        )
    assert not (actual / "trial.jaw_candidate.json").exists()


def test_jaw_candidate_refuses_public_writable_parent_or_approved_payload(tmp_path):
    import os

    parent = tmp_path / "public"
    parent.mkdir(mode=0o700)
    os.chmod(parent, 0o777)
    target = parent / "trial.jaw_candidate.json"
    with pytest.raises(ValueError, match="not writable"):
        jaw.write_jaw_candidate(target, {"measured": False})
    assert not target.exists()
    with pytest.raises(ValueError, match="unreviewed"):
        jaw.write_jaw_candidate(
            tmp_path / "candidate.json", {"measured": True},
        )


def test_jaw_candidate_refuses_invalid_nonfinite_json_before_file_creation(tmp_path):
    target = tmp_path / "trial.jaw_candidate.json"
    with pytest.raises(ValueError):
        jaw.write_jaw_candidate(target, {"measured": False, "raw": float("nan")})
    assert not target.exists()
