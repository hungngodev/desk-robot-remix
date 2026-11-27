"""Malformed audio and observation inputs cannot update accepted state."""
from pathlib import Path

import pytest
from desk_robot.observation_policy import prepare_camera_receipt, receipt_age_is_current


@pytest.fixture
def audio(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "laptop/server/overlay"))
    import desk_robot_omni_audio

    return desk_robot_omni_audio


@pytest.mark.parametrize("invalid", [None, False, 0, "", "ab", [], [1, 2], bytearray(b"ab")])
def test_pcm_input_rejected_before_resampler(audio, invalid):
    calls = []

    def ratecv(chunk, *args):
        calls.append(args[-1])
        return chunk, (1, ((0, 0),))

    framer = audio.PcmOpusFramer(ratecv)
    framer.append(b"ab")
    with pytest.raises(ValueError):
        framer.append(invalid)
    framer.append(b"cd")
    assert calls == [None, (1, ((0, 0),))]
    assert framer.padded_tail() == b"abcd".ljust(audio.FRAME_BYTES, b"\0")


@pytest.mark.parametrize("invalid", [None, False, "ab", [1, 2], bytearray(b"ab")])
def test_pcm_output_rejected_without_advancing_state(audio, invalid):
    states = []

    def ratecv(chunk, *args):
        states.append(args[-1])
        if chunk == b"xx":
            return invalid, (99, ((0, 0),))
        return chunk, (1, ((0, 0),))

    framer = audio.PcmOpusFramer(ratecv)
    framer.append(b"ab")
    with pytest.raises(ValueError):
        framer.append(b"xx")
    framer.append(b"cd")
    assert states == [None, (1, ((0, 0),)), (1, ((0, 0),))]
    assert framer.padded_tail() == b"abcd".ljust(audio.FRAME_BYTES, b"\0")


@pytest.mark.parametrize("started,now", [(True, 2), (0, False), (0, float("nan")),
    (0, float("inf")), (float("-inf"), 0), (2, 1), (0, 10**400), ("0", 1),
    (-1e308, 1e308)])
def test_invalid_packet_clocks_rejected(audio, started, now):
    with pytest.raises(ValueError):
        audio.remaining_packet_delay(started, now)


@pytest.mark.parametrize("field", ["received_at", "now", "max_age"])
@pytest.mark.parametrize("invalid", [True, False, None, "10", float("nan"),
    float("inf"), float("-inf"), 10**400])
def test_invalid_receipt_fields_rejected(field, invalid):
    fields = {"received_at": 9, "now": 10, "max_age": 1}
    fields[field] = invalid
    assert not receipt_age_is_current(**fields)


@pytest.mark.parametrize("wall_now", [True, False, None, "10", float("nan"),
    float("inf"), float("-inf"), 10**400])
def test_invalid_wall_clock_rejected(wall_now):
    assert prepare_camera_receipt(robot_id="pet1", event_id="event", wall_now=wall_now,
        monotonic_now=10, received_at=9, max_age=1, source_identity=None) is None


def test_receipt_arithmetic_overflow_rejected():
    assert prepare_camera_receipt(robot_id="pet1", event_id="event", wall_now=-1e308,
        monotonic_now=1e308, received_at=0, max_age=1e308, source_identity=None) is None


def test_valid_boundaries_preserved(audio):
    assert audio.remaining_packet_delay(10, 10) == audio.FRAME_SECONDS
    assert audio.remaining_packet_delay(10, 11) == 0
    assert receipt_age_is_current(received_at=10, now=10, max_age=0)
    assert not receipt_age_is_current(received_at=10, now=10, max_age=-1)
    assert prepare_camera_receipt(robot_id="pet1", event_id="event", wall_now=100,
        monotonic_now=10, received_at=9, max_age=1, source_identity=None) == ("event", 99)
