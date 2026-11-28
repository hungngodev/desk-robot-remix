"""Exercise the offline LiveTurns adapter contract without a network or device."""

import pytest
from desk_robot.live_turns import LiveTurns


@pytest.mark.parametrize("invalid", [True, None, "2", 2.0, 1, 3])
def test_observation_completion_rejects_noncurrent_or_coerced_epoch(invalid):
    turns = LiveTurns(heartbeat_interval=1)
    turns.set_connected(True)
    turns.enable_proactivity(now=0)
    turns.offer_frame(b"jpeg", captured_at=1, now=1, connection_epoch=turns.connection_epoch)
    request = turns.poll_observation(now=1)
    assert request is not None
    assert request.epoch == 2
    assert not turns.finish_observation(invalid)
    assert turns.finish_observation(request.epoch)
    assert not turns.finish_observation(request.epoch)


def test_finished_generation_and_drained_host_queue_do_not_release_playback_owner():
    """Product definition, Yield: stay busy until adapter reports playback complete."""
    turns = LiveTurns(heartbeat_interval=1)
    turns.set_connected(True)
    turns.enable_proactivity(now=0)
    assert turns.offer_frame(
        b"first", captured_at=1, now=1, connection_epoch=turns.connection_epoch,
    )
    request = turns.poll_observation(now=1)
    assert request is not None
    assert turns.set_busy(request.epoch, model=True)
    assert turns.queue_audio(request.epoch, b"\x01\x00")
    assert turns.finish_observation(request.epoch)
    chunk = turns.pop_audio()
    assert chunk is not None and chunk.epoch == request.epoch
    assert turns.queued_audio_bytes == 0

    assert turns.offer_frame(b"next", captured_at=2, now=2, connection_epoch=turns.connection_epoch)
    assert turns.poll_observation(now=2) is None
    assert not turns.set_busy(request.epoch - 1, model=False)
    assert turns.poll_observation(now=2) is None

    # This represents the adapter's completion signal, not physical playback proof.
    assert turns.set_busy(request.epoch, model=False)
    following = turns.poll_observation(now=2)
    assert following is not None and following.epoch > request.epoch
    assert following.jpeg == b"next"
