"""Read-only XIAO camera bench contract; mocks never establish physical AEC."""
import asyncio
import importlib.util
import time
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


async def test_stream_motion_instrumentation_reports_light_and_cover_without_media():
    import io

    from PIL import Image

    def jpeg(dark, light, *, cover=False):
        image = Image.new("L", (64, 48))
        image.putdata([
            20 if cover else (dark if (i // 64 + i % 64) % 2 else light)
            for i in range(64 * 48)
        ])
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=95)
        return out.getvalue()

    class PhotometricHead:
        def __init__(self):
            self._last_camera = None
            self.commands = []

        async def stream_frames(self):
            began = time.monotonic()
            for index, frame in enumerate((
                jpeg(40, 110), jpeg(80, 220), jpeg(0, 0, cover=True),
            )):
                self._last_camera = (19, index + 1, (index + 1) * 1_000_000)
                yield frame, began - 2 + index
                await asyncio.sleep(0)
            await asyncio.sleep(.22)

        async def status(self):
            return {"robot_id": "robot-01"}

        async def snapshot(self):
            raise AssertionError("No snapshot during continuous stream")

        async def command(self, *args, **kwargs):
            self.commands.append(args)
            raise AssertionError("Bench cannot command body")

    head = PhotometricHead()
    result = await bench.measure(
        head, "robot-01", seconds=.2, status_period_s=.05,
        stream=True, score_motion=True,
    )
    assert result["camera_error_count"] == 0
    assert result["motion_score_instrumented"] is True
    assert result["motion_sample_pair_count"] == 2
    assert result["motion_changed_fraction_max"] > .9
    assert result["motion_changed_fraction_p95"] > .9
    assert result["physical_motion_qualified"] is False
    assert result["sensor_exposure_clock_synchronized"] is False
    assert head.commands == []


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


async def test_live_stream_bench_rejects_gap_even_when_new_jpeg_arrives(monkeypatch):
    """A recovered camera feed is not a continuously healthy one."""
    monkeypatch.setattr(bench, "MAX_CAMERA_GAP_S", 0.05)

    class InterruptedHead:
        _last_camera = None

        async def stream_frames(self):
            self._last_camera = (99, 1, 100)
            yield b"\xff\xd8first\xff\xd9", time.monotonic()
            await asyncio.sleep(0.08)
            self._last_camera = (99, 2, 200)
            yield b"\xff\xd8second\xff\xd9", time.monotonic()

        async def status(self):
            return {"robot_id": "robot-01"}

    result = await bench.measure(
        InterruptedHead(), "robot-01", seconds=0.14,
        status_period_s=0.05, stream=True,
    )
    assert result["camera_error_count"] == 1
    assert any("stalled" in error for error in result["camera_errors"])
    assert result["camera_frames_received"] == 1
    assert result["speaker_silence_verified"] is False


async def test_live_stream_bench_rejects_end_without_recent_frame(monkeypatch):
    """Ending near the deadline does not conceal a stale last frame."""
    monkeypatch.setattr(bench, "MAX_CAMERA_GAP_S", 0.05)

    class StaleHead:
        _last_camera = None

        async def stream_frames(self):
            self._last_camera = (101, 1, 100)
            yield b"\xff\xd8first\xff\xd9", time.monotonic()
            await asyncio.sleep(0.09)

        async def status(self):
            return {"robot_id": "robot-01"}

    result = await bench.measure(
        StaleHead(), "robot-01", seconds=0.1,
        status_period_s=0.05, stream=True,
    )
    assert result["camera_error_count"] == 1
    assert any("without recent JPEG" in error for error in result["camera_errors"])
    assert result["camera_frames_received"] == 1


async def test_live_camera_bench_rejects_sense_capture_gap_masked_by_fast_receipt(monkeypatch):
    """Fast Mac receipt alone cannot excuse a stalled physical frame producer."""
    monkeypatch.setattr(bench, "MAX_CAMERA_GAP_S", 0.05)

    class BufferedHead:
        _last_camera = None

        async def stream_frames(self):
            self._last_camera = (91, 1, 1_000_000)
            yield b"\xff\xd8old\xff\xd9", time.monotonic()
            await asyncio.sleep(0.01)
            self._last_camera = (91, 2, 1_300_000)
            yield b"\xff\xd8new\xff\xd9", time.monotonic()

        async def status(self):
            return {"robot_id": "robot-01"}

    result = await bench.measure(
        BufferedHead(), "robot-01", seconds=0.15,
        status_period_s=0.05, stream=True,
    )
    assert result["camera_frames_received"] == 1
    assert result["camera_error_count"] == 1
    assert any("capture stalled" in error for error in result["camera_errors"])
    assert result["sense_capture_completion_interarrival"]["count"] == 1
    assert result["sensor_exposure_clock_synchronized"] is False


async def test_live_camera_bench_rejects_reboot_even_if_receipts_look_fresh(monkeypatch):
    """A brownout/new camera boot during a continuity trial is not a pass."""
    monkeypatch.setattr(bench, "MAX_CAMERA_GAP_S", 0.05)

    class RebootingHead:
        _last_camera = None

        async def stream_frames(self):
            self._last_camera = (91, 1, 1_000_000)
            yield b"\xff\xd8old\xff\xd9", time.monotonic()
            await asyncio.sleep(0.01)
            self._last_camera = (92, 1, 50_000)
            yield b"\xff\xd8new\xff\xd9", time.monotonic()

        async def status(self):
            return {"robot_id": "robot-01"}

    result = await bench.measure(
        RebootingHead(), "robot-01", seconds=0.15,
        status_period_s=0.05, stream=True,
    )
    assert result["camera_frames_received"] == 1
    assert result["camera_error_count"] == 1
    assert any("rebooted" in error for error in result["camera_errors"])

async def test_camera_bench_collects_actual_sense_aec_reference_counters():
    """Read-only diagnostic uses the existing head without a second mic."""
    class Head:
        _last_camera = None

        def __init__(self):
            self.frames = 0
            self.audio_reads = 0

        async def snapshot(self):
            self.frames += 1
            self._last_camera = (17, self.frames, self.frames * 1000)
            return b"\xff\xd8valid jpeg\xff\xd9"

        async def status(self):
            return {"robot_id": "robot-01"}

        async def audio_reference_status(self):
            self.audio_reads += 1
            return {
                "robot_id": "robot-01",
                "reference_underflow_reads": 4,
                "reference_overwrite_reads": 0,
                "discarded_stale_writes": 1,
                "reference_integrity_failed": True,
                "speaker_playback_verified": False,
                "aec_physically_qualified": False,
            }

    head = Head()
    result = await bench.measure(
        head, "robot-01", seconds=0.12,
        camera_period_s=0.05, status_period_s=0.05,
    )
    assert head.audio_reads == 1
    assert result["aec_reference_diagnostics"]["reference_underflow_reads"] == 4
    assert result["aec_reference_diagnostics"]["reference_integrity_failed"] is True
    assert result["aec_reference_probe_error"] is None
    assert result["physical_aec_latency_measured"] is False
    assert result["speaker_silence_verified"] is False

async def test_slow_audio_reference_diagnostic_does_not_reduce_camera_fps():
    """The optional AEC read runs after, not inside, the camera FPS window."""
    class Head:
        _last_camera = None

        def __init__(self):
            self.frames = 0

        async def snapshot(self):
            self.frames += 1
            self._last_camera = (19, self.frames, self.frames * 1000)
            return b"\xff\xd8jpeg\xff\xd9"

        async def status(self):
            return {"robot_id": "robot-01"}

        async def audio_reference_status(self):
            await asyncio.sleep(0.25)
            return {
                "robot_id": "robot-01",
                "reference_underflow_reads": 0,
                "reference_overwrite_reads": 0,
                "discarded_stale_writes": 0,
                "short_output_writes": 0,
                "reference_integrity_failed": False,
                "speaker_playback_verified": False,
                "aec_physically_qualified": False,
            }

    start = time.monotonic()
    report = await bench.measure(
        Head(), "robot-01", seconds=0.12,
        camera_period_s=0.05, status_period_s=0.05,
    )
    total = time.monotonic() - start
    assert report["camera_frames_received"] >= 2
    assert total - report["elapsed_s"] >= 0.2
    assert report["successful_camera_fps"] >= 5
    assert report["physical_aec_latency_measured"] is False
    assert report["speaker_silence_verified"] is False
