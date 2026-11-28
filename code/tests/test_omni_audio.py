"""Codec state and pacing without a model, socket or real speaker."""
from pathlib import Path

import pytest


@pytest.fixture
def audio(monkeypatch):
    overlay = Path(__file__).resolve().parents[1] / "laptop/server/overlay"
    monkeypatch.syspath_prepend(str(overlay))
    import desk_robot_omni_audio

    return desk_robot_omni_audio


def test_frame_split_tail_and_reset(audio):
    states = []

    def ratecv(chunk, width, channels, source_rate, dest_rate, state):
        assert (width, channels, source_rate, dest_rate) == (2, 1, 24000, 16000)
        states.append(state)
        return chunk, (len(states), ((0, 0),))

    framer = audio.PcmOpusFramer(ratecv)
    assert framer.padded_tail() == b''
    framer.append(b'a' * 1000)
    assert not framer.has_frame()
    with pytest.raises(ValueError):
        framer.pop_frame()
    framer.append(b'b' * 1000)
    assert framer.has_frame()
    assert framer.pop_frame() == b'a' * 1000 + b'b' * 920
    assert not framer.has_frame()
    assert framer.padded_tail() == b'b' * 80 + b'\0' * 1840
    framer.reset()
    assert framer.padded_tail() == b''
    framer.append(b'c' * 1920)
    assert framer.pop_frame() == b'c' * 1920
    assert states == [None, (1, ((0, 0),)), None]


@pytest.mark.parametrize(('send_seconds', 'delay'), [(0.015, 0.045), (0.060, 0), (0.090, 0)])
def test_packet_delay_includes_socket_time(audio, send_seconds, delay):
    assert audio.remaining_packet_delay(100, 100 + send_seconds) == pytest.approx(delay)


def test_empty_and_invalid_input_preserve_resampler_state(audio):
    states = []

    def ratecv(chunk, width, channels, source_rate, dest_rate, state):
        states.append(state)
        return chunk, (len(states), ((0, 0),))

    framer = audio.PcmOpusFramer(ratecv)
    framer.append(b'')
    assert framer.padded_tail() == b''
    framer.append(b'ab')
    framer.append(b'')
    for invalid in (b'x', b'x' * 96002):
        with pytest.raises(ValueError):
            framer.append(invalid)
    assert framer.padded_tail() == b'ab' + b'\0' * 1918
    framer.append(b'cd')
    assert states == [None, (1, ((0, 0),))]


def test_backlog_requires_drain_before_append_or_tail(audio):
    calls = []

    def ratecv(chunk, width, channels, source_rate, dest_rate, state):
        assert (width, channels, source_rate, dest_rate) == (2, 1, 24000, 16000)
        calls.append((chunk, state))
        return chunk, (len(calls), ((0, 0),))

    framer = audio.PcmOpusFramer(ratecv)
    framer.append(b'a' * 1922)
    with pytest.raises(ValueError):
        framer.append(b'bc')
    with pytest.raises(ValueError):
        framer.padded_tail()
    assert calls == [(b'a' * 1922, None)]
    assert framer.pop_frame() == b'a' * 1920
    framer.append(b'bc')
    assert calls == [(b'a' * 1922, None), (b'bc', (1, ((0, 0),)))]
    assert framer.padded_tail() == b'aabc' + b'\0' * 1916


@pytest.mark.parametrize('invalid_output', [b'x', b'x' * 64002], ids=['odd', 'oversized'])
def test_invalid_resample_output_does_not_commit_state(audio, invalid_output):
    states = []

    def ratecv(chunk, width, channels, source_rate, dest_rate, state):
        states.append(state)
        if chunk == b'xx':
            return invalid_output, (99, ((0, 0),))
        return chunk, (1, ((0, 0),))

    framer = audio.PcmOpusFramer(ratecv)
    framer.append(b'ab')
    with pytest.raises(ValueError):
        framer.append(b'xx')
    framer.append(b'cd')
    assert states == [None, (1, ((0, 0),)), (1, ((0, 0),))]
    assert framer.padded_tail() == b'abcd' + b'\0' * 1916


def test_real_resampler_max_chunk_and_reset(audio):
    audioop = pytest.importorskip('audioop')
    framer = audio.PcmOpusFramer(audioop.ratecv)
    framer.append(b'\x01\x00' * 48000)
    frames = []
    while framer.has_frame():
        frames.append(framer.pop_frame())
    assert frames == [b'\x01\x00' * 960] * 33
    assert framer.padded_tail() == b'\x01\x00' * 320 + b'\0' * 1280
    framer.reset()
    assert framer.padded_tail() == b''
    # A cancellation/reset must not retain the prior response's PCM or phase.
    framer.append(b'\x02\x00' * 1440)
    assert framer.pop_frame() == b'\x02\x00' * 960
    assert framer.padded_tail() == b''
