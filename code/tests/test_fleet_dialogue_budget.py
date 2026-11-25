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
