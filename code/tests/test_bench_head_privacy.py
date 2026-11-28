"""Source regressions for the read-only Sense physical BOOT privacy bench."""
import importlib.util
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sense_privacy_bench", ROOT / "scripts/bench_head_privacy.py",
)
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def test_privacy_report_rejects_untrusted_ancestor_without_creating_directories(
    tmp_path,
):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    (shared / "alias").symlink_to(private, target_is_directory=True)
    created = private / "not_yet_created"
    output = shared / "alias" / created.name / "privacy.json"
    with pytest.raises(ValueError, match="unsafe symlink"):
        bench.preflight_private_report(output)
    assert not created.exists()
    with pytest.raises(ValueError, match="unsafe symlink"):
        bench.save_private_report(output, {"privacy_muted": True})
    assert not created.exists()


def test_privacy_report_refuses_parent_traversal_before_mkdir(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "alias" / ".." / "created" / "privacy.json"
    with pytest.raises(ValueError, match="parent traversal"):
        bench.preflight_private_report(output)
    with pytest.raises(ValueError, match="parent traversal"):
        bench.save_private_report(output, {"privacy_muted": True})
    assert not (private / "created").exists()


def test_boot_privacy_report_preflight_rejects_public_or_existing_path(
    tmp_path,
):
    private = tmp_path / "consented" / "privacy.json"
    bench.preflight_private_report(private)
    assert stat.S_IMODE(private.parent.stat().st_mode) == 0o700
    private.write_text("preserve previous BOOT evidence")
    with pytest.raises(FileExistsError):
        bench.preflight_private_report(private)
    assert private.read_text() == "preserve previous BOOT evidence"
    public = tmp_path / "world-readable"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(ValueError, match="private mode"):
        bench.preflight_private_report(public / "privacy.json")


def test_privacy_report_rejects_nested_ancestor_symlink_and_is_exclusive(
    tmp_path,
):
    target = tmp_path / "attacker"
    target.mkdir(mode=0o700)
    (target / "reports").mkdir(mode=0o700)
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)
    (shared / "alias").symlink_to(target, target_is_directory=True)
    redirected = shared / "alias" / "reports" / "privacy.json"
    assert not redirected.parent.is_symlink()
    assert stat.S_IMODE(redirected.parent.stat().st_mode) == 0o700
    with pytest.raises(ValueError, match="unsafe symlink"):
        bench.preflight_private_report(redirected)
    with pytest.raises(ValueError, match="unsafe symlink"):
        bench.save_private_report(redirected, {"muted": True})
    assert not (target / "reports" / "privacy.json").exists()

    safe = tmp_path / "private" / "privacy.json"
    bench.save_private_report(safe, {"raw_pcm_captured": False})
    assert stat.S_IMODE(safe.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        bench.save_private_report(safe, {"raw_pcm_captured": True})
    assert '"raw_pcm_captured": false' in safe.read_text()


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


def sample(muted: bool, epoch: int, frames: int, *, boot: int = 19) -> dict:
    return {
        "robot_id": "robot-01",
        "boot": boot,
        "microphone_frames_read": frames,
        "microphone_privacy_muted": muted,
        "microphone_privacy_epoch": epoch,
        "speaker_playback_verified": False,
        "aec_physically_qualified": False,
    }


class Head:
    def __init__(self, samples):
        self.samples = samples
        self.calls = 0

    async def audio_reference_status(self):
        i = self.calls
        self.calls += 1
        return self.samples[min(i, len(self.samples) - 1)]


CYCLE = [
    sample(False, 0, 100),
    sample(False, 0, 120),
    sample(True, 1, 130),
    sample(True, 1, 132),
    sample(True, 1, 132),
    sample(True, 1, 132),
    sample(True, 1, 132),
    sample(False, 2, 132),
    sample(False, 2, 170),
]


async def run(samples, *, duration=0.7):
    timer = Clock()
    notices = []
    report = await bench.measure(
        Head(samples), "robot-01",
        seconds=duration, poll_period_s=0.05,
        hold_min_s=0.18, quiet_grace_s=0.04,
        clock=timer, sleeper=timer.sleep,
        on_ready=notices.append,
    )
    return report, notices


async def test_real_source_counter_cycle_with_two_manual_boot_presses():
    report, messages = await run(CYCLE)
    assert report["software_boot_privacy_cycle_observed"] is True
    assert report["muted_samples_after_grace"] >= 2
    assert report["post_unmute_microphone_reads_resumed"] is True
    assert len(messages) == 2
    assert report["head_boot"] == 19
    assert report["raw_pcm_captured"] is False
    assert report["actual_network_audio_cutoff_verified"] is False
    assert report["physical_audio_privacy_qualified"] is False


@pytest.mark.parametrize("broken", [
    CYCLE[:2] + [sample(True, 0, 130)] + CYCLE[3:],
    CYCLE[:4] + [sample(True, 1, 134)] + CYCLE[5:],
    CYCLE[:7] + [sample(False, 1, 132)] + CYCLE[8:],
    CYCLE[:3] + [sample(False, 2, 140)] + CYCLE[4:],
    CYCLE[:5] + [sample(True, 1, 132, boot=20)] + CYCLE[6:],
    CYCLE[:6] + [sample(True, 0, 132)] + CYCLE[7:],
])
async def test_boot_privacy_cycle_rejects_bad_epoch_mute_early_resume_or_reboot(
    broken,
):
    report, _ = await run(broken)
    assert report["software_boot_privacy_cycle_observed"] is False
    assert report["physical_audio_privacy_qualified"] is False


async def test_no_unmuted_input_is_not_a_privacy_pass():
    report, messages = await run([
        sample(False, 0, 0), sample(False, 0, 0), sample(True, 1, 0),
    ], duration=0.3)
    assert not report["software_boot_privacy_cycle_observed"]
    assert not messages


@pytest.mark.parametrize("broken", [
    dict(CYCLE[0], microphone_privacy_muted=1),
    dict(CYCLE[0], microphone_privacy_epoch=True),
    dict(CYCLE[0], microphone_frames_read=-1),
    dict(CYCLE[0], robot_id="robot-02"),
    dict(CYCLE[0], speaker_playback_verified=True),
])
async def test_privacy_bench_rejects_untrusted_typed_head_status(broken):
    report, _ = await run([broken], duration=0.2)
    assert report["polls_accepted"] == 0
    assert report["errors"]
    assert not report["software_boot_privacy_cycle_observed"]


@pytest.mark.parametrize("duration, period, hold, grace", [
    (float("inf"), .05, .2, .05),
    (.8, 0, .2, .05),
    (.8, .05, True, .05),
    (.8, .05, .2, .2),
])
async def test_privacy_bench_refuses_invalid_trial_limits(duration, period, hold, grace):
    timer = Clock()
    with pytest.raises(ValueError, match="Invalid Sense"):
        await bench.measure(
            Head([]), "robot-01", seconds=duration,
            poll_period_s=period, hold_min_s=hold,
            quiet_grace_s=grace, clock=timer, sleeper=timer.sleep,
        )


@pytest.mark.asyncio
async def test_cli_ignores_ambient_proxy_for_authenticated_boot_privacy_bench(
    tmp_path, monkeypatch,
):
    """Direct head privacy telemetry never inherits an ambient bearer proxy."""
    import json
    import sys

    monkeypatch.setenv("HTTPS_PROXY", "http://unexpected-proxy.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://unexpected-proxy.invalid:8080")
    monkeypatch.setattr(sys, "argv", [
        "bench_head_privacy.py", "--robot", "robot-01",
        "--seconds", "5", "--report", str(tmp_path / "privacy.json"),
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

    async def fake_measure(head, robot_id, *, seconds, poll_period_s, on_ready):
        assert head is not None
        assert robot_id == "robot-01"
        assert seconds == 5
        assert poll_period_s == 0.1
        assert callable(on_ready)
        return {
            "software_boot_privacy_cycle_observed": False,
            "physical_audio_privacy_qualified": False,
            "speaker_playback_verified": False,
        }

    monkeypatch.setattr(bench, "measure", fake_measure)
    assert await bench.main() == 1
    assert client_options == [{"trust_env": False}]
    report = json.loads((tmp_path / "privacy.json").read_text())
    assert report["speaker_playback_verified"] is False
    assert report["physical_audio_privacy_qualified"] is False


@pytest.mark.parametrize("broken", [
    # Extra cycles before mute, during the muted interval, and after unmute.
    CYCLE[:2] + [dict(row, microphone_privacy_epoch=row["microphone_privacy_epoch"] + 2)
                 for row in CYCLE[2:]],
    CYCLE[:4] + [dict(row, microphone_privacy_epoch=row["microphone_privacy_epoch"] + 2)
                 for row in CYCLE[4:]],
    CYCLE[:8] + [sample(False, 4, 170)],
    [CYCLE[0]] + [dict(row, microphone_privacy_epoch=row["microphone_privacy_epoch"] + 2)
                  for row in CYCLE[1:]],
    # Epoch wrap during the trial cannot prove the exact two transitions.
    [sample(False, 0xfffffffe, 100), sample(False, 0xfffffffe, 120),
     sample(True, 0xffffffff, 130), sample(True, 0xffffffff, 132),
     sample(True, 0xffffffff, 132), sample(True, 0xffffffff, 132),
     sample(True, 0xffffffff, 132), sample(False, 0, 132), sample(False, 0, 170)],
])
async def test_boot_privacy_cycle_rejects_hidden_transitions_and_rollover(broken):
    report, _ = await run(broken)
    assert report["software_boot_privacy_cycle_observed"] is False
    assert report["errors"]
    assert report["physical_audio_privacy_qualified"] is False


async def test_privacy_cycle_requires_observed_full_muted_interval():
    # The unmuted receipt cannot prove the preceding unobserved time was muted.
    report, notices = await run(CYCLE[:6] + CYCLE[7:])
    assert not report["software_boot_privacy_cycle_observed"]
    assert report["errors"] == ["Muted interval was too short"]
    assert len(notices) == 1
