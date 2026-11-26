"""Cancelled HTTP status reads cannot restore motion authority."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.transport import BODY_STATUS_PROTOCOL, HeadError, HttpHead


@pytest.mark.asyncio
@pytest.mark.parametrize("late_error", [False, True])
async def test_cancelled_status_discards_late_response_and_fences_queue(monkeypatch, late_error):
    entered = asyncio.Event()
    sent = []
    reads = 0

    async def handler(request):
        nonlocal reads
        if request.method == "GET":
            reads += 1
            if reads == 2:
                entered.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    if late_error:
                        raise OSError("late disconnect") from None
            return httpx.Response(200, json={
                "robot_id": "robot-01", "protocol": BODY_STATUS_PROTOCOL,
            })
        command = json.loads(request.content)["command"]
        sent.append(command)
        return httpx.Response(200, json={
            "ok": True, "robot_id": "robot-01", "reply": f"OK {command}",
        })

    config = SimpleNamespace(
        id="robot-01", head_url="http://robot.invalid", token_env="HEAD_TOKEN",
    )
    monkeypatch.setenv("HEAD_TOKEN", "fixture-token-0123456789abcdef0123456789")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        head = HttpHead(config, client, require_body_protocol=True)
        await head.status()
        await head.command("arm")
        status = asyncio.create_task(head.status())
        queued = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            queued = asyncio.create_task(head.command("keepalive"))
            await asyncio.sleep(0)
            status.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(status, timeout=1)
            with pytest.raises(HeadError, match="superseded"):
                await asyncio.wait_for(queued, timeout=1)
            assert not head.lock.locked()
            assert not head.command_lock.locked()
            assert not head._body_protocol_verified
            assert sent == ["arm"]
            await head.status()
            with pytest.raises(HeadError, match="require acknowledged HALT"):
                await head.command("arm")
            await head.command("halt")
            await head.command("arm")
            assert sent == ["arm", "halt", "arm"]
        finally:
            tasks = [task for task in (status, queued) if task is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
