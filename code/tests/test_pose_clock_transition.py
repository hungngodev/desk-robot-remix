import pytest
from desk_robot.spatial_pose import PoseError, PoseFence


def packet(seq, sample_us, **changes):
    data = dict(robot_id="robot-01", v=1, body_boot=9, origin=3, head_boot=12,
                seq=seq, sample_us=sample_us, x_mm=0, y_mm=0, yaw_mrad=0,
                quality="valid")
    data.update(changes)
    return data


@pytest.mark.parametrize("identity", [{"origin": 4}, {"head_boot": 13}])
def test_same_body_boot_transition_does_not_erase_accumulated_lag(identity):
    fence = PoseFence("robot-01")
    fence.observe(packet(1, 1_000_000), 100.0)
    fence.observe(packet(2, 1_100_000), 100.2)
    with pytest.raises(PoseError, match="re-anchor"):
        fence.observe(packet(3, 1_200_000, **identity), 100.5)
    for seq, stamp, sample in [(4, 100.6, 1_300_000), (5, 100.7, 1_400_000)]:
        with pytest.raises(PoseError, match="lags"):
            fence.observe(packet(seq, sample, **identity), stamp)
        assert fence.current(stamp) is None
    fence.observe(packet(6, 1_800_000, **identity), 100.8)
    fresh = fence.observe(packet(7, 1_900_000, **identity), 100.9)
    assert fence.current(100.9) is fresh
    assert fence.needs_reanchor


@pytest.mark.parametrize("identity", [{"origin": 4}, {"head_boot": 13}])
def test_same_body_boot_transition_rejects_implausible_clock_jump(identity):
    fence = PoseFence("robot-01")
    fence.observe(packet(1, 1_000_000), 100.0)
    fence.observe(packet(2, 1_100_000), 100.1)
    with pytest.raises(PoseError, match="implausibly"):
        fence.observe(packet(3, 20_000_000, **identity), 100.2)
    assert fence.current(100.2) is None
    assert fence.last.seq == 2
    with pytest.raises(PoseError, match="re-anchor"):
        fence.observe(packet(4, 1_300_000, **identity), 100.3)
    fence.observe(packet(5, 1_400_000, **identity), 100.4)
    fresh = fence.observe(packet(6, 1_500_000, **identity), 100.5)
    assert fence.current(100.5) is fresh
