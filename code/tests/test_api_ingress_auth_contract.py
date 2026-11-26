"""Exercise the production ingress with synthetic credentials and no robot runtime."""

import asyncio

import pytest
from desk_robot.api_ingress import APIIngress
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@pytest.mark.parametrize("authorization", [None, b"Bearer invalid-token", b"Basic operator-token"])
def test_rejected_credentials_never_read_body_or_dispatch(method, authorization):
    async def exercise():
        sent = []

        async def downstream(scope, receive, send):
            pytest.fail("Rejected request reached the downstream application")

        async def receive():
            pytest.fail("Rejected request attempted to read its body")

        async def send(message):
            sent.append(message)

        headers = [(b"content-type", b"application/json")]
        if authorization is not None:
            headers.append((b"authorization", authorization))
        ingress = APIIngress(downstream, tokens=lambda: ("operator-token", "tool-token"))
        await ingress(
            {"type": "http", "method": method, "path": "/v1/fixture", "headers": headers},
            receive,
            send,
        )
        assert sent[0]["type"] == "http.response.start"
        assert sent[0]["status"] == 401
        assert (b"www-authenticate", b"Bearer") in sent[0]["headers"]

    asyncio.run(exercise())


@pytest.mark.parametrize("credential", ["operator-token", "tool-token"])
def test_authenticated_validation_preserves_422_and_success(credential):
    app = FastAPI()
    app.add_middleware(APIIngress, tokens=lambda: ("operator-token", "tool-token"))
    calls = []

    @app.post("/v1/fixture")
    async def action(payload: dict[str, int]):
        calls.append(payload)
        return payload

    headers = {"Authorization": f"Bearer {credential}"}
    with TestClient(app) as client:
        assert client.post("/v1/fixture", json={"count": "invalid"}).status_code == 401
        invalid = client.post("/v1/fixture", headers=headers, json={"count": "invalid"})
        assert invalid.status_code == 422
        assert calls == []
        response = client.post("/v1/fixture", headers=headers, json={"count": 1})
        assert response.status_code == 200
        assert response.json() == {"count": 1}
        assert calls == [{"count": 1}]
