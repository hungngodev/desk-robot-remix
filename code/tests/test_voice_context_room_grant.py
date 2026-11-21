"""Verify room context cannot cross a revoked sharing grant."""
import time
from types import SimpleNamespace

import pytest
from desk_robot.api_memory_routes import register_voice_context_route
from desk_robot.multimodal import CameraFrameHub
from desk_robot.room_station import RoomObservation
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "change",
    (
        None,
        "revoke_during_recent",
        "revoke_during_search",
        "revoke_during_core",
        "grant_during_recent",
    ),
)
def test_voice_context_room_grant_is_fenced_across_sqlite(settings, change):
    settings.mode = "hardware"
    settings.voice_memory_tools_enabled = True
    settings.room_station_context_enabled = change != "grant_during_recent"
    initial_generation = settings.room_station_consent_generation

    hub = CameraFrameHub(["robot-01"])
    hub.remember_room(RoomObservation(
        seq=1,
        at_ms=100,
        received_at=time.monotonic(),
        readings={},
        summary="ROOM PRIVATE: old USB observation",
    ))

    def maybe_change(stage):
        if change == f"revoke_during_{stage}":
            settings.room_station_context_enabled = False
            settings.room_station_context_enabled = True
        elif change == f"grant_during_{stage}":
            settings.room_station_context_enabled = True

    class Memory:
        def recent(self, robot_id, *, limit):
            assert robot_id == "robot-01" and limit == 6
            maybe_change("recent")
            return []

        def search(self, robot_id, query, *, limit):
            assert robot_id == "robot-01" and query == "room" and limit == 6
            maybe_change("search")
            return []

        def core_facts(self, robot_id, *, limit):
            assert robot_id == "robot-01" and limit == 8
            maybe_change("core")
            return []

    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=Memory(),
        multimodal=SimpleNamespace(hub=hub),
        conversation=SimpleNamespace(
            _private_memory_generation={"robot-01": 0},
        ),
    )
    register_voice_context_route(
        app,
        settings,
        authorize=lambda: None,
        requested_tool_context=lambda *args: None,
        remember_tool_context=lambda *args: None,
    )
    with TestClient(app) as client:
        response = client.get(
            "/v1/pet/robot-01/voice-context",
            params={"query": "room"} if change == "revoke_during_search" else None,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["no_new_motion_permission"] is True
    room_entries = [
        item for item in payload["current_interaction_timeline"]
        if item.get("channel") == "room_station"
    ]
    if change is None:
        assert room_entries
        assert "ROOM PRIVATE" in str(room_entries)
    else:
        assert room_entries == []
        assert "ROOM PRIVATE" not in response.text
    expected_revocations = int(bool(change and change.startswith("revoke_")))
    assert (
        settings.room_station_consent_generation
        == initial_generation + expected_revocations
    )
