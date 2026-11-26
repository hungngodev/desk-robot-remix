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
