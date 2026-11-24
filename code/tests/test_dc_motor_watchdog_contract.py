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


def test_default_full_stepper_refuses_arming_without_independent_motor_cutoff():
    ini = (BODY / "platformio.ini").read_text(encoding="utf-8")
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    assert "-DDESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED=0" in ini
    assert "#define DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED 0" in main
    assert main.count(
        "#if DESK_ROBOT_STEPPER && !DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED"
    ) >= 1
    assert "#if !DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED" in main
    assert 'write_stepper(body_pins::kLeftStepperPins, 0);' in main
    assert 'write_stepper(body_pins::kRightStepperPins, 0);' in main
    assert '"ERR arm stepper_cutoff_unqualified"' in main
    assert '"READY desk-robot-body stepper motor_disabled_cutoff_unqualified"' in main


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
    # Firmware latches a missed CPU edge until deliberate local USB recovery.
    assert "if (!local_motion_authorized || missed_deadline_)" in heartbeat
    assert "void reset()" in heartbeat
    assert "motor_heartbeat.reset();" in main


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


def test_raw_contact_inhibition_precedes_optional_event_debounce():
    """Both raw GPIO paths must inhibit wheels before gesture timing."""
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    control = (BODY / "lib/BodyControl/BodyControl.cpp").read_text(
        encoding="utf-8"
    )
    for function, raw, delayed in (
        (
            "poll_touch",
            "control.sample_touch_input(active);",
            "if (now_ms - touch_last_sample_ms < 25) return;",
        ),
        (
            "poll_optional",
            "control.sample_bumper_input(digitalRead(body_pins::kBumperInput) == HIGH);",
            "if (now_ms - last_extra_sample_ms < 25) return;",
        ),
    ):
        signature = f"void {function}(std::uint32_t now_ms) {{"
        assert main.count(signature) == 1
        section = main.split(signature, 1)[1].split("\n}", 1)[0]
        assert section.index(raw) < section.index(delayed)

    assert "sample_bumper_input((enabled_mask & 1U) != 0U && bumper);" in control
    # Raw HIGH remains an interlock even before the first debounce mask.
    assert "const bool bumper_hit = state_.bumper_raw ||" in control
    assert "if (state_.bumper_raw ||" in control


def test_default_full_dc_wheels_stay_disabled_until_external_cutoff_qualified():
    ini = (BODY / "platformio.ini").read_text(encoding="utf-8")
    firmware = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    test_source = (BODY / "tests/guarded_body_tests.cpp").read_text(encoding="utf-8")
    assert "-DDESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED=0" in ini
    assert "#define DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED 0" in firmware
    assert "!DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED" in firmware
    assert "zero_motor_pwm();" in firmware.split(
        "#if DESK_ROBOT_FULL_SENSORS && !DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED", 1
    )[1].split("#else", 1)[0]
    assert "control.inhibit_unqualified_motor_cutoff();" in firmware
    assert "dc.inhibit_unqualified_motor_cutoff();" in test_source
    # Bench only: preserve the historical DC fixture for disconnected tests.
    assert "[env:esp32dev]" in ini
    bench_section = ini.split("[env:esp32dev]", 1)[1].split("\n[env:", 1)[0]
    assert "DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED=0" not in bench_section


def test_full_guarded_builds_enable_direct_nc_collision_contacts():
    ini = (BODY / "platformio.ini").read_text(encoding="utf-8")
    firmware = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    body = (BODY / "lib/BodyControl/BodyControl.cpp").read_text(encoding="utf-8")
    guarded = (BODY / "tests/guarded_body_tests.cpp").read_text(encoding="utf-8")
    wiring = (HARDWARE / "wiring.md").read_text(encoding="utf-8")

    def section(name):
        marker = "[env:" + name + "]"
        assert ini.count(marker) == 1
        return ini.split(marker, 1)[1].split("\n[env:", 1)[0]

    for name in ("esp32_full", "esp32_dc_full"):
        assert "-DDESK_ROBOT_ENABLE_BUMPER=1" in section(name)
    assert "DESK_ROBOT_ENABLE_BUMPER=1" not in section("esp32dev")
    assert "control.sample_bumper_input(digitalRead(body_pins::kBumperInput) == HIGH);" in firmware
    assert "if (guarded_motion_profile()) bumper_fault_latched_ = true;" in body
    assert "raw_bumper_trip_preempts_debounce_and_preserves_payload" in guarded
    assert "two normally closed bumpers wired in series" in wiring
    assert "External 3.3 V pullup is mandatory" in wiring


def test_uart_and_output_paths_check_cpu_deadline_without_advancing_pulses():
    """A resumed UART path must not drive PWM or refresh the one-shot."""
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    helper = main.split("void enforce_motor_heartbeat(bool advance) {", 1)[1].split(
        "\n}\n", 1
    )[0]
    outputs = main.split("void apply_outputs() {", 1)[1].split("\n}\n", 1)[0]
    uart = main.split("void process_input(", 1)[1].split("\n}\n", 1)[0]
    loop = main.split("void loop() {", 1)[1]
    assert main.count("motor_heartbeat.update(") == 1
    assert main.count("enforce_motor_heartbeat(true);") == 1
    assert "if (advance)" in helper
    assert "motor_heartbeat.check_authority(millis(), allow_heartbeat)" in helper
    assert "control.motor_watchdog_trip();" in helper
    assert loop.index("control.tick(millis());") < loop.index(
        "enforce_motor_heartbeat(true);"
    ) < loop.index("apply_outputs();")
    assert outputs.index("control.tick(millis());") < outputs.index(
        "enforce_motor_heartbeat(false);"
    ) < outputs.index("write_motor_pair(")
    assert uart.index("enforce_motor_heartbeat(false);") < uart.index("receiver.feed(")
    assert uart.index("apply_outputs();") < uart.index(
        'ERR drive motor_watchdog_latched'
    ) < uart.index("replies.enqueue_line(reply)")
    assert 'ERR arm motor_watchdog_latched' in uart
    assert 'completed && local_usb && strcmp(reply, "OK rearm") == 0' in uart
