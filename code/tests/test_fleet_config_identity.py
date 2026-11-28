import tomllib
from pathlib import Path

import pytest
from desk_robot.fleet_identity import device_identity_key

HARDWARE = Path(__file__).resolve().parents[1] / "config/fleet.hardware.example.toml"


@pytest.mark.parametrize("alias", ["AA:BB:CC:DD:EE:01", "aa-bb-cc-dd-ee-01", "aabbccddee01"])
def test_mac_identity_key_aliases(alias):
    assert device_identity_key(alias) == device_identity_key("aa:bb:cc:dd:ee:01")
    assert device_identity_key(alias) != device_identity_key("aa:bb:cc:dd:ee:02")


def test_opaque_device_ids_remain_distinct():
    assert device_identity_key("Head-A") == "head-a"
    assert device_identity_key("Head-A") != device_identity_key("HeadA")
    assert device_identity_key("") == ""


@pytest.mark.parametrize(
    ("field", "first", "second"),
    [
        ("device_id", "aa:bb:cc:dd:ee:01", "AA-BB-CC-DD-EE-01"),
        ("device_id", "aa:bb:cc:dd:ee:01", "aabbccddee01"),
        ("device_id", "Head-A", "head-a"),
        ("dock_beacon_id", 1, 1),
        ("id", "robot-01", "ROBOT-01"),
        ("head_url", "http://192.0.2.1:8081", "http://192.0.2.1:8082"),
    ],
)
def test_hardware_config_rejects_duplicate_identity(field, first, second):
    from desk_robot.config import ConfigurationError, load_settings

    with HARDWARE.open("rb") as stream:
        robots = tomllib.load(stream)["robots"]
    robots[0][field] = first
    robots[1][field] = second
    with pytest.raises(ConfigurationError):
        load_settings(HARDWARE, overrides={"robots": robots})


def test_hardware_config_preserves_literal_device_routing():
    from desk_robot.config import load_settings

    with HARDWARE.open("rb") as stream:
        robots = tomllib.load(stream)["robots"]
    robots[0]["device_id"] = "AA:BB:CC:DD:EE:01"
    robots[1]["device_id"] = "aa-bb-cc-dd-ee-02"
    settings = load_settings(HARDWARE, overrides={"robots": robots})
    assert [robot.device_id for robot in settings.robots] == [
        "AA:BB:CC:DD:EE:01", "aa-bb-cc-dd-ee-02", "", "", "",
    ]
