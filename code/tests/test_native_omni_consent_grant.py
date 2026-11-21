"""Native Xiaozhi startup must not reuse revoked private or camera permits."""

from types import SimpleNamespace

import pytest
from desk_robot.api_native_omni_routes import register_native_omni_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize("toggle", ("none", "memory", "camera"))
def test_native_startup_rejects_permission_regrant_during_sqlite_read(
    settings, toggle,
):
    settings.mode = "hardware"
    settings.voice_memory_tools_enabled = True
    settings.voice_vision_tools_enabled = True
    robot_id = settings.robots[0].id
    memory_grant = settings.voice_memory_consent_generation
    camera_grant = settings.camera_consent_generation

    class Memory:
        def core_facts(self, robot, *, limit):
            assert robot == robot_id
            if toggle == "memory":
                settings.voice_memory_tools_enabled = False
                settings.voice_memory_tools_enabled = True
            elif toggle == "camera":
                settings.voice_vision_tools_enabled = False
                settings.voice_vision_tools_enabled = True
            return []

        def recent(self, robot, *, limit):
            assert robot == robot_id
            return []

    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=Memory(),
        conversation=SimpleNamespace(
            _private_memory_generation={robot_id: 0},
        ),
    )
    register_native_omni_routes(
        app, settings,
        authorize=lambda: None,
        coordinator=lambda: SimpleNamespace(
            robot=lambda robot: SimpleNamespace(persona="Quiet companion")
        ),
        native_pet_speech_policy=lambda robot: {},
    )
    with TestClient(app) as client:
        response = client.get(f"/v1/pet/{robot_id}/omni-context")
    if toggle == "none":
        assert response.status_code == 200
        assert response.json()["untrusted_historical_evidence"] == {
            "core": "", "recent": "",
        }
        assert settings.voice_memory_consent_generation == memory_grant
        assert settings.camera_consent_generation == camera_grant
    else:
        assert response.status_code == 403
        assert "historical_evidence" not in response.text
        assert settings.voice_memory_tools_enabled is True
        assert settings.voice_vision_tools_enabled is True
        if toggle == "memory":
            assert settings.voice_memory_consent_generation > memory_grant
        else:
            assert settings.camera_consent_generation > camera_grant
