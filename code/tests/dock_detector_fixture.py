"""Test-only pose injection at the subprocess supervisor boundary."""
import asyncio

from desk_robot import dock_runtime


def mock_dock_detector(monkeypatch, detector):
    """Exercise callers with a fake pose; real process faults have separate tests."""
    async def detect(jpeg, camera, *, captured_at):
        return await asyncio.to_thread(detector, jpeg, camera, captured_at=captured_at)

    monkeypatch.setattr(dock_runtime._DETECTOR_POOL, "detect", detect)
