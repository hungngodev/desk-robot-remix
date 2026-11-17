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


if __name__ == "__main__":
    unittest.main()
