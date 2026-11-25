"""Adversarial HTTP ingress tests before FastAPI parsing and route execution."""
import asyncio

import pytest
from desk_robot.api_ingress import APIIngress, MAX_REQUEST_BYTES
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def guarded_app():
    app = FastAPI()
    app.state.calls = []
    app.add_middleware(APIIngress, tokens=lambda: ("operator-secret", "tool-secret"))

    @app.post("/v1/action")
    async def action(payload: dict):
        app.state.calls.append(payload)
        return payload

    @app.post("/v1/stop")
    async def stop():
        return {"stopped": True}

    return app


@pytest.mark.parametrize("token", ["operator-secret", "tool-secret"])
def test_both_roles_and_empty_stop(guarded_app, token):
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(guarded_app) as client:
        assert client.post("/v1/action", headers=headers, json={"ok": True}).status_code == 200
        assert client.post("/v1/stop", headers=headers).json() == {"stopped": True}


def test_auth_precedes_json_and_length_validation(guarded_app):
    with TestClient(guarded_app) as client:
        response = client.post("/v1/action", content=b"{" * (MAX_REQUEST_BYTES + 1))
        assert response.status_code == 401
        assert guarded_app.state.calls == []


def test_reject_oversize_wrong_type_and_duplicate_headers(guarded_app):
    auth = ("Authorization", "Bearer tool-secret")
    with TestClient(guarded_app) as client:
        assert client.post(
            "/v1/action", headers=[auth], content=b"x" * (MAX_REQUEST_BYTES + 1),
        ).status_code == 413
        assert client.post("/v1/action", headers=[auth], content=b"{}").status_code == 415
        assert client.post(
            "/v1/action", headers=[auth, auth], json={},
        ).status_code == 401
        assert client.post(
            "/v1/action", headers=[auth, ("Content-Length", "2"), ("Content-Length", "2")],
            content=b"{}",
        ).status_code == 400
        assert client.post(
            "/v1/action", headers=[auth, ("Content-Encoding", "gzip")], json={},
        ).status_code == 415
        assert guarded_app.state.calls == []


def test_chunked_body_limit_without_content_length(guarded_app):
    async def exercise():
        messages = iter([
            {"type": "http.request", "body": b"x" * MAX_REQUEST_BYTES, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": False},
        ])
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        await guarded_app({
            "type": "http", "method": "POST", "path": "/v1/action",
            "headers": [(b"authorization", b"Bearer tool-secret"),
                        (b"content-type", b"application/json")],
        }, receive, send)
        assert sent[0]["status"] == 413
        assert guarded_app.state.calls == []

    asyncio.run(exercise())
