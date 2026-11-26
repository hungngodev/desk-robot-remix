"""Dock approach must not oscillate indefinitely around the closest pose."""

import math

import pytest
from desk_robot.dock_progress import DockApproachProgress


@pytest.mark.parametrize("distances", [(500, 500, 500, 500), (500, 510, 505, 510)])
def test_three_failed_pulses_require_help(distances):
    progress = DockApproachProgress()
    assert [progress.observe(distance) for distance in distances] == [False] * 3 + [True]


def test_only_new_closest_distance_resets_failures():
    progress = DockApproachProgress()
    distances = (500, 510, 505, 490, 500, 495, 490)
    assert [progress.observe(distance) for distance in distances] == [False] * 6 + [True]


def test_continuous_progress_preserves_existing_pulse_budget():
    progress = DockApproachProgress()
    assert not any(progress.observe(distance) for distance in range(500, 484, -1))


def test_equal_range_stalls_and_one_ulp_closer_resets_exactly():
    progress = DockApproachProgress()
    assert not progress.observe(500.0)
    assert progress.best_distance_mm == 500.0
    assert progress.failed_attempts == 0
    assert not progress.observe(500.0)
    assert progress.failed_attempts == 1
    assert not progress.observe(math.nextafter(500.0, math.inf))
    assert progress.failed_attempts == 2
    closer = math.nextafter(500.0, 0.0)
    assert not progress.observe(closer)
    assert progress.best_distance_mm == closer
    assert progress.failed_attempts == 0
    for count in range(1, 4):
        assert progress.observe(closer) is (count == 3)
        assert progress.failed_attempts == count
        assert progress.best_distance_mm == closer
