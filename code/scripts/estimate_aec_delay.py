"""Offline speaker/microphone delay measurement for the reused RIO AEC pathway.

This does not perform AEC and does not imply a physically qualified robot.
Speaker and microphone WAV files must represent aligned actual board capture.
For the Sense, use capture_sense_aec.py with the private zero-delay bench image;
see docs/guides/audio-barge-in.md for acquisition and physical acceptance.
"""
from __future__ import annotations

import argparse
import json
import math
import wave
from pathlib import Path

import numpy as np


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    if not path.is_file() or path.stat().st_size > 12_000_000:
        raise ValueError("WAV file missing or too large")
    with wave.open(str(path), "rb") as file:
        rate = file.getframerate()
        count = file.getnframes()
        if (file.getnchannels() != 1 or file.getsampwidth() != 2
                or rate not in (16000, 24000, 32000)
                or not rate // 50 <= count <= 10 * rate):
            raise ValueError("WAV needs mono PCM16 at 16, 24 or 32 kHz, from 20 ms to ten seconds")
        # wave rounds an odd data-chunk byte count down to whole frames.
        # Read one extra frame to detect a trailing incomplete PCM16 sample.
        pcm = file.readframes(count + 1)
        if len(pcm) < 2 * count:
            raise ValueError("WAV file truncated: header frame count exceeds PCM data")
        if len(pcm) != 2 * count:
            raise ValueError("WAV contains incomplete PCM16 sample")
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    return samples / 32768, rate


def resample_reference(source: np.ndarray, original_rate: int) -> np.ndarray:
    if original_rate == 16000:
        return source
    if original_rate == 32000:
        # Match the selected Sense 3-tap 32-to-16 kHz AEC reference phase.
        # Real acoustic delay still requires synchronized board recordings.
        values = np.asarray(source, dtype=np.float64)
        if values.ndim != 1 or len(values) < 2:
            raise ValueError("Need mono speaker PCM")
        padded = np.pad(values, (2, 0))
        filtered = (padded[:-2] + 2 * padded[1:-1] + padded[2:]) / 4.0
        return np.concatenate((np.zeros(1), filtered[1:-1:2]))
    if original_rate != 24000:
        raise ValueError("Unsupported speaker sample rate")
    # Historical RIO captures at 24 kHz remain supported.
    ticks = np.arange(round(len(source) * 2 / 3)) * 1.5
    return np.interp(ticks, np.arange(len(source)), source)


def estimate_delay(
    reference: np.ndarray, microphone: np.ndarray,
    *, sample_rate: int = 16000, max_delay_ms: float = 250,
) -> dict:
    """Positive lag is microphone capture after the supplied reference."""
    if sample_rate != 16000 or not 10 <= max_delay_ms <= 400:
        raise ValueError("Measure 16 kHz capture with 10 to 400 ms search")
    if (not isinstance(reference, np.ndarray)
            or not isinstance(microphone, np.ndarray)
            or reference.ndim != 1 or microphone.ndim != 1
            or min(len(reference), len(microphone)) < 320
            or max(len(reference), len(microphone)) > 160000):
        raise ValueError("Expected bounded one-channel arrays")
    # A 20 ms frame cannot establish a delay over a requested 250 ms
    # search window. Leave 100 ms of captured signal after the largest
    # candidate lag instead of silently clipping the search to array length.
    requested_lag = round(sample_rate * max_delay_ms / 1000)
    if min(len(reference), len(microphone)) < requested_lag + sample_rate // 10:
        raise ValueError(
            "Audio capture too short for requested delay search and 100 ms tail"
        )
    if len(reference) != len(microphone):
        raise ValueError("Aligned reference and microphone need equal sample counts")
    if not np.isfinite(reference).all() or not np.isfinite(microphone).all():
        raise ValueError("Nonfinite audio samples")
    ref = reference.astype(np.float64, copy=False)
    mic = microphone.astype(np.float64, copy=False)
    ref, mic = ref - ref.mean(), mic - mic.mean()
    ref_energy = float(np.linalg.norm(ref))
    mic_energy = float(np.linalg.norm(mic))
    if ref_energy < 0.0001 or mic_energy < 0.0001:
        raise ValueError("Acoustic signal insufficient")
    size = len(ref) + len(mic) - 1
    nfft = 1 << (size - 1).bit_length()
    corr = np.fft.irfft(
        np.fft.rfft(mic, nfft) * np.conj(np.fft.rfft(ref, nfft)),
        nfft,
    )
    # Normalize each FFT lag using only its overlapping samples. Whole-clip
    # energy penalizes long delays and unrelated noise outside the overlap.
    # Prefix sums give the local Pearson coefficient without a per-lag scan.
    # The capture-length check above guarantees at least 100 ms per candidate.
    # Include negative lags so a misaligned reference cannot hide a
    # dominant microphone lead behind a weaker positive correlation peak.
    lags = np.arange(-requested_lag, requested_lag + 1)
    ref_starts = np.maximum(-lags, 0)
    mic_starts = np.maximum(lags, 0)
    counts = np.minimum(len(ref) - ref_starts, len(mic) - mic_starts)

    def overlap_stats(values, starts, ends):
        sums = np.concatenate(([0.0], np.cumsum(values)))
        squares = np.concatenate(([0.0], np.cumsum(values * values)))
        total = sums[ends] - sums[starts]
        energy = np.maximum(
            squares[ends] - squares[starts] - total * total / counts, 0.0,
        )
        return total, energy

    ref_sum, ref_variance = overlap_stats(ref, ref_starts, ref_starts + counts)
    mic_sum, mic_variance = overlap_stats(mic, mic_starts, mic_starts + counts)
    covariance = corr[lags % nfft] - ref_sum * mic_sum / counts
    denominator = np.sqrt(ref_variance * mic_variance)
    strength = np.divide(
        np.abs(covariance), denominator, out=np.zeros_like(denominator),
        where=(ref_variance >= 1e-8) & (mic_variance >= 1e-8),
    )
    strength = np.clip(strength, 0.0, 1.0)
    peak_index = int(np.argmax(strength))
    lag = int(lags[peak_index])
    peak = float(strength[peak_index])
    confidence = peak
    if not math.isfinite(confidence) or confidence < 0.15:
        raise ValueError("Playback and microphone capture insufficiently correlated")
    # One confidently correlated peak does not make the delay identifiable:
    # periodic tones and equally loud echoes generate several plausible lags.
    # Exclude the 1 ms neighbourhood of the best peak (filter sidelobes),
    # then fail closed when a separate echo is nearly as strong. Physical
    # AEC setup must use a broadband stimulus with a unique correlation peak.
    alternate = strength.copy()
    guard = sample_rate // 1000
    alternate[max(0, peak_index - guard):peak_index + guard + 1] = 0
    if float(alternate.max()) >= 0.90 * peak:
        raise ValueError("Ambiguous acoustic delay: periodic tone or competing echo")
    if lag < 0:
        raise ValueError("Misaligned capture: microphone leads speaker reference")
    samples_per_ms = sample_rate // 1000
    setting_applicable = lag <= 250 * samples_per_ms
    # Kconfig accepts integer milliseconds; round half up from exact samples.
    # Do not round an out-of-range measurement back into an accepted setting.
    setting_ms = ((lag + samples_per_ms // 2) // samples_per_ms
                  if setting_applicable else None)
    return {
        "reference_delay_ms": round(lag * 1000 / sample_rate, 3),
        "sample_lag": lag,
        "normalized_correlation": round(confidence, 4),
        # Sense Kconfig only accepts 0..250 ms. Larger measured delays
        # remain useful diagnostics but cannot be copied into the build.
        "esp_idf_delay_setting_applicable": setting_applicable,
        "esp_idf_delay_setting_ms": setting_ms,
        "esp_idf_delay_max_ms": 250,
        "aec_physically_verified": False,
        "natural_barge_in_verified": False,
    }


def estimate_clock_drift(
    reference: np.ndarray, microphone: np.ndarray, *,
    sample_rate: int = 16000, max_delay_ms: float = 250,
) -> dict:
    """Estimate relative clock slip from four spaced audio time windows.

    A single global cross-correlation lag cannot expose gradual speaker to
    microphone drift. Windows share the same original sample timeline; never
    re-align them before calculating the slope. An irregular lag trajectory
    is NOT a clock estimate and must fail rather than silently fit a line.
    This is diagnostic only, not verified hardware AEC or barge-in.
    """
    if (sample_rate != 16000 or type(max_delay_ms) not in (int, float)
            or not math.isfinite(max_delay_ms)
            or not 10 <= max_delay_ms <= 400
            or not isinstance(reference, np.ndarray)
            or not isinstance(microphone, np.ndarray)
            or reference.ndim != 1 or microphone.ndim != 1
            or len(reference) != len(microphone)
            or not 4 * sample_rate <= len(reference) <= 10 * sample_rate):
        raise ValueError("Clock drift needs 4-10 seconds of aligned 16 kHz recordings")
    if not np.isfinite(reference).all() or not np.isfinite(microphone).all():
        raise ValueError("Nonfinite clock drift input")
    window = sample_rate * 3 // 2
    span = len(reference) - window
    starts = [0, span // 3, 2 * span // 3, span]
    lags = []
    correlations = []
    for start in starts:
        result = estimate_delay(
            reference[start:start + window],
            microphone[start:start + window],
            sample_rate=sample_rate, max_delay_ms=max_delay_ms,
        )
        lags.append(result["sample_lag"])
        correlations.append(result["normalized_correlation"])
    # Least-squares slope in samples of lag per sample of recording time.
    t = np.asarray(starts, dtype=np.float64)
    y = np.asarray(lags, dtype=np.float64)
    centered = t - t.mean()
    slope = float(np.dot(centered, y - y.mean()) / np.dot(centered, centered))
    predicted = y.mean() + slope * centered
    residual = float(np.max(np.abs(predicted - y)))
    if not math.isfinite(slope) or residual > 3.0:
        raise ValueError("Changing acoustic delay is not a stable clock drift")
    ppm = slope * 1_000_000.0
    return {
        "clock_drift_ppm_estimate": round(ppm, 1),
        "clock_drift_window_lags_samples": lags,
        "clock_drift_min_correlation": round(min(correlations), 4),
        "clock_drift_max_fit_residual_samples": round(residual, 2),
        "clock_drift_needs_hardware_review": abs(ppm) > 100,
        "clock_drift_status": "offline_estimate_not_hardware_qualified",
        "aec_physically_verified": False,
        "natural_barge_in_verified": False,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--speaker", required=True, type=Path)
    cli.add_argument("--microphone", required=True, type=Path)
    cli.add_argument("--max-delay-ms", type=float, default=250.0)
    args = cli.parse_args()
    speaker, speaker_rate = read_wav(args.speaker)
    microphone, mic_rate = read_wav(args.microphone)
    if mic_rate != 16000:
        raise ValueError("Microphone recording must be 16 kHz")
    reference = resample_reference(speaker, speaker_rate)
    report = estimate_delay(
        reference, microphone, max_delay_ms=args.max_delay_ms,
    )
    try:
        report.update(estimate_clock_drift(
            reference, microphone, max_delay_ms=args.max_delay_ms,
        ))
    except ValueError as exc:
        # No drift number is better than a fabricated estimate from silence,
        # abrupt latency jumps or insufficient evidence.
        report.update({
            "clock_drift_ppm_estimate": None,
            "clock_drift_status": "unavailable",
            "clock_drift_reason": str(exc),
            "aec_physically_verified": False,
            "natural_barge_in_verified": False,
        })
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
