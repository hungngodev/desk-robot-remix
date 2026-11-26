"""Dock approach must not oscillate indefinitely around the closest pose."""

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
