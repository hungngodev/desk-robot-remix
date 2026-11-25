"""Exercise motion admission during startup, fatal service exit and shutdown."""

from types import SimpleNamespace

import httpx
from desk_robot.api_lifecycle import require_runtime_ready, runtime_ready
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def test_lifecycle_dependency_fails_closed():
    app = FastAPI()
    calls = []

    @app.post("/motion", dependencies=[Depends(require_runtime_ready)])
    async def motion():
        calls.append("motion")
        return {"ok": True}

    with TestClient(app) as client:
        assert client.post("/motion").status_code == 503
        app.state.runtime_started = True
        assert client.post("/motion").status_code == 503
        app.state.runtime = SimpleNamespace(_closed=False)
        assert runtime_ready(app.state)
        assert client.post("/motion").status_code == 200
        app.state.runtime._fatal_service_error = RuntimeError("service exited")
        assert client.post("/motion").status_code == 503
        app.state.runtime._fatal_service_error = None
        app.state.runtime._closed = True
        assert client.post("/motion").status_code == 503
        app.state.runtime._closed = False
        app.state.runtime_started = False
        assert client.post("/motion").status_code == 503
    assert calls == ["motion"]


def test_motion_routes_reject_requests_during_lifecycle_transitions(settings, tokens):
    from desk_robot.api import create_app

    robot_id = settings.robots[0].id
    prefix = f"/v1/robots/{robot_id}"
    operator = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}
    routes = [
        (prefix + "/enable", operator, None),
        (prefix + "/move", operator, {"command": "drive 1 1 100"}),
        (prefix + "/explore", operator, None),
        (prefix + "/pickup", tool, {"target": "key"}),
        (prefix + "/dock/approach", operator, None),
        (prefix + "/navigate", operator, {"label": "key"}),
        (f"/v1/pet/{robot_id}/start", operator, None),
    ]
    calls = []

    async def arm(_robot_id):
        calls.append("permit")
        return {"operator_permit": True, "physical_armed": False}

    async def stop(_robot_id):
        calls.append("stop")
        return {"stopped": True}

    async def pause(_robot_id):
        return {}

    async def check_transition():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            health = await client.get("/v1/health", headers=operator)
            assert health.status_code == 503
            for path, headers, payload in routes:
                response = await client.post(path, headers=headers, json=payload)
                assert response.status_code == 503, (path, response.text)
            # STOP must not inherit the movement admission dependency.
            response = await client.post(prefix + "/stop", headers=tool)
            assert response.status_code == 200
            assert response.json() == {"stopped": True}

    runtime = SimpleNamespace(
        start=check_transition, close=check_transition, _closed=False,
        coordinator=SimpleNamespace(robot=lambda _: None, operator_arm=arm, stop=stop),
        pet=SimpleNamespace(pause=pause),
    )
    app = create_app(settings, runtime=runtime)
    with TestClient(app) as client:
        assert calls == ["stop"]
        assert client.get("/v1/health", headers=operator).status_code == 200
        assert client.post(prefix + "/enable", headers=operator).json() == {
            "operator_permit": True, "physical_armed": False,
        }
        runtime._fatal_service_error = RuntimeError("service exited")
        for path, headers, payload in routes:
            assert client.post(path, headers=headers, json=payload).status_code == 503
        runtime._fatal_service_error = None
        runtime._closed = True
        for path, headers, payload in routes:
            assert client.post(path, headers=headers, json=payload).status_code == 503
    assert calls == ["stop", "permit", "stop"]
