import math

import pytest
from desk_robot.habituation import HabituationWindow


def test_sliding_window_and_exact_decay_boundary():
    model = HabituationWindow[str]()
    assert not model.refresh_if_repeated("mug", 1000)
    assert model.record("mug", 1000)
    for now in (1121, 1242, 1363, 1484, 1605, 1726):
        assert model.refresh_if_repeated("mug", now)
    assert model.recent_repeats(2625.999) == {"mug": 7}
    assert model.recent_repeats(2626) == {}
    assert not model.refresh_if_repeated("mug", 2626)
    assert model.record("mug", 2626)
    assert model.recent_repeats(2626) == {}


def test_novel_candidate_does_not_consume_admission():
    model = HabituationWindow[str](window_s=10)
    assert not model.refresh_if_repeated("mug", 1)
    assert not model.refresh_if_repeated("mug", 2)
    assert model.recent_repeats(2) == {}
    assert model.record("mug", 3)
    assert model.refresh_if_repeated("mug", 4)


def test_capacity_refresh_and_eviction():
    model = HabituationWindow[str](window_s=10, capacity=2)
    model.record("a", 1)
    model.record("b", 2)
    assert model.refresh_if_repeated("a", 3)
    model.record("c", 4)
    assert not model.refresh_if_repeated("b", 5)
    assert model.refresh_if_repeated("a", 5)
    assert model.refresh_if_repeated("c", 5)


def test_epoch_and_robot_isolation():
    first = HabituationWindow[str]()
    second = HabituationWindow[str]()
    first.begin_epoch((1, 2))
    first.record("mug", 1)
    first.begin_epoch((1, 2))
    assert first.refresh_if_repeated("mug", 2)
    assert not second.refresh_if_repeated("mug", 2)
    first.begin_epoch((1, 3))
    assert not first.refresh_if_repeated("mug", 3)
    first.record("mug", 3)
    first.begin_epoch((2, 3))
    assert not first.refresh_if_repeated("mug", 4)
    first.record("mug", 4)
    first.reset()
    assert not first.refresh_if_repeated("mug", 5)


def test_physical_context_counts_decay_independently():
    model = HabituationWindow[str](window_s=10)
    for key, now in (("safety_fault", 1), ("safety_fault", 2),
                     ("touch", 5), ("touch", 6)):
        assert model.record(key, now)
    assert model.recent_repeats(11.999) == {"safety_fault": 2, "touch": 2}
    assert model.recent_repeats(12) == {"touch": 2}
    assert model.record("safety_fault", 12)
    assert model.recent_repeats(12) == {"touch": 2}
    assert model.recent_repeats(16) == {}


def test_rejected_time_does_not_renew_or_rewind():
    model = HabituationWindow[str](window_s=10)
    assert model.record("mug", 10)
    for invalid in (True, math.nan, math.inf, -math.inf, 10**1000, 9):
        assert not model.record("mug", invalid)
        assert model.refresh_if_repeated("mug", invalid)
    assert model.recent_repeats(19) == {}
    assert not model.refresh_if_repeated("mug", 20)


@pytest.mark.parametrize("window,capacity", [
    (0, 1), (-1, 1), (math.inf, 1), (math.nan, 1), (True, 1),
    (1, 0), (1, -1), (1, True), (1, 1.5),
])
def test_invalid_configuration(window, capacity):
    with pytest.raises(ValueError):
        HabituationWindow(window_s=window, capacity=capacity)


def test_equal_timestamp_observations_count_without_rewinding():
    model = HabituationWindow[str](window_s=10)
    assert model.record("mug", 10)
    assert model.record("mug", 10)
    assert model.recent_repeats(10) == {"mug": 2}
    assert model.refresh_if_repeated("mug", 10)
    assert model.recent_repeats(10) == {"mug": 3}
    assert model.recent_repeats(9) == {}


@pytest.mark.parametrize("now", [True, math.nan, math.inf, -math.inf, 10**1000, "10"])
def test_invalid_repeat_query_is_empty_and_nonmutating(now):
    model = HabituationWindow[str]()
    assert model.record("mug", 9)
    assert model.record("mug", 10)
    assert model.recent_repeats(now) == {}
    assert model.recent_repeats(10) == {"mug": 2}


def test_reset_retires_epoch_even_if_the_same_epoch_is_reintroduced():
    model = HabituationWindow[str]()
    model.begin_epoch((1, None))
    model.record("mug", 1)
    model.reset()
    model.record("key", 2)
    model.begin_epoch((1, None))
    assert not model.refresh_if_repeated("key", 3)


def test_expired_candidate_cannot_be_revived_by_a_regressing_query():
    model = HabituationWindow[str](window_s=10)
    model.record("mug", 10)
    assert not model.refresh_if_repeated("mug", 20)
    assert not model.refresh_if_repeated("mug", 19)
