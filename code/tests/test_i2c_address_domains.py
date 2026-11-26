"""Static address-domain checks; actual mux isolation remains a hardware gate."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BODY = ROOT / "code/firmware/body/lib"


def _source_address(path, symbol):
    source = path.read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
    matches = re.findall(rf"\b{symbol}\s*=\s*(0x[0-9a-fA-F]+)\b", source)
    assert len(matches) == 1, (path, symbol, matches)
    return int(matches[0], 16)


def _address_rows():
    plan = json.loads((ROOT / "docs/hardware/full-feature-plan.json").read_text())
    bus = plan["bus"]
    # None denotes an always-visible target on the controller's physical bus.
    rows = [("wroom", None, None, d["address"]) for d in bus["upstream"]]
    touch = BODY / "ExpansionTouch/ExpansionTouch.h"
    tof = BODY / "TofBus/TofBus.h"
    for key, symbol in (("mux_ranges", "kMuxAddress"),
                        ("mux_extras", "kOptionalMuxAddress")):
        mux = bus[key]
        assert mux["address"] == _source_address(tof, symbol)
        assert sorted(lane["channel"] for lane in mux["channels"]) == list(range(8))
        for lane in mux["channels"]:
            for device in lane["devices"]:
                address = device["address"]
                if key == "mux_ranges":
                    assert address == _source_address(tof, "kSensorAddress")
                rows.append(("wroom", mux["address"], lane["channel"], address))
                if device["name"] == "CAP1188":
                    assert address == _source_address(touch, "kPreferredAddress")
                    rows.append(("wroom", mux["address"], lane["channel"],
                                 _source_address(touch, "kAlternativeAddress")))
                elif device["name"] == "BMP280":
                    # Both supported strap choices must avoid all lane peers.
                    assert address in (0x76, 0x77)
                    rows.append(("wroom", mux["address"], lane["channel"],
                                 0x77 if address == 0x76 else 0x76))
    # MPU6050 AD0 may be strapped high; reserve both supported addresses.
    mpu = next(d["address"] for d in bus["upstream"] if d["device"] == "MPU6050")
    assert mpu in (0x68, 0x69)
    rows.append(("wroom", None, None, 0x69 if mpu == 0x68 else 0x68))
    head = ROOT / "code/firmware/head/sense/desk_robot_sense.cc"
    room = ROOT / "code/firmware/room_station/src/main.cpp"
    rows.append(("sense_oled", None, None, _source_address(head, "dev_addr")))
    assert "scd.begin(Wire, SCD41_I2C_ADDR_62);" in room.read_text(encoding="utf-8")
    rows.append(("room", None, None, 0x62))
    for symbol in ("kBmePrimary", "kBmeAlternate", "kAmgAddress"):
        rows.append(("room", None, None, _source_address(room, symbol)))
    return rows


def _assert_unique(rows):
    for bus, mux, lane, address in rows:
        assert type(address) is int and 0x08 <= address <= 0x77
        assert (mux is None and lane is None) or (mux in (0x70, 0x71) and 0 <= lane < 8)
    duplicates = {row: count for row, count in Counter(rows).items() if count > 1}
    assert not duplicates, f"I2C address collision: {duplicates}"
    upstream = {(bus, address) for bus, mux, _, address in rows if mux is None}
    conflicts = [row for row in rows if row[1] is not None and (row[0], row[3]) in upstream]
    assert not conflicts, f"I2C upstream collision: {conflicts}"


def test_all_i2c_address_domains():
    rows = _address_rows()
    assert {row[:3] for row in rows if row[1] is not None} == {
        ("wroom", mux, lane) for mux in (0x70, 0x71) for lane in range(8)
    }
    assert {row[0] for row in rows} == {"wroom", "sense_oled", "room"}
    _assert_unique(rows)


@pytest.mark.parametrize("row", [
    ("wroom", 0x70, 0, 0x29),
    ("wroom", 0x71, 0, 0x28),
    ("wroom", 0x71, 3, 0x77),
    ("wroom", None, None, 0x69),
    ("sense_oled", None, None, 0x3C),
    ("room", None, None, 0x62),
    ("room", None, None, 0x76),
])
def test_duplicate_address_in_same_domain_is_rejected(row):
    rows = _address_rows()
    assert row in rows
    with pytest.raises(AssertionError, match="I2C address collision"):
        _assert_unique([*rows, row])


@pytest.mark.parametrize("address", [0x68, 0x69, 0x70, 0x71])
def test_downstream_address_cannot_shadow_upstream(address):
    with pytest.raises(AssertionError, match="I2C upstream collision"):
        _assert_unique([*_address_rows(), ("wroom", 0x71, 2, address)])


def test_same_address_on_isolated_buses_or_lanes_is_legal():
    _assert_unique([
        ("wroom", 0x70, 0, 0x29),
        ("wroom", 0x70, 1, 0x29),
        ("wroom", 0x71, 0, 0x29),
        ("sense_oled", None, None, 0x29),
        ("room", None, None, 0x29),
    ])
