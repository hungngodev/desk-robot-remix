"""The complete shared station must actually compile soil acquisition.

These are source contract checks, not physically applied 5V/3.3V tests.
"""
import json
import shutil
import subprocess
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



def test_amg8833_scan_is_bounded_incremental_and_never_fakes_frame_time():
    firmware = (
        ROOT / "code/firmware/room_station/src/main.cpp"
    ).read_text()
    stage = firmware.split("void thermal_step(", 1)[1].split(
        "void thermal_observation(", 1
    )[0]
    report = firmware.split("void thermal_observation(", 1)[1].split(
        "void report(", 1
    )[0]
    assert "thermal_step(now);" in firmware
    assert firmware.index("radar.read();") < firmware.index("thermal_step(now);")
    assert stage.count("read_thermal_chunk(") == 1
    assert "thermal_staging + 8U * thermal_next_chunk" in stage
    assert "thermal_valid = false;" in stage
    assert "thermal_next_chunk == AMG88xx_PIXEL_ARRAY_SIZE / 8U" in stage
    assert "thermal[i] = thermal_staging[i];" in stage
    assert "thermal_sample_ms = now;" in stage
    assert "thermal_valid = true;" in stage
    assert "kThermalScanMaxMs = 250;" in firmware
    assert "read_thermal_chunk" not in report
    assert "thermal_valid && now - thermal_sample_ms <= kThermalStaleMs" in report
    assert "Serial.print(thermal_sample_ms);" in report
    assert "Serial.print(now);" not in report


def test_bme_empty_upstream_conversion_cannot_reuse_old_gas_as_fresh():
    code = (ROOT / "code/firmware/room_station/src/main.cpp").read_text()
    # Upstream Adafruit_BME680 2.0.5 endReading() returns true on
    # n_fields=0 without updating public sensor values. Invalidate the
    # last gas value before initiating the next conversion.
    start = code.split("void bme_step(", 1)[1].split("void bme_observation(", 1)[0]
    assert "bme.gas_resistance = 0;" in start
    assert start.index("bme.gas_resistance = 0;") < start.index("bme.beginReading()")
    # Unsigned integer gas resistance uses >= 1 rather than > 0. Both
    # reject the zero sentinel; the upper bound rejects absurd stale data.
    assert "bme.gas_resistance >= 1" in start
    assert "bme.gas_resistance <= 1000000000U" in start
    assert "bme_completed.publish(bme.temperature, bme.humidity, bme.pressure," in start
    assert "bme.gas_resistance, now);" in start


def test_bme_unstable_gas_sentinel_is_not_sent_as_valid():
    code = (ROOT / "code/firmware/room_station/src/main.cpp").read_text()
    assert "isfinite(bme.gas_resistance) && bme.gas_resistance >= 1" in code
    assert "bme.gas_resistance <= 1000000000U" in code
    assert "bme.gas_resistance >= 0" not in code


def test_optional_radar_absence_never_blocks_shared_station_boot():
    # Pinned ncmreynolds/ld2410 v0.2.2 begin(Stream, true) waits up to
    # one second for firmware identification if the optional radar is absent.
    # Explicit nonblocking boot must preserve fresh UART packet gating.
    src = (ROOT / "code/firmware/room_station/src/main.cpp").read_text()
    assert "radar.begin(Serial1, false);" in src
    assert "radar.begin(Serial1);" not in src
    assert "radar.read();" in src
    assert "radar.isConnected()" in src
    assert "radar_sample_clock.has_sample()" in src


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
    assert "const bool fresh = bme_completed.fresh(now, kBmeStaleMs);" in report
    assert 'Serial.print(bme_completed.sample_ms);' in report
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

def test_scd40_readiness_failure_invalidates_cached_measurement_in_runtime():
    # The pure-C++ helper test is insufficient if the real Feather producer
    # accidentally stops calling it. Keep the actual firmware consumer wired.
    source = (ROOT / "code/firmware/room_station/src/main.cpp").read_text()
    helper = (ROOT / "code/firmware/room_station/src/scd_sample_freshness.h").read_text()
    poll = source.split("void scd_observation(uint32_t now) {", 1)[1].split(
        "void bme_step(", 1
    )[0]
    assert '#include "scd_sample_freshness.h"' in source
    assert "const int readiness_status = scd.getDataReadyStatus(ready);" in poll
    assert "if (readiness_status == 0 && ready)" in poll
    assert "scd_valid = desk_robot_room::scd_sample_valid_after_poll(" in poll
    assert "scd_valid, readiness_status, ready, measurement_valid);" in poll
    assert "const bool fresh = scd_valid && now - last_scd_ms <= kScdStaleMs;" in poll
    assert "if (readiness_status != 0) return false;" in helper
    ci = (ROOT / ".github/workflows/host-verification.yml").read_text()
    assert "room_station/tests/scd_sample_freshness_tests.cpp" in ci


def test_thermal_scan_publishes_only_complete_staged_frames():
    # An I2C failure in chunk eight may invalidate a scan. Never expose
    # a mixed old/new 64-pixel array or make the report block radar UART.
    source = (ROOT / "code/firmware/room_station/src/main.cpp").read_text()
    scan = source.split("void thermal_step(uint32_t now) {", 1)[1].split(
        "void thermal_observation(uint32_t now) {", 1
    )[0]
    report = source.split("void thermal_observation(uint32_t now) {", 1)[1].split(
        "void report(uint32_t now) {", 1
    )[0]
    assert "thermal_staging + 8U * thermal_next_chunk" in scan
    assert "thermal_valid = false;" in scan
    assert "if (++thermal_next_chunk == AMG88xx_PIXEL_ARRAY_SIZE / 8U)" in scan
    assert "thermal[i] = thermal_staging[i];" in scan
    assert scan.index("thermal[i] = thermal_staging[i];") < scan.index(
        "thermal_valid = true;"
    )
    assert "thermal_sample_ms = now;" in scan
    assert "read_thermal_chunk(" not in report
    assert "thermal_valid && now - thermal_sample_ms <= kThermalStaleMs" in report
    assert "thermal_step(now);" in source

def test_bme688_producer_ranges_match_room_decoder():
    # A BME outlier should be emitted as valid:false, not as a plausible
    # value that makes the Mac drop unrelated CO2, radar and thermal data.
    firmware = (ROOT / "code/firmware/room_station/src/main.cpp").read_text()
    mac = (ROOT / "code/laptop/src/desk_robot/room_station.py").read_text()
    sample = firmware.split("void bme_step(uint32_t now) {", 1)[1].split(
        "void bme_observation(", 1
    )[0]
    decoder = mac.split('elif sensor == "bme688":', 1)[1].split(
        'elif sensor == "ld2410c":', 1
    )[0]
    assert "bme.pressure >= 30000.0f" in sample
    assert "bme.pressure <= 125000.0f" in sample
    assert "bme.gas_resistance >= 1" in sample
    assert "bme.gas_resistance <= 1000000000U" in sample
    assert '_value(data, "pressure_pa", 30000, 125000)' in decoder
    assert '_value(data, "gas_ohms", 1, 1e9)' in decoder

def test_bme_pending_conversion_reports_only_last_completed_tuple():
    source = (ROOT / "code/firmware/room_station/src/main.cpp").read_text()
    helper = (ROOT / "code/firmware/room_station/src/bme_completed_sample.h").read_text()
    scan = source.split("void bme_step(uint32_t now) {", 1)[1].split(
        "void bme_observation(uint32_t now) {", 1
    )[0]
    report = source.split("void bme_observation(uint32_t now) {", 1)[1].split(
        "void radar_observation(", 1
    )[0]
    assert '#include "bme_completed_sample.h"' in source
    assert "bme.gas_resistance = 0;" in scan
    assert "if (!bme_pending) bme_completed.invalidate();" in scan
    assert "bme_completed.publish(" in scan
    assert "bme_completed.invalidate();" in scan
    assert "bme_completed.fresh(now, kBmeStaleMs)" in report
    assert "now_ms - sample_ms <= max_age_ms" in helper
    for raw in ("bme.temperature", "bme.humidity", "bme.pressure", "bme.gas_resistance"):
        assert raw not in report
    for field in ("temperature_c", "humidity_pct", "pressure_pa", "gas_ohms", "sample_ms"):
        assert "bme_completed." + field in report


def test_bme_completed_native_conversion_cache_with_sanitizers(tmp_path):
    # Executed C++ behavior, not just text matching a possible implementation.
    compiler = shutil.which("c++")
    assert compiler is not None, "C++17 compiler is required for station tests"
    src = ROOT / "code/firmware/room_station/tests/bme_completed_sample_tests.cpp"
    includes = ROOT / "code/firmware/room_station/src"
    executable = tmp_path / "bme_completed_sample_tests"
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        f"-I{includes}", str(src), "-o", str(executable),
    ], check=True, capture_output=True, text=True, timeout=30)
    subprocess.run([str(executable)], check=True, capture_output=True,
                   text=True, timeout=15)
