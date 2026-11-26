import tomllib
from pathlib import Path

import pytest
from desk_robot.fleet_identity import device_identity_key, valid_unique_robot_ids

ROOT = Path(__file__).resolve().parents[1]


def test_guide_identity_table_matches_hardware_examples():
    guide = (ROOT.parent / "docs/guides/five-robots.md").read_text(encoding="utf-8")
    rows = [
        tuple(cell.strip().strip("`") for cell in line.split("|")[1:-1])
        for line in guide.splitlines()
        if line.startswith("| robot-")
    ]
    assert [row[0] for row in rows] == [f"robot-{i:02}" for i in range(1, 6)]
    for example in ("fleet.example.toml", "fleet.hardware.example.toml", "robots.example.toml"):
        with (ROOT / "config" / example).open("rb") as stream:
            robots = tomllib.load(stream)["robots"]
        assert rows == [
            (robot["id"], robot["name"], robot["token_env"], robot["voice"]) for robot in robots
        ], example


@pytest.mark.parametrize("ids", [
    ["robot-01", "ROBOT-01"], ["robot-01", " robot-02"], ["COM1"], ["a" * 41],
])
def test_documented_robot_id_rejections(ids):
    assert not valid_unique_robot_ids(ids)


def test_documented_robot_id_acceptance():
    assert valid_unique_robot_ids(["Pip_01", "robot-02", "A" * 40])


@pytest.mark.parametrize("device_id", [
    "AABBCCDDEEFF", "aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", " aabbccddeeff ",
])
def test_documented_device_id_collision_keys(device_id):
    assert device_identity_key(device_id) == "aabbccddeeff"


def test_documented_non_mac_device_id_collision_keys():
    assert device_identity_key(" Sense-Pip ") == "sense-pip"
    assert device_identity_key("sensepip") != device_identity_key("sense-pip")
