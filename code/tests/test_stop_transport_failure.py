"""Regression for urgent STOP transport failure with uncooperative jobs."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from desk_robot.controller import Coordinator, Job
from desk_robot.simulator import SimulationVision


def _coordinator(head):
    robot = SimpleNamespace(id="robot-01", motion_enabled=True)
    settings = SimpleNamespace(
        robots=[robot], robot=lambda robot_id: robot,
        mode="simulation", max_job_seconds=10,
    )
    coordinator = Coordinator(settings, {"robot-01": head}, SimulationVision())
    coordinator.permits = {"robot-01": 123.0}
    return coordinator


class StopTransportFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_recovery_keeps_failed_idle_stop_latched(self):
        from desk_robot.operations import OperationError

        coordinator = _coordinator(object())
        with patch(
            "desk_robot.controller._bounded_body_stop",
            side_effect=RuntimeError("USB STOP failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "USB STOP failed"):
                await coordinator.stop("robot-01")

        # No active roaming remains, but a successful audio retry cannot
        # establish the missing body receipt or reopen the acoustic floor.
        for _ in range(2):
            with self.assertRaisesRegex(OperationError, "WROOM STOP unconfirmed"):
                await coordinator.stop_active_exploration()

        with patch(
            "desk_robot.controller._bounded_body_stop",
            return_value={"ok": True, "reply": "OK halt", "robot_id": "robot-01"},
        ):
            await coordinator.stop("robot-01")
        self.assertEqual(await coordinator.stop_active_exploration(), ())


    async def test_terminal_stop_halts_body_but_short_pulse_preserves_arm(self):
        from desk_robot.controller import _bounded_pulse_stop
        from desk_robot.simulator import SimulatedHead
        from desk_robot.transport import HeadError

        head = SimulatedHead("robot-01")
        await head.command("arm")
        self.assertTrue(head.armed)
        pulse = await _bounded_pulse_stop(head, "robot-01")
        self.assertEqual(pulse["reply"], "OK stop")
        self.assertTrue(head.armed)  # one authorized job can drive again
        await head.command("drive 20 20 100")

        coordinator = _coordinator(head)

        receipt = await coordinator.stop("robot-01")
        self.assertEqual(receipt["reply"], "OK halt")
        self.assertEqual(head.commands[-1], "halt")
        self.assertFalse(head.armed)
        self.assertNotIn("robot-01", coordinator.permits)
        with self.assertRaisesRegex(HeadError, "Body disarmed"):
            await head.command("drive 20 20 100")


    async def test_new_stop_preserves_historical_cancellation_reason(self):
        from desk_robot.simulator import SimulatedHead

        coordinator = _coordinator(SimulatedHead("robot-01"))
        historical = asyncio.create_task(asyncio.sleep(10))
        historical.cancel()
        await asyncio.gather(historical, return_exceptions=True)
        old_job = Job(
            "old", "robot-01", "pickup", state="cancelled",
            error="Operator cancelled",
        )
        current = asyncio.create_task(asyncio.sleep(10))
        new_job = Job("new", "robot-01", "pickup")
        coordinator.jobs = {"old": old_job, "new": new_job}
        coordinator.tasks = {"old": historical, "new": current}
        try:
            receipt = await coordinator.stop("robot-01")
            self.assertEqual(receipt["reply"], "OK halt")
            self.assertEqual(old_job.state, "cancelled")
            self.assertEqual(old_job.error, "Operator cancelled")
            self.assertTrue(current.cancelled())
            self.assertEqual(new_job.state, "cancelled")
            self.assertEqual(new_job.error, "Operator cancelled before job started")
        finally:
            current.cancel()
            await asyncio.gather(current, return_exceptions=True)

    async def test_failed_stop_receipt_survives_cancelled_job_timeout(self):
        release = asyncio.Event()
        started = asyncio.Event()

        async def uncooperative_job():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()

        task = asyncio.create_task(uncooperative_job())
        await started.wait()
        coordinator = _coordinator(object())
        coordinator.jobs = {"job-01": Job("job-01", "robot-01", "pickup", state="running")}
        coordinator.tasks = {"job-01": task}
        try:
            with patch("desk_robot.controller._bounded_body_stop", side_effect=RuntimeError("USB STOP failed")):
                with self.assertRaisesRegex(RuntimeError, "USB STOP failed"):
                    await coordinator.stop("robot-01")
            self.assertEqual(coordinator.jobs["job-01"].state, "failed")
            self.assertEqual(
                coordinator.jobs["job-01"].error,
                "WROOM physical STOP unconfirmed; rely on local watchdog",
            )
            self.assertNotIn("robot-01", coordinator.permits)
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=1)

    async def test_cooperative_job_cancellation_preserves_failed_physical_stop(self):
        started = asyncio.Event()

        class FakeHead:
            async def command(self, command):
                return {"ok": True}

        coordinator = _coordinator(FakeHead())
        coordinator.jobs = {"job-01": Job("job-01", "robot-01", "pickup")}

        async def work(job):
            started.set()
            await asyncio.Event().wait()

        async def stop_receipt(head, robot_id):
            # Operator STOP fails; the separate _run finally STOP succeeds.
            stop_receipt.calls += 1
            if stop_receipt.calls == 1:
                raise RuntimeError("USB STOP failed")
            return {"ok": True}

        stop_receipt.calls = 0
        task = asyncio.create_task(coordinator._run(coordinator.jobs["job-01"], work))
        coordinator.tasks = {"job-01": task}
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            with patch("desk_robot.controller._bounded_body_stop", side_effect=stop_receipt):
                with self.assertRaisesRegex(RuntimeError, "USB STOP failed"):
                    await coordinator.stop("robot-01")
                await asyncio.wait_for(task, timeout=1)
            job = coordinator.jobs["job-01"]
            self.assertEqual(job.state, "failed")
            self.assertEqual(job.error, "WROOM physical STOP unconfirmed; rely on local watchdog")
            self.assertEqual(stop_receipt.calls, 2)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_cancelled_task_cannot_erase_failed_stop_receipt(self):
        started = asyncio.Event()

        async def cancellable_job():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(cancellable_job())
        await started.wait()
        coordinator = _coordinator(object())
        coordinator.jobs = {"job-01": Job("job-01", "robot-01", "pickup", state="running")}
        coordinator.tasks = {"job-01": task}

        async def failed_receipt(head, robot_id):
            # Allow cooperative cancellation to finish before STOP fails.
            await asyncio.sleep(0)
            raise RuntimeError("USB STOP failed")

        with patch("desk_robot.controller._bounded_body_stop", side_effect=failed_receipt):
            with self.assertRaisesRegex(RuntimeError, "USB STOP failed"):
                await coordinator.stop("robot-01")
        self.assertTrue(task.cancelled())
        self.assertEqual(coordinator.jobs["job-01"].state, "failed")
        self.assertEqual(
            coordinator.jobs["job-01"].error,
            "WROOM physical STOP unconfirmed; rely on local watchdog",
        )



    async def test_urgent_halt_bypasses_stalled_status_request(self):
        """Terminal STOP bypasses both pending reads and retires queued drive."""
        import httpx
        from desk_robot.transport import HeadError, HttpHead

        entered = asyncio.Event()
        camera_entered = asyncio.Event()
        release = asyncio.Event()
        halt_sent = asyncio.Event()
        jpeg = b"\xff\xd8\xff\xd9"  # Synthetic transport envelope, not a decoded frame.

        async def handler(request):
            self.assertEqual(
                request.headers["Authorization"], "Bearer fixture-token"
            )
            if request.method == "GET" and request.url.path == "/api/status":
                entered.set()
                await release.wait()
                return httpx.Response(200, json={"robot_id": "robot-01"})
            if request.method == "GET" and request.url.path == "/api/camera.jpg":
                camera_entered.set()
                await release.wait()
                return httpx.Response(200, content=jpeg)
            if request.method == "POST" and request.url.path == "/api/command":
                self.assertEqual(json.loads(request.content), {"command": "halt"})
                halt_sent.set()
                return httpx.Response(
                    200, json={"ok": True, "robot_id": "robot-01", "reply": "OK halt"}
                )
            raise AssertionError(f"Unexpected request {request.method} {request.url}")

        config = SimpleNamespace(
            id="robot-01", head_url="http://robot.invalid", token_env="HEAD_TOKEN"
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            head = HttpHead(config, client)
            coordinator = _coordinator(head)
            with patch("desk_robot.transport.secret", return_value="fixture-token"):
                stalled_get = asyncio.create_task(head.status())
                stalled_camera = asyncio.create_task(head.snapshot())
                queued_drive = None
                try:
                    await asyncio.wait_for(entered.wait(), timeout=1.0)
                    await asyncio.wait_for(camera_entered.wait(), timeout=1.0)
                    self.assertTrue(head.lock.locked())
                    self.assertTrue(head.capture_lock.locked())
                    queued_drive = asyncio.create_task(head.command("drive 20 20 100"))
                    await asyncio.sleep(0)
                    self.assertFalse(queued_drive.done())
                    receipt = await asyncio.wait_for(
                        coordinator.stop("robot-01"), timeout=0.5
                    )
                    self.assertTrue(halt_sent.is_set())
                    self.assertEqual(receipt["reply"], "OK halt")
                    self.assertNotIn("robot-01", coordinator.permits)
                    self.assertEqual(coordinator._permit_epoch["robot-01"], 1)
                    self.assertFalse(stalled_get.done())
                    self.assertFalse(stalled_camera.done())
                    release.set()
                    await asyncio.wait_for(stalled_get, timeout=1.0)
                    self.assertEqual(
                        await asyncio.wait_for(stalled_camera, timeout=1.0), jpeg
                    )
                    with self.assertRaisesRegex(HeadError, "superseded"):
                        await asyncio.wait_for(queued_drive, timeout=1.0)
                finally:
                    release.set()
                    await asyncio.gather(
                        *(task for task in (stalled_get, stalled_camera, queued_drive)
                          if task is not None),
                        return_exceptions=True,
                    )


    async def test_halt_fences_queued_commands_without_overtaking_arm_post(self):
        """HALT may beat GET, never overtake a prior physical command POST."""
        import httpx
        from desk_robot.transport import HeadError, HttpHead

        first_post = asyncio.Event()
        release_first = asyncio.Event()
        sent = []

        async def handler(request):
            command = json.loads(request.content)["command"]
            sent.append(command)
            if command == "arm":
                first_post.set()
                await release_first.wait()
            return httpx.Response(
                200, json={
                    "ok": True, "robot_id": "robot-01", "reply": f"OK {command}"
                }
            )

        config = SimpleNamespace(
            id="robot-01", head_url="http://robot.invalid", token_env="HEAD_TOKEN"
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            head = HttpHead(config, client)
            with patch("desk_robot.transport.secret", return_value="fixture-token"):
                first = asyncio.create_task(head.command("arm"))
                queued = None
                halted = None
                try:
                    await asyncio.wait_for(first_post.wait(), timeout=1.0)
                    queued = asyncio.create_task(head.command("arm"))
                    await asyncio.sleep(0)
                    halted = asyncio.create_task(head.command("halt"))
                    await asyncio.sleep(0)
                    self.assertEqual(sent, ["arm"])
                    release_first.set()
                    with self.assertRaisesRegex(HeadError, "superseded"):
                        await asyncio.wait_for(first, timeout=1.0)
                    with self.assertRaisesRegex(HeadError, "superseded"):
                        await asyncio.wait_for(queued, timeout=1.0)
                    acknowledgement = await asyncio.wait_for(halted, timeout=1.0)
                    self.assertEqual(acknowledgement["reply"], "OK halt")
                    self.assertEqual(sent, ["arm", "halt"])
                finally:
                    release_first.set()
                    await asyncio.gather(
                        *(task for task in (first, queued, halted) if task is not None),
                        return_exceptions=True,
                    )


    async def _assert_uncertain_write_fences_control(self, *, cancel):
        import httpx
        from desk_robot.transport import HeadError, HttpHead

        entered = asyncio.Event()
        release = asyncio.Event()
        sent = []
        fail_halt = True

        async def handler(request):
            nonlocal fail_halt
            command = json.loads(request.content)["command"]
            sent.append(command)
            if command == "drive 20 20 100":
                entered.set()
                await release.wait()
                raise httpx.ReadError("lost body receipt")
            if command == "halt" and fail_halt:
                fail_halt = False
                raise httpx.ReadError("lost HALT receipt")
            return httpx.Response(
                200, json={"ok": True, "robot_id": "robot-01",
                           "reply": f"OK {command}"},
            )

        config = SimpleNamespace(
            id="robot-01", head_url="http://robot.invalid", token_env="HEAD_TOKEN"
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            head = HttpHead(config, client)
            with patch("desk_robot.transport.secret", return_value="fixture-token"):
                first = asyncio.create_task(head.command("drive 20 20 100"))
                queued = None
                try:
                    await asyncio.wait_for(entered.wait(), timeout=1)
                    queued = asyncio.create_task(head.command("keepalive"))
                    await asyncio.sleep(0)
                    if cancel:
                        first.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await first
                    else:
                        release.set()
                        with self.assertRaisesRegex(HeadError, "no retry"):
                            await asyncio.wait_for(first, timeout=1)
                    with self.assertRaisesRegex(HeadError, "superseded"):
                        await asyncio.wait_for(queued, timeout=1)
                    self.assertFalse(head.lock.locked())
                    self.assertFalse(head.command_lock.locked())
                    self.assertEqual(sent, ["drive 20 20 100"])
                    for command in ("arm", "keepalive", "drive 20 20 100"):
                        with self.assertRaisesRegex(HeadError, "require acknowledged HALT"):
                            await head.command(command)
                    with self.assertRaisesRegex(HeadError, "no retry"):
                        await head.command("halt")
                    with self.assertRaisesRegex(HeadError, "require acknowledged HALT"):
                        await head.command("arm")
                    self.assertEqual(sent, ["drive 20 20 100", "halt"])
                    self.assertEqual((await head.command("halt"))["reply"], "OK halt")
                    # A NEW explicit arm is possible after recovery; no old
                    # command or prior lease is silently resumed.
                    self.assertEqual((await head.command("arm"))["reply"], "OK arm")
                    self.assertEqual(sent, ["drive 20 20 100", "halt", "halt", "arm"])
                finally:
                    release.set()
                    await asyncio.gather(
                        *(task for task in (first, queued) if task is not None),
                        return_exceptions=True,
                    )

    async def test_failed_write_fences_queued_and_new_control(self):
        await self._assert_uncertain_write_fences_control(cancel=False)

    async def test_cancelled_write_fences_queued_and_new_control(self):
        await self._assert_uncertain_write_fences_control(cancel=True)

    async def test_cancelled_pending_halt_does_not_restore_control(self):
        import httpx
        from desk_robot.transport import HeadError, HttpHead

        entered = asyncio.Event()
        release = asyncio.Event()
        sent = []

        async def handler(request):
            command = json.loads(request.content)["command"]
            sent.append(command)
            if command == "arm":
                entered.set()
                await release.wait()
            return httpx.Response(
                200, json={"ok": True, "robot_id": "robot-01",
                           "reply": f"OK {command}"},
            )

        config = SimpleNamespace(
            id="robot-01", head_url="http://robot.invalid", token_env="HEAD_TOKEN"
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            head = HttpHead(config, client)
            with patch("desk_robot.transport.secret", return_value="fixture-token"):
                first = asyncio.create_task(head.command("arm"))
                halted = None
                try:
                    await asyncio.wait_for(entered.wait(), timeout=1)
                    halted = asyncio.create_task(head.command("halt"))
                    await asyncio.sleep(0)
                    with self.assertRaisesRegex(HeadError, "require acknowledged HALT"):
                        await head.command("keepalive")
                    halted.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await halted
                    release.set()
                    with self.assertRaisesRegex(HeadError, "superseded"):
                        await asyncio.wait_for(first, timeout=1)
                    with self.assertRaisesRegex(HeadError, "require acknowledged HALT"):
                        await head.command("keepalive")
                    self.assertEqual(sent, ["arm"])
                    self.assertEqual((await head.command("halt"))["reply"], "OK halt")
                    self.assertEqual(sent, ["arm", "halt"])
                finally:
                    release.set()
                    await asyncio.gather(
                        *(task for task in (first, halted) if task is not None),
                        return_exceptions=True,
                    )


    async def test_uart_status_disconnect_fences_queued_control_until_halt(self):
        import httpx
        from desk_robot.transport import HeadError, HttpHead

        entered = asyncio.Event()
        release = asyncio.Event()
        online = False
        sent = []

        async def handler(request):
            if request.method == "GET":
                if not online:
                    entered.set()
                    await release.wait()
                    return httpx.Response(504, json={"ok": False})
                return httpx.Response(200, json={"robot_id": "robot-01"})
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
                await head.command("arm")
                status = asyncio.create_task(head.status())
                queued = None
                try:
                    await asyncio.wait_for(entered.wait(), timeout=1)
                    queued = asyncio.create_task(head.command("keepalive"))
                    await asyncio.sleep(0)
                    release.set()
                    with self.assertRaises(HeadError):
                        await asyncio.wait_for(status, timeout=1)
                    with self.assertRaisesRegex(HeadError, "superseded"):
                        await asyncio.wait_for(queued, timeout=1)
                    online = True
                    await head.status()
                    with self.assertRaisesRegex(HeadError, "require acknowledged HALT"):
                        await head.command("arm")
                    await head.command("halt")
                    await head.command("arm")
                    self.assertEqual(sent, ["arm", "halt", "arm"])
                finally:
                    release.set()
                    await asyncio.gather(
                        *(task for task in (status, queued) if task is not None),
                        return_exceptions=True,
                    )


if __name__ == "__main__":
    unittest.main()
