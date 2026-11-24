from dataclasses import replace

import pytest
from desk_robot.spatial_grid import (
    CELL_MM,
    GridEvidenceError,
    RangeCellBatch,
    SpatialGrid,
)


def grid():
    return SpatialGrid(
        "robot-01", 7, "odom-1", "tag-4", "camera-abc", 4, 3,
        ttl_us=1_000_000,
    )


def evidence(kind, lane, seq=1, *, received_us=1_000_000, cells=((1, 1),)):
    return RangeCellBatch(
        "robot-01", 7, "odom-1", 0, "camera-abc", lane, seq,
        seq * 100_000, received_us, kind, cells, True,
    )


def test_only_fresh_floor_and_forward_clearance_can_make_a_safe_cell():
    g = grid()
    assert g.state(1, 1, now_us=1_000_010) == "unknown"
    g.record(evidence("floor_supported", 0), now_us=1_000_010)
    assert g.state(1, 1, now_us=1_000_010) == "unknown"
    g.record(evidence("obstacle_clear", 4), now_us=1_000_020)
    assert g.state(1, 1, now_us=1_000_020) == "safe"
    snapshot = g.snapshot(now_us=1_000_020)
    assert snapshot.cell_mm == CELL_MM == 20
    assert snapshot.support[5] == "safe"
    assert snapshot.support[0] == "unknown"
    assert snapshot.anchored is False
    assert snapshot.robot_id == "robot-01" and snapshot.anchor_id == "tag-4"


def test_occupied_free_unknown_and_log_odds_clamp():
    g = grid()
    g.record(evidence("floor_supported", 0), now_us=1_000_010)
    g.record(evidence("obstacle_clear", 4), now_us=1_000_010)
    assert g.log_odds(1, 1) == pytest.approx(-0.8)
    for seq in range(2, 12):
        g.record(evidence("obstacle_hit", 4, seq, received_us=1_000_000 + seq * 10),
                 now_us=1_000_000 + seq * 10)
    assert g.log_odds(1, 1) == pytest.approx(4.0)
    assert g.state(1, 1, now_us=1_000_110) == "occupied"
    for seq in range(12, 30):
        g.record(evidence("obstacle_clear", 4, seq, received_us=1_000_000 + seq * 10),
                 now_us=1_000_000 + seq * 10)
    assert g.log_odds(1, 1) == pytest.approx(-4.0)
    assert g.state(1, 1, now_us=1_000_300) == "safe"


def test_floor_unsafe_is_independent_and_overrides_free():
    g = grid()
    g.record(evidence("floor_supported", 0), now_us=1_000_010)
    g.record(evidence("obstacle_clear", 4), now_us=1_000_010)
    g.record(evidence("floor_unsafe", 1), now_us=1_000_010)
    assert g.state(1, 1, now_us=1_000_010) == "unsafe"


@pytest.mark.parametrize("bad", [
    {"kind": "obstacle_clear", "lane": 5},
    {"kind": "floor_supported", "lane": 4},
    {"kind": "jpeg_free", "lane": 4},
    {"kind": "apriltag_clear", "lane": 4},
    {"kind": "obstacle_hit", "lane": 0},
    {"kind": "obstacle_clear", "lane": 4, "geometry_qualified": False},
    {"kind": "obstacle_clear", "lane": 4, "robot_id": "robot-02"},
    {"kind": "obstacle_clear", "lane": 4, "origin_id": "odom-old"},
    {"kind": "obstacle_clear", "lane": 4, "calibration_id": "wrong"},
    {"kind": "obstacle_clear", "lane": 4, "epoch": 1},
    {"kind": "obstacle_clear", "lane": 4, "cells": ((1, 1), (4, 1))},
    {"kind": "obstacle_clear", "lane": 4, "cells": ((1, 1), (1, 1))},
    {"kind": "obstacle_clear", "lane": 4, "cells": ((1, 1), ([1], 2))},
])
def test_unqualified_evidence_is_rejected_atomically(bad):
    g = grid()
    base = evidence("obstacle_clear", 4)
    with pytest.raises(GridEvidenceError):
        g.record(replace(base, **bad), now_us=1_000_010)
    assert g.log_odds(1, 1) == 0
    assert g.snapshot(now_us=1_000_010).support[5] == "unknown"


def test_stale_and_out_of_calibration_are_explicit():
    g = grid()
    g.record(evidence("floor_supported", 0), now_us=1_000_010)
    g.record(evidence("obstacle_clear", 4), now_us=1_000_010)
    assert g.state(1, 1, now_us=2_000_001) == "stale"
    g.invalidate_calibration("camera-new")
    assert g.state(1, 1, now_us=1_000_010) == "out_of_calibration"
    snap = g.snapshot(now_us=1_000_010)
    assert snap.support[5] == "unsafe"
    assert snap.epoch == 1 and not snap.anchored


def test_duplicate_source_sample_rejected_no_partial_grid_change():
    g = grid()
    g.record(evidence("obstacle_hit", 4), now_us=1_000_010)
    with pytest.raises(GridEvidenceError, match="Replayed"):
        g.record(evidence("obstacle_clear", 4, cells=((2, 1),)), now_us=1_000_010)
    assert g.log_odds(2, 1) == 0
    assert g.log_odds(1, 1) == pytest.approx(1.2)


def test_pickup_origin_change_invalidates_cells_and_older_batches():
    g = grid()
    g.record(evidence("floor_supported", 0), now_us=1_000_010)
    g.record(evidence("obstacle_clear", 4), now_us=1_000_010)
    g.invalidate_origin(8, "odom-2")
    assert g.state(1, 1, now_us=1_000_010) == "unknown"
    assert g.epoch == 1 and g.body_boot == 8 and not g.anchored
    with pytest.raises(GridEvidenceError):
        g.record(evidence("obstacle_clear", 4, 2), now_us=1_000_010)


def test_late_or_future_receipt_and_bad_windows_fail_closed():
    g = grid()
    with pytest.raises(GridEvidenceError):
        g.record(evidence("floor_supported", 0), now_us=1_300_001)
    with pytest.raises(GridEvidenceError):
        g.record(evidence("floor_supported", 0), now_us=999_999)
    with pytest.raises(ValueError):
        g.snapshot(now_us=-1)


def test_recalibration_cannot_reuse_old_clearance_or_blockage():
    g = grid()
    g.record(evidence("floor_supported", 0), now_us=1_000_010)
    for seq in range(1, 7):
        at = 1_000_000 + seq * 10
        g.record(evidence("obstacle_clear", 4, seq, received_us=at), now_us=at)
    assert g.log_odds(1, 1) == pytest.approx(-4.0)
    assert g.state(1, 1, now_us=1_000_060) == "safe"

    g.invalidate_calibration("camera-new")
    assert g.state(1, 1, now_us=1_000_060) == "out_of_calibration"
    new_floor = replace(evidence("floor_supported", 0, received_us=1_100_000),
                        calibration_id="camera-new", epoch=1)
    g.record(new_floor, now_us=1_100_000)
    assert g.state(1, 1, now_us=1_100_000) == "out_of_calibration"
    new_hit = replace(evidence("obstacle_hit", 4, received_us=1_100_010),
                      calibration_id="camera-new", epoch=1)
    g.record(new_hit, now_us=1_100_010)
    # One qualified new hit must not inherit the old -4 free-space confidence.
    assert g.log_odds(1, 1) == pytest.approx(1.2)
    assert g.state(1, 1, now_us=1_100_010) == "occupied"

    g.invalidate_calibration("camera-next")
    new_floor = replace(evidence("floor_supported", 0, received_us=1_200_000),
                        calibration_id="camera-next", epoch=2)
    g.record(new_floor, now_us=1_200_000)
    new_clear = replace(evidence("obstacle_clear", 4, received_us=1_200_010),
                        calibration_id="camera-next", epoch=2)
    g.record(new_clear, now_us=1_200_010)
    # The obsolete occupied belief must not survive a fresh geometry change.
    assert g.log_odds(1, 1) == pytest.approx(-0.8)
    assert g.state(1, 1, now_us=1_200_010) == "safe"


def test_delayed_body_conversion_revokes_clearance_without_trusting_receipt():
    g = grid()
    g.record(evidence("floor_supported", 0), now_us=1_000_000)
    g.record(evidence("obstacle_clear", 4), now_us=1_000_000)
    assert g.state(1, 1, now_us=1_000_010) == "safe"

    # The head delivers a newly timed sample whose WROOM conversion barely
    # advanced in half a second. Its increasing sequence is not freshness.
    delayed = replace(
        evidence("obstacle_clear", 4, seq=2, received_us=1_500_000),
        sample_us=110_000,
    )
    with pytest.raises(GridEvidenceError, match="source clock diverged"):
        g.record(delayed, now_us=1_500_000)
    assert g.state(1, 1, now_us=1_500_000) == "unknown"
    assert g.snapshot(now_us=1_500_000).observed_at_us == 0

    # A later truthful conversion catches up to the same body clock. The
    # earlier rejected packet never moved the replay fence forward.
    fresh_floor = replace(
        evidence("floor_supported", 0, seq=2, received_us=1_600_000),
        sample_us=700_000,
    )
    fresh_clear = replace(
        evidence("obstacle_clear", 4, seq=3, received_us=1_600_000),
        sample_us=700_000,
    )
    g.record(fresh_floor, now_us=1_600_000)
    assert g.state(1, 1, now_us=1_600_000) == "unknown"
    g.record(fresh_clear, now_us=1_600_000)
    assert g.state(1, 1, now_us=1_600_000) == "safe"


def test_implausible_body_clock_leap_revokes_previous_grid():
    g = grid()
    g.record(evidence("floor_supported", 0), now_us=1_000_000)
    g.record(evidence("obstacle_clear", 4), now_us=1_000_000)
    leap = replace(
        evidence("obstacle_hit", 4, seq=2, received_us=1_010_000),
        sample_us=10_000_000,
    )
    with pytest.raises(GridEvidenceError, match="source clock diverged"):
        g.record(leap, now_us=1_010_000)
    assert g.state(1, 1, now_us=1_010_000) == "unknown"


@pytest.mark.parametrize("received_us", (-1, 0))
def test_nonpositive_mac_receipt_time_is_not_fresh(received_us):
    g = grid()
    batch = replace(evidence("obstacle_clear", 4), received_us=received_us)
    with pytest.raises(GridEvidenceError, match="Invalid grid source"):
        g.record(batch, now_us=0)
    assert g.state(1, 1, now_us=0) == "unknown"


def test_floor_unsafe_expires_to_stale_without_becoming_safe():
    g = grid()
    g.record(evidence("floor_unsafe", 0), now_us=1_000_010)
    assert g.state(1, 1, now_us=1_000_010) == "unsafe"
    # The conservative floor hazard does not require obstacle evidence.
    assert g.state(1, 1, now_us=2_000_000) == "unsafe"
    assert g.state(1, 1, now_us=2_000_001) == "stale"
    assert g.snapshot(now_us=2_000_001).support[5] == "stale"
    # A host clock rollback cannot make that expired reading current.
    assert g.state(1, 1, now_us=999_999) == "stale"
    assert "safe" not in g.snapshot(now_us=2_000_001).support


@pytest.mark.parametrize(
    ("old_kind", "fresh_kind", "old_confidence", "fresh_confidence", "expected"),
    [
        ("obstacle_clear", "obstacle_hit", -4.0, 1.2, "occupied"),
        ("obstacle_hit", "obstacle_clear", 4.0, -0.8, "safe"),
    ],
)
def test_expired_obstacle_confidence_never_biases_new_measurement(
    old_kind, fresh_kind, old_confidence, fresh_confidence, expected,
):
    g = grid()
    # Several mutually consistent old measurements saturate the log odds.
    for seq in range(1, 6):
        receipt = 1_000_000 + seq * 10
        g.record(evidence(old_kind, 4, seq, received_us=receipt), now_us=receipt)
    assert g.log_odds(1, 1) == pytest.approx(old_confidence)

    # The new floor support is fresh, but the obstacle belief has expired.
    now = 2_000_100
    g.record(evidence("floor_supported", 0, received_us=now), now_us=now)
    assert g.state(1, 1, now_us=now) == "stale"
    new_sample = replace(
        evidence(fresh_kind, 4, seq=6, received_us=now),
        sample_us=1_500_050,
    )
    g.record(new_sample, now_us=now)
    assert g.log_odds(1, 1) == pytest.approx(fresh_confidence)
    assert g.state(1, 1, now_us=now) == expected


def test_current_obstacle_evidence_still_accumulates_confidence():
    g = grid()
    g.record(evidence("obstacle_clear", 4, received_us=1_000_000),
             now_us=1_000_000)
    g.record(
        replace(evidence("obstacle_clear", 4, seq=2, received_us=1_000_100),
                sample_us=100_100),
        now_us=1_000_100,
    )
    assert g.log_odds(1, 1) == pytest.approx(-1.6)


@pytest.mark.parametrize(
    ("now_us", "expected_expiry", "first_state", "second_state"),
    [
        (1_900_000, 2_000_000, "safe", "safe"),
        (2_000_000, 2_000_000, "safe", "safe"),
        (2_000_001, 2_100_000, "stale", "safe"),
        (2_100_001, 3_100_001, "stale", "stale"),
    ],
)
def test_snapshot_expiry_never_renews_old_safe_cell_evidence(
    now_us, expected_expiry, first_state, second_state,
):
    g = grid()
    g.record(evidence("floor_supported", 0), now_us=1_000_000)
    g.record(evidence("obstacle_clear", 4, received_us=1_100_000,
                      cells=((2, 1),)), now_us=1_100_000)
    g.record(evidence("obstacle_clear", 4, seq=2, received_us=1_400_000),
             now_us=1_400_000)
    g.record(evidence("floor_supported", 1, received_us=1_500_000,
                      cells=((2, 1),)), now_us=1_500_000)
    snapshot = g.snapshot(now_us=now_us)
    assert snapshot.support[5:7] == (first_state, second_state)
    assert snapshot.support[0] == "unknown"
    assert snapshot.expires_at_us == expected_expiry
    assert g.to_route_snapshot(now_us=now_us).expires_at_us == expected_expiry


@pytest.mark.parametrize("lag_lane,kind", [(0, "floor_supported"), (4, "obstacle_clear")])
def test_gradual_range_clock_lag_revokes_grid_and_cannot_rebaseline(lag_lane, kind):
    g = grid()
    for lane, source_kind in [(0, "floor_supported"), (4, "obstacle_clear")]:
        g.record(evidence(source_kind, lane), now_us=1_000_000)
    g.anchored = True  # Simulated existing localization; not hardware evidence.
    g.record(evidence(kind, lag_lane, seq=2, received_us=1_300_000),
             now_us=1_300_000)
    assert g.state(1, 1, now_us=1_300_000) == "safe"
    for seq in range(3, 8):
        now = 1_000_000 + (seq - 1) * 300_000
        with pytest.raises(GridEvidenceError, match="source clock diverged"):
            g.record(evidence(kind, lag_lane, seq=seq, received_us=now), now_us=now)
        assert g.state(1, 1, now_us=now) == "unknown"
        assert not g.snapshot(now_us=now).anchored
        assert g.snapshot(now_us=now).observed_at_us == 0
    # Catch-up is not map re-anchoring, and both layers must be repopulated.
    now = 3_100_000
    fresh = replace(evidence(kind, lag_lane, seq=8, received_us=now), sample_us=2_200_000)
    g.record(fresh, now_us=now)
    assert g.state(1, 1, now_us=now) == "unknown"
    other_lane, other_kind = (4, "obstacle_clear") if lag_lane == 0 else (0, "floor_supported")
    g.record(replace(evidence(other_kind, other_lane, seq=2, received_us=now),
                     sample_us=2_200_000), now_us=now)
    assert g.state(1, 1, now_us=now) == "safe"
    assert not g.snapshot(now_us=now).anchored


def test_matching_range_clocks_do_not_accumulate_lag():
    g = grid()
    for i in range(100):
        now = 1_000_000 + i * 300_000
        for lane, kind in [(0, "floor_supported"), (4, "obstacle_clear")]:
            g.record(replace(evidence(kind, lane, seq=i + 1, received_us=now),
                             sample_us=100_000 + i * 300_000), now_us=now)
        assert g.state(1, 1, now_us=now) == "safe"


def test_grid_clock_reference_restarts_with_explicit_new_origin():
    g = grid()
    g.record(evidence("obstacle_clear", 4), now_us=1_000_000)
    g.record(evidence("obstacle_clear", 4, seq=2, received_us=1_300_000),
             now_us=1_300_000)
    with pytest.raises(GridEvidenceError, match="source clock diverged"):
        g.record(evidence("obstacle_clear", 4, seq=3, received_us=1_600_000),
                 now_us=1_600_000)
    g.invalidate_origin(8, "odom-2")
    g.record(replace(evidence("obstacle_clear", 4, received_us=1_700_000),
                     body_boot=8, origin_id="odom-2", epoch=1), now_us=1_700_000)
    assert g.log_odds(1, 1) == pytest.approx(-0.8)
    assert not g.snapshot(now_us=1_700_000).anchored
