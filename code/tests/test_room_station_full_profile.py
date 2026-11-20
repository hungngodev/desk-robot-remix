"""The complete shared station must actually compile soil acquisition.

These are source contract checks, not physically applied 5V/3.3V tests.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_station_has_both_full_soil_and_safe_bench_profiles():
    ini = (ROOT / "code/firmware/room_station/platformio.ini").read_text()
    assert "default_envs = feather_nrf52840_room_bench" in ini
    assert ini.count("[env:feather_nrf52840_room_full]") == 1
    assert ini.count("[env:feather_nrf52840_room_bench]") == 1
    assert "[env]\n" in ini
    full = ini.split("[env:feather_nrf52840_room_full]", 1)[1].split(
        "[env:feather_nrf52840_room_bench]", 1)[0]
    bench = ini.split("[env:feather_nrf52840_room_bench]", 1)[1]
    assert "build_flags = ${env.build_flags} -DROOM_SOIL_FITTED=1" in full
    assert "build_flags = ${env.build_flags} -DROOM_SOIL_FITTED=0" in bench
    assert ini.count("https://github.com/Sensirion/arduino-i2c-scd4x.git#1.1.0") == 1
    assert ini.count("https://github.com/adafruit/Adafruit_AMG88xx.git#1.3.2") == 1


def test_full_soil_adc_is_actual_three_sample_acquisition_not_stub():
    code = (ROOT / "code/firmware/room_station/src/main.cpp").read_text()
    helper = (ROOT / "code/firmware/room_station/src/soil_sample.h").read_text()
    assert "#if ROOM_SOIL_FITTED" in code
    assert "analogReadResolution(12);" in code
    assert "return analogRead(A0);" in code
    assert "read_soil_sample" in code
    assert "const int a = read();" in helper
    assert "const int b = read();" in helper
    assert "const int c = read();" in helper
    assert "largest - smallest > 256" in helper


def test_room_station_power_budget_is_machine_readable_and_fail_closed():
    plan = json.loads(
        (ROOT / "docs/hardware/full-feature-plan.json").read_text()
    )
    power = plan["room_pod"]["power_reference"]
    assert power["scd40"]["rail_candidate_v"] == 3.3
    assert power["scd40"]["peak_ma_at_3v3_max"] == 205
    assert power["scd40"]["periodic_average_ma_at_3v3_max"] == 18
    assert power["bme688"]["custom_mode_current_ma_max"] == 12
    assert power["amg8833"]["reference_current_ma_typ"] == 4.5
    assert power["ld2410c"]["rail_candidate_v"] == 5.0
    assert power["ld2410c"]["supply_capacity_ma_must_exceed"] == 200
    assert power["room_controller"]["regulator_3v3_peak_ma"] == 500
    assert power["room_controller"][
        "regulator_500ma_continuous_from_5v_qualified"
    ] is False
    for role in ("room_controller", "scd40", "bme688", "amg8833",
                 "ld2410c", "soil_probe"):
        assert any(
            key.endswith("_qualified") and value is False
            for key, value in power[role].items()
        )
    assert power["physical_release"].startswith("HOLD")



def test_bme688_gas_conversion_never_blocks_radar_uart_or_fakes_sample_age():
    # The pinned Adafruit_BME680 2.0.5 API supports an asynchronous
    # conversion; this is a source contract until physical Feather trials.
    code = (ROOT / "code/firmware/room_station/src/main.cpp").read_text()
    assert "bme.performReading()" not in code
    assert "bme_pending = bme.beginReading() != 0U;" in code
    assert "const int remaining = bme.remainingReadingMillis();" in code
    assert "if (remaining > Adafruit_BME680::reading_complete) return;" in code
    assert "remaining != Adafruit_BME680::reading_complete || !bme.endReading()" in code
    assert "bme_step(now);" in code
    assert code.index("radar.read();") < code.index("bme_step(now);")
    report = code.split("void bme_observation(", 1)[1].split("void radar_observation", 1)[0]
    assert "bme.beginReading()" not in report
    assert "bme.endReading()" not in report
    assert "const bool fresh = bme_valid && now - bme_sample_ms <= kBmeStaleMs;" in report
    assert 'Serial.print(bme_sample_ms);' in report
    assert "constexpr uint32_t kBmeStaleMs = 3000;" in code


def test_ci_builds_complete_station_not_just_sensor_disabled_stub():
    ci = (ROOT / ".github/workflows/host-verification.yml").read_text()
    assert "pio run -d code/firmware/room_station -e feather_nrf52840_room_full" in ci
    assert "pio run -d code/firmware/room_station -e feather_nrf52840_room_bench" in ci
    note = (ROOT / "code/firmware/room_station/README.md").read_text()
    assert "A0" in note
    assert "3.3V" in note
    assert "room_full" in note
    assert "no 5V output reaches A0" in note
    assert "LD2410C" in note
    assert "never** the Feather 3V pin" in note
    assert "nominally 4.5 to 5.2 V" in note
    assert "candidate source, not a qualified" in note
    assert "TX/RX remain 3.3 V logic only" in note
    assert "205 mA peak" in note
    assert "500 mA peak" in note
    assert "not a continuous 3.3 V budget" in note
    assert "greater than 200 mA" in note
    assert "run the exact fitted" in note
