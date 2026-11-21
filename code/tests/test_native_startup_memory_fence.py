"""Native startup must reject private memories invalidated during SQLite reads."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from desk_robot.api_native_omni_routes import register_native_omni_routes
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute


@pytest.mark.parametrize(
    "changed_pet", ["self_delete", "self_edit", "other_pet", "bool_alias"]
)
async def test_paused_native_startup_read_is_revision_fenced(settings, changed_pet):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    robot, peer = settings.robots[0].id, settings.robots[1].id
    generations = {robot: 1 if changed_pet == "bool_alias" else 3, peer: 8}
    entered, release = threading.Event(), threading.Event()

    class Memory:
        def core_facts(self, robot_id, *, limit):
            assert robot_id == robot and limit == 6
            entered.set()
            assert release.wait(1.5)
            return []

        def recent(self, robot_id, *, limit):
            assert robot_id == robot and limit == 6
            return []

    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=Memory(),
        conversation=SimpleNamespace(_private_memory_generation=generations),
    )
    register_native_omni_routes(
        app, settings, authorize=lambda: None,
        coordinator=lambda: SimpleNamespace(robot=settings.robot),
        native_pet_speech_policy=lambda _: {},
    )
    endpoint = next(
        route.endpoint for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/v1/pet/{robot_id}/omni-context"
    )
    task = asyncio.create_task(endpoint(robot))
    try:
        assert await asyncio.to_thread(entered.wait, 1.0)
        if changed_pet == "bool_alias":
            generations[robot] = True
        else:
            generations[peer if changed_pet == "other_pet" else robot] += 1
    finally:
        release.set()
    if changed_pet == "other_pet":
        result = await task
        assert result["untrusted_historical_evidence"] == {
            "core": "", "recent": "",
        }
        assert result["private_memory_generation"] == generations[robot]
    else:
        with pytest.raises(HTTPException) as exc:
            await task
        assert exc.value.status_code == 409
        assert "Private memory changed" in exc.value.detail


async def test_missing_native_memory_generation_owner_fails_closed(settings):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True

    class Memory:
        def core_facts(self, *args, **kwargs):
            raise AssertionError("Missing revision owner must prevent reads")

        def recent(self, *args, **kwargs):
            raise AssertionError("Missing revision owner must prevent reads")

    app = FastAPI()
    app.state.runtime = SimpleNamespace(memory=Memory())
    register_native_omni_routes(
        app, settings, authorize=lambda: None,
        coordinator=lambda: SimpleNamespace(robot=settings.robot),
        native_pet_speech_policy=lambda _: {},
    )
    endpoint = next(
        route.endpoint for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/v1/pet/{robot_id}/omni-context"
    )
    with pytest.raises(HTTPException) as exc:
        await endpoint(settings.robots[0].id)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("revisions", [
    {},
    {"robot-02": 0},
    {"robot-01": True},
    {"robot-01": -1},
])
async def test_native_startup_requires_exact_pet_integer_revision_owner(
    settings, revisions,
):
    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True

    class NeverRead:
        def core_facts(self, *args, **kwargs):
            raise AssertionError("No private SQLite read without owned revision")

        def recent(self, *args, **kwargs):
            raise AssertionError("No private SQLite read without owned revision")

    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=NeverRead(),
        conversation=SimpleNamespace(_private_memory_generation=revisions),
    )
    register_native_omni_routes(
        app, settings, authorize=lambda: None,
        coordinator=lambda: SimpleNamespace(robot=settings.robot),
        native_pet_speech_policy=lambda _: {},
    )
    endpoint = next(
        route.endpoint for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/v1/pet/{robot_id}/omni-context"
    )
    with pytest.raises(HTTPException) as exc:
        await endpoint(settings.robots[0].id)
    assert exc.value.status_code == 409
    assert "revision unavailable" in exc.value.detail
