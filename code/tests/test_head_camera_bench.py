"""Read-only XIAO camera bench contract; mocks never establish physical AEC."""
import asyncio
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sense_camera_bench", ROOT / "scripts/bench_head_camera.py"
)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def test_bench_percentiles_are_bounded_and_do_not_claim_a_latency_with_no_samples():
    assert bench.summarize([])["p95_ms"] is None
    p = bench.summarize([0.01, 0.03, 0.02])
    assert p == {"count": 3, "p50_ms": 20.0,
                 "p95_ms": 30.0, "max_ms": 30.0}


async def test_live_bench_uses_read_only_camera_status_without_audio_or_motors():
    class FakeHead:
        def __init__(self):
            self.calls = []
            self._last_camera = None

        async def snapshot(self):
            self.calls.append("camera")
            await asyncio.sleep(0.004)
            sequence = self.calls.count("camera")
            self._last_camera = (31337, sequence, sequence * 1000)
            return b"\xff\xd8" + b"valid fake jpeg" + b"\xff\xd9"

        async def status(self):
            self.calls.append("status")
            await asyncio.sleep(0.002)
            return {"robot_id": "robot-01"}

    head = FakeHead()
    receipt = await bench.measure(
        head, "robot-01", seconds=0.2, camera_period_s=0.06,
        status_period_s=0.05
    )
    assert head.calls.count("camera") >= 2
    assert head.calls.count("status") >= 2
    assert set(head.calls) == {"camera", "status"}
    assert receipt["camera_latency"]["count"] == head.calls.count("camera")
    assert receipt["status_latency"]["count"] == head.calls.count("status")
    assert receipt["distinct_source_camera_identities"] == head.calls.count("camera")
    assert receipt["camera_error_count"] == 0
    assert receipt["status_error_count"] == 0
    assert receipt["physical_aec_latency_measured"] is False
    assert receipt["speaker_silence_verified"] is False
    assert receipt["charging_verified"] is False
    assert receipt["assembly_ready"] is False


async def test_bench_records_stale_jpeg_and_wrong_head_identity_as_failures():
    class BadHead:
        _last_camera = (1, 1, 1)

        async def snapshot(self):
            return b"non-jpeg"

        async def status(self):
            return {"robot_id": "robot-02"}  # another physical pet

    result = await bench.measure(
        BadHead(), "robot-01", seconds=0.12,
        camera_period_s=0.05, status_period_s=0.05,
    )
    assert result["camera_error_count"] > 0
    assert result["status_error_count"] > 0
    assert result["camera_latency"]["count"] == 0
    assert result["status_latency"]["count"] == 0
    assert result["sensor_exposure_clock_synchronized"] is False
