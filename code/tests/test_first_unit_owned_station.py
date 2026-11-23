"""Owned station hardware must never be mistaken for five extra robot MCUs."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _record(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_owned_feather_allocated_once_to_required_shared_station():
    inventory = _record("docs/hardware/fleet-inventory.json")
    plan = _record("docs/hardware/full-feature-plan.json")
    controller = next(
        row for row in inventory["components"]
        if row["component"] == "Adafruit Feather nRF52840"
    )
    station = next(
        row for row in plan["room_pod"]["modules"]
        if row["id"] == "room_controller"
    )
    assert plan["target_robots"] == 5
    assert controller["owned_count"] == station["reported_owned_total"] == 1
    assert controller["needed_per_robot"] == 0
    assert controller["needed_for_shared_station"] == station["quantity_per_room"] == 1
    assert controller["needed_for_five"] == 1  # ONE station for five pets
    assert "uninspected" in controller["usage"]
    assert "read-only USB room station" in controller["usage"]

    profiles = (
        ROOT / "code/firmware/room_station/platformio.ini"
    ).read_text(encoding="utf-8")
    assert "board = adafruit_feather_nrf52840" in profiles
    assert "default_envs = feather_nrf52840_room_bench" in profiles
    assert "[env:feather_nrf52840_room_full]" in profiles
    # A selected firmware target is not an inspected PCB or power qualification.
    assert station["location"].endswith("not yet an approved controller")


def test_berryimu_spare_does_not_replace_selected_mpu6050():
    inventory = _record("docs/hardware/fleet-inventory.json")
    plan = _record("docs/hardware/full-feature-plan.json")
    parts = {p["id"]: p for p in plan["parts"]}
    assert parts["imu"]["per_robot"] == 1
    assert "MPU6050" in parts["imu"]["name"]
    assert "BerryIMU" not in parts["imu"]["name"]
    owned = {p["component"]: p for p in inventory["components"]}
    berry = next(p for name, p in owned.items() if name.startswith("OzzMaker BerryIMU"))
    assert berry["needed_per_robot"] == 0
    assert berry["functionality_tested"] is False
    assert "MPU6050 remains the selected first-unit IMU" in inventory["note"]
    assert "BerryIMU replaces new IMU procurement" not in inventory["note"]
