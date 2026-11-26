import pytest
from desk_robot.fleet_dialogue_budget import RollingGroupBudget


@pytest.mark.parametrize("size,limit", [(2, 6), (3, 6), (4, 8), (5, 10)])
def test_rolling_group_budget_wrap(size, limit):
    now = [1000.0]
    budget = RollingGroupBudget(lambda: now[0])
    budget.claim(size)
    now[0] += 1
    for _ in range(limit - 1):
        budget.claim(size)
    now[0] = 1299.999
    assert budget.remaining(size) == 0
    with pytest.raises(RuntimeError, match="budget exhausted"):
        budget.claim(size)
    now[0] = 1300.0
    assert budget.remaining(size) == 1
    budget.claim(size)
    assert budget.remaining(size) == 0
    now[0] = 1301.0
    assert budget.remaining(size) == limit - 1


def test_changing_group_size_never_clears_fleet_history():
    budget = RollingGroupBudget(lambda: 1000.0)
    for _ in range(6):
        budget.claim(2)
    assert budget.remaining(3) == 0
    assert budget.remaining(4) == 2
    for _ in range(2):
        budget.claim(4)
    assert budget.remaining(5) == 2
    for _ in range(2):
        budget.claim(5)
    assert all(budget.remaining(size) == 0 for size in range(2, 6))


@pytest.mark.parametrize("size", [0, 1, 6, 2.0, 4.5, True, None, "5"])
def test_invalid_group_size_cannot_change_allowance(size):
    budget = RollingGroupBudget(lambda: 1000.0)
    budget.claim(5)
    with pytest.raises(ValueError, match="two to five"):
        budget.claim(size)
    with pytest.raises(ValueError, match="two to five"):
        budget.remaining(size)
    assert budget.remaining(5) == 9


def test_repeated_mixed_group_claims_match_rolling_reference():
    now = [1000.0]
    budget = RollingGroupBudget(lambda: now[0])
    accepted = []
    limits = {2: 6, 3: 6, 4: 8, 5: 10}
    # Rotate pair and group sizes on every tick, including exact expiry.
    # Rejected attempts must neither refill nor extend the silence window.
    for tick in range(1201):
        now[0] = 1000.0 + tick * 0.5
        size = (2, 5, 3, 4)[tick % 4]
        accepted = [stamp for stamp in accepted if now[0] - stamp < 300.0]
        expected = max(0, limits[size] - len(accepted))
        assert budget.remaining(size) == expected
        if expected:
            budget.claim(size)
            accepted.append(now[0])
        else:
            with pytest.raises(RuntimeError, match="budget exhausted"):
                budget.claim(size)
        assert len(accepted) <= 10
        for other_size, limit in limits.items():
            assert budget.remaining(other_size) == max(0, limit - len(accepted))
