"""Boundary regressions for side ranging acquisition metadata."""

import pytest
from desk_robot.side_ranging import SideRangeEvents


def _body(distance=600, **identity):
    return {"side_ranges": {
        "mm": [distance, 600, 600],
        "age_ms": [30] * 3,
        "present_mask": 7,
        "valid_mask": 7,
        "motion_certified": False,
        **identity,
    }}


@pytest.mark.parametrize("identity", [
    {"sample_ms": None},
    {"boot_id": None},
    {"sample_ms": None, "boot_id": None},
])
def test_explicit_null_identity_cannot_count_as_legacy_sample(identity):
    tracker = SideRangeEvents()

    def observe(distance, now, **fields):
        return tracker.observe(_body(distance, **fields), now=now, near_mm=170)

    assert observe(600, 1.0) == []
    assert observe(100, 1.1) == []
    assert observe(95, 1.2, **identity) == []
    # Malformed metadata breaks confirmation rather than preserving a near vote.
    assert observe(95, 1.3) == []
    assert observe(95, 1.4) == []
    assert observe(600, 1.5) == []
    assert observe(600, 1.6) == []
    assert observe(100, 1.7) == []
    assert observe(95, 1.8) == [("left", 95)]


def test_trackers_do_not_share_votes_or_boot_history():
    first, second = SideRangeEvents(), SideRangeEvents()
    first.observe(_body(sample_ms=[100] * 3, boot_id=1), now=1.0, near_mm=170)
    first.observe(_body(sample_ms=[200] * 3, boot_id=2), now=1.1, near_mm=170)
    first.observe(_body(100, sample_ms=[300] * 3, boot_id=2), now=1.2, near_mm=170)
    assert first.retired_boot_ids == {1}
    assert first.directions[0].consecutive_near == 1
    assert second.retired_boot_ids == set()
    assert second.active_boot_id is None
    assert not second.directions[0].initialized
    assert second.directions[0].consecutive_near == 0
