"""Immutable private camera evidence times; never raw media or exposure claims."""

import time
from dataclasses import replace

import pytest
from desk_robot.memory import CameraProvenance, MemoryStore


def _camera_rows(memory, robot_id):
    # The public getter joins memories, so it cannot expose an orphan sidecar.
    with memory._connect(robot_id) as conn:
        return conn.execute(
            "SELECT event_id, mac_received_at, interpreted_at, device_boot, "
            "device_frame, device_complete_us FROM camera_provenance ORDER BY event_id"
        ).fetchall()


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
    original = memory.get_episode("robot-01", "camera-test")
    assert original is not None
    assert memory.correct_episode("robot-01", "camera-test", "A brass key")
    corrected = replace(original, summary="A brass key")
    assert memory.get_episode("robot-01", "camera-test") == corrected
    assert memory.get_camera_provenance("robot-01", "camera-test") == receipt
    assert memory.remember(
        "robot-02", "camera-test", "A brass key", kind="key",
        source_robot="robot-01", witnessed=False, observed_at=now - 3,
        camera_provenance=receipt,
    )
    reopened = MemoryStore(tmp_path, ["robot-01", "robot-02"])
    assert reopened.get_episode("robot-01", "camera-test") == corrected
    assert reopened.get_camera_provenance("robot-01", "camera-test") == receipt
    assert reopened.get_episode("robot-02", "camera-test") == replace(
        corrected, robot_id="robot-02", witnessed=False,
    )
    assert reopened.get_camera_provenance("robot-02", "camera-test") == receipt
    expected_row = ("camera-test", now - 3, now, 7, 19, str((1 << 63) + 17))
    assert _camera_rows(reopened, "robot-01") == [expected_row]
    assert _camera_rows(reopened, "robot-02") == [expected_row]
    assert reopened.forget_episode("robot-01", "camera-test")
    assert reopened.get_camera_provenance("robot-01", "camera-test") is None
    assert reopened.get_episode("robot-01", "camera-test") is None
    assert _camera_rows(reopened, "robot-01") == []
    assert _camera_rows(reopened, "robot-02") == [expected_row]
    assert reopened.get_camera_provenance("robot-02", "camera-test") == receipt
    assert reopened.forget_episode("robot-02", "camera-test")
    assert reopened.get_camera_provenance("robot-02", "camera-test") is None
    assert reopened.get_episode("robot-02", "camera-test") is None
    assert _camera_rows(reopened, "robot-02") == []


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
        assert memory.get_episode("robot-01", "invalid-camera") is None
        assert _camera_rows(memory, "robot-01") == []
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
    assert _camera_rows(memory, "robot-01") == [
        ("old-camera", now - 200, now - 190, 1, 2, "90000"),
    ]
    for i in range(250):
        assert memory.remember(
            "robot-01", f"new-{i}", f"Recent scene {i}", kind="key",
            source_robot="robot-01", witnessed=True,
            observed_at=now - 10 + i / 1000,
        )
    assert memory.count("robot-01") == 250
    assert memory.get_episode("robot-01", "old-camera") is None
    assert memory.get_camera_provenance("robot-01", "old-camera") is None
    assert _camera_rows(memory, "robot-01") == []
    assert memory.get_episode("robot-01", "new-249") is not None


@pytest.mark.parametrize(("column", "value"), [
    ("device_boot", 7.5),
    ("device_boot", None),
    ("device_frame", None),
    ("device_frame", 0),
    ("device_complete_us", "00019"),
    ("device_complete_us", "18446744073709551616"),
    ("device_complete_us", "١٩"),
    ("device_complete_us", b"19"),
    pytest.param("device_complete_us", "9" * 5000, id="oversized-device-clock"),
    ("mac_received_at", "bad"),
    ("mac_received_at", float("inf")),
    ("mac_received_at", 1.0),
])
def test_dirty_persisted_camera_receipt_cannot_be_reinterpreted(tmp_path, column, value):
    robots = ["robot-01", "robot-02"]
    memory = MemoryStore(tmp_path, robots)
    now = time.time()
    receipt = CameraProvenance(now - 3, now, (7, 19, (1 << 64) - 1))
    for robot in robots:
        assert memory.remember(
            robot, "same-event", "A key", kind="key", source_robot=robot,
            witnessed=True, observed_at=now - 3, camera_provenance=receipt,
        )
    with memory._connect("robot-01") as conn:
        assert conn.execute(
            f"UPDATE camera_provenance SET {column}=? WHERE event_id=?",
            (value, "same-event"),
        ).rowcount == 1
    reopened = MemoryStore(tmp_path, robots)
    with pytest.raises(ValueError, match="Invalid persisted camera"):
        reopened.get_camera_provenance("robot-01", "same-event")
    assert reopened.get_camera_provenance("robot-02", "same-event") == receipt


def test_camera_receipt_without_device_identity_remains_readable(tmp_path):
    memory = MemoryStore(tmp_path, ["robot-01"])
    now = time.time()
    receipt = CameraProvenance(now - 3, now)
    assert memory.remember(
        "robot-01", "legacy-clock", "A key", kind="key", source_robot="robot-01",
        witnessed=True, observed_at=now - 3, camera_provenance=receipt,
    )
    reopened = MemoryStore(tmp_path, ["robot-01"])
    assert reopened.get_camera_provenance("robot-01", "legacy-clock") == receipt


def test_duplicate_camera_episode_cannot_replace_original_receipt(tmp_path):
    memory = MemoryStore(tmp_path, ["robot-01"])
    now = time.time()
    original = CameraProvenance(now - 3, now, (7, 19, 20))
    changed = CameraProvenance(now - 2, now, (8, 20, 21))
    assert memory.remember(
        "robot-01", "duplicate", "Original", kind="key",
        source_robot="robot-01", witnessed=True, observed_at=now - 3,
        camera_provenance=original,
    ) is True
    original_episode = memory.get_episode("robot-01", "duplicate")
    assert original_episode is not None
    assert memory.remember(
        "robot-01", "duplicate", "Replacement", kind="key",
        source_robot="robot-01", witnessed=True, observed_at=now - 2,
        camera_provenance=changed,
    ) is False
    reopened = MemoryStore(tmp_path, ["robot-01"])
    assert reopened.count("robot-01") == 1
    assert reopened.get_episode("robot-01", "duplicate") == original_episode
    assert reopened.get_camera_provenance("robot-01", "duplicate") == original
    assert _camera_rows(reopened, "robot-01") == [
        ("duplicate", now - 3, now, 7, 19, "20"),
    ]
