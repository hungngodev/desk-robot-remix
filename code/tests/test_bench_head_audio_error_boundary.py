"""Only expected audio probe failures become failed diagnostic receipts."""
import asyncio
import importlib.util
from pathlib import Path

import pytest
from desk_robot.transport import HeadError

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sense_audio_error_boundary", ROOT / "scripts/bench_head_audio.py"
)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


@pytest.mark.parametrize("error_type", [HeadError, TimeoutError, ValueError])
@pytest.mark.asyncio
async def test_expected_probe_errors_remain_failed_receipts(error_type):
    class Head:
        async def audio_reference_status(self):
            raise error_type("probe failed")

    report = await bench.measure(Head(), "robot-01", seconds=0.1, poll_period_s=0.05)
    assert report["samples"] == 0
    assert report["probe_errors"] >= 1
    assert report["probe_error_details"] == [
        f"{error_type.__name__}: probe failed"
    ] * report["probe_errors"]
    assert report["reference_software_integrity_observed"] is False
    assert report["actual_speaker_playback_verified"] is False


@pytest.mark.parametrize(
    "error_type", [TypeError, AssertionError, RuntimeError, asyncio.CancelledError],
)
@pytest.mark.asyncio
async def test_unexpected_probe_errors_and_cancellation_propagate(error_type):
    class Head:
        async def audio_reference_status(self):
            raise error_type("probe failed")

    with pytest.raises(error_type, match="probe failed"):
        await bench.measure(Head(), "robot-01", seconds=0.1, poll_period_s=0.05)
