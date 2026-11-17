"""Read-only dual RMT IR receiver field log must not forge movement."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "terminal_ir_calibrator", ROOT / "code/scripts/calibrate_terminal_ir.py"
)
cal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cal)


def position_records():
    rows = []
    left_seq = right_seq = 0
    now = 1000.0
    for label in ("left", "center", "right"):
        for _ in range(20):
            left_seen = label in ("left", "center")
            r = label in ("center", "right")
            if left_seen:
                left_seq += 1
            if r:
                right_seq += 1
            rows.append({
                "label": label, "received_monotonic": now,
                "ir": {
                    "robot_id": "robot-01", "left_valid": left_seen,
                    "right_valid": r, "match": left_seen and r,
                    "left_seq": left_seq, "right_seq": right_seq,
                    "left_age_ms": 20 if left_seen else 0xffffffff,
                    "right_age_ms": 20 if r else 0xffffffff,
                    "code": 0xCB34ED12 if left_seen and r else 0,
                    "motor_authorized": False,
                    "charging_authorized": False,
                    "physical_qualified": False,
                },
            })
            now += .25
    return rows


def test_labeled_signal_rate_detects_candidate_not_steering_calibration():
    result = cal.analyze(position_records(), "robot-01")
    assert result["observations_total"] == 60
    assert result["candidate_differential_signal"] is True
    assert result["physical_acceptance_pass"] is False
    assert result["absolute_bearing_calibrated"] is False
    assert result["motor_authorized"] is False
    assert result["charging_authorized"] is False


def test_forged_valid_sample_without_new_rmt_frame_is_not_optical_evidence():
    rows = position_records()
    rows[1]["ir"]["left_seq"] = rows[0]["ir"]["left_seq"]
    with pytest.raises(ValueError, match="Replayed"):
        cal.analyze(rows, "robot-01")


@pytest.mark.parametrize("mutation", [
    lambda r: r[1].update(received_monotonic=r[0]["received_monotonic"]),
    lambda r: r[0]["ir"].update(charging_authorized=True),
    lambda r: r[0]["ir"].update(robot_id="robot-02"),
    lambda r: r[0].update(label="unmeasured"),
])
def test_untrustworthy_receiver_trial_is_rejected(mutation):
    rows = position_records()
    mutation(rows)
    with pytest.raises(ValueError):
        cal.analyze(rows, "robot-01")


def test_unbalanced_optics_cannot_be_sold_as_differential_bearing():
    rows = position_records()
    # All signal samples from all locations appear identical. RMT frame
    # sequences still legitimately advance, but baffles tell us nothing.
    for n, row in enumerate(rows, 1):
        row["ir"].update(
            left_valid=True, right_valid=True, match=True,
            left_seq=n, right_seq=n, code=0xCB34ED12,
            left_age_ms=15, right_age_ms=15,
        )
    result = cal.analyze(rows, "robot-01")
    assert result["candidate_differential_signal"] is False


async def test_capture_uses_authenticated_mac_read_only_ir_endpoint(monkeypatch):
    monkeypatch.setattr(cal.asyncio, "sleep", fast_sleep)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.path == "/v1/robots/robot-01/dock/ir"
        assert request.headers["Authorization"] == "Bearer " + "S" * 40
        data = position_records()[0]["ir"]
        data["left_seq"] += len(calls)
        return httpx.Response(200, json=data)

    actual = httpx.AsyncClient

    def create_client(*args, **kwargs):
        return actual(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(cal.httpx, "AsyncClient", create_client)
    rows = await cal.capture(
        "http://localhost:8765", "S" * 40, "robot-01",
        "left", 20, .05,
    )
    assert len(calls) == 20
    assert len(rows) == 20
    assert all(row["ir"]["charging_authorized"] is False for row in rows)


async def fast_sleep(_seconds):
    return None



def test_labeled_trial_rejects_dock_from_another_physical_robot():
    rows = position_records()  # robot 01 currently observes dock 04
    assert cal.analyze(rows, "robot-01", expected_dock_id=4)[
        "candidate_differential_signal"
    ]
    with pytest.raises(ValueError, match="Foreign NEC dock beacon"):
        cal.analyze(rows, "robot-01", expected_dock_id=1)


async def test_capture_rejects_foreign_assigned_dock_at_http_boundary(monkeypatch):
    monkeypatch.setattr(cal.asyncio, "sleep", fast_sleep)
    calls = []

    def handler(request):
        calls.append(request)
        frame = position_records()[20]["ir"]  # both sides fresh, dock 04
        return httpx.Response(200, json=frame)

    actual = httpx.AsyncClient

    def create_client(*args, **kwargs):
        return actual(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(cal.httpx, "AsyncClient", create_client)
    with pytest.raises(ValueError, match="Foreign NEC dock beacon"):
        await cal.capture("http://localhost:8765", "S" * 40,
                          "robot-01", "center", 20, .05, 1)
    assert len(calls) == 1
