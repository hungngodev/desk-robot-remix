"""Pose diagnostics preserve source clocks separately from Mac receipt age."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from desk_robot import api_spatial_pose
from desk_robot.spatial_pose import PoseFence
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _packet(seq, **changes):
    return {
        "robot_id": "robot-01", "v": 1, "body_boot": 9, "origin": 3,
        "seq": seq, "sample_us": seq * 100_000, "x_mm": 25,
        "y_mm": -10, "yaw_mrad": 300, "quality": "valid", "head_boot": 12,
        **changes,
    }


def _read(monkeypatch, fence, receipt, now):
    monkeypatch.setattr(api_spatial_pose, "time", SimpleNamespace(monotonic=lambda: now))

    async def pose_status():
        return receipt

    head = SimpleNamespace(pose_status=pose_status, pose_fence=fence)
    owner = SimpleNamespace(robot=lambda _: None, heads={"robot-01": head})
    app = FastAPI()
    api_spatial_pose.register_spatial_pose_route(
        app, operator=lambda: None, coordinator=lambda: owner,
    )
    with TestClient(app) as client:
        response = client.get("/v1/robots/robot-01/pose")
    assert response.status_code == 200
    return response.json()


def _continuous():
    fence = PoseFence("robot-01")
    fence.observe(_packet(1), 100.0, request_started_at=99.95)
    receipt = fence.observe(_packet(2), 100.1, request_started_at=100.06)
    return fence, receipt


def test_pose_age_is_local_not_body_clock(monkeypatch):
    fence, receipt = _continuous()
    data = _read(monkeypatch, fence, receipt, 100.15)
    assert data["mac_receipt_age_ms"] == pytest.approx(50)
    assert data["mac_request_age_ms"] == pytest.approx(90)
    assert data["source_age_ms"] is None
    assert data["pose"]["sample_us"] == 200_000
    assert data["local_odometry_continuous"] is True
    assert data["map_anchored"] is False


def test_stale_pose_diagnostic_does_not_renew_continuity(monkeypatch):
    fence, receipt = _continuous()
    data = _read(monkeypatch, fence, receipt, 100.4)
    assert data["mac_receipt_age_ms"] == pytest.approx(300)
    assert data["mac_request_age_ms"] == pytest.approx(340)
    assert data["source_age_ms"] is None
    assert data["pose"]["quality"] == "valid"
    assert data["local_odometry_continuous"] is False
    assert data["blocked_reason"] == "stale_receipt"
    assert data["navigation_authorized"] is False


def test_unavailable_legacy_pose_keeps_unknown_metadata(monkeypatch):
    fence = PoseFence("robot-01")
    receipt = fence.observe(_packet(1, origin=0, quality="unavailable", head_boot=None), 100)
    data = _read(monkeypatch, fence, receipt, 100.05)
    assert data["available"] is True  # A diagnostic reply, not usable odometry.
    assert data["pose"]["quality"] == "unavailable"
    assert data["pose"]["origin"] == 0
    assert data["pose"]["head_boot"] is None
    assert data["mac_receipt_age_ms"] == pytest.approx(50)
    assert data["mac_request_age_ms"] is None
    assert data["source_age_ms"] is None
    assert data["local_odometry_continuous"] is False


def test_equal_but_unowned_pose_cannot_claim_continuity(monkeypatch):
    fence, receipt = _continuous()
    copy = replace(receipt)
    assert copy == receipt and copy is not receipt
    data = _read(monkeypatch, fence, copy, 100.15)
    assert data["local_odometry_continuous"] is False
    assert data["blocked_reason"] == "receipt_not_current"
