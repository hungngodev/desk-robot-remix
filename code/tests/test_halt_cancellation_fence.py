"""Terminal HALT recovery must not trust a cancelled transport receipt."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from desk_robot.transport import HeadError, HttpHead


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled_command", ["halt", "drive 20 20 100"])
async def test_cancelled_command_receipt_cannot_reopen_motion(cancelled_command):
    entered = asyncio.Event()
    sent = []
    replies = {
        "halt": "OK halt",
        "arm": "OK arm",
        "drive 20 20 100": "OK drive left=20 right=20 ms=100",
    }

    async def request(method, path, *, json):
        assert (method, path) == ("POST", "/api/command")
        command = json["command"]
        sent.append(command)
        if len(sent) == 1:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass  # An adapter can return an ACK after swallowing cancellation.
        return httpx.Response(200, json={
            "ok": True, "robot_id": "robot-01", "reply": replies[command],
        })

    async with httpx.AsyncClient() as client:
        config = SimpleNamespace(id="robot-01", head_url="http://robot.invalid")
        head = HttpHead(config, client)
        head._request = request
        interrupted = asyncio.create_task(head.command(cancelled_command))
        contender = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            contender = asyncio.create_task(head.command("drive 20 20 100"))
            await asyncio.sleep(0)
            interrupted.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(interrupted, timeout=1)
            with pytest.raises(HeadError, match="superseded|require acknowledged HALT"):
                await asyncio.wait_for(contender, timeout=1)
            for command in ("arm", "keepalive", "drive 20 20 100"):
                with pytest.raises(HeadError, match="require acknowledged HALT"):
                    await head.command(command)
            assert sent == [cancelled_command]
            assert (await head.command("halt"))["reply"] == "OK halt"
            assert (await head.command("arm"))["reply"] == "OK arm"
            await head.command("drive 20 20 100")
            assert sent == [cancelled_command, "halt", "arm", "drive 20 20 100"]
        finally:
            interrupted.cancel()
            if contender is not None:
                contender.cancel()
            await asyncio.gather(
                *(task for task in (interrupted, contender) if task is not None),
                return_exceptions=True,
            )
