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


@pytest.mark.parametrize("previously_stored", [False, True])
@pytest.mark.parametrize("regrant", [False, True])
def test_parent_memory_revocation_cleans_native_transcript_write(
    settings, tmp_path, previously_stored, regrant,
):
    """Parent memory consent is required throughout a SQLite ASR write."""
    settings.mode = "hardware"
    settings.voice_memory_tools_enabled = True
    settings.voice_transcript_memory_enabled = True
    robot_id = settings.robots[0].id
    store = MemoryStore(tmp_path / "private", [r.id for r in settings.robots])
    event_id = "omni_" + "a" * 12 + "_" + "c" * 20
    original = store.remember
    if previously_stored:
        assert original(
            robot_id, event_id, "Previously retained before memory opt out",
            kind="heard_human", source_robot=robot_id, witnessed=True,
            confidence=0.6,
        )
    count_before = store.count(robot_id)
    original_generation = settings.voice_memory_consent_generation

    def parent_revoke_while_writing(*args, **kwargs):
        result = original(*args, **kwargs)
        settings.voice_memory_tools_enabled = False
        if regrant:
            settings.voice_memory_tools_enabled = True
        return result

    store.remember = parent_revoke_while_writing
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=store, multimodal=None, attention=None,
    )
    register_native_omni_routes(
        app, settings, authorize=lambda: None,
        coordinator=lambda: SimpleNamespace(robot=settings.robot),
        native_pet_speech_policy=lambda _robot_id: {},
    )
    with TestClient(app) as client:
        response = client.post(
            f"/v1/pet/{robot_id}/omni-heard",
            json={
                "event_id": event_id,
                "transcript": "A sentence before parent memory opt out",
            },
        )
    assert response.status_code == 403
    assert settings.voice_transcript_memory_enabled is True
    assert settings.voice_memory_tools_enabled is regrant
    assert settings.voice_memory_consent_generation > original_generation
    assert store.count(robot_id) == count_before
    episode = store.get_episode(robot_id, event_id)
    if previously_stored:
        assert episode is not None
        assert episode.summary == "Previously retained before memory opt out"
    else:
        assert episode is None


@pytest.mark.parametrize("live_context_enabled", [False, True])
def test_parent_memory_disabled_never_retains_native_transcript(
    settings, tmp_path, live_context_enabled,
):
    """Transcript flag alone must not grant private storage at runtime."""
    from desk_robot.multimodal import CameraFrameHub

    settings.mode = "hardware"
    settings.voice_memory_tools_enabled = False
    settings.voice_transcript_memory_enabled = True
    settings.voice_vision_tools_enabled = live_context_enabled
    robot_id = settings.robots[0].id
    store = MemoryStore(tmp_path / "private", [r.id for r in settings.robots])
    hub = CameraFrameHub([r.id for r in settings.robots])
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=store, multimodal=SimpleNamespace(hub=hub), attention=None,
    )
    register_native_omni_routes(
        app, settings, authorize=lambda: None,
        coordinator=lambda: SimpleNamespace(robot=settings.robot),
        native_pet_speech_policy=lambda _robot_id: {},
    )
    with TestClient(app) as client:
        response = client.post(
            f"/v1/pet/{robot_id}/omni-heard",
            json={
                "event_id": "omni_" + "d" * 12 + "_" + "e" * 20,
                "transcript": "A sentence without durable memory permission",
            },
        )
    assert response.status_code == (200 if live_context_enabled else 403)
    if live_context_enabled:
        assert response.json()["stored"] is False
        assert response.json()["retained_on_disk"] is False
        assert response.json()["ephemeral_context_added"] is True
    assert store.count(robot_id) == 0
