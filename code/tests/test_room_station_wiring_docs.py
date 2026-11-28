"""DRX-1457: source-level station wiring checks, not electrical qualification."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATION = ROOT / "code/firmware/room_station"
HARDWARE = ROOT / "docs/hardware"


@pytest.mark.parametrize(
    "relative_path",
    [
        "code/firmware/room_station/README.md",
        "docs/hardware/full-feature-wiring-and-shopping.md",
    ],
)
def test_room_station_wiring_documents_keep_electrical_contract(relative_path):
    doc = (ROOT / relative_path).read_text()
    for token in (
        "D22/P0.12",
        "D23/P0.11",
        "D1/P0.24 from radar TX",
        "D0/P0.25 to radar RX",
        "A0/D14/P0.04",
        "0x62",
        "0x77",
        "0x76",
        "0x69",
        "100 kHz",
        "256000",
        "Qwiic and STEMMA QT",
        "pullups to 3.3 V",
        "5 V station branch",
        "greater than 200 mA",
        "HOLD",
    ):
        assert token in doc


def test_room_station_wiring_matches_firmware_and_power_plan():
    firmware = (STATION / "src/main.cpp").read_text()
    for token in (
        "Wire.setClock(100000);",
        "Serial1.begin(256000);",
        "SCD41_I2C_ADDR_62",
        "kBmePrimary = 0x77;",
        "kBmeAlternate = 0x76;",
        "kAmgAddress = 0x69;",
        "analogRead(A0)",
    ):
        assert token in firmware
    pod = json.loads((HARDWARE / "full-feature-plan.json").read_text())["room_pod"]
    power = pod["power_reference"]
    assert power["ld2410c"]["rail_candidate_v"] == 5.0
    assert power["ld2410c"]["io_logic_v"] == 3.3
    assert power["ld2410c"]["supply_capacity_ma_must_exceed"] == 200
    assert power["soil_probe"]["rail_candidate_v"] == 3.3
    assert power["physical_release"].startswith("HOLD")
    thermal = next(module for module in pod["modules"] if module["id"] == "amg8833")
    assert thermal["purchase_status"] == "conditional_optional"
