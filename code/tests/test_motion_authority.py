import pytest
from desk_robot.motion_authority import StopConfirmationTracker


@pytest.mark.parametrize("latest_acknowledged", [False, True])
@pytest.mark.parametrize("latest_finishes_first", [False, True])
def test_overlapping_stop_attempts_keep_latest_receipt_and_all_pending_counts(
    latest_acknowledged: bool, latest_finishes_first: bool,
) -> None:
    tracker = StopConfirmationTracker(["a", "b"])
    older = tracker.begin("a")
    newer = tracker.begin("a")
    assert newer > older
    attempts = [(older, not latest_acknowledged), (newer, latest_acknowledged)]
    if latest_finishes_first:
        attempts.reverse()
    for index, (generation, acknowledged) in enumerate(attempts):
        tracker.finish("a", generation, acknowledged=acknowledged)
        assert tracker.pending.get("a", 0) == 1 - index
        assert not tracker.blocked("b")
        if index == 0:
            assert tracker.blocked()
    assert tracker.blocked("a") is (not latest_acknowledged)
    assert tracker.blocked() is (not latest_acknowledged)
    assert not tracker.pending


def test_peer_stop_cannot_clear_failed_stop_and_owner_has_priority() -> None:
    tracker = StopConfirmationTracker(["a", "b"])
    tracker.finish("a", tracker.begin("a"), acknowledged=False)
    tracker.finish("b", tracker.begin("b"), acknowledged=True)
    assert tracker.blocked("a")
    assert not tracker.blocked("b")
    assert tracker.fleet_block_reason("job") == (
        "Fleet motion busy: one moving pet until WROOM STOP is acknowledged"
    )
    assert tracker.fleet_block_reason(None) == (
        "Fleet motion blocked: WROOM STOP pending or unconfirmed"
    )
    tracker.finish("a", tracker.begin("a"), acknowledged=True)
    assert tracker.fleet_block_reason(None) is None


def test_pending_idle_stop_blocks_fleet_until_receipt() -> None:
    tracker = StopConfirmationTracker(["a", "b"])
    generation = tracker.begin("b")
    assert not tracker.blocked("a")
    assert tracker.blocked("b")
    assert tracker.fleet_block_reason(None) is not None
    tracker.finish("b", generation, acknowledged=True)
    assert tracker.fleet_block_reason(None) is None
