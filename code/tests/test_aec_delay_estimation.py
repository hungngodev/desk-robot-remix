"""Simulated audio tests do not establish physical echo cancellation."""
import runpy
from pathlib import Path

import numpy as np
import pytest

source = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/estimate_aec_delay.py"
))
estimate_delay = source["estimate_delay"]
resample_reference = source["resample_reference"]
estimate_clock_drift = source["estimate_clock_drift"]


def test_estimates_positive_lag_from_correlated_playback():
    rng = np.random.default_rng(21)
    speaker = rng.normal(0, 0.2, 8000)
    lag = 1120
    mic = np.concatenate([np.zeros(lag), speaker])[:8000]
    report = estimate_delay(speaker, mic)
    assert report["sample_lag"] == 1120
    assert report["reference_delay_ms"] == 70.0
    assert report["normalized_correlation"] > 0.8
    assert report["esp_idf_delay_setting_applicable"]
    assert report["esp_idf_delay_max_ms"] == 250
    assert not report["aec_physically_verified"]
    assert not report["natural_barge_in_verified"]


def test_audio_must_cover_requested_acoustic_delay_horizon():
    """A short correlated clip cannot substantiate a longer search window."""
    rng = np.random.default_rng(991)
    short = rng.normal(0, 0.15, 320)  # 20 ms, not a 250 ms trial
    microphone = np.concatenate((np.zeros(60), short))[:320]
    # Before this bound, the algorithm reports a confident 3.75 ms delay.
    for left, right in (
        (short, microphone),
        (short, np.pad(microphone, (0, 8000 - len(microphone)))),
    ):
        with pytest.raises(ValueError, match="too short for requested delay"):
            estimate_delay(left, right)

    speaker = rng.normal(0, 0.2, 8000)
    recorded = np.concatenate((np.zeros(1120), speaker))[:8000]
    report = estimate_delay(speaker, recorded)
    assert report["sample_lag"] == 1120
    assert report["aec_physically_verified"] is False


def test_silence_uncorrelated_or_nonfinite_cannot_fake_calibration():
    with pytest.raises(ValueError):
        estimate_delay(np.zeros(1000), np.ones(1000))
    rng = np.random.default_rng(29)
    with pytest.raises(ValueError):
        estimate_delay(rng.normal(size=10000), rng.normal(size=10000))
    for value in (float("nan"), float("inf")):
        signal = np.ones(1000)
        signal[0] = value
        with pytest.raises(ValueError):
            estimate_delay(signal, np.ones(1000))


def test_periodic_tone_or_two_similarly_loud_echoes_is_not_unique_delay():
    # A pure tone can have near-perfect correlation at many different delays.
    # The estimator must not turn the first such peak into an AEC setting.
    samples = 8000
    time = np.arange(samples)
    tone = 0.18 * np.sin(2 * np.pi * 1000 * time / 16000)
    microphone = np.concatenate((np.zeros(1120), tone))[:samples]
    with pytest.raises(ValueError, match="Ambiguous acoustic delay"):
        estimate_delay(tone, microphone)

    # Two strong real reflections are ambiguous even for broadband audio.
    rng = np.random.default_rng(483)
    speaker = rng.normal(0, 0.18, samples)
    early = np.concatenate((np.zeros(1120), speaker))[:samples]
    late = np.concatenate((np.zeros(1280), speaker))[:samples]
    with pytest.raises(ValueError, match="Ambiguous acoustic delay"):
        estimate_delay(speaker, early + late)


def test_sample_rate_and_window_are_strict():
    signal = np.ones(1000)
    with pytest.raises(ValueError):
        estimate_delay(signal, signal, sample_rate=24000)
    with pytest.raises(ValueError):
        estimate_delay(signal, signal, max_delay_ms=2)
    with pytest.raises(ValueError):
        resample_reference(signal, 48000)
    assert len(resample_reference(np.zeros(24000), 24000)) == 16000


def test_multiwindow_drift_estimates_real_sample_slip_not_global_latency():
    """A known clock slope is distinct from the initial acoustic delay."""
    rng = np.random.default_rng(281)
    speaker = rng.normal(0, 0.15, 160000)
    positions = np.arange(len(speaker), dtype=np.float64)
    for drift_ppm in (0, 200, -200):
        mic = np.interp(
            positions - 1120 - positions * drift_ppm / 1_000_000,
            positions, speaker, left=0, right=0,
        )
        result = estimate_clock_drift(speaker, mic)
        assert result["clock_drift_ppm_estimate"] == pytest.approx(
            drift_ppm, abs=25
        )
        assert len(result["clock_drift_window_lags_samples"]) == 4
        assert result["clock_drift_min_correlation"] > 0.15
        assert result["clock_drift_max_fit_residual_samples"] <= 3
        assert result["clock_drift_needs_hardware_review"] == (
            abs(drift_ppm) > 100
        )
        assert not result["aec_physically_verified"]
        assert not result["natural_barge_in_verified"]


def test_clock_drift_requires_long_aligned_correlated_recordings():
    rng = np.random.default_rng(282)
    source = rng.normal(size=160000)
    for a, b in (
        (source[:32000], source[:32000]),
        (source, source[:-1]),
        (source, np.zeros_like(source)),
    ):
        with pytest.raises(ValueError):
            estimate_clock_drift(a, b)
    with pytest.raises(ValueError):
        estimate_clock_drift(source, source, sample_rate=24000)
    with pytest.raises(ValueError):
        estimate_clock_drift(source, source, max_delay_ms=float("nan"))


def test_sudden_latency_step_is_not_mislabeled_as_clock_drift():
    rng = np.random.default_rng(283)
    source = rng.normal(0, 0.15, 160000)
    mic = np.zeros_like(source)
    for i in range(160000):
        lag = 1120 if i < 80000 else 1180
        if i >= lag:
            mic[i] = source[i - lag]
    with pytest.raises(ValueError, match="not a stable clock drift"):
        estimate_clock_drift(source, mic)


def test_large_acoustic_delay_is_diagnostic_only_not_copyable_to_idf():
    rng = np.random.default_rng(284)
    speaker = rng.normal(0, 0.2, 16000)
    mic = np.concatenate([np.zeros(4800), speaker])[:16000]
    report = estimate_delay(speaker, mic, max_delay_ms=400)
    assert report["sample_lag"] == 4800
    assert report["reference_delay_ms"] == 300
    assert not report["esp_idf_delay_setting_applicable"]
    assert report["esp_idf_delay_max_ms"] == 250
    assert not report["aec_physically_verified"]

def test_sense_32khz_speaker_wav_matches_reference_phase(tmp_path):
    """Synthetic source and lag, not proof of acoustic qualification."""
    import wave

    rng = np.random.default_rng(335)
    pcm = np.clip(rng.normal(0, 0.12, 64000), -0.99, 0.99)
    file = tmp_path / "sense_32k.wav"
    with wave.open(str(file), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(32000)
        wav.writeframes((pcm * 32767).astype("<i2").tobytes())
    recorded, rate = source["read_wav"](file)
    reference = resample_reference(recorded, rate)
    assert rate == 32000
    assert len(reference) == 32000
    assert reference[0] == 0
    expected_pcm = int((2 * recorded[0] + recorded[1]) * 32768 / 4)
    assert reference[1] == expected_pcm / 32768
    microphone = np.concatenate((np.zeros(1120), reference))[:len(reference)]
    report = estimate_delay(reference, microphone)
    assert report["reference_delay_ms"] == 70.0
    assert not report["aec_physically_verified"]


def test_sense_32khz_speaker_over_ten_seconds_is_rejected(tmp_path):
    import wave

    file = tmp_path / "too_long.wav"
    with wave.open(str(file), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(32000)
        wav.writeframes(bytes(320001 * 2))
    with pytest.raises(ValueError, match="WAV"):
        source["read_wav"](file)


def test_truncated_wav_header_cannot_be_used_for_acoustic_calibration(tmp_path):
    """Declared frame count is not evidence that the capture contains PCM."""
    import struct
    import wave

    file = tmp_path / "missing_pcm.wav"
    with wave.open(str(file), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(bytes(16000 * 2))
    raw = bytearray(file.read_bytes())
    claimed_bytes = 32000 * 2
    struct.pack_into("<I", raw, 4, 36 + claimed_bytes)
    struct.pack_into("<I", raw, raw.index(b"data") + 4, claimed_bytes)
    file.write_bytes(raw)
    with pytest.raises(ValueError, match="WAV file truncated"):
        source["read_wav"](file)


@pytest.mark.parametrize("lag", [0, 1, 1120, 4000, 6400])
def test_noisy_delay_uses_only_overlapping_samples(lag):
    """Strong ambient noise must not dilute a valid long-lag overlap."""
    rng = np.random.default_rng(350)
    speaker = rng.normal(0, 0.1, 8000)
    mic = (np.concatenate((np.zeros(lag), speaker))[:8000]
           + rng.normal(0, 0.2, 8000))
    report = estimate_delay(speaker, mic, max_delay_ms=400)
    assert report["sample_lag"] == lag
    expected = abs(np.corrcoef(speaker[:8000 - lag], mic[lag:])[0, 1])
    assert report["normalized_correlation"] == pytest.approx(expected, abs=0.00005)
    assert report["esp_idf_delay_setting_applicable"] == (lag <= 4000)
    assert not report["aec_physically_verified"]


@pytest.mark.parametrize("lag, setting", [
    (0, 0), (7, 0), (8, 1), (1128, 71), (3999, 250),
    (4000, 250), (4001, None), (6400, None),
])
def test_integer_firmware_delay_setting_is_bounded(lag, setting):
    rng = np.random.default_rng(351)
    speaker = rng.normal(0, 0.1, 8000)
    mic = np.concatenate((np.zeros(lag), speaker))[:8000]
    report = estimate_delay(speaker, mic, max_delay_ms=400)
    assert report["reference_delay_ms"] == round(lag / 16, 3)
    assert report["esp_idf_delay_setting_ms"] == setting
    assert report["esp_idf_delay_setting_applicable"] == (setting is not None)
    if setting is not None:
        assert type(report["esp_idf_delay_setting_ms"]) is int
    assert not report["aec_physically_verified"]


def test_cli_emits_integer_candidate_without_qualifying_hardware(tmp_path):
    import json
    import subprocess
    import sys
    import wave

    rng = np.random.default_rng(352)
    speaker = rng.integers(-6000, 6000, size=8000, dtype=np.int16)
    mic = np.concatenate((np.zeros(1128, dtype=np.int16), speaker))[:8000]
    for filename, samples in (("speaker.wav", speaker), ("mic.wav", mic)):
        with wave.open(str(tmp_path / filename), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(samples.astype("<i2").tobytes())
    script = Path(__file__).resolve().parents[1] / "scripts/estimate_aec_delay.py"
    result = subprocess.run([
        sys.executable, str(script), "--speaker", str(tmp_path / "speaker.wav"),
        "--microphone", str(tmp_path / "mic.wav"),
    ], check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report["reference_delay_ms"] == 70.5
    assert report["esp_idf_delay_setting_ms"] == 71
    assert type(report["esp_idf_delay_setting_ms"]) is int
    assert report["clock_drift_status"] == "unavailable"
    assert not report["aec_physically_verified"]
    assert not report["natural_barge_in_verified"]


@pytest.mark.parametrize("rate", [16000, 24000, 32000])
def test_odd_pcm_chunk_byte_cannot_be_silently_discarded(tmp_path, rate):
    """wave reports whole frames even when the data chunk ends mid-sample."""
    import struct
    import wave

    file = tmp_path / "odd_pcm.wav"
    with wave.open(str(file), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(rate * 2))
    # Include a valid RIFF pad byte; only the PCM chunk itself is malformed.
    raw = bytearray(file.read_bytes())
    struct.pack_into("<I", raw, 4, len(raw) - 8 + 2)
    struct.pack_into("<I", raw, raw.index(b"data") + 4, rate * 2 + 1)
    raw.extend(b"\xff\x00")
    file.write_bytes(raw)
    with pytest.raises(ValueError, match="incomplete PCM16"):
        source["read_wav"](file)



@pytest.mark.parametrize("fault", ["negative_lead", "unequal_duration"])
def test_misaligned_board_wavs_cannot_emit_delay_candidate(tmp_path, fault):
    """A weak positive echo must not mask a stronger noncausal alignment."""
    import subprocess
    import sys
    import wave

    rng = np.random.default_rng(996)
    speaker = rng.normal(0, 0.12, 64000)
    positive_echo = np.concatenate((np.zeros(1120), speaker))[:64000]
    if fault == "negative_lead":
        microphone = np.concatenate((speaker[960:], np.zeros(960))) + 0.45 * positive_echo
        message = "microphone leads speaker reference"
    else:
        microphone = positive_echo[:60000]
        message = "equal sample counts"
    with pytest.raises(ValueError, match=message):
        estimate_delay(speaker, microphone)
    for filename, samples in (("speaker.wav", speaker), ("mic.wav", microphone)):
        with wave.open(str(tmp_path / filename), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes((samples * 32767).astype("<i2").tobytes())
    script = Path(__file__).resolve().parents[1] / "scripts/estimate_aec_delay.py"
    result = subprocess.run([
        sys.executable, str(script), "--speaker", str(tmp_path / "speaker.wav"),
        "--microphone", str(tmp_path / "mic.wav"),
    ], capture_output=True, text=True)
    assert result.returncode != 0
    assert message in result.stderr
    assert not result.stdout


def test_capture_receipt_binds_same_length_wavs(tmp_path):
    import json

    capture = runpy.run_path(str(
        Path(__file__).resolve().parents[1] / "scripts/capture_sense_aec.py"
    ))
    rng = np.random.default_rng(71)
    speaker = rng.integers(-16000, 16000, 64000, dtype=np.int16)
    mic = np.concatenate((np.zeros(1120, dtype=np.int16), speaker[:-1120]))
    raw = np.column_stack((mic, speaker)).astype("<i2").tobytes()
    metadata = {
        "capture_source": "authenticated_sense_codec_private_pcm_window",
        "head_bearer_response_checked": True,
        "frames": 64000, "sample_rate_hz": 16000,
        "first_sample_us": 1, "last_sample_us": 4000001,
    }
    directory = tmp_path / "capture"
    capture["save_wavs"](directory, raw, metadata)
    read = source["read_wav"]
    validate = source["validate_capture_report"]
    ref, rate = read(directory / "speaker_reference.wav")
    received, mic_rate = read(directory / "microphone.wav")
    receipt = directory / "capture.json"
    validate(receipt, ref, rate, received, mic_rate)
    assert estimate_delay(ref, received)["sample_lag"] == 1120
    with pytest.raises(ValueError, match="digest mismatch"):
        validate(receipt, np.roll(ref, 1), rate, received, mic_rate)
    with pytest.raises(ValueError, match="digest mismatch"):
        validate(receipt, received, rate, ref, mic_rate)
    saved = json.loads(receipt.read_text())
    for key, value in (("last_sample_us", 9000001), ("frames", True),
                       ("microphone_pcm_sha256", None)):
        receipt.write_text(json.dumps({**saved, key: value}))
        with pytest.raises(ValueError, match="Sense capture report"):
            validate(receipt, ref, rate, received, mic_rate)
    receipt.write_text('{"frames": 64000, "frames": 64000}')
    with pytest.raises(ValueError, match="Duplicate"):
        validate(receipt, ref, rate, received, mic_rate)


@pytest.mark.parametrize("samples", [
    [1, -3, -4, 0, 1, 1, 0],
    [32767, -32768, -32768, 32767, 32767, -32768],
    [1, 1, 1, -1, -1, -1, 0, 0],
])
def test_sense_exact_integer_filter(samples):
    # Mirror the codec's reset phase and signed C++ integer division.
    expected = []
    previous2 = previous1 = previous_filtered = 0
    for index, sample in enumerate(samples):
        if index % 2 == 0:
            expected.append(previous_filtered)
        previous_filtered = int((previous2 + 2 * previous1 + sample) / 4)
        previous2, previous1 = previous1, sample
    actual = resample_reference(np.asarray(samples, dtype=np.float64) / 32768, 32000)
    np.testing.assert_array_equal(actual * 32768, expected)


@pytest.mark.parametrize("value", [np.nan, np.inf, -1.0001, 1.0])
def test_sense_reference_rejects_impossible_pcm(value):
    with pytest.raises(ValueError, match="PCM16"):
        resample_reference(np.array([0.0, value]), 32000)


@pytest.mark.parametrize("lo,hi", [(1.6, 2.7), (4.5, 5.5), (7.3, 8.4)])
def test_transient_latency_in_drift_window_gaps_is_rejected(lo, hi):
    rng = np.random.default_rng(8901)
    ref = rng.normal(0, 0.12, 160000)
    pos = np.arange(ref.size)
    delay = np.where((pos >= lo * 16000) & (pos < hi * 16000), 1240, 1120)
    mic = np.interp(pos - delay, pos, ref, left=0, right=0)
    # Global correlation still looks like a 70 ms echo despite the excursion.
    assert estimate_delay(ref, mic)["sample_lag"] == 1120
    with pytest.raises(ValueError, match="not a stable clock drift"):
        estimate_clock_drift(ref, mic)


@pytest.mark.parametrize("unstable", [True, False])
def test_cli_long_capture_requires_stable_drift_for_fixed_setting(tmp_path, unstable):
    import json
    import subprocess
    import sys
    import wave

    rng = np.random.default_rng(8901)
    ref = rng.integers(-6000, 6000, size=160000, dtype=np.int16)
    pos = np.arange(len(ref))
    delay = np.where((pos >= 25600) & (pos < 43200), 1240, 1120) if unstable else 1120
    mic = np.zeros_like(ref)
    idx = pos - delay
    mic[idx >= 0] = ref[idx[idx >= 0]]
    for name, samples in (("speaker.wav", ref), ("mic.wav", mic)):
        with wave.open(str(tmp_path / name), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(samples.astype("<i2").tobytes())
    script = Path(__file__).resolve().parents[1] / "scripts/estimate_aec_delay.py"
    result = subprocess.run([
        sys.executable, str(script), "--speaker", str(tmp_path / "speaker.wav"),
        "--microphone", str(tmp_path / "mic.wav"),
    ], capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    assert report["sample_lag"] == 1120
    assert report["esp_idf_delay_setting_applicable"] is not unstable
    assert report["esp_idf_delay_setting_ms"] == (None if unstable else 70)
    assert not report["aec_physically_verified"]
    assert not report["natural_barge_in_verified"]
