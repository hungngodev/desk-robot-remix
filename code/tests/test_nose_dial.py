import pytest
from desk_robot.aux import NoseDialGate


def sample(angle, seq, *, age=0, boot=7, valid=1):
    return {
        "raw": [angle, 0, 0], "valid_mask": valid, "seq": [seq, 0, 0],
        "age_ms": [age, 0, 0], "boot_id": boot,
    }


def observe(gate, data, *, elapsed=0, threshold=500):
    return gate.observe(data, boot_id=7, threshold=threshold, request_elapsed_ms=elapsed)


@pytest.mark.parametrize(("start", "end", "expected"), [
    (100, 599, False), (100, 600, False), (100, 601, True),
    (600, 100, False), (601, 100, True), (4095, 0, False),
    (4000, 404, False), (4000, 405, True), (404, 4000, False),
    (405, 4000, True),
])
def test_circular_deadband(start, end, expected):
    gate = NoseDialGate()
    assert not observe(gate, sample(start, 1))
    assert observe(gate, sample(end, 2)) is expected


def test_replay_cannot_rebase_or_emit():
    gate = NoseDialGate()
    assert not observe(gate, sample(100, 10))
    for seq in (10, 9):
        assert not observe(gate, sample(1500, seq))
        assert (gate.last_angle, gate.last_seq) == (100, 10)
    assert observe(gate, sample(601, 11))
    assert not observe(gate, sample(100, 10))


@pytest.mark.parametrize("bad", [
    {"age_ms": [350, 0, 0]}, {"boot_id": 8}, {"boot_id": True},
    {"seq": [0, 0, 0]}, {"seq": [True, 0, 0]}, {"seq": [2]},
    {"age_ms": None}, {"valid_mask": 0},
])
def test_invalid_breaks_continuity_without_rewinding_fence(bad):
    gate = NoseDialGate()
    assert not observe(gate, sample(100, 10))
    assert not observe(gate, {**sample(1800, 11), **bad})
    assert gate.last_angle is None and gate.last_seq == 10
    assert not observe(gate, sample(1800, 9))
    assert not observe(gate, sample(1800, 12))
    assert observe(gate, sample(2301, 13))


def test_transport_age_and_sequence_wrap():
    gate = NoseDialGate()
    assert not observe(gate, sample(100, 0xffffffff))
    assert observe(gate, sample(601, 1, age=300), elapsed=49)
    assert not observe(gate, sample(1200, 2, age=300), elapsed=50)
    assert gate.last_angle is None and gate.last_seq == 1
    gate.reset()
    assert not observe(gate, sample(1200, 1))


def test_legacy_and_disabled_are_not_event_sources():
    gate = NoseDialGate()
    assert not observe(gate, {"raw": [1000, 0, 0], "valid_mask": 1})
    assert not observe(gate, sample(2000, 1), threshold=None)
