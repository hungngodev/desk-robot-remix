"""Direct owner cancellation must never admit a second native detector."""
import asyncio
import sys
import time

import pytest

from desk_robot.dock_process import DetectorPool, DockDetectorBusy
from desk_robot.dock_vision import DockCameraCalibration


@pytest.mark.asyncio
async def test_cancelled_native_retirement_fences_warm_spare(monkeypatch):
    worker = 'import sys, time; print("ready", flush=True); sys.stdin.readline(); time.sleep(60)'
    pool = DetectorPool((sys.executable, "-u", "-c", worker))
    camera = DockCameraCalibration(410, 410, 320, 240, 60, 12)
    await pool.prewarm()
    child = pool._ready[0]
    entered = asyncio.Event()
    real_kill = pool._kill
    real_communicate = child.communicate

    async def blocked_communicate():
        entered.set()
        await asyncio.Event().wait()

    # Inject an unconfirmed OS retirement; the worker remains alive until cleanup.
    monkeypatch.setattr(pool, "_kill", lambda process: None)
    monkeypatch.setattr(child, "communicate", blocked_communicate)
    observer = asyncio.create_task(pool.detect(b"hang", camera, captured_at=time.monotonic()))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        owner = pool._active
        assert owner is not None and pool._active_retiring
        # Event-loop shutdown may cancel the actual owner, not merely its awaiter.
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        assert child in pool._owned and child.returncode is None
        assert pool._faulted
        with pytest.raises(DockDetectorBusy, match="busy, closing or retirement unconfirmed"):
            await pool.detect(b"fresh", camera, captured_at=time.monotonic())
        assert pool._sequence == 1
    finally:
        monkeypatch.setattr(pool, "_kill", real_kill)
        monkeypatch.setattr(child, "communicate", real_communicate)
        await pool.close()
    assert not pool._owned
    assert child.returncode is not None
