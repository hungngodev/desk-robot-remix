"""Seeded five-pet STOP receipt interleavings at the host admission boundary."""

import random

import pytest
from desk_robot.motion_authority import StopConfirmationTracker


@pytest.mark.parametrize("seed", [0, 17, 1146, 20261126])
def test_five_pet_stop_receipt_chaos(seed):
    rng = random.Random(seed)
    robots = [f"robot-{i:02}" for i in range(1, 6)]
    tracker = StopConfirmationTracker(robots)
    last_failed = dict.fromkeys(robots, False)
    for _ in range(25):
        outstanding = {robot: set() for robot in robots}
        latest = {}
        receipts = []
        # All five pets have two overlapping STOP attempts before any receipt.
        for robot in rng.sample(robots * 2, 10):
            generation = tracker.begin(robot)
            outstanding[robot].add(generation)
            latest[robot] = generation
            receipts.append((robot, generation, rng.choice([False, True])))
            assert tracker.fleet_block_reason(None) is not None
        rng.shuffle(receipts)
        for robot, generation, acknowledged in receipts:
            tracker.finish(robot, generation, acknowledged=acknowledged)
            outstanding[robot].remove(generation)
            if generation == latest[robot]:
                last_failed[robot] = not acknowledged
            expected = {
                pet: bool(outstanding[pet]) or last_failed[pet] for pet in robots
            }
            assert {pet: tracker.blocked(pet) for pet in robots} == expected
            assert tracker.blocked() == any(expected.values())
            assert (tracker.fleet_block_reason(None) is not None) == any(expected.values())
            assert tracker.fleet_block_reason("active-job") is not None
        assert not tracker.pending

    # A successful fresh STOP from every pet is necessary to clear failures.
    for robot in robots:
        tracker.finish(robot, tracker.begin(robot), acknowledged=True)
        last_failed[robot] = False
        assert tracker.blocked() == any(last_failed.values())
    assert tracker.fleet_block_reason(None) is None
    assert tracker.fleet_block_reason("active-job") is not None
