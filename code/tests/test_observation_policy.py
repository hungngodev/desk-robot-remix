"""Receipt preparation is deterministic without SQLite or real clocks."""

import math

import pytest
from desk_robot.observation_policy import (
    camera_receipt_is_current,
    prepare_camera_receipt,
    receipt_age_is_current,
)


def _prepare(received_at=95.0, source_identity=None):
    return prepare_camera_receipt(
        robot_id="pet1", event_id="random-id", wall_now=1000.0,
        monotonic_now=100.0, received_at=received_at, max_age=10.0,
        source_identity=source_identity,
    )


@pytest.mark.parametrize("received_at", [89.999, 100.001, float("nan"), float("inf"),
                                         True, "95", 10**400])
def test_impossible_receipt_is_rejected(received_at):
    assert _prepare(received_at) is None
    assert not camera_receipt_is_current(received_at=received_at, now=100.0, max_age=10.0)


def test_original_receipt_chronology_and_inclusive_expiry_boundary():
    assert _prepare(90.0) == ("random-id", 990.0)
    assert _prepare(100.0) == ("random-id", 1000.0)
    assert _prepare() == _prepare() == ("random-id", 995.0)


def test_device_identity_is_deterministic_and_robot_scoped():
    identity = (0, 1, 0xAB)
    assert _prepare(source_identity=identity) == ("camera_pet1_00000000_00000001_ab", 995.0)
    assert prepare_camera_receipt(
        robot_id="pet2", event_id="different", wall_now=1000.0,
        monotonic_now=100.0, received_at=95.0, max_age=10.0, source_identity=identity,
    ) == ("camera_pet2_00000000_00000001_ab", 995.0)


@pytest.mark.parametrize("identity", [(True, 1, 1), (0, 0, 1), (0, 1, 0),
                                      (2**32, 1, 1), (0, 2**32, 1), (0, 1, 2**64),
                                      (0, 1), [0, 1, 1]])
def test_invalid_identity_is_never_promoted(identity):
    with pytest.raises(ValueError, match="Invalid device camera completion identity"):
        _prepare(source_identity=identity)


@pytest.mark.parametrize(
    ("received_at", "max_age", "expected"),
    [
        (math.nextafter(8.25, -math.inf), 7.75, False),
        (8.25, 7.75, True),
        (math.nextafter(8.25, math.inf), 7.75, True),
        (math.nextafter(16.0, -math.inf), 0.0, False),
        (16.0, 0.0, True),
        (math.nextafter(16.0, math.inf), 7.75, False),
        (4.0, 12.0, True),
        (4.0, 11.75, False),
    ],
)
def test_configurable_receipt_age_at_adjacent_float_boundaries(received_at, max_age, expected):
    for predicate in (receipt_age_is_current, camera_receipt_is_current):
        assert predicate(received_at=received_at, now=16.0, max_age=max_age) is expected
    receipt = prepare_camera_receipt(
        robot_id="pet1", event_id="event", wall_now=1000.0,
        monotonic_now=16.0, received_at=received_at, max_age=max_age,
        source_identity=None,
    )
    assert (receipt is not None) is expected


@pytest.mark.parametrize(
    ("identity", "event_id"),
    [
        ((0, 1, 1), "camera_pet1_00000000_00000001_1"),
        ((0xffffffff, 0xffffffff, 0xffffffffffffffff),
         "camera_pet1_ffffffff_ffffffff_ffffffffffffffff"),
    ],
)
def test_device_identity_accepts_inclusive_endpoints(identity, event_id):
    assert _prepare(source_identity=identity) == (event_id, 995.0)


def test_negative_boot_identity_rejected_before_persistence():
    with pytest.raises(ValueError, match="Invalid device camera completion identity"):
        _prepare(source_identity=(-1, 1, 1))


def test_expired_receipt_is_rejected_before_identity_validation():
    assert _prepare(received_at=89.0, source_identity=(-1, 1, 1)) is None
