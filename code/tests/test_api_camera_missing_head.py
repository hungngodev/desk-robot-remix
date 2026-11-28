"""Operator raw preview fails closed when the selected head is unavailable.

Synthetic startup/injection fixture; not a physical JPEG timing or camera test.
"""

from types import SimpleNamespace

import pytest
from desk_robot.api import create_app
from fastapi.testclient import TestClient


def test_operator_camera_missing_head_is_explicitly_unavailable(settings, tokens):
    robot_id = settings.robots[0].id
    calls = []

    async def noop():
        pass

    def lookup(selected_id):
        calls.append(("lookup", selected_id))
        return settings.robot(selected_id)

    coordinator = SimpleNamespace(robot=lookup, heads={})
    runtime = SimpleNamespace(coordinator=coordinator, start=noop, close=noop)
    url = f"/v1/robots/{robot_id}/camera.jpg"
    operator = {"Authorization": "Bearer " + tokens["DESK_ROBOT_API_TOKEN"]}
    tool = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}

    with TestClient(create_app(settings, runtime=runtime)) as client:
        assert client.get(url).status_code == 401
        assert client.get(url, headers=tool).status_code == 403
        assert calls == []

        absent = client.get(url, headers=operator)
        assert absent.status_code == 503
        assert "camera unavailable" in absent.json()["detail"].lower()
        assert calls == [("lookup", robot_id)]

        # An older/partial hardware adapter cannot accidentally grant preview.
        coordinator.heads[robot_id] = SimpleNamespace()
        unsupported = client.get(url, headers=operator)
        assert unsupported.status_code == 503
        assert len(calls) == 2

        class Head:
            async def snapshot(self):
                calls.append(("snapshot", robot_id))
                return b"\xff\xd8fixture\xff\xd9"

        coordinator.heads[robot_id] = Head()
        response = client.get(url, headers=operator)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "no-store"
        assert response.content == b"\xff\xd8fixture\xff\xd9"

    assert calls == [
        ("lookup", robot_id), ("lookup", robot_id),
        ("lookup", robot_id), ("snapshot", robot_id),
    ]


async def test_operator_camera_preview_deadline_rejects_late_jpeg(settings, monkeypatch):
    """A snapshot adapter that ignores cancellation cannot send a late JPEG."""
    import asyncio

    import desk_robot.api as api

    robot_id = settings.robots[0].id
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def snapshot():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        finally:
            finished.set()
        return b"late JPEG"

    coordinator = SimpleNamespace(
        robot=settings.robot,
        heads={robot_id: SimpleNamespace(snapshot=snapshot)},
    )
    runtime = SimpleNamespace(coordinator=coordinator)
    app = create_app(settings, runtime=runtime)
    app.state.runtime = runtime
    endpoint = next(
        route.endpoint for route in app.routes
        if getattr(route, "path", None) == "/v1/robots/{robot_id}/camera.jpg"
    )
    monkeypatch.setattr(api, "_CAMERA_PREVIEW_TIMEOUT_S", 0.02)
    task = asyncio.create_task(endpoint(robot_id))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        done, _ = await asyncio.wait({task}, timeout=1)
        assert task in done
        with pytest.raises(TimeoutError, match="Robot camera preview deadline exceeded"):
            task.result()
        await asyncio.wait_for(cancelled.wait(), timeout=1)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.wait_for(finished.wait(), timeout=1)
