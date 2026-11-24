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


def test_station_and_imu_supersessions_retained_in_decision_log():
    decisions = (ROOT / "docs/decision-log.md").read_text(encoding="utf-8")
    assert "Feather/USB-C breakout/continuous servo are spares" in decisions
    assert "**2026-11-23 owned station allocation supersession:**" in decisions
    assert "ONE shared read-only room" in decisions
    assert "reported_owned_total=1" in decisions
    assert "feather_nrf52840_room_bench" in decisions
    assert "not an authorized" in decisions
    assert "BerryIMU remains" in decisions


def test_parts_table_allocates_feather_to_one_station_without_spare_confusion():
    parts = (ROOT / "docs/hardware/parts.md").read_text(encoding="utf-8")
    assert "| Adafruit Feather nRF52840 | One reported owned |" in parts
    assert "ONE shared read-only room station serving five pets" in parts
    assert "physical assembly remain unqualified" in parts
    assert "Adafruit USB-C breakout #4090 and DFRobot SER0043 continuous servo" in parts
    assert "Adafruit Feather nRF52840, Adafruit USB-C breakout" not in parts


def test_historical_builder_table_uses_current_eight_ranges_and_two_muxes():
    import re

    plan = _record("docs/hardware/full-feature-plan.json")
    roles = {part["id"]: part for part in plan["parts"]}
    assert roles["cliff_obstacle"]["per_robot"] == 8
    assert roles["i2c_mux"]["per_robot"] == 2
    parts = (ROOT / "docs/hardware/parts.md").read_text(encoding="utf-8")
    rows = [row for row in parts.splitlines() if row.startswith("| ")]
    range_rows = [
        row for row in rows if "VL53L0X" in row and re.search(r"\bcarriers?\b", row)
    ]
    assert len(range_rows) == 3
    quantities = []
    for row in range_rows:
        quantity = re.fullmatch(r"(\d+) / (\d+)", row.split("|")[2].strip())
        assert quantity is not None, row
        quantities.append(tuple(map(int, quantity.groups())))
    assert sorted(quantities) == [(1, 5), (3, 15), (4, 20)]
    assert any("0x70 lanes 5–7" in row and "3 / 15" in row for row in range_rows)
    mux_rows = [row for row in rows if "TCA9548A mux" in row]
    assert len(mux_rows) == 1
    assert "| 2 / 10 |" in mux_rows[0]
    assert "0x71 accessory mux" in mux_rows[0]
    assert "eight matching carriers in all" in parts
    assert "fallback only if the selected MPU6050 is proven unsuitable" in parts
