"""The complete shared station must actually compile soil acquisition.

These are source contract checks, not physically applied 5V/3.3V tests.
"""
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


def test_ci_builds_complete_station_not_just_sensor_disabled_stub():
    ci = (ROOT / ".github/workflows/host-verification.yml").read_text()
    assert "pio run -d code/firmware/room_station -e feather_nrf52840_room_full" in ci
    assert "pio run -d code/firmware/room_station -e feather_nrf52840_room_bench" in ci
    note = (ROOT / "code/firmware/room_station/README.md").read_text()
    assert "A0" in note
    assert "3.3V" in note
    assert "room_full" in note
    assert "no 5V output reaches A0" in note
