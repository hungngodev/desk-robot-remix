import pytest
from desk_robot.spatial_bracket import BracketError, validate_stationary_bracket
from desk_robot.spatial_pose import PoseFence


@pytest.mark.parametrize('delta', [0, 1, -1])
def test_intermediate_motion(delta):
    fence = PoseFence('robot-01')
    packet = dict(robot_id='robot-01', v=1, body_boot=9, origin=3, seq=1,
                  sample_us=1_000_000, x_mm=25, y_mm=-30, yaw_mrad=1000,
                  quality='valid', head_boot=12)
    fence.observe(packet, 100.0, request_started_at=99.99)
    before = fence.observe(dict(packet, seq=2, sample_us=1_100_000), 100.1,
                           request_started_at=100.09)
    fence.observe(dict(packet, seq=3, sample_us=1_200_000, x_mm=25 + delta),
                  100.2, request_started_at=100.19)
    after = fence.observe(dict(packet, seq=4, sample_us=1_300_000), 100.3,
                          request_started_at=100.27)
    kwargs = dict(fence=fence, before=before, after=after,
                  previous_camera=(12, 7, 9000), camera=(12, 8, 10000),
                  camera_received_at=100.2, stream_generation_before=1,
                  stream_generation_after=1, motion_epoch_before=4, motion_epoch_after=4,
                  disarmed_before=True, disarmed_after=True, now=100.31,
                  max_optical_lag_s=0.05, max_body_lag_s=0.05)
    if delta:
        with pytest.raises(BracketError, match='changed odometry'):
            validate_stationary_bracket(**kwargs)
    else:
        assert validate_stationary_bracket(**kwargs).odom_base.x_mm == 25
