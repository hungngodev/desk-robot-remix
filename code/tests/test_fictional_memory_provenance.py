"""G005 authored fiction must never become physical evidence after recall."""
from __future__ import annotations

import time
from dataclasses import replace

import pytest
from desk_robot.api import create_app
from desk_robot.brain_context import compose_brain_context, memory_provenance_label
from desk_robot.memory import CameraProvenance, MemoryStore
from desk_robot.spatial_memory import SpatialEvidence, SpatialMemory
from fastapi.testclient import TestClient


@pytest.mark.parametrize("kind", ["dream", "fictional_dream"])
def test_dream_kind_survives_correction_restart_and_private_recall(tmp_path, kind):
    robots = ["robot-01", "robot-02"]
    store = MemoryStore(tmp_path, robots)
    when = time.time() - 86400
    assert store.remember(
        robots[0], "dream001", "A key moved to the blue box",
        kind=kind, source_robot=robots[0], witnessed=True, observed_at=when,
    )
    assert store.search(robots[1], "key") == []
    assert store.correct_episode(robots[0], "dream001", "A brass key moved to the blue box")
    assert not store.remember(
        robots[0], "dream001", "A real key moved", kind="key",
        source_robot=robots[0], witnessed=True,
    )
    # A consented text copy retains the original kind and source, not sight.
    assert store.remember(
        robots[1], "dream001", "A brass key moved to the blue box",
        kind=kind, source_robot=robots[0], witnessed=False, observed_at=when,
    )
    reopened = MemoryStore(tmp_path, robots)
    for robot in robots:
        recalled, = reopened.search(robot, "brass key")
        assert recalled.kind == kind and recalled.source_robot == robots[0]
        assert recalled.summary == "A brass key moved to the blue box"
        context = compose_brain_context([recalled], [], []).recent
        assert "fictional dream (imagined, not a physical observation)" in context
        assert "I observed:" not in context
        assert "confidence" not in context
        assert reopened.witnessed_episode_revision(robot, "dream001") is None
        # Even a contradictory local-origin flag cannot override the kind.
        assert "fictional dream" in memory_provenance_label(
            replace(recalled, witnessed=not recalled.witnessed)
        )
    assert reopened.forget_episode(robots[0], "dream001")
    assert reopened.search(robots[0], "brass key") == []
    assert reopened.search(robots[1], "brass key")


@pytest.mark.parametrize("kind", ["dream", "fictional_dream"])
def test_dream_rejects_camera_receipt_before_insert(tmp_path, kind):
    store = MemoryStore(tmp_path, ["robot-01"])
    when = time.time() - 1
    with pytest.raises(ValueError, match="camera provenance"):
        store.remember(
            "robot-01", "dream001", "A key moved", kind=kind,
            source_robot="robot-01", witnessed=True, observed_at=when,
            camera_provenance=CameraProvenance(when, when + 0.01, (11, 4, 900000)),
        )
    assert store.count("robot-01") == 0


def test_legacy_fiction_with_contradictory_receipts_cannot_be_spatial(tmp_path):
    robot = "robot-01"
    store = MemoryStore(tmp_path, [robot])
    spatial = SpatialMemory(store)
    when = time.time() - 1
    assert store.remember(
        robot, "legacy", "A key was seen", kind="vision",
        source_robot=robot, witnessed=True, observed_at=when,
        camera_provenance=CameraProvenance(when, when + 0.01, (11, 4, 900000)),
    )
    evidence = SpatialEvidence(
        object_key="flat_key", observed_at=when, body_boot=7, origin_id="odom-1",
        pose_seq=10, pose_sample_us=800000, camera_boot=11, camera_seq=4,
        camera_complete_us=900000, calibration_id="cal-a", x_mm=120, y_mm=-40,
        yaw_mrad=100, uncertainty_mm=35,
    )
    # Deliberately emulate a legacy contradictory kind/receipt, not a public edit.
    with store._connect(robot) as db:
        db.execute("UPDATE memories SET kind='dream' WHERE event_id='legacy'")
    with pytest.raises(ValueError, match="fictional memory"):
        store.get_camera_provenance(robot, "legacy")
    assert not spatial.attach(robot, "legacy", evidence)
    with store._connect(robot) as db:
        db.execute("UPDATE memories SET kind='vision' WHERE event_id='legacy'")
    assert spatial.attach(robot, "legacy", evidence)
    assert spatial.last_seen(robot, "flat_key", now=when + 2) is not None
    with store._connect(robot) as db:
        db.execute("UPDATE memories SET kind='fictional_dream' WHERE event_id='legacy'")
    assert spatial.last_seen(robot, "flat_key", now=when + 2) is None


def test_voice_and_operator_memory_json_do_not_claim_dream_witness(settings, tokens, tmp_path):
    settings.memory_dir = tmp_path
    settings.voice_memory_tools_enabled = True
    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    operator = {"Authorization": f"Bearer {tokens['DESK_ROBOT_API_TOKEN']}"}
    with TestClient(create_app(settings)) as client:
        store = client.app.state.runtime.memory
        assert store.remember(
            "robot-01", "dream001", "A brass key moved to the blue box",
            kind="fictional_dream", source_robot="robot-01", witnessed=True,
        )
        voice = client.get(
            "/v1/pet/robot-01/voice-context", headers=tool, params={"query": "brass key"},
        )
        own = client.get("/v1/pet/robot-01/memories", headers=operator)
        assert voice.status_code == own.status_code == 200
        for record in (voice.json()["memories"][0], own.json()["records"][0]):
            assert record["fictional"] is True
            assert record["witnessed"] is False
            assert record["observed_at"] is None and record["confidence"] is None
            assert record["recorded_at"] > 0
            assert "not a physical observation" in record["provenance"]
        peer = client.get(
            "/v1/pet/robot-02/voice-context", headers=tool, params={"query": "brass key"},
        )
        assert peer.status_code == 200 and peer.json()["memories"] == []


@pytest.mark.parametrize("kind", ["peer_claim", "peer_report", "peer_utterance"])
def test_peer_report_cannot_be_promoted_to_firsthand(tmp_path, kind):
    source, listener = "robot-01", "robot-02"
    store = MemoryStore(tmp_path, [source, listener])
    event_id = "peer001"
    summary = "A key moved to the blue box"
    with pytest.raises(ValueError, match="Peer reports cannot be witnessed"):
        store.remember(
            listener, event_id, summary, kind=kind,
            source_robot=listener, witnessed=True,
        )
    assert store.count(listener) == 0
    assert store.remember(
        listener, event_id, summary, kind=kind,
        source_robot=source, witnessed=False,
    )
    with pytest.raises(ValueError, match="Peer reports cannot be witnessed"):
        store.remember(
            listener, event_id, summary, kind=kind,
            source_robot=listener, witnessed=True,
        )
    reopened = MemoryStore(tmp_path, [source, listener])
    recalled, = reopened.search(listener, "blue box")
    assert recalled.source_robot == source
    assert recalled.kind == kind and recalled.witnessed is False
    assert reopened.recent(listener, own_only=True) == []
    assert reopened.search(listener, "blue box", own_only=True) == []
    assert reopened.witnessed_episode_revision(listener, event_id) is None
    assert reopened.search(source, "blue box") == []
    assert "I observed" not in memory_provenance_label(recalled)
    assert source in memory_provenance_label(recalled)


@pytest.mark.parametrize("kind", ["peer_claim", "peer_report", "peer_utterance"])
def test_legacy_peer_row_cannot_be_recalled_or_relayed_as_firsthand(tmp_path, kind):
    robot = "robot-02"
    store = MemoryStore(tmp_path, [robot])
    assert store.remember(
        robot, "legacy", "A blue box moved", kind="scene",
        source_robot=robot, witnessed=True,
    )
    # Emulate a row persisted before the peer-kind write guard.
    with store._connect(robot) as db:
        db.execute("UPDATE memories SET kind=? WHERE event_id='legacy'", (kind,))
    reopened = MemoryStore(tmp_path, [robot])
    episode = reopened.get_episode(robot, "legacy")
    assert episode is not None
    assert episode.witnessed is False
    assert reopened.recent(robot) == [episode]
    assert reopened.search(robot, "blue box") == [episode]
    assert reopened.recent(robot, own_only=True) == []
    assert reopened.search(robot, "blue box", own_only=True) == []
    assert reopened.witnessed_episode_revision(robot, "legacy") is None
    assert "Unattributed peer report" in memory_provenance_label(episode)
    assert "Unattributed peer report" in memory_provenance_label(
        replace(episode, witnessed=True)
    )
    assert reopened.count(robot) == 1
