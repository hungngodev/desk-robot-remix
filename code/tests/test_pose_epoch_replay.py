import pytest
from desk_robot.spatial_pose import PoseError, PoseFence


def packet(seq, *, body=9, origin=3, head=12):
    return dict(robot_id="robot-01", v=1, body_boot=body, origin=origin,
                seq=seq, sample_us=seq * 100_000, x_mm=0, y_mm=0,
                yaw_mrad=0, quality="valid" if origin else "unavailable",
                head_boot=head)


def observe(fence, seq, **kwargs):
    return fence.observe(packet(seq, **kwargs), 100 + seq / 10)


def transition(fence, seq, **kwargs):
    with pytest.raises(PoseError, match="re-anchor"):
        observe(fence, seq, **kwargs)
    assert fence.current(100 + seq / 10) is None


@pytest.mark.parametrize("changed,replay", [
    ({"origin": 4}, {"head": 13}),
    ({"body": 10}, {"head": 13}),
    ({"head": 13}, {"origin": 4}),
])
def test_retired_identity_cannot_be_recombined(changed, replay):
    fence = PoseFence("robot-01")
    observe(fence, 1)
    original = observe(fence, 2)
    transition(fence, 3, **changed)
    observe(fence, 4, **changed)
    observe(fence, 5, **changed)
    assert fence.current(100.5) is not None
    for seq in (6, 7, 8):
        with pytest.raises(PoseError, match="Retired or failed"):
            observe(fence, seq, **replay)
        assert fence.current(100 + seq / 10) is None
    assert not fence.owns_continuous_receipt(original)


def test_zero_origin_can_report_repeated_pickup_without_reusing_old_origin():
    fence = PoseFence("robot-01")
    observe(fence, 1)
    observe(fence, 2)
    transition(fence, 3, origin=0)
    assert observe(fence, 4, origin=0).quality == "unavailable"
    transition(fence, 5, origin=4)
    observe(fence, 6, origin=4)
    observe(fence, 7, origin=4)
    transition(fence, 8, origin=0)
    assert observe(fence, 9, origin=0).quality == "unavailable"
    assert fence.current(100.9) is None
    transition(fence, 10, origin=5)
    observe(fence, 11, origin=5)
    current = observe(fence, 12, origin=5)
    assert fence.current(101.2) is current
    with pytest.raises(PoseError, match="Retired or failed"):
        observe(fence, 13, origin=4, head=13)


@pytest.mark.parametrize("changed", [{"head": 13}, {"origin": 4}])
def test_body_clock_does_not_restart_when_only_head_or_origin_changes(changed):
    fence = PoseFence("robot-01")
    observe(fence, 1)
    observe(fence, 2)
    with pytest.raises(PoseError, match="sequence"):
        fence.observe(packet(1, **changed), 100.3)
    assert fence.last.seq == 2
    assert fence.current(100.3) is None
    transition(fence, 4, **changed)
    observe(fence, 5, **changed)
    current = observe(fence, 6, **changed)
    assert fence.current(100.6) is current
