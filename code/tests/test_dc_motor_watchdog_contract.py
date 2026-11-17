"""Guard exact DC-only independent motor cutoff and mutually exclusive pins.

Static source agreement and pure C++ do not qualify any 3.3V 74HC123 pulse,
DRV8833 breakout nSLEEP pullup, stopping distance, charger or full robot.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BODY = ROOT / "code/firmware/body"
HARDWARE = ROOT / "docs/hardware"


def test_guarded_full_dc_must_compile_with_cpu_watchdog_even_outside_lab():
    ini = (BODY / "platformio.ini").read_text(encoding="utf-8")
    assert "default_envs = esp32_full" in ini

    def section(name):
        marker = "[env:" + name + "]"
        assert ini.count(marker) == 1
        return ini.split(marker, 1)[1].split("\n[env:", 1)[0]

    lab = section("esp32_dc_watchdog_lab")
    assert "extends = env:esp32_dc_full" in lab
    assert "-DDESK_ROBOT_ENABLE_DC_WATCHDOG=1" in lab
    # Full-sensor DC drive must never build without the independent CPU
    # heartbeat. The old test wrongly insisted the guarded DC profile omit
    # it, contradicting the fail-closed D15 firmware compile guard.
    assert "-DDESK_ROBOT_ENABLE_DC_WATCHDOG=1" in section("esp32_dc_full")
    for non_dc in ("esp32_full", "esp32_stepper", "esp32_full_haptic_lab"):
        assert "DESK_ROBOT_ENABLE_DC_WATCHDOG=1" not in section(non_dc)
    firmware = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    assert "#error Full-sensor DC motion requires the independent motor watchdog heartbeat" in firmware
    assert "!defined(DESK_ROBOT_ENABLE_DC_WATCHDOG)" in firmware


def test_gpio23_is_cpu_only_and_cannot_share_stepper_phase_or_ledc():
    pins = (BODY / "include/BodyPins.h").read_text(encoding="utf-8")
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    heartbeat = (BODY / "lib/BodyControl/MotorHeartbeat.h").read_text(
        encoding="utf-8")
    assert "constexpr int kDcHeartbeatPin = 23;" in pins
    assert "constexpr int kRightStepperPins[] = {27, 32, 33, 23};" in pins
    for line in ("constexpr int kLeftIn1 = 25;", "constexpr int kLeftIn2 = 26;",
                 "constexpr int kRightIn1 = 27;", "constexpr int kRightIn2 = 32;"):
        assert line in pins
    assert "#error Motor watchdog lab requires full sensors with DC drive pins" in main
    assert "motor_heartbeat.update(millis(), allow_heartbeat)" in main
    assert "drive.armed" in main
    assert "drive.left != 0 || drive.right != 0" in main
    assert "digitalWrite(body_pins::kDcHeartbeatPin, LOW);" in main
    assert "pinMode(body_pins::kDcHeartbeatPin, OUTPUT);" in main
    assert main.index("digitalWrite(body_pins::kDcHeartbeatPin, LOW);") < (
        main.index("pinMode(body_pins::kDcHeartbeatPin, OUTPUT);"))
    assert "kToggleIntervalMs = 15" in heartbeat
    assert "if (!local_motion_authorized)" in heartbeat
    assert "reset();" in heartbeat


def test_codegen_assembly_harness_and_hardware_note_agree_on_exclusion():
    emitter = (ROOT / "code/scripts/emit_wiring_manifest.py").read_text(
        encoding="utf-8")
    harness = (HARDWARE / "one-robot-signal-harness.generated.md").read_text(
        encoding="utf-8")
    note = (HARDWARE / "dc-motor-independent-watchdog.md").read_text(
        encoding="utf-8")
    assert "kDcHeartbeatPin" in emitter
    assert 'row("WROOM GPIO23 (DC only; same as STEP right coil 4)"' in emitter
    assert "| WROOM GPIO23 (DC only; same as STEP right coil 4) |" in harness
    assert "esp32_dc_watchdog_lab" in note
    assert "nSLEEP" in note
    assert "500 k" in note
    assert "NOT" in note
    assert "NOT" in harness or "unqualified" in harness


def test_procurement_requires_real_independent_motor_shutdown_receipt():
    release = (ROOT / "code/scripts/procurement_release.py").read_text(
        encoding="utf-8")
    assert '"hardware_motor_driver_fails_low_after_cpu_stall"' in release
    assert '"effective_selected_fleet_total"' in release
    assert '"physical_motor_variant_in_cart"' in release
    assert '"do_not_buy_legacy_stepper_when_dc_selected"' in release
