"""Sense AEC diagnostic polling cannot claim physical playback or leak PCM."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sense_audio_bench", ROOT / "scripts/bench_head_audio.py"
)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def test_audio_diagnostic_receipts_are_private_and_exclusive(tmp_path):
    path = tmp_path / "audio-private" / "diagnostic.json"
    bench.preflight_private_report(path)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    bench.save_private_report(path, {"robot_id": "robot-01", "aec": False})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["aec"] is False
    with pytest.raises(FileExistsError):
        bench.save_private_report(path, {"aec": True})
    assert json.loads(path.read_text())["aec"] is False
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(ValueError, match="private mode"):
        bench.preflight_private_report(public / "leak.json")


def test_audio_diagnostic_report_rejects_replaceable_ancestor_symlink(tmp_path):
    # The immediate child is 0700 and not itself a symlink. An older
    # preflight trusted it even though an ancestor redirected the write.
    target = tmp_path / "attacker"
    target.mkdir(mode=0o700)
    (target / "reports").mkdir(mode=0o700)
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    (shared / "alias").symlink_to(target, target_is_directory=True)
    report = shared / "alias" / "reports" / "acoustic.json"
    with pytest.raises(ValueError, match="unsafe symlink"):
        bench.preflight_private_report(report)
    with pytest.raises(ValueError, match="unsafe symlink"):
        bench.save_private_report(report, {"private": True})
    assert not (target / "reports" / "acoustic.json").exists()


def test_audio_bench_rejects_symlink_ancestor_without_creating_target_directory(
    tmp_path,
):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    (shared / "alias").symlink_to(private, target_is_directory=True)
    unexpected = private / "not_yet_created"
    output = shared / "alias" / unexpected.name / "diagnostic.json"
    with pytest.raises(ValueError, match="unsafe symlink"):
        bench.preflight_private_report(output)
    assert not unexpected.exists()
    with pytest.raises(ValueError, match="unsafe symlink"):
        bench.save_private_report(output, {"microphone_frames_read": 1})
    assert not unexpected.exists()


def test_audio_bench_rejects_parent_traversal_before_mkdir(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "alias" / ".." / "created" / "diagnostic.json"
    with pytest.raises(ValueError, match="parent traversal"):
        bench.preflight_private_report(output)
    with pytest.raises(ValueError, match="parent traversal"):
        bench.save_private_report(output, {"microphone_frames_read": 1})
    assert not (private / "created").exists()


def _sample(n: int, *, robot_id: str = "robot-01", failure=False,
            underflow_reads: int = 8) -> dict:
    return {
        "robot_id": robot_id,
        "boot": 19,
        "reference_underflow_reads": underflow_reads,
        "reference_overwrite_reads": 0,
        "discarded_stale_writes": 0,
        "short_output_writes": 0,
        "microphone_frames_read": n * 160,
        "speaker_frames_accepted": n * 320,
        "microphone_privacy_muted": False,
        "microphone_privacy_epoch": 0,
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
    assert report["reference_counter_delta"]["reference_underflow_reads"] == 0
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


async def test_audio_bench_rejects_fresh_reference_underflows():
    class Head:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return _sample(self.calls, underflow_reads=8 + self.calls)

    result = await bench.measure(
        Head(), "robot-01", seconds=0.13, poll_period_s=0.05,
    )
    assert result["samples"] >= 2
    assert result["reference_counter_delta"]["reference_underflow_reads"] > 0
    assert result["reference_software_integrity_observed"] is False
    assert result["physical_aec_delay_measured"] is False


@pytest.mark.parametrize("missing", [
    "microphone_frames_read", "speaker_frames_accepted",
])
async def test_audio_bench_cannot_pass_with_idle_microphone_or_speaker(missing):
    class SilentPathHead:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return dict(_sample(self.calls), **{missing: 0})

    result = await bench.measure(
        SilentPathHead(), "robot-01", seconds=0.17, poll_period_s=0.05,
    )
    assert result["samples"] >= 2
    assert result["reference_counter_delta"][missing] == 0
    assert result["reference_software_integrity_observed"] is False
    assert result["physical_aec_delay_measured"] is False


async def test_audio_bench_rejects_active_boot_privacy_mute():
    class MutedHead:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return dict(_sample(self.calls), microphone_privacy_muted=True,
                        microphone_privacy_epoch=1)

    result = await bench.measure(
        MutedHead(), "robot-01", seconds=0.16, poll_period_s=0.05,
    )
    assert result["samples"] >= 2
    assert result["microphone_privacy_muted_observed"] is True
    assert result["reference_software_integrity_observed"] is False
    assert result["actual_speaker_playback_verified"] is False


async def test_audio_bench_rejects_mute_epoch_change_even_after_unmute():
    class ToggledHead:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return dict(_sample(self.calls),
                        microphone_privacy_muted=self.calls == 2,
                        microphone_privacy_epoch=max(0, self.calls - 1))

    result = await bench.measure(
        ToggledHead(), "robot-01", seconds=0.2, poll_period_s=0.05,
    )
    assert result["samples"] >= 2
    assert result["microphone_privacy_muted_observed"] is True
    assert result["microphone_privacy_epoch_delta"] > 0
    assert result["reference_software_integrity_observed"] is False


async def test_audio_bench_rejects_privacy_regrant_between_samples():
    # Both observations say unmuted, but the device privacy epoch proves
    # a revoke and regrant occurred between samples.
    class RegrantedHead:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return dict(_sample(self.calls),
                        microphone_privacy_epoch=7 if self.calls == 1 else 8)

    report = await bench.measure(
        RegrantedHead(), "robot-01", seconds=0.17, poll_period_s=0.05,
    )
    assert report["samples"] >= 2
    assert report["probe_errors"] == 0
    assert report["microphone_privacy_muted_observed"] is False
    assert report["microphone_privacy_epoch_delta"] == 1
    assert report["reference_software_integrity_observed"] is False
    assert report["actual_speaker_playback_verified"] is False
    assert report["physical_aec_delay_measured"] is False


async def test_audio_bench_rejects_regressed_privacy_epoch():
    class EpochRewindHead:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return dict(_sample(self.calls), microphone_privacy_epoch=(8 if self.calls == 1 else 7))

    result = await bench.measure(
        EpochRewindHead(), "robot-01", seconds=0.13, poll_period_s=0.05,
    )
    assert result["counter_regressions"] >= 1
    assert result["reference_software_integrity_observed"] is False


async def test_audio_bench_rejects_incomplete_speaker_output_receipts():
    class Head:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return dict(_sample(self.calls), short_output_writes=self.calls - 1)

    result = await bench.measure(
        Head(), "robot-01", seconds=0.15, poll_period_s=0.05,
    )
    assert result["samples"] >= 2
    assert result["reference_counter_delta"]["short_output_writes"] > 0
    assert result["reference_software_integrity_observed"] is False
    assert result["actual_speaker_playback_verified"] is False


async def test_audio_bench_rejects_regressed_output_integrity_counter():
    class Head:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return dict(_sample(self.calls), short_output_writes=5 if self.calls == 1 else 4)

    result = await bench.measure(
        Head(), "robot-01", seconds=0.15, poll_period_s=0.05,
    )
    assert result["counter_regressions"] >= 1
    assert result["reference_software_integrity_observed"] is False


async def test_audio_bench_counter_reset_cannot_be_healthy():
    class ResetHead:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return _sample(
                self.calls, underflow_reads=10 if self.calls == 1 else 9,
            )

    report = await bench.measure(
        ResetHead(), "robot-01", seconds=0.12, poll_period_s=0.05,
    )
    assert report["counter_regressions"] >= 1
    assert report["reference_software_integrity_observed"] is False


async def test_audio_bench_rejects_silent_device_reboot_with_zero_counters():
    class RebootingHead:
        def __init__(self):
            self.calls = 0

        async def audio_reference_status(self):
            self.calls += 1
            return dict(
                _sample(self.calls, underflow_reads=0),
                boot=19 if self.calls == 1 else 20,
            )

    report = await bench.measure(
        RebootingHead(), "robot-01", seconds=0.15, poll_period_s=0.05,
    )
    assert report["head_boot"] == 19
    assert report["counter_regressions"] >= 1
    assert report["reference_software_integrity_observed"] is False
    assert report["actual_speaker_playback_verified"] is False


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


@pytest.mark.asyncio
async def test_cli_ignores_ambient_proxy_for_authenticated_audio_bench(
    tmp_path, monkeypatch,
):
    """The operator's bearer and AEC diagnostics stay on the selected device."""
    import sys

    monkeypatch.setenv("HTTPS_PROXY", "http://unexpected-proxy.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://unexpected-proxy.invalid:8080")
    monkeypatch.setattr(sys, "argv", [
        "bench_head_audio.py", "--robot", "robot-01",
        "--seconds", "5", "--report", str(tmp_path / "audio.json"),
    ])

    class Robot:
        id = "robot-01"
        device_id = "unique-sense-device"

    class Settings:
        mode = "hardware"

        def robot(self, name):
            assert name == "robot-01"
            return Robot()

    monkeypatch.setattr(bench, "load_settings", lambda _config: Settings())
    client_options = []

    class Client:
        def __init__(self, **kwargs):
            client_options.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(bench.httpx, "AsyncClient", Client)

    def head_factory(robot, client):
        assert robot.id == "robot-01"
        assert isinstance(client, Client)
        return object()

    monkeypatch.setattr(bench, "HttpHead", head_factory)

    async def fake_measure(head, robot_id, *, seconds, poll_period_s):
        assert head is not None
        assert robot_id == "robot-01"
        assert seconds == 5
        assert poll_period_s == 0.2
        return {
            "reference_software_integrity_observed": False,
            "actual_speaker_playback_verified": False,
        }

    monkeypatch.setattr(bench, "measure", fake_measure)
    assert await bench.main() == 1
    assert client_options == [{"trust_env": False}]
    report = json.loads((tmp_path / "audio.json").read_text())
    assert report["actual_speaker_playback_verified"] is False
