import time
from dataclasses import replace

import pytest
from desk_robot.memory import MemoryStore
from desk_robot.spatial_memory import SpatialEvidence, SpatialMemory


def evidence(observed_at):
    return SpatialEvidence(
        object_key="flat_key", observed_at=observed_at,
        body_boot=7, origin_id="odom-1", pose_seq=10,
        pose_sample_us=800_000, camera_boot=11,
        camera_seq=4, camera_complete_us=900_000,
        calibration_id="cal-a", x_mm=120, y_mm=-40,
        yaw_mrad=100, uncertainty_mm=35,
    )


def remember(db, robot, event, when, *, source=None, witnessed=True):
    return db.remember(robot, event, "A key was seen", kind="vision",
                       source_robot=source or robot, witnessed=witnessed,
                       observed_at=when)


def test_spatial_insert_restart_migration_and_forget_are_per_robot(tmp_path):
    root = tmp_path / "private"
    db = MemoryStore(root, ["robot-01", "robot-02"])
    spatial = SpatialMemory(db)
    when = time.time() - 1
    assert spatial.last_seen("robot-01", "flat_key", now=time.time()) is None
    assert remember(db, "robot-01", "seen1", when)
    assert spatial.attach("robot-01", "seen1", evidence(when))
    result = spatial.last_seen("robot-01", "flat_key", now=when + 2)
    assert result.event_id == "seen1"
    assert result.evidence.x_mm == 120
    assert result.status == "pending_localization"
    assert spatial.last_seen("robot-02", "flat_key", now=when + 2) is None
    db2 = MemoryStore(root, ["robot-01", "robot-02"])
    spatial2 = SpatialMemory(db2)
    assert spatial2.last_seen("robot-01", "flat_key", now=when + 2).event_id == "seen1"
    assert db2.forget_episode("robot-01", "seen1")
    assert spatial2.last_seen("robot-01", "flat_key", now=when + 2) is None
    assert not spatial2.attach("robot-01", "seen1", evidence(when))
    assert not remember(db2, "robot-01", "seen1", when)


def test_duplicate_frame_and_correction_do_not_rewrite_spatial_evidence(tmp_path):
    db = MemoryStore(tmp_path / "private", ["robot-01"])
    spatial = SpatialMemory(db)
    when = time.time() - 1
    assert remember(db, "robot-01", "first", when)
    assert remember(db, "robot-01", "second", when + 0.001)
    assert spatial.attach("robot-01", "first", evidence(when))
    assert not spatial.attach("robot-01", "first", replace(evidence(when), x_mm=200))
    assert not spatial.attach("robot-01", "second", evidence(when + 0.001))
    result = spatial.last_seen("robot-01", "flat_key", now=when + 2)
    assert result.event_id == "first"
    assert result.evidence.x_mm == 120


def test_last_seen_invalid_origin_and_expired_are_explicit(tmp_path):
    db = MemoryStore(tmp_path / "private", ["robot-01"])
    spatial = SpatialMemory(db)
    when = time.time() - 1
    assert remember(db, "robot-01", "seen1", when)
    spatial.attach("robot-01", "seen1", evidence(when))
    result = spatial.last_seen("robot-01", "flat_key", now=when + 2,
                               current_origin=(8, "odom-2"))
    assert result.status == "invalid_origin"
    assert spatial.last_seen("robot-01", "flat_key", now=when + 200_000).status == "stale"


@pytest.mark.parametrize("bad", [
    {"object_key": "DROP TABLE memories"},
    {"frame": "map", "anchor_id": "forged-tag"},
    {"x_mm": 1_000_001}, {"uncertainty_mm": 0},
    {"camera_seq": 0}, {"camera_boot": -1},
    {"body_boot": True}, {"pose_seq": True},
    {"observed_at": float("nan")}, {"pose_sample_us": -3},
    {"calibration_id": "../../private"},
])
def test_invalid_spatial_input_rejected_atomically(tmp_path, bad):
    db = MemoryStore(tmp_path / "private", ["robot-01"])
    spatial = SpatialMemory(db)
    when = time.time() - 1
    assert remember(db, "robot-01", "seen1", when)
    with pytest.raises(ValueError):
        spatial.attach("robot-01", "seen1", replace(evidence(when), **bad))
    assert spatial.last_seen("robot-01", "flat_key", now=when + 2) is None


def test_peer_told_episode_cannot_gain_firsthand_spatial_claim(tmp_path):
    db = MemoryStore(tmp_path / "private", ["robot-01", "robot-02"])
    spatial = SpatialMemory(db)
    when = time.time() - 1
    assert remember(db, "robot-01", "told1", when, source="robot-02", witnessed=False)
    with pytest.raises(ValueError, match="firsthand"):
        spatial.attach("robot-01", "told1", evidence(when))


def test_episode_rolling_retention_removes_spatial_sidecar(tmp_path):
    db = MemoryStore(tmp_path / "private", ["robot-01"])
    spatial = SpatialMemory(db)
    when = time.time() - 1000
    assert remember(db, "robot-01", "old", when)
    assert spatial.attach("robot-01", "old", evidence(when))
    for i in range(251):
        assert remember(db, "robot-01", f"event_{i}", when + 10 + i)
    assert spatial.last_seen("robot-01", "flat_key", now=time.time()) is None


def test_human_correction_retires_old_spatial_coordinates(tmp_path):
    db = MemoryStore(tmp_path / "private", ["robot-01"])
    spatial = SpatialMemory(db)
    when = time.time() - 1
    assert remember(db, "robot-01", "seen1", when)
    assert spatial.attach("robot-01", "seen1", evidence(when))
    assert db.correct_episode("robot-01", "seen1", "The key was actually in a drawer")
    assert spatial.last_seen("robot-01", "flat_key", now=time.time()) is None
