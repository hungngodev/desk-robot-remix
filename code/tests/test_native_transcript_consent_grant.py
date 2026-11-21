"""Revoking transcript retention aborts pending SQLite writes despite regrant."""

from types import SimpleNamespace

import pytest
from desk_robot.api_native_omni_routes import register_native_omni_routes
from desk_robot.memory import MemoryStore
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize("previously_stored", [False, True])
def test_regrant_during_native_transcript_write_preserves_only_prior_data(
    settings, tmp_path, previously_stored,
):
    settings.mode = "hardware"
    settings.voice_memory_tools_enabled = True
    settings.voice_transcript_memory_enabled = True
    robot_id = settings.robots[0].id
    store = MemoryStore(tmp_path / "private", [r.id for r in settings.robots])
    event_id = "omni_" + "a" * 12 + "_" + "b" * 20
    original = store.remember
    if previously_stored:
        assert original(
            robot_id, event_id, "A previously accepted transcript",
            kind="heard_human", source_robot=robot_id, witnessed=True,
            confidence=0.6,
        )
    before = store.count(robot_id)
    grant = settings.transcript_consent_generation

    def write_then_revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        settings.voice_transcript_memory_enabled = False
        settings.voice_transcript_memory_enabled = True
        return result

    store.remember = write_then_revoke
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=store, multimodal=None, attention=None,
    )
    register_native_omni_routes(
        app, settings,
        authorize=lambda: None,
        coordinator=lambda: SimpleNamespace(robot=settings.robot),
        native_pet_speech_policy=lambda _robot_id: {},
    )
    with TestClient(app) as client:
        response = client.post(
            f"/v1/pet/{robot_id}/omni-heard",
            json={
                "event_id": event_id,
                "transcript": "A private sentence sent before opt out",
            },
        )
    assert response.status_code == 403
    assert settings.voice_transcript_memory_enabled is True
    assert settings.transcript_consent_generation > grant
    assert store.count(robot_id) == before
    if previously_stored:
        episode = store.get_episode(robot_id, event_id)
        assert episode is not None
        assert episode.summary == "A previously accepted transcript"
    else:
        assert store.get_episode(robot_id, event_id) is None
