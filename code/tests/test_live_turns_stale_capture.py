import pytest
from desk_robot.live_turns import LiveTurns


@pytest.mark.parametrize("clock", [float("nan"), float("inf"), 10**400, None])
@pytest.mark.parametrize("field", ["captured_at", "now"])
def test_retired_camera_rejects_invalid_clock_before_payload_validation(clock, field):
    value = LiveTurns()
    value.set_connected(True)
    retired = value.connection_epoch
    value.set_connected(False)
    value.set_connected(True)
    current = value.connection_epoch
    assert value.offer_frame(b"current", captured_at=2, now=2, connection_epoch=current)
    times = {"captured_at": 2, "now": 2}
    times[field] = clock
    assert not value.offer_frame(b"", connection_epoch=retired, **times)
    with pytest.raises(ValueError, match="finite monotonic"):
        value.offer_frame(b"", connection_epoch=current, **times)
    assert value.take_video_frame(now=2).jpeg == b"current"
