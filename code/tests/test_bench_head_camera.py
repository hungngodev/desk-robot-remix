"""Source-only camera/status bench contracts; never physical acoustic evidence."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "desk_robot_camera_bench", ROOT / "scripts/bench_head_camera.py"
)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)

JPEG = b"\xff\xd8" + b"real frame" + b"\xff\xd9"


async def test_camera_bench_keeps_status_independent_and_never_qualifies_hardware():
    class Head:
        def __init__(self):
            self.sequence = 0
            self.status_calls = 0

        async def snapshot(self):
            self.sequence += 1
            self._last_camera = (7, self.sequence, self.sequence * 100)
            return JPEG

        async def status(self):
            self.status_calls += 1
            return {"robot_id": "robot-01"}

    head = Head()
    result = await bench.measure(
        head, "robot-01", seconds=0.21,
        camera_period_s=0.05, status_period_s=0.05,
    )
    assert result["camera_latency"]["count"] >= 2
    assert result["status_latency"]["count"] >= 2
    assert result["distinct_source_camera_identities"] >= 2
    assert result["camera_error_count"] == 0
    assert result["status_error_count"] == 0
    assert result["sensor_exposure_clock_synchronized"] is False
    assert result["physical_aec_latency_measured"] is False
    assert result["charging_verified"] is False
    assert result["assembly_ready"] is False


async def test_hung_jpeg_does_not_prevent_body_status_reading_or_bounded_exit():
    class HungCamera:
        def __init__(self):
            self.reads = 0

        async def snapshot(self):
            await asyncio.Event().wait()

        async def status(self):
            self.reads += 1
            return {"robot_id": "robot-01"}

    head = HungCamera()
    report = await asyncio.wait_for(bench.measure(
        head, "robot-01", seconds=0.23,
        camera_period_s=0.05, status_period_s=0.05,
    ), timeout=1.0)
    assert head.reads >= 2
    assert report["camera_error_count"] >= 1
    assert "TimeoutError" in report["camera_errors"][0]
    assert report["status_error_count"] == 0
    assert report["camera_latency"]["count"] == 0


async def test_replayed_xiao_frame_identity_rejected_by_camera_bench():
    class ReplayedHead:
        _last_camera = (17, 42, 900)

        async def snapshot(self):
            return JPEG

        async def status(self):
            return {"robot_id": "robot-01"}

    report = await bench.measure(
        ReplayedHead(), "robot-01", seconds=0.16,
        camera_period_s=0.05, status_period_s=0.05,
    )
    assert report["camera_latency"]["count"] == 1
    assert report["camera_error_count"] >= 1
    assert "duplicate camera identity" in report["camera_errors"][0]
