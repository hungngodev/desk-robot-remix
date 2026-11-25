import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from desk_robot.transport import HeadError, HttpHead


class UrgentHaltBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_halt_bypasses_each_blocked_accessory_poll(self):
        for method, path in (
            ("aux_status", "/api/aux"),
            ("optics_status", "/api/optics"),
            ("ir_status", "/api/ir"),
        ):
            with self.subTest(method=method):
                await self._assert_halt_bypasses_poll(method, path)

    async def _assert_halt_bypasses_poll(self, method, path):
        entered = asyncio.Event()
        sent = []

        async def handler(request):
            if request.method == "GET" and request.url.path == path:
                entered.set()
                await asyncio.Event().wait()
            self.assertEqual(request.url.path, "/api/command")
            command = json.loads(request.content)["command"]
            sent.append(command)
            return httpx.Response(200, json={
                "ok": True, "robot_id": "robot-01", "reply": f"OK {command}",
            })

        config = SimpleNamespace(
            id="robot-01", head_url="http://robot.invalid", token_env="HEAD_TOKEN",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            head = HttpHead(config, client)
            with patch("desk_robot.transport.secret", return_value="fixture-token"):
                poll = asyncio.create_task(getattr(head, method)())
                queued = None
                try:
                    await asyncio.wait_for(entered.wait(), timeout=1)
                    queued = asyncio.create_task(head.command("drive 20 20 100"))
                    await asyncio.sleep(0)
                    self.assertTrue(head.lock.locked())
                    self.assertFalse(queued.done())
                    receipt = await asyncio.wait_for(head.command("halt"), timeout=0.5)
                    self.assertEqual(receipt["reply"], "OK halt")
                    self.assertEqual(sent, ["halt"])
                    self.assertFalse(poll.done())
                    poll.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await poll
                    with self.assertRaisesRegex(HeadError, "superseded"):
                        await asyncio.wait_for(queued, timeout=1)
                    self.assertEqual(sent, ["halt"])
                finally:
                    poll.cancel()
                    if queued is not None:
                        queued.cancel()
                    await asyncio.gather(
                        *(task for task in (poll, queued) if task is not None),
                        return_exceptions=True,
                    )

    async def test_hung_actuator_ack_keeps_control_fenced_after_halt_timeout(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        sent = []

        async def handler(request):
            command = json.loads(request.content)["command"]
            sent.append(command)
            if command == "arm" and len(sent) == 1:
                entered.set()
                await release.wait()
            return httpx.Response(200, json={
                "ok": True, "robot_id": "robot-01", "reply": f"OK {command}",
            })

        config = SimpleNamespace(
            id="robot-01", head_url="http://robot.invalid", token_env="HEAD_TOKEN",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            head = HttpHead(config, client)
            with patch("desk_robot.transport.secret", return_value="fixture-token"):
                arm = asyncio.create_task(head.command("arm"))
                try:
                    await asyncio.wait_for(entered.wait(), timeout=1)
                    with self.assertRaises(TimeoutError):
                        await asyncio.wait_for(head.command("halt"), timeout=0.05)
                    self.assertEqual(sent, ["arm"])
                    with self.assertRaisesRegex(HeadError, "require acknowledged HALT"):
                        await head.command("keepalive")
                    release.set()
                    with self.assertRaisesRegex(HeadError, "superseded"):
                        await asyncio.wait_for(arm, timeout=1)
                    with self.assertRaisesRegex(HeadError, "require acknowledged HALT"):
                        await head.command("arm")
                    self.assertEqual((await head.command("halt"))["reply"], "OK halt")
                    self.assertEqual((await head.command("arm"))["reply"], "OK arm")
                    self.assertEqual(sent, ["arm", "halt", "arm"])
                finally:
                    release.set()
                    await asyncio.gather(arm, return_exceptions=True)
