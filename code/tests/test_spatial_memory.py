import time
from dataclasses import replace

import pytest
from desk_robot.memory import CameraProvenance, MemoryStore
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


def remember(db, robot, event, when, *, source=None, witnessed=True,
             identity=(11, 4, 900_000)):
    return db.remember(robot, event, "A key was seen", kind="vision",
                       source_robot=source or robot, witnessed=witnessed,
                       observed_at=when, camera_provenance=(
                           CameraProvenance(when, when + 0.01, identity)
                           if identity is not None else None))


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
    assert not spatial.attach(
        "robot-01", "second",
        replace(evidence(when + 0.001), camera_complete_us=900_001),
    )
    # Distinct objects may legitimately be detected in one camera frame.
    assert remember(db, "robot-01", "third", when + 0.002)
    assert spatial.attach(
        "robot-01", "third",
        replace(evidence(when + 0.002), object_key="wrapped_candy"),
    )
    assert spatial.last_seen(
        "robot-01", "wrapped_candy", now=when + 2,
    ).event_id == "third"
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


@pytest.mark.parametrize("identity", [None, (12, 4, 900_000),
                                      (11, 5, 900_000), (11, 4, 900_001)])
def test_attachment_requires_exact_original_camera_receipt(tmp_path, identity):
    db = MemoryStore(tmp_path / "private", ["robot-01"])
    when = time.time() - 1
    assert remember(db, "robot-01", "seen1", when, identity=identity)
    spatial = SpatialMemory(db)
    assert not spatial.attach("robot-01", "seen1", evidence(when))
    assert spatial.last_seen("robot-01", "flat_key", now=time.time()) is None


def test_reserved_or_corrected_episode_cannot_regain_coordinates(tmp_path):
    root = tmp_path / "private"
    db = MemoryStore(root, ["robot-01"])
    when = time.time() - 1
    assert remember(db, "robot-01", "seen1", when)
    spatial = SpatialMemory(db)
    assert spatial.attach("robot-01", "seen1", evidence(when))
    generation = db.reserve_episode_mutation("robot-01", "seen1", "Corrected")
    assert spatial.last_seen("robot-01", "flat_key", now=time.time()) is None
    assert not spatial.attach("robot-01", "seen1", evidence(when))
    assert db.correct_episode("robot-01", "seen1", "Corrected",
                              mutation_generation=generation)
    spatial = SpatialMemory(MemoryStore(root, ["robot-01"]))
    assert not spatial.attach("robot-01", "seen1", evidence(when))
    assert spatial.last_seen("robot-01", "flat_key", now=time.time()) is None


@pytest.mark.parametrize(("frame", "anchor"), [
    ("map", "forged-tag"), ("map", None), ("odom", "forged-tag"),
])
def test_unqualified_persisted_anchor_cannot_hide_pending_observation(
        tmp_path, frame, anchor):
    db = MemoryStore(tmp_path / "private", ["robot-01"])
    spatial = SpatialMemory(db)
    when = time.time() - 1
    assert remember(db, "robot-01", "older", when)
    assert spatial.attach("robot-01", "older", evidence(when))
    newer = replace(evidence(when + 0.5), camera_seq=5,
                    camera_complete_us=950_000)
    assert remember(db, "robot-01", "newer", newer.observed_at,
                    identity=(11, 5, 950_000))
    assert spatial.attach("robot-01", "newer", newer)
    with db._connect("robot-01") as conn:
        conn.execute(
            "UPDATE spatial_observations SET frame=?, anchor_id=? WHERE event_id=?",
            (frame, anchor, "newer"),
        )
    sighting = spatial.last_seen(
        "robot-01", "flat_key", now=when + 0.6,
        current_origin=(7, "odom-1"), current_camera=(11, 5, 950_000),
    )
    assert sighting is not None and sighting.event_id == "older"
    assert sighting.status == "pending_localization"
    with db._connect("robot-01") as conn:
        conn.execute("DELETE FROM spatial_observations WHERE event_id=?", ("older",))
    assert spatial.last_seen("robot-01", "flat_key", now=when + 0.6) is None


def test_plain_odometry_remains_pending_with_current_camera(tmp_path):
    db = MemoryStore(tmp_path / "private", ["robot-01"])
    spatial = SpatialMemory(db)
    when = time.time() - 1
    assert remember(db, "robot-01", "valid", when)
    assert spatial.attach("robot-01", "valid", evidence(when))
    sighting = spatial.last_seen(
        "robot-01", "flat_key", now=when + 0.1,
        current_origin=(7, "odom-1"), current_camera=(11, 4, 900_000),
    )
    assert sighting is not None and sighting.status == "pending_localization"


def test_overlapping_robot_receipt_ids_recover_and_remain_private(tmp_path):
    root = tmp_path / "private"
    robots = ["robot-01", "robot-02"]
    db = MemoryStore(root, robots)
    spatial = SpatialMemory(db)
    when = time.time() - 1
    first = evidence(when)
    second = replace(
        first, origin_id="odom-2", calibration_id="cal-b", x_mm=-80, y_mm=60,
    )
    event = "shared_event_id"
    for robot in robots:
        assert remember(db, robot, event, when)

    assert spatial.attach(robots[0], event, first)
    with pytest.raises(ValueError, match="Unknown robot"):
        spatial.attach("foreign-pet", event, second)
    assert not spatial.attach(
        robots[1], event, replace(second, camera_complete_us=900_001),
    )
    assert spatial.last_seen(robots[1], "flat_key", now=when + 0.1) is None
    assert spatial.attach(robots[1], event, second)

    # Same event and sensor counters are legitimate on different robots.
    # Distinct private local origins are not claims of measured map anchors.
    reopened = MemoryStore(root, robots)
    spatial = SpatialMemory(reopened)
    for robot, expected in zip(robots, (first, second), strict=True):
        sighting = spatial.last_seen(
            robot, "flat_key", now=when + 0.1,
            current_origin=(expected.body_boot, expected.origin_id),
            current_camera=(11, 4, 900_000),
        )
        assert sighting is not None
        assert sighting.event_id == event
        assert sighting.evidence == expected
        assert sighting.status == "pending_localization"
    assert spatial.last_seen(
        robots[1], "flat_key", now=when + 0.1,
        current_origin=(first.body_boot, first.origin_id),
        current_camera=(11, 4, 900_000),
    ).status == "invalid_origin"

    assert reopened.forget_episode(robots[0], event)
    assert not spatial.attach(robots[0], event, first)
    assert not remember(reopened, robots[0], event, when)
    assert spatial.last_seen(robots[0], "flat_key", now=when + 0.1) is None
    remaining = spatial.last_seen(
        robots[1], "flat_key", now=when + 0.1,
        current_origin=(second.body_boot, second.origin_id),
        current_camera=(11, 4, 900_000),
    )
    assert remaining is not None and remaining.evidence == second
    assert remaining.status == "pending_localization"


def test_legacy_pre_spatial_sqlite_migrates_and_reads_back_original_records(tmp_path):
    """Genuine pre-spatial private DB without relay_token or spatial tables upgrades cleanly."""
    import sqlite3

    root = tmp_path / "legacy_private"
    root.mkdir(mode=0o700, parents=True)
    db_path = root / "robot-01.sqlite3"
    when = time.time() - 5.0
    # Seed the legacy pre-spatial schema (no relay_token, no spatial/provenance tables).
    with sqlite3.connect(db_path) as legacy:
        legacy.execute(
            """CREATE TABLE memories (
                 event_id TEXT PRIMARY KEY,
                 source_robot TEXT NOT NULL,
                 witnessed INTEGER NOT NULL CHECK(witnessed IN (0,1)),
                 kind TEXT NOT NULL,
                 summary TEXT NOT NULL,
                 observed_at REAL NOT NULL,
                 confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1)
               )"""
        )
        legacy.execute(
            """INSERT INTO memories
               (event_id, source_robot, witnessed, kind, summary, observed_at, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("legacy-evt-1", "robot-01", 1, "vision", "Pre-upgrade desk key note", when, 0.9),
        )
        legacy.commit()

    store = MemoryStore(root, ["robot-01"])
    spatial = SpatialMemory(store)
    rows = store.recent("robot-01", limit=10)
    assert any(r.event_id == "legacy-evt-1" and r.summary == "Pre-upgrade desk key note" for r in rows)

    # Reopen and attach spatial evidence to another newly observed episode cleanly.
    reopened = MemoryStore(root, ["robot-01"])
    spatial2 = SpatialMemory(reopened)
    assert any(r.event_id == "legacy-evt-1" for r in reopened.recent("robot-01", limit=10))
    now2 = time.time()
    assert remember(reopened, "robot-01", "post-upgrade-1", now2)
    assert spatial2.attach("robot-01", "post-upgrade-1", evidence(now2))
    assert spatial.last_seen("robot-01", "flat_key", now=now2 + 0.1).event_id == "post-upgrade-1"


def test_forgotten_spatial_episode_cannot_replay_after_wal_restart(tmp_path):
    """Retire one pet's episode across reopened, concurrent SQLite writers."""
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing
    from threading import Barrier

    root = tmp_path / "private"
    robots = ["robot-01", "robot-02"]
    store = MemoryStore(root, robots)
    when = time.time() - 1
    old = evidence(when)
    fresh = replace(old, observed_at=when + 0.5, camera_seq=5,
                    camera_complete_us=950_000)
    for robot in robots:
        assert remember(store, robot, "forgotten", when)
        assert SpatialMemory(store).attach(robot, "forgotten", old)

    path = root / "robot-01.sqlite3"
    with closing(sqlite3.connect(path)) as reader:
        assert reader.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        reader.execute("BEGIN")
        assert reader.execute(
            "SELECT event_id FROM memories",
        ).fetchone() == ("forgotten",)
        # Keep an older WAL read snapshot alive while deleting and reopening.
        assert store.forget_episode("robot-01", "forgotten")
        reopened = MemoryStore(root, robots)
        spatial = SpatialMemory(reopened)
        barrier = Barrier(2)

        def replay():
            barrier.wait(timeout=5)
            assert not remember(reopened, "robot-01", "forgotten", when)
            assert not spatial.attach("robot-01", "forgotten", old)

        def new_sighting():
            barrier.wait(timeout=5)
            assert remember(
                reopened, "robot-01", "fresh", fresh.observed_at,
                identity=(11, 5, 950_000),
            )
            assert spatial.attach("robot-01", "fresh", fresh)

        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(replay), workers.submit(new_sighting)]
            for future in futures:
                future.result(timeout=10)

        assert reopened.get_episode("robot-01", "forgotten") is None
        assert reopened.get_camera_provenance("robot-01", "forgotten") is None
        sighting = spatial.last_seen("robot-01", "flat_key", now=when + 1)
        assert sighting is not None and sighting.event_id == "fresh"
        with reopened._connect("robot-01") as conn:
            assert conn.execute(
                "SELECT event_id FROM spatial_observations",
            ).fetchall() == [("fresh",)]
        # A different robot may have independently retained the same ID.
        peer = spatial.last_seen("robot-02", "flat_key", now=when + 1)
        assert peer is not None and peer.event_id == "forgotten"
        reader.rollback()

    final = MemoryStore(root, robots)
    assert final.get_episode("robot-01", "forgotten") is None
    assert [entry.event_id for entry in final.search("robot-01", "key")] == ["fresh"]
    sighting = SpatialMemory(final).last_seen(
        "robot-01", "flat_key", now=when + 200_000,
    )
    assert sighting is not None and sighting.status == "stale"
