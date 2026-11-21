"""Immutable private camera evidence times; never raw media or exposure claims."""

import time

import pytest

from desk_robot.memory import CameraProvenance, MemoryStore


def test_camera_clocks_and_wide_device_ticks_survive_restart_and_deletion(tmp_path):
    memory = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    now = time.time()
    receipt = CameraProvenance(now - 3, now, (7, 19, (1 << 63) + 17))
    assert memory.remember(
        "robot-01", "camera-test", "A key", kind="key",
        source_robot="robot-01", witnessed=True, observed_at=now - 3,
        camera_provenance=receipt,
    )
    assert memory.get_camera_provenance("robot-01", "camera-test") == receipt
    assert memory.get_camera_provenance("robot-02", "camera-test") is None
    assert memory.correct_episode("robot-01", "camera-test", "A brass key")
    assert memory.get_camera_provenance("robot-01", "camera-test") == receipt
    assert memory.remember(
        "robot-02", "camera-test", "A brass key", kind="key",
        source_robot="robot-01", witnessed=False, observed_at=now - 3,
        camera_provenance=receipt,
    )
    reopened = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    assert reopened.get_camera_provenance("robot-02", "camera-test") == receipt
    assert reopened.forget_episode("robot-01", "camera-test")
    assert reopened.get_camera_provenance("robot-01", "camera-test") is None
    assert reopened.get_camera_provenance("robot-02", "camera-test") == receipt
    assert reopened.forget_episode("robot-02", "camera-test")
    assert reopened.get_camera_provenance("robot-02", "camera-test") is None


def test_camera_clock_provenance_rejects_invalid_data_before_insert(tmp_path):
    memory = MemoryStore(tmp_path, ["robot-01"])
    now = time.time()
    invalid = (
        CameraProvenance(now + 5, now, (1, 1, 20)),
        CameraProvenance(now - 3, now - 4, (1, 1, 20)),
        CameraProvenance(now - 3, float("nan"), (1, 1, 20)),
        CameraProvenance(now - 3, now, (1, 0, 20)),
        CameraProvenance(now - 3, now, (1, 1, 1 << 64)),
    )
    for evidence in invalid:
        with pytest.raises(ValueError, match="camera"):
            memory.remember(
                "robot-01", "invalid-camera", "Bad scene", kind="key",
                source_robot="robot-01", witnessed=True, observed_at=now - 3,
                camera_provenance=evidence,
            )
    assert memory.count("robot-01") == 0


def test_camera_sidecar_is_trimmed_with_bounded_episode_store(tmp_path):
    memory = MemoryStore(tmp_path, ["robot-01"])
    now = time.time()
    assert memory.remember(
        "robot-01", "old-camera", "Old scene", kind="key",
        source_robot="robot-01", witnessed=True,
        observed_at=now - 200,
        camera_provenance=CameraProvenance(
            now - 200, now - 190, (1, 2, 90000),
        ),
    )
    for i in range(250):
        assert memory.remember(
            "robot-01", f"new-{i}", f"Recent scene {i}", kind="key",
            source_robot="robot-01", witnessed=True,
            observed_at=now - 10 + i / 1000,
        )
    assert memory.count("robot-01") == 250
    assert memory.get_episode("robot-01", "old-camera") is None
    assert memory.get_camera_provenance("robot-01", "old-camera") is None
