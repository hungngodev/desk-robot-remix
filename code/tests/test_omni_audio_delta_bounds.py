"""Bound native model PCM without allocating oversized decoded audio."""
import base64

import pytest
from desk_robot import realtime_omni_protocol as protocol


@pytest.mark.parametrize("size", [0, 3, 96_001])
def test_invalid_pcm_size(size):
    encoded = base64.b64encode(bytes(size)).decode("ascii")
    with pytest.raises(ValueError):
        protocol._decode_audio_delta(encoded, max_bytes=96_000)


def test_audio_at_exact_limit_is_accepted():
    pcm = bytes(96_000)
    encoded = base64.b64encode(pcm).decode("ascii")
    assert protocol._decode_audio_delta(encoded, max_bytes=96_000) == pcm


def test_oversized_encoded_delta_is_rejected_before_decode(monkeypatch):
    def unexpected_decode(*args, **kwargs):
        pytest.fail("Oversized audio must not reach the decoder")

    monkeypatch.setattr(protocol.base64, "b64decode", unexpected_decode)
    with pytest.raises(ValueError, match="Unbounded"):
        protocol._decode_audio_delta("A" * 128_004, max_bytes=96_000)


def test_empty_encoded_delta_is_rejected_before_decode(monkeypatch):
    def unexpected_decode(*args, **kwargs):
        pytest.fail("Empty audio must not reach the decoder")

    monkeypatch.setattr(protocol.base64, "b64decode", unexpected_decode)
    with pytest.raises(ValueError, match="Malformed"):
        protocol._decode_audio_delta("", max_bytes=96_000)
