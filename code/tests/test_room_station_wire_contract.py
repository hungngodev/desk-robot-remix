"""Room station wire measurements must match the actual Feather producer."""
import json

import pytest
from desk_robot.room_station import RoomStationDecoder


def _frame(seq: int, clock: int) -> dict:
    return {
        "v": 1, "station": "room-pod-01", "seq": seq, "at_ms": clock,
        "readings": {
            "scd40": {"valid": True, "sample_ms": clock, "co2_ppm": 630,
                      "temp_c": 23.4, "humidity_pct": 46.1},
            "bme688": {"valid": True, "sample_ms": clock, "temp_c": 24.0,
                       "humidity_pct": 44.5, "pressure_pa": 100830,
                       "gas_ohms": 35201},
            "ld2410c": {"valid": True, "sample_ms": clock, "presence": True,
                        "stationary": True, "moving": True,
                        "stationary_cm": 107, "moving_cm": 42},
            "soil": {"valid": False},
            "amg8833": {"valid": False},
        },
    }


@pytest.mark.parametrize(("sensor", "field", "value"), [
    ("scd40", "co2_ppm", 630.5),
    ("scd40", "co2_ppm", 630.0),
    ("bme688", "gas_ohms", 35201.5),
    ("bme688", "gas_ohms", 35201.0),
    ("ld2410c", "moving_cm", 42.5),
    ("ld2410c", "stationary_cm", 107.0),
    ("ld2410c", "moving_cm", 0),
    ("ld2410c", "stationary_cm", 0),
])
def test_impossible_wire_measurement_is_atomic(sensor, field, value):
    decoder = RoomStationDecoder()
    decoder.accept(json.dumps(_frame(1, 1000)), now=1.0)
    bad = _frame(2, 2000)
    bad["readings"][sensor][field] = value
    with pytest.raises(ValueError):
        decoder.accept(json.dumps(bad), now=2.0)
    good = decoder.accept(json.dumps(_frame(2, 2000)), now=2.0)
    assert good.seq == 2
    assert all(good.readings[name]["valid"] for name in ("scd40", "bme688", "ld2410c"))
    assert not good.motion_authorized and not good.charging_authorized


def test_inactive_radar_ranges_remain_compatible_with_firmware():
    payload = _frame(1, 1000)
    # The gate can retain nonzero distance fields with no active target.
    payload["readings"]["ld2410c"].update(
        moving=False, stationary=False, moving_cm=0, stationary_cm=65535,
    )
    result = RoomStationDecoder().accept(json.dumps(payload), now=1.0)
    assert result.readings["ld2410c"]["valid"]
    assert "Station radar detected an echo" in result.summary
    assert "65535 cm" not in result.summary


@pytest.mark.parametrize("gas", [0, -1, 0.5])
def test_existing_gas_range_rejection_keeps_its_error_contract(gas):
    payload = _frame(1, 1000)
    payload["readings"]["bme688"]["gas_ohms"] = gas
    with pytest.raises(ValueError, match="Room sensor reading out of range"):
        RoomStationDecoder().accept(json.dumps(payload), now=1.0)


@pytest.mark.parametrize(("sensor", "field", "value", "message"), [
    ("scd40", "co2_ppm", True, "Invalid room sensor number"),
    ("scd40", "co2_ppm", 50001.0, "Room sensor reading out of range"),
    ("scd40", "co2_ppm", 630.0, "CO2 ppm must be an integer"),
    ("ld2410c", "moving_cm", -1, "Room sensor reading out of range"),
    ("ld2410c", "moving_cm", -0.5, "Room sensor reading out of range"),
    ("ld2410c", "moving_cm", 65536, "Room sensor reading out of range"),
    ("soil", "raw_adc", 99999, "Invalid or saturated raw soil ADC sample"),
    ("soil", "raw_adc", True, "Invalid or saturated raw soil ADC sample"),
    ("scd40", "temp_c", float("nan"), "Nonfinite room JSON token NaN"),
])
def test_numeric_wire_error_precedes_coercion_and_preserves_decoder_epoch(
    sensor, field, value, message,
):
    decoder = RoomStationDecoder()
    decoder.accept(json.dumps(_frame(1, 1000)), now=1.0)
    bad = _frame(2, 2000)
    if sensor == "soil":
        bad["readings"]["soil"] = {"valid": True, "sample_ms": 2000, "raw_adc": 2000}
    bad["readings"][sensor][field] = value
    with pytest.raises(ValueError, match=message):
        decoder.accept(json.dumps(bad), now=2.0)

    corrected = _frame(2, 2000)
    corrected["readings"]["soil"] = {"valid": True, "sample_ms": 2000, "raw_adc": 2000}
    good = decoder.accept(json.dumps(corrected), now=2.0)
    assert good.seq == 2
    assert good.readings["soil"]["raw_adc"] == 2000
    assert not good.motion_authorized
    assert not good.charging_authorized
    assert not good.person_identified
