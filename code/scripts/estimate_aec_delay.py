"""Offline speaker/microphone delay measurement for the reused RIO AEC pathway.

This does not perform AEC and does not imply a physically qualified robot.
Speaker and microphone WAV files must represent aligned actual board capture.
For the Sense, use capture_sense_aec.py with the private zero-delay bench image;
see docs/guides/audio-barge-in.md for acquisition and physical acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import wave
from pathlib import Path

import numpy as np

# Numerical floor for mean-centered normalized PCM, not a measured noise gate.
MIN_SIGNAL_RMS = 1e-4


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    try:
        return _read_pcm_wav(path)
    except (wave.Error, EOFError) as exc:
        raise ValueError("Invalid or incomplete WAV header") from exc


def _read_pcm_wav(path: Path) -> tuple[np.ndarray, int]:
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


def validate_capture_report(
    path: Path, speaker: np.ndarray, speaker_rate: int,
    microphone: np.ndarray, mic_rate: int,
) -> None:
    """Match exported PCM to its local receipt, not a physical attestation."""
    with path.open("rb") as file:
        raw = file.read(8193)
    if len(raw) > 8192:
        raise ValueError("Sense capture report too large")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate Sense capture report field")
            result[key] = value
        return result

    receipt = json.loads(raw, object_pairs_hook=unique_keys)
    if not isinstance(receipt, dict):
        raise ValueError("Invalid Sense capture report")
    first, last = receipt.get("first_sample_us"), receipt.get("last_sample_us")
    if (receipt.get("capture_source") != "authenticated_sense_codec_private_pcm_window"
            or receipt.get("head_bearer_response_checked") is not True
            or type(receipt.get("frames")) is not int
            or receipt["frames"] != 64000
            or type(receipt.get("sample_rate_hz")) is not int
            or receipt["sample_rate_hz"] != 16000
            or speaker_rate != 16000 or mic_rate != 16000
            or len(speaker) != 64000 or len(microphone) != 64000
            or type(first) is not int or type(last) is not int
            or not 1 <= first < last <= 2**63 - 1
            or not 3_920_000 <= last - first <= 4_080_000):
        raise ValueError("Invalid Sense capture report format or timing")
    for key, samples in (("microphone_pcm_sha256", microphone),
                         ("speaker_reference_pcm_sha256", speaker)):
        digest = hashlib.sha256((samples * 32768).astype("<i2").tobytes()).hexdigest()
        if receipt.get(key) != digest:
            raise ValueError("Sense capture report PCM digest mismatch")


def resample_reference(source: np.ndarray, original_rate: int) -> np.ndarray:
    if original_rate == 16000:
        return source
    if original_rate == 32000:
        # Mirror ReferenceDecimator's causal Q15 FIR, zero history and even phase.
        values = np.asarray(source, dtype=np.float64)
        if values.ndim != 1 or len(values) < 2:
            raise ValueError("Need mono speaker PCM")
        if not np.isfinite(values).all() or np.any(
            (values < -1.0) | (values > 32767 / 32768)
        ):
            raise ValueError("Speaker reference must contain finite normalized PCM16")
        half = np.array([
            1, 15, 21, -1, -34, -19, 43, 57, -34, -106, -9, 151, 96, -163, -221, 111,
            362, 35, -475, -291, 497, 649, -350, -1078, -64, 1519, 908, -1906,
            -2698, 2170, 10158,
        ], dtype=np.int64)
        taps = np.concatenate((half, [14080], half[::-1]))
        pcm = np.rint(values * 32768).astype(np.int64)
        sums = np.convolve(pcm, taps, mode="full")[:len(pcm):2]
        rounded = np.sign(sums) * ((np.abs(sums) + 16384) // 32768)
        return np.clip(rounded, -32768, 32767) / 32768
    if original_rate != 24000:
        raise ValueError("Unsupported speaker sample rate")
    # Historical RIO captures at 24 kHz remain supported.
    ticks = np.arange(round(len(source) * 2 / 3)) * 1.5
    return np.interp(ticks, np.arange(len(source)), source)


def _reject_saturated_pcm(samples: np.ndarray, channel: str) -> None:
    """Fail closed at either PCM16 rail; clipping obscures the acoustic signal."""
    if np.any((samples <= -1.0) | (samples >= 32767 / 32768)):
        raise ValueError(f"{channel} contains clipped or out-of-range PCM16 samples")


def _peak_lag_and_correlation(
    reference: np.ndarray, microphone: np.ndarray, *,
    sample_rate: int, max_delay_ms: float,
) -> tuple[int, float, float]:
    """Return integer lag, parabolic sub-sample lag, and overlap Pearson correlation."""
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
    _reject_saturated_pcm(reference, "Speaker reference")
    _reject_saturated_pcm(microphone, "Microphone")
    ref = reference.astype(np.float64, copy=False)
    mic = microphone.astype(np.float64, copy=False)
    ref, mic = ref - ref.mean(), mic - mic.mean()
    ref_rms = float(np.linalg.norm(ref)) / math.sqrt(len(ref))
    mic_rms = float(np.linalg.norm(mic)) / math.sqrt(len(mic))
    if ref_rms < MIN_SIGNAL_RMS:
        raise ValueError("Speaker reference acoustic signal insufficient")
    if mic_rms < MIN_SIGNAL_RMS:
        raise ValueError("Microphone acoustic signal insufficient")
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
    # Each candidate needs signal in both overlapping windows, not just the clip.
    min_energy = counts * MIN_SIGNAL_RMS**2
    strength = np.divide(
        np.abs(covariance), denominator, out=np.zeros_like(denominator),
        where=(ref_variance >= min_energy) & (mic_variance >= min_energy),
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
    fractional_lag = float(lag)
    if 0 < peak_index < len(strength) - 1:
        denom = float(
            strength[peak_index - 1] - 2.0 * strength[peak_index] + strength[peak_index + 1]
        )
        if denom < -1e-12:
            delta = 0.5 * float(strength[peak_index - 1] - strength[peak_index + 1]) / denom
            if abs(delta) <= 0.5 and fractional_lag + delta >= 0.0:
                fractional_lag += delta
    return lag, fractional_lag, confidence


def estimate_delay(
    reference: np.ndarray, microphone: np.ndarray,
    *, sample_rate: int = 16000, max_delay_ms: float = 250,
) -> dict:
    """Positive lag is microphone capture after the supplied reference."""
    if (sample_rate != 16000 or type(max_delay_ms) not in (int, float)
            or not 10 <= max_delay_ms <= 400):
        raise ValueError("Measure 16 kHz capture with finite delay search of 10 to 400 ms")
    if (not isinstance(reference, np.ndarray)
            or not isinstance(microphone, np.ndarray)
            or reference.ndim != 1 or microphone.ndim != 1
            or min(len(reference), len(microphone)) < 320
            or max(len(reference), len(microphone)) > 160000):
        raise ValueError("Expected bounded one-channel arrays")
    lag, _, confidence = _peak_lag_and_correlation(
        reference, microphone, sample_rate=sample_rate, max_delay_ms=max_delay_ms,
    )
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
            or not 10 <= max_delay_ms <= 400
            or not isinstance(reference, np.ndarray)
            or not isinstance(microphone, np.ndarray)
            or reference.ndim != 1 or microphone.ndim != 1
            or len(reference) != len(microphone)
            or not 4 * sample_rate <= len(reference) <= 10 * sample_rate):
        raise ValueError("Clock drift needs 4-10 seconds of aligned 16 kHz recordings")
    if not np.isfinite(reference).all() or not np.isfinite(microphone).all():
        raise ValueError("Nonfinite clock drift input")
    # Use 1.0 s windows on short 4-5 s captures to keep the time baseline wide
    # enough for sub-25 ppm slip estimation, expanding up to 1.5 s on longer captures.
    window = min(sample_rate * 3 // 2, max(sample_rate, len(reference) // 4))
    span = len(reference) - window
    starts = [0, span // 3, 2 * span // 3, span]
    lags = []
    correlations = []
    for start in starts:
        _, frac_lag, confidence = _peak_lag_and_correlation(
            reference[start:start + window],
            microphone[start:start + window],
            sample_rate=sample_rate, max_delay_ms=max_delay_ms,
        )
        lags.append(frac_lag)
        correlations.append(confidence)
    # Least-squares slope in samples of lag per sample of recording time.
    # For short 4-5 s captures, a fractional parabolic lag error can shift ppm;
    # keep explicit duration uncertainty bounds so callers see the resolution.
    t = np.asarray(starts, dtype=np.float64)
    y = np.asarray(lags, dtype=np.float64)
    centered = t - t.mean()
    slope = float(np.dot(centered, y - y.mean()) / np.dot(centered, centered))
    predicted = y.mean() + slope * centered
    residual = float(np.max(np.abs(predicted - y)))
    if not math.isfinite(slope) or residual > 3.0:
        raise ValueError("Changing acoustic delay is not a stable clock drift")
    # Long recordings leave blind intervals between the primary windows.
    # Probe the midpoint of each gap with the same correlation estimator;
    # reject an ambiguous or inconsistent local delay before reporting drift.
    for left, right in zip(starts[:-1], starts[1:], strict=True):
        if right - left <= window:
            continue
        start = (left + right) // 2
        try:
            _, frac_lag, confidence = _peak_lag_and_correlation(
                reference[start:start + window], microphone[start:start + window],
                sample_rate=sample_rate, max_delay_ms=max_delay_ms,
            )
        except ValueError as exc:
            raise ValueError("Changing acoustic delay is not a stable clock drift") from exc
        expected = y.mean() + slope * (start - t.mean())
        residual = max(residual, abs(frac_lag - expected))
        correlations.append(confidence)
        if residual > 3.0:
            raise ValueError("Changing acoustic delay is not a stable clock drift")
    ppm = slope * 1_000_000.0
    duration_s = len(reference) / sample_rate
    # Empirically, smoothed broadband peaks have ~1.6-sample endpoint variance;
    # 4-5 s captures cannot guarantee sub-25 ppm slip resolution while 10 s does.
    uncertainty_ppm = round(1.6 / max(span, 1) * 1_000_000.0, 1)
    within_25ppm_bound = uncertainty_ppm <= 25.0
    return {
        "clock_drift_ppm_estimate": round(ppm, 1),
        "clock_drift_uncertainty_ppm": uncertainty_ppm,
        "clock_drift_within_25ppm_bound": within_25ppm_bound,
        "clock_drift_capture_seconds": round(duration_s, 3),
        "clock_drift_window_lags_samples": [round(lag, 3) for lag in lags],
        "clock_drift_min_correlation": round(min(correlations), 4),
        "clock_drift_max_fit_residual_samples": round(residual, 2),
        "clock_drift_needs_hardware_review": abs(ppm) > 100,
        "clock_drift_status": (
            "offline_estimate_not_hardware_qualified"
            if within_25ppm_bound
            else "short_capture_exceeds_25ppm_uncertainty_bound"
        ),
        "aec_physically_verified": False,
        "natural_barge_in_verified": False,
    }


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--speaker", required=True, type=Path)
    cli.add_argument("--microphone", required=True, type=Path)
    cli.add_argument("--capture-report", type=Path)
    cli.add_argument("--max-delay-ms", type=float, default=250.0)
    args = cli.parse_args()
    try:
        report = _estimate_capture(args)
    except (ValueError, OSError) as exc:
        print(json.dumps({
            "error": "invalid_aec_capture",
            "message": str(exc),
            "aec_physically_verified": False,
            "natural_barge_in_verified": False,
        }), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


def _estimate_capture(args: argparse.Namespace) -> dict:
    speaker, speaker_rate = read_wav(args.speaker)
    microphone, mic_rate = read_wav(args.microphone)
    if mic_rate != 16000:
        raise ValueError("Microphone recording must be 16 kHz")
    if speaker_rate == 32000 and len(speaker) != 2 * len(microphone):
        raise ValueError("Raw 32 kHz speaker and 16 kHz microphone need equal sample counts "
                         "after exact 2:1 conversion")
    if args.capture_report is not None:
        validate_capture_report(args.capture_report, speaker, speaker_rate, microphone, mic_rate)
    # Resampling can hide a saturated raw speaker sample.
    _reject_saturated_pcm(speaker, "Speaker reference")
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
        # Preserve short-clip diagnostic compatibility, but a complete
        # four-second or longer trial with failed drift validation must not
        # advertise a copyable fixed delay setting.
        if len(reference) >= 4 * 16000:
            report["esp_idf_delay_setting_applicable"] = False
            report["esp_idf_delay_setting_ms"] = None
    # A stable slope can still exceed the existing hardware review threshold.
    # Keep the measured delay diagnostic but do not recommend a fixed setting.
    if report.get("clock_drift_needs_hardware_review"):
        report["esp_idf_delay_setting_applicable"] = False
        report["esp_idf_delay_setting_ms"] = None
    report["capture_report_pcm_matched"] = args.capture_report is not None
    return report


if __name__ == "__main__":
    raise SystemExit(main())
