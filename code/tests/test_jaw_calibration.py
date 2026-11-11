"""Grasp calibration arithmetic never replaces physical servo/force trials."""
import runpy
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
tool = runpy.run_path(str(ROOT / "scripts/calibrate_jaw_fsr.py"))
propose = tool["propose_force_limits"]
capture = tool["capture"]


def measured_samples():
    return {
        "free": [(100 + (i % 3), i + 1) for i in range(8)],
        "contact": [(700 + (i % 3), i + 9) for i in range(8)],
        "upper": [(2100 + (i % 3), i + 17) for i in range(8)],
    }


def test_recommends_signed_raw_limits_without_marking_physical_success():
    result = propose(measured_samples())
    assert result["grip_force_sign"] == 1
    assert 300 <= result["grip_force_delta_raw"] < 600
    assert result["grip_force_limit_raw"] > result["grip_force_delta_raw"]
    assert not result["newtons_measured"]
    assert not result["physical_force_safety_qualified"]
    assert result["manual_review_required"]


def test_inverted_adc_polarity_supported():
    samples = measured_samples()
    for rows in samples.values():
        for i, row in enumerate(rows):
            rows[i] = (-row[0], row[1])
    assert propose(samples)["grip_force_sign"] == -1


def test_flat_contact_and_duplicate_or_reordered_hardware_frames_rejected():
    samples = measured_samples()
    samples["contact"] = [(100, i + 9) for i in range(8)]
    with pytest.raises(ValueError):
        propose(samples)
    samples = measured_samples()
    samples["contact"][1] = samples["contact"][0]
    with pytest.raises(ValueError, match="strictly increasing"):
        propose(samples)
    samples = measured_samples()
    samples["upper"] = [(730, i + 17) for i in range(8)]
    with pytest.raises(ValueError):
        propose(samples)


async def test_capture_requires_independent_jaw_seq_and_reuses_existing_aux():
    next_seq = 0
    def respond(request):
        nonlocal next_seq
        assert request.url.path == "/v1/robots/robot-01/aux"
        assert request.headers["Authorization"] == "Bearer " + "s" * 32
        next_seq += 1
        return httpx.Response(200, json={
            "force": {"valid": True, "calibrated": False,
                      "adc": [0, 100], "jaw_seq": next_seq},
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        rows = await capture(client, base_url="http://127.0.0.1:8008",
                             robot="robot-01", token="s" * 32,
                             count=5, interval=0.12)
    assert rows == [(100, seq) for seq in range(1, 6)]
