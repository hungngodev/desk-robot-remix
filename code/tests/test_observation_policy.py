"""Receipt preparation is deterministic without SQLite or real clocks."""

import pytest
from desk_robot.observation_policy import camera_receipt_is_current, prepare_camera_receipt


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
