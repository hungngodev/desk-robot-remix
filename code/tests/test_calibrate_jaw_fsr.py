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
