"""Voice recall keeps admission, consent and receipt ordering across SQLite awaits."""
from types import SimpleNamespace

import pytest
from desk_robot.api_memory_routes import register_voice_context_route
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


@pytest.mark.parametrize("query", [None, "favorite color"])
@pytest.mark.parametrize("change", [
    "none", "memory", "sharing", "camera", "room", "revision", "other_revision",
    "conversation", "turn",
])
@pytest.mark.parametrize("phase", ["records", "core"])
def test_voice_context_read_fences(query, change, phase):
    app = FastAPI()
    settings = SimpleNamespace(
        robots=[SimpleNamespace(id="pet")],
        voice_memory_tools_enabled=True, voice_memory_consent_generation=0,
        fleet_text_sharing_enabled=False, fleet_sharing_consent_generation=0,
        voice_vision_tools_enabled=True, camera_consent_generation=0,
        camera_consent_started_at=0, room_station_context_enabled=True,
        room_station_consent_generation=0,
    )
    conversation = SimpleNamespace(_private_memory_generation={"pet": 1})
    receipts = []
    reads = []
    own = SimpleNamespace(
        robot_id="pet", source_robot="pet", witnessed=True, kind="scene",
        summary="silver key", event_id="own", observed_at=1.0, confidence=0.8,
    )
    peer = SimpleNamespace(
        robot_id="pet", source_robot="other", witnessed=False, kind="scene",
        summary="peer key", event_id="peer", observed_at=2.0, confidence=0.8,
    )

    def mutate(at):
        if at != phase:
            return
        if change == "memory":
            settings.voice_memory_consent_generation += 1
        elif change == "sharing":
            settings.fleet_sharing_consent_generation += 1
        elif change == "camera":
            settings.camera_consent_generation += 1
        elif change == "room":
            settings.room_station_consent_generation += 1
        elif change == "revision":
            conversation._private_memory_generation["pet"] += 1
        elif change == "other_revision":
            conversation._private_memory_generation["other"] = 2
        elif change == "conversation":
            app.state.runtime.conversation = SimpleNamespace(
                _private_memory_generation={"pet": 1},
            )

    def recent(robot_id, *, limit, own_only=False):
        reads.append((robot_id, limit, own_only))
        mutate("records")
        return [own, peer]

    def search(robot_id, text, *, limit, own_only=False):
        assert text == query
        return recent(robot_id, limit=limit, own_only=own_only)

    def core_facts(robot_id, *, limit):
        assert (robot_id, limit) == ("pet", 8)
        mutate("core")
        return [SimpleNamespace(slot="favorite_color", value="blue")]

    def current(_owner, _robot_id, message):
        if change == "turn":
            raise HTTPException(409, message)

    timeline = [
        {"channel": "camera"}, {"channel": "room_station"},
        {"channel": "tool", "kind": "memory_recall"}, {"channel": "sensor"},
    ]
    hub = SimpleNamespace(
        recent_events=lambda *_: [{"kind": "touch"}],
        recent_tool_context=lambda *_: [{"kind": "memory_recall"}, {"kind": "visual_look"}],
        interaction_timeline=lambda *_, **__: timeline,
    )
    app.state.runtime = SimpleNamespace(
        conversation=conversation, multimodal=SimpleNamespace(hub=hub),
        memory=SimpleNamespace(recent=recent, search=search, core_facts=core_facts),
    )
    register_voice_context_route(
        app, settings, authorize=lambda: None,
        requested_tool_context=lambda *_: "turn", remember_tool_context=lambda *a: receipts.append(a),
        current_tool_context=current,
    )
    with TestClient(app) as client:
        response = client.get(
            "/v1/pet/pet/voice-context", params={} if query is None else {"query": query},
            headers={"x-desk-robot-tool-receipt": "1"},
        )
    assert reads == [("pet", 6, True)]
    failures = {
        "memory": (403, "Voice memory consent revoked during read"),
        "sharing": (403, "Fleet sharing consent revoked during memory read"),
        "revision": (409, "Private memory changed during retrieval"),
        "conversation": (409, "Private memory changed during retrieval"),
        "turn": (409, "Voice tool turn superseded during memory retrieval"),
    }
    if change in failures:
        status, detail = failures[change]
        assert response.status_code == status
        assert response.json() == {"detail": detail}
        assert receipts == []
        return
    assert response.status_code == 200
    data = response.json()
    assert [entry["event_id"] for entry in data["memories"]] == ["own"]
    assert data["private_memory_generation"] == 1
    assert data["selected_core_fact"] == (
        {"slot": "favorite_color", "value": "blue"} if query else None
    )
    assert data["no_new_motion_permission"] is True
    assert data["current_interaction_timeline"] == (
        [] if change == "camera" else [
            item for item in timeline
            if item.get("kind") != "memory_recall"
            and not (change == "room" and item["channel"] == "room_station")
        ]
    )
    assert data["recent_tool_interpretations"] == (
        [] if change == "camera" else [{"kind": "visual_look"}]
    )
    assert receipts == [("turn", "pet", "memory_recall", (
        "operator curated fact: favorite_color: blue" if query
        else "My camera model suggested: silver key"
    ))]
