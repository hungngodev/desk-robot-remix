"""Regression for urgent STOP transport failure with uncooperative jobs."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from desk_robot.controller import Coordinator, Job


class StopTransportFailureTests(unittest.IsolatedAsyncioTestCase):
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
        coordinator = object.__new__(Coordinator)
        coordinator.settings = SimpleNamespace(robot=lambda robot_id: object())
        coordinator.heads = {"robot-01": object()}
        coordinator.jobs = {"job-01": Job("job-01", "robot-01", "pickup", state="running")}
        coordinator.tasks = {"job-01": task}
        coordinator.permits = {"robot-01": 123.0}
        coordinator._permit_epoch = {"robot-01": 0}
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

        coordinator = object.__new__(Coordinator)
        coordinator.settings = SimpleNamespace(robot=lambda robot_id: object(), mode="simulation", max_job_seconds=10)
        coordinator.heads = {"robot-01": FakeHead()}
        coordinator.locks = {"robot-01": asyncio.Lock()}
        coordinator.jobs = {"job-01": Job("job-01", "robot-01", "pickup")}
        coordinator.permits = {"robot-01": 123.0}
        coordinator._permit_epoch = {"robot-01": 0}

        async def work(job):
            started.set()
            await asyncio.Event().wait()

        async def stop_receipt(head):
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


if __name__ == "__main__":
    unittest.main()
