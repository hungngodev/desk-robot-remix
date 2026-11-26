"""Identity comparison must not silently rewrite a fleet routing ID."""

import pytest
from desk_robot.fleet_identity import device_identity_key, valid_unique_robot_ids


@pytest.mark.parametrize(
    "ids",
    [None, "robot-01", [], [""], [" "], [" robot-01"], ["robot-01\t"],
     ["robot-01", "robot-01"], ["robot-01", "ROBOT-01"], ["NUL"], [None]],
)
def test_invalid_robot_identity_sets(ids):
    assert not valid_unique_robot_ids(ids)


def test_distinct_robot_ids_preserve_literal_spelling():
    ids = ["Robot-01", "robot-02", "robot_01"]
    assert valid_unique_robot_ids(ids)
    assert ids == ["Robot-01", "robot-02", "robot_01"]


@pytest.mark.parametrize(
    "device", ["012345ABCDEF", "01:23:45:ab:cd:ef", "01-23-45-AB-CD-EF", " 012345abcdef "],
)
def test_mac_spellings_share_one_collision_key(device):
    assert device_identity_key(device) == "012345abcdef"


def test_opaque_device_keys_keep_separators_and_empty_mapping():
    assert device_identity_key(" Head-A ") == "head-a"
    assert device_identity_key("Head-A") != device_identity_key("HeadA")
    assert device_identity_key("") == ""
