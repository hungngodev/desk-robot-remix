"""Sense AEC diagnostic polling cannot claim physical playback or leak PCM."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sense_audio_bench", ROOT / "scripts/bench_head_audio.py"
)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def _sample(n: int, *, robot_id: str = "robot-01", failure=False) -> dict:
    return {
        "robot_id": robot_id,
        "reference_underflow_reads": 8 + n,
        "reference_overwrite_reads": 0,
        "discarded_stale_writes": 0,
        "reference_integrity_failed": failure,
        "speaker_playback_verified": False,
        "aec_physically_qualified": False,
    }


async def test_audio_bench_samples_real_codec_status_without_pcm_or_motor():
    class Head:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return _sample(self.calls)

    head = Head()
    report = await bench.measure(
        head, "robot-01", seconds=0.17, poll_period_s=0.05,
    )
    assert head.calls >= 2
    assert report["samples"] >= 2
    assert report["reference_counter_delta"]["reference_underflow_reads"] >= 1
    assert report["probe_errors"] == 0
    assert report["reference_software_integrity_observed"] is True
    assert report["physical_aec_delay_measured"] is False
    assert report["actual_speaker_playback_verified"] is False
    assert report["natural_human_barge_in_verified"] is False
    assert report["raw_pcm_captured"] is False


@pytest.mark.parametrize("bad", [
    _sample(1, robot_id="robot-02"),
    dict(_sample(1), speaker_playback_verified=True),
    dict(_sample(1), reference_overwrite_reads=True),
    dict(_sample(1), aec_physically_qualified=True),
])
async def test_audio_bench_rejects_foreign_and_untrusted_status(bad):
    class Head:
        async def audio_reference_status(self):
            return bad

    report = await bench.measure(
        Head(), "robot-01", seconds=0.11, poll_period_s=0.05,
    )
    assert report["samples"] == 0
    assert report["probe_errors"] >= 1
    assert report["reference_software_integrity_observed"] is False


async def test_audio_bench_counter_reset_cannot_be_healthy():
    class ResetHead:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return _sample(2 if self.calls == 1 else 1)

    report = await bench.measure(
        ResetHead(), "robot-01", seconds=0.12, poll_period_s=0.05,
    )
    assert report["counter_regressions"] >= 1
    assert report["reference_software_integrity_observed"] is False


async def test_audio_bench_hung_endpoint_cannot_block_completion():
    class Head:
        async def audio_reference_status(self):
            await asyncio.Event().wait()

    report = await asyncio.wait_for(
        bench.measure(Head(), "robot-01", seconds=0.12, poll_period_s=0.05),
        timeout=0.5,
    )
    assert report["samples"] == 0
    assert report["probe_errors"] >= 1
    assert report["actual_speaker_playback_verified"] is False


@pytest.mark.parametrize("seconds, period", [
    (float("nan"), 0.2), (0.2, float("inf")), (True, 0.2),
    (0, 0.2), (0.5, 0), (0.5, 20),
])
async def test_audio_bench_rejects_unbounded_intervals(seconds, period):
    with pytest.raises(ValueError, match="Invalid bounded audio"):
        await bench.measure(None, "robot-01", seconds=seconds, poll_period_s=period)
