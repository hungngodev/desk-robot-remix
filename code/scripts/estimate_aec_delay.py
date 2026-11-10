"""Offline speaker/microphone delay measurement for the reused RIO AEC pathway.

This does not perform AEC and does not imply a physically qualified robot.
Speaker and microphone WAV files must represent aligned actual board capture.
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
                or rate not in (16000, 24000) or not 320 <= count <= 240000):
            raise ValueError("Need mono PCM16, 16 or 24 kHz, up to ten seconds")
        samples = np.frombuffer(file.readframes(count), dtype="<i2").astype(np.float64)
    return samples / 32768, rate


def resample_reference(source: np.ndarray, original_rate: int) -> np.ndarray:
    if original_rate == 16000:
        return source
    if original_rate != 24000:
        raise ValueError("Unsupported speaker sample rate")
    # Offline rough estimate. The actual device uses a stateful resampler.
    ticks = np.arange(round(len(source) * 2 / 3)) * 1.5
    return np.interp(ticks, np.arange(len(source)), source)


def estimate_delay(
    reference: np.ndarray, microphone: np.ndarray,
    *, sample_rate: int = 16000, max_delay_ms: float = 250,
) -> dict:
    """Positive lag is microphone capture after actual loudspeaker playback."""
    if sample_rate != 16000 or not 10 <= max_delay_ms <= 400:
        raise ValueError("Measure 16 kHz capture with 10 to 400 ms search")
    if (not isinstance(reference, np.ndarray)
            or not isinstance(microphone, np.ndarray)
            or reference.ndim != 1 or microphone.ndim != 1
            or min(len(reference), len(microphone)) < 320
            or max(len(reference), len(microphone)) > 160000):
        raise ValueError("Expected bounded one-channel arrays")
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
    lag_limit = min(round(sample_rate * max_delay_ms / 1000), len(mic) - 1)
    lag = int(np.argmax(np.abs(corr[:lag_limit + 1])))
    confidence = float(abs(corr[lag]) / (ref_energy * mic_energy))
    if not math.isfinite(confidence) or confidence < 0.15:
        raise ValueError("Playback and microphone capture insufficiently correlated")
    return {
        "reference_delay_ms": round(lag * 1000 / sample_rate, 3),
        "sample_lag": lag,
        "normalized_correlation": round(confidence, 4),
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
    report = estimate_delay(
        resample_reference(speaker, speaker_rate), microphone,
        max_delay_ms=args.max_delay_ms,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
