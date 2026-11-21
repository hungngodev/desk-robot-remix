"""Source-only camera/status bench contracts; never physical acoustic evidence."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "desk_robot_camera_bench", ROOT / "scripts/bench_head_camera.py"
)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)

JPEG = b"\xff\xd8" + b"real frame" + b"\xff\xd9"


async def test_hardware_camera_cli_requires_live_mjpeg_not_snapshots(
    tmp_path, monkeypatch, capsys,
):
    import sys

    monkeypatch.setattr(sys, "argv", [
        "bench_head_camera.py", "--robot", "robot-01",
        "--report", str(tmp_path / "camera.json"),
    ])
    with pytest.raises(SystemExit) as exc:
        await bench.main()
    assert exc.value.code == 2
    assert "requires --stream persistent MJPEG" in capsys.readouterr().err
    assert not (tmp_path / "camera.json").exists()


def test_camera_bench_report_private_exclusive_and_preflighted(tmp_path):
    path = tmp_path / "private" / "trial.json"
    bench.preflight_private_report(path)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    bench.save_private_report(path, {"robot_id": "robot-01", "stream": True})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == {
        "robot_id": "robot-01", "stream": True,
    }
    with pytest.raises(FileExistsError):
        bench.preflight_private_report(path)
    with pytest.raises(FileExistsError):
        bench.save_private_report(path, {"stream": False})
    assert json.loads(path.read_text())["stream"] is True
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(ValueError, match="private mode"):
        bench.preflight_private_report(public / "another.json")


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


async def test_snapshot_camera_bench_rejects_reboot_without_hiding_status():
    class RebootedHead:
        def __init__(self):
            self.sequence = 0
            self._last_camera = None
            self.status_calls = 0

        async def snapshot(self):
            self.sequence += 1
            boot = 17 if self.sequence < 3 else 18
            self._last_camera = (boot, self.sequence, self.sequence * 1000)
            return JPEG

        async def status(self):
            self.status_calls += 1
            return {"robot_id": "robot-01"}

    head = RebootedHead()
    result = await bench.measure(
        head, "robot-01", seconds=0.22,
        camera_period_s=0.05, status_period_s=0.05,
    )
    assert result["camera_acquisition_mode"] == "legacy_snapshot"
    assert result["camera_frames_received"] == 2
    assert result["camera_error_count"] >= 1
    assert "Sense camera rebooted during snapshot bench" in result["camera_errors"][0]
    assert result["distinct_source_camera_identities"] == 2
    assert result["status_error_count"] == 0
    assert head.status_calls >= 2
    assert result["assembly_ready"] is False


async def test_real_mjpeg_bench_receives_continuous_frames_without_snapshot_http():
    import time

    class StreamingHead:
        def __init__(self):
            self._last_camera = None
            self.snapshot_calls = 0
            self.status_calls = 0

        async def snapshot(self):
            self.snapshot_calls += 1
            raise AssertionError("MJPEG bench must never pull single snapshots")

        async def stream_frames(self):
            for seq in range(12):
                await asyncio.sleep(.025)
                self._last_camera = (31337, seq + 1, (seq + 1) * 25000)
                yield JPEG, time.monotonic()

        async def status(self):
            self.status_calls += 1
            return {"robot_id": "robot-01"}

    head = StreamingHead()
    result = await bench.measure(
        head, "robot-01", seconds=.21, status_period_s=.05, stream=True
    )
    assert result["camera_acquisition_mode"] == "persistent_mjpeg"
    assert result["camera_frames_received"] >= 4
    assert result["successful_camera_fps"] > 4
    assert result["distinct_source_camera_identities"] >= 4
    assert result["stream_frame_interarrival"]["count"] >= 3
    assert result["camera_latency"]["count"] == 0  # no snapshot timing invented
    assert result["status_latency"]["count"] >= 3
    assert head.snapshot_calls == 0
    assert head.status_calls >= 3
    assert result["camera_error_count"] == 0


async def test_cancelled_camera_bench_closes_stream_lease():
    """Cancelling a bench must release the same live MJPEG HTTP lease."""
    entered, closed = asyncio.Event(), asyncio.Event()

    class Head:
        async def stream_frames(self):
            try:
                entered.set()
                while True:
                    await asyncio.sleep(10)
                    yield b"unused", 0
            finally:
                closed.set()

        async def status(self):
            return {"robot_id": "robot-01"}

    task = asyncio.create_task(
        bench.measure(Head(), "robot-01", seconds=60,
                      status_period_s=.05, stream=True)
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()  # Lease closed before cancellation completes.


async def test_stalled_continuous_mjpeg_is_reported_not_mistaken_for_live():
    class StalledHead:
        _last_camera = None
        status_calls = 0

        async def stream_frames(self):
            await asyncio.Event().wait()
            yield JPEG, 0.0

        async def status(self):
            self.status_calls += 1
            return {"robot_id": "robot-01"}

    head = StalledHead()
    report = await asyncio.wait_for(
        bench.measure(
            head, "robot-01", seconds=.12,
            status_period_s=.05, stream=True,
        ), timeout=1.5
    )
    assert report["camera_frames_received"] == 0
    assert report["camera_error_count"] >= 1
    assert report["status_latency"]["count"] >= 2
    assert head.status_calls >= 2
    assert report["speaker_silence_verified"] is False
