"""Reject hardware spatial camera evidence without measured stationarity."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from desk_robot.object_detector import DetectorFrame
from desk_robot.object_targets import ObjectEvidence
from desk_robot.spatial_runtime import SpatialRuntime


@pytest.fixture
def runtime():
    settings = SimpleNamespace(
        mode="hardware",
        robots=[SimpleNamespace(id="robot-01")],
        voice_vision_tools_enabled=True,
        voice_memory_tools_enabled=True,
        camera_consent_generation=1,
    )
    return SpatialRuntime(settings, None)


async def test_direct_hardware_frame_cannot_bypass_stationarity(runtime, monkeypatch):
    infer = AsyncMock()
    monkeypatch.setattr("desk_robot.spatial_runtime.detect_object_frame", infer)
    frame = DetectorFrame(
        "robot-01", "operator-session", "operator-turn", "unanchored", 1,
        "unanchored", "uncalibrated", 0, runtime.host_boot_id, 1, 1,
        1_000_000, 1_000_000, 1_800_000_000, b"frame",
    )
    monkeypatch.setattr(runtime, "now_us", lambda: 1_000_000)
    receipt = await runtime.confirm_target_frame(
        Mock(), frame, label="key", model_qualified=True,
        safety_clear=lambda: True, request_is_current=lambda: True,
    )
    assert receipt.status == "rejected"
    assert receipt.reason == "camera_stationarity_unproven"
    assert receipt.evidence is None and receipt.box is None
    assert not receipt.may_execute and not receipt.arrived
    infer.assert_not_called()


@pytest.mark.parametrize("source", ["camera_seen", "camera_not_seen"])
def test_unproven_camera_observation_never_reaches_memory(runtime, monkeypatch, source):
    attach = Mock(return_value=True)
    monkeypatch.setattr(runtime.spatial_memory, "attach", attach)
    evidence = ObjectEvidence(
        "robot-01", "key", source, 1_800_000_000,
        captured_us=1_000_000, receipt_us=1_000_000,
        floor_mm=(40, 60) if source == "camera_seen" else None,
        projection_qualified=source == "camera_seen", confidence=0.95,
    )
    assert runtime.record_object_sighting(
        "robot-01", evidence, event_id="episode", spatial_evidence=Mock(),
    ) is False
    assert runtime.state("robot-01").observations == []
    attach.assert_not_called()


@pytest.mark.parametrize("mode,source", [
    ("simulation", "camera_seen"), ("hardware", "user_reported"),
])
def test_synthetic_replay_and_user_report_are_not_camera_attestations(runtime, mode, source):
    runtime.settings.mode = mode
    evidence = ObjectEvidence("robot-01", "key", source, 1_800_000_000)
    assert runtime.record_object_sighting("robot-01", evidence) is True
    assert runtime.state("robot-01").observations == [evidence]
