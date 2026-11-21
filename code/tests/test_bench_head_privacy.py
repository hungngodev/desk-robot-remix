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
