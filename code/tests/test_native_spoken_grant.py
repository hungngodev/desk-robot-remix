"""Native sent text must not reenter a newly granted live context."""

import time
from types import SimpleNamespace

from desk_robot.api_native_omni_routes import register_native_omni_routes
from desk_robot.attention import AttentionLedger
from desk_robot.config import Settings
from desk_robot.multimodal import CameraFrameHub
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _post(client, robot_id, suffix, sent_at_us, text):
    return client.post(
        f"/v1/pet/{robot_id}/omni-spoken",
        json={
            "event_id": "omni_sent_" + "a" * 12 + "_" + suffix * 20,
            "model_text": text,
            "sent_at_us": sent_at_us,
        },
    )


def test_native_spoken_receipt_cannot_cross_live_regrant(settings):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    ids = [r.id for r in settings.robots]
    hub = CameraFrameHub(ids)
    attention = AttentionLedger(ids)
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        multimodal=SimpleNamespace(hub=hub), attention=attention,
    )
    register_native_omni_routes(
        app, settings, authorize=lambda: None,
        coordinator=lambda: SimpleNamespace(robot=settings.robot),
        native_pet_speech_policy=lambda _robot_id: {},
    )
    robot_id, other_robot = ids[:2]

    with TestClient(app) as client:
        first_stamp = time.monotonic_ns() // 1000
        first = _post(client, robot_id, "b", first_stamp, "Current speech")
        assert first.status_code == 200
        assert first.json()["ephemeral_context_added"] is True
        assert first.json()["audio_playback_verified"] is False
        duplicate = _post(client, robot_id, "b", first_stamp, "Current speech")
        assert duplicate.status_code == 200
        assert duplicate.json()["ephemeral_context_added"] is False
        assert len(hub.spoken_history[robot_id]) == 1

        # The model has transmitted, but its HTTP receipt remains queued.
        old_stamp = time.monotonic_ns() // 1000 - 10_000
        original_grant = settings.camera_consent_generation
        settings.voice_vision_tools_enabled = False
        denied = _post(client, robot_id, "c", old_stamp, "Old denied speech")
        assert denied.status_code == 403
        settings.voice_vision_tools_enabled = True
        assert settings.camera_consent_generation == original_grant + 1
        assert old_stamp < int(settings.camera_consent_started_at * 1_000_000)

        stale = _post(client, robot_id, "c", old_stamp, "Old queued speech")
        assert stale.status_code == 403
        assert "predates current live consent" in stale.json()["detail"]
        assert len(hub.spoken_history[robot_id]) == 1
        assert not any("Old queued speech" in event["content"]
                       for event in hub.interaction_timeline(robot_id, time.monotonic()))
        assert not any("Old queued speech" in event["content"]
                       for event in attention.timeline(robot_id, time.monotonic()))

        new_stamp = time.monotonic_ns() // 1000
        fresh = _post(client, robot_id, "d", new_stamp, "Fresh new grant speech")
        assert fresh.status_code == 200
        assert fresh.json()["ephemeral_context_added"] is True
        assert fresh.json()["audio_playback_verified"] is False
        assert len(hub.spoken_history[robot_id]) == 2
        assert attention._state(robot_id).sent == "Fresh new grant speech"

    assert not hub.spoken_history[other_robot]
    assert attention._state(other_robot).sent == ""


def test_boot_enabled_settings_starts_native_receipt_fence(settings):
    data = settings.model_dump()
    data["mode"] = "hardware"
    data["voice_vision_tools_enabled"] = True
    boot_settings = Settings.model_validate(data)
    assert boot_settings.camera_consent_started_at > 0
    assert boot_settings.camera_consent_started_at <= time.monotonic()
