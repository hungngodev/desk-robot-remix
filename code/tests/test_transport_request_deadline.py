"""Regression for a finite HTTP command response with no end of body."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from desk_robot.transport import HeadError, HttpHead


@pytest.mark.asyncio
async def test_trickling_command_has_total_deadline_and_is_not_replayed():
    sent = []
    closed = asyncio.Event()

    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.005)
                yield b" "

        async def aclose(self):
            closed.set()

    async def handler(request):
        command = json.loads(request.content)["command"]
        sent.append(command)
        if command == "arm" and len(sent) == 1:
            return httpx.Response(200, stream=Trickle())
        return httpx.Response(200, json={
            "ok": True, "robot_id": "robot-01", "reply": f"OK {command}",
        })

    config = SimpleNamespace(
        id="robot-01", head_url="http://robot.invalid", token_env="HEAD_TOKEN",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(config, client)
        with (
            patch("desk_robot.transport.secret", return_value="fixture-token"),
            patch("desk_robot.transport._REQUEST_DEADLINE_SECONDS", 0.05, create=True),
        ):
            with pytest.raises(HeadError, match="no retry"):
                await asyncio.wait_for(head.command("arm"), timeout=0.5)
            assert closed.is_set()
            with pytest.raises(HeadError, match="require acknowledged HALT"):
                await head.command("keepalive")
            assert sent == ["arm"]
            assert (await head.command("halt"))["reply"] == "OK halt"
            assert (await head.command("arm"))["reply"] == "OK arm"
            assert sent == ["arm", "halt", "arm"]
