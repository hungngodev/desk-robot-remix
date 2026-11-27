"""Body deadlines must not cancel an already-started response."""

import asyncio

import pytest
from desk_robot import api_ingress


def test_oversize_response_is_outside_body_deadline(monkeypatch):
    async def exercise():
        sent = []
        # Force deadline expiration at the next suspension, without wall-clock sleeps.
        monkeypatch.setattr(api_ingress, "BODY_TIMEOUT_SECONDS", 0)

        async def downstream(scope, receive, send):
            pytest.fail("Oversized request dispatched")

        async def receive():
            return {"type": "http.request", "body": b"x" * (api_ingress.MAX_REQUEST_BYTES + 1)}

        async def send(message):
            sent.append(message)
            await asyncio.sleep(0)

        ingress = api_ingress.APIIngress(downstream, tokens=lambda: ("operator", "tool"))
        await ingress(
            {"type": "http", "path": "/v1/fixture", "method": "POST",
             "headers": [(b"authorization", b"Bearer tool")]},
            receive, send,
        )
        assert [message["type"] for message in sent] == [
            "http.response.start", "http.response.body",
        ]
        assert sent[0]["status"] == 413
        assert sent[1]["body"] == b'{"detail":"Request body too large"}'

    asyncio.run(exercise())


def test_body_deadline_cancels_receive_without_dispatch(monkeypatch):
    async def exercise():
        sent = []
        cleaned = asyncio.Event()
        monkeypatch.setattr(api_ingress, "BODY_TIMEOUT_SECONDS", 0)

        async def downstream(scope, receive, send):
            pytest.fail("Timed out request dispatched")

        async def receive():
            try:
                await asyncio.Future()
            finally:
                cleaned.set()

        async def send(message):
            sent.append(message)

        ingress = api_ingress.APIIngress(downstream, tokens=lambda: ("operator", "tool"))
        await ingress(
            {"type": "http", "path": "/v1/fixture", "method": "POST",
             "headers": [(b"authorization", b"Bearer tool")]},
            receive, send,
        )
        assert cleaned.is_set()
        assert [message["type"] for message in sent] == [
            "http.response.start", "http.response.body",
        ]
        assert sent[0]["status"] == 408
        assert sent[1]["body"] == b'{"detail":"Request body deadline exceeded"}'

    asyncio.run(exercise())
