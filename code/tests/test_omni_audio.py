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
