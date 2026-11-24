"""Digital coexistence evidence must overlap accepted camera receipts."""
import asyncio
import importlib.util
import time
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "camera_window_bench", Path(__file__).resolve().parents[1] / "scripts/bench_head_camera.py"
)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def _counters(count):
    return {
        key: count if key in ("microphone_frames_read", "speaker_frames_accepted") else 0
        for key in bench.CONCURRENT_AUDIO_COUNTERS
    }


def test_audio_request_window_brackets_reject_disjoint_or_straddling_samples():
    samples = [
        (0.0, 0.5, _counters(0)),
        (0.5, 1.5, _counters(10)),  # begins before first accepted JPEG
        (2.0, 2.5, _counters(10)),
        (3.0, 3.5, _counters(10)),
        (4.5, 5.5, _counters(20)),  # finishes after last accepted JPEG
        (6.0, 6.5, _counters(30)),
    ]
    count, delta = bench._camera_window_audio_delta(samples, 1.0, 5.0)
    assert count == 2
    assert delta == _counters(0)
    assert bench._camera_window_audio_delta(samples, None, 5.0) == (0, None)
    assert bench._camera_window_audio_delta(samples, 1.0, 2.0) == (0, None)
    assert bench._camera_window_audio_delta(samples, 1.0, 3.0) == (1, None)
    samples[3] = (3.0, 3.5, _counters(15))
    assert bench._camera_window_audio_delta(samples, 1.0, 5.0) == (2, _counters(5))


async def test_pre_camera_codec_activity_cannot_pass_combined_bench():
    class Head:
        def __init__(self):
            self._last_camera = None
            self.audio_reads = 0
            self.advanced = asyncio.Event()

        async def audio_reference_status(self):
            self.audio_reads += 1
            if self.audio_reads >= 2:
                self.advanced.set()
            return {
                **_counters(min(self.audio_reads, 2) * 160),
                "robot_id": "robot-01", "boot": 7,
                "microphone_privacy_epoch": 1,
                "microphone_privacy_muted": False,
                "reference_integrity_failed": False,
                "speaker_playback_verified": False,
                "aec_physically_qualified": False,
            }

        async def stream_frames(self):
            await self.advanced.wait()
            await asyncio.sleep(.04)
            for seq in range(40):
                self._last_camera = (7, seq + 1, (seq + 1) * 25_000)
                yield b"\xff\xd8frame\xff\xd9", time.monotonic()
                await asyncio.sleep(.025)

        async def status(self):
            return {"robot_id": "robot-01"}

    report = await bench.measure(Head(), "robot-01", seconds=.6, status_period_s=.05, stream=True)
    assert report["camera_error_count"] == 0
    assert report["concurrent_audio_errors"] == []
    assert report["concurrent_audio_counter_delta"]["speaker_frames_accepted"] > 0
    assert report["camera_window_audio_samples"] >= 2
    assert report["camera_window_audio_counter_delta"] == _counters(0)
    assert not report["concurrent_audio_driver_activity_observed"]
    assert not bench.bench_passed(report, require_audio=True)
