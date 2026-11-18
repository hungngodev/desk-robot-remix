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
