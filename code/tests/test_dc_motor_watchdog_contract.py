"""Guard exact DC-only independent motor cutoff and mutually exclusive pins.

Static source agreement and pure C++ do not qualify any 3.3V 74HC123 pulse,
DRV8833 breakout nSLEEP pullup, stopping distance, charger or full robot.
"""
import shlex
import shutil
import subprocess
from configparser import ConfigParser
from pathlib import Path

import pytest

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
    setup = main.split("void setup() {", 1)[1].split("\n}\n", 1)[0]
    assert "digitalWrite(body_pins::kDcHeartbeatPin, LOW);" in setup
    assert "pinMode(body_pins::kDcHeartbeatPin, OUTPUT);" in setup
    assert setup.index("digitalWrite(body_pins::kDcHeartbeatPin, LOW);") < (
        setup.index("pinMode(body_pins::kDcHeartbeatPin, OUTPUT);"))
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
    # The emitter computes the coil from the validated wiring plan; check the
    # generated contract rather than requiring a hard-coded source literal.
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
            "const bool active = sample_raw_touch(now_ms);",
            "if (touch_debounce.poll(active, now_ms)) {",
        ),
        (
            "poll_optional",
            "sample_raw_bumper();",
            "if (now_ms - last_extra_sample_ms < 25) return;",
        ),
    ):
        signature = f"void {function}(std::uint32_t now_ms) {{"
        assert main.count(signature) == 1
        section = main.split(signature, 1)[1].split("\n}", 1)[0]
        assert section.index(raw) < section.index(delayed)

    raw_touch = main.split("bool sample_raw_touch(std::uint32_t now_ms) {", 1)[1].split("\n}\n", 1)[0]
    assert "control.sample_touch_input(active, now_ms, touch_debounce.baseline_ready());" in raw_touch
    raw_bumper = main.split("bool sample_raw_bumper() {", 1)[1].split("\n}\n", 1)[0]
    assert "control.sample_bumper_input(digitalRead(body_pins::kBumperInput) == HIGH);" in raw_bumper
    assert "return control.state().bumper_raw;" in raw_bumper
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
    assert "const bool allow_heartbeat = DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED &&" in helper
    assert "if (advance)" in helper
    assert "motor_heartbeat.check_authority(millis(), allow_heartbeat)" in helper
    assert "control.motor_watchdog_trip();" in helper
    heartbeat = loop.index("enforce_motor_heartbeat(true);")
    assert loop.index("control.tick(millis());") < heartbeat
    assert heartbeat < loop.index("apply_outputs();", heartbeat)
    assert outputs.index("control.tick(millis());") < outputs.index(
        "enforce_motor_heartbeat(false);"
    ) < outputs.index("write_motor_pair(")
    assert uart.index("enforce_motor_heartbeat(false);") < uart.index("receiver.feed(")
    veto = uart.index("desk_robot::MotionAckVeto::MotorWatchdogLatched")
    assert uart.index("apply_outputs();  // apply accepted") < uart.index(
        "if (completed && motor_heartbeat.missed_deadline())"
    ) < veto < uart.index("replies.enqueue_line(reply)")
    control = (BODY / "lib/BodyControl/BodyControl.cpp").read_text(encoding="utf-8")
    formatter = control.split("void veto_motion_ack(", 1)[1].split("\n}\n", 1)[0]
    assert '"motor_watchdog_latched"' in formatter
    assert '"ERR %s %s", command, reason' in formatter
    for command in ("arm", "drive"):
        assert f'command = "{command}";' in formatter
    assert 'completed && local_usb && strcmp(reply, "OK rearm") == 0' in uart


def test_watchdog_halt_clears_both_dc_motor_pairs_and_retains_servo_hold():
    """Check the complete logical path, not the physical nSLEEP voltage."""
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    control = (BODY / "lib/BodyControl/BodyControl.cpp").read_text(encoding="utf-8")
    pins = (BODY / "include/BodyPins.h").read_text(encoding="utf-8")
    trip = control.split("void BodyControl::motor_watchdog_trip() {", 1)[1].split(
        "\n}\n", 1
    )[0]
    stop = control.split("void BodyControl::stop_motion() {", 1)[1].split("\n}\n", 1)[0]
    zero = main.split("void zero_motor_pwm() {", 1)[1].split("\n}\n", 1)[0]
    pair = main.split("void write_motor_pair(", 1)[1].split("\n}\n", 1)[0]
    outputs = main.split("void apply_outputs() {", 1)[1].split("\n}\n", 1)[0]

    assert "motor_watchdog_latched_ = true;" in trip
    assert "stop_motion();" in trip
    assert "state_.armed = false;" in trip
    assert "state_.servos_attached = false;" not in trip
    assert "state_.left = 0;" in stop
    assert "state_.right = 0;" in stop
    assert "drive_duration_ms_ = 0;" in stop
    assert "state_.lift_target = state_.lift;" in stop
    assert "state_.grip_target = state_.grip;" in stop
    assert "constexpr int kMotorChannels[] = {0, 1, 2, 3};" in pins
    assert "for (int channel : body_pins::kMotorChannels) ledcWrite(channel, 0);" in zero
    assert "ledcWrite(forward_channel, 0);" in pair
    assert "ledcWrite(reverse_channel, percent < 0 ? duty : 0);" in pair
    assert "applied_left = left_duty_ramp.update(now_us, state.left, state.armed);" in outputs
    assert "applied_right = right_duty_ramp.update(now_us, state.right, state.armed);" in outputs
    assert (
        "write_motor_pair(body_pins::kMotorChannels[0], "
        "body_pins::kMotorChannels[1], applied_left);"
    ) in outputs
    assert (
        "write_motor_pair(body_pins::kMotorChannels[2], "
        "body_pins::kMotorChannels[3], applied_right);"
    ) in outputs


def test_shipped_profiles_never_opt_in_to_unmeasured_cutoff():
    """Inspect every declared environment, including inherited lab overrides."""
    ini = ConfigParser(interpolation=None)
    ini.read_string((BODY / "platformio.ini").read_text(encoding="utf-8"))
    keys = {
        "DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED",
        "DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED",
    }
    for section in ini.sections():
        flags = shlex.split(ini[section].get("build_flags", ""))
        for index, flag in enumerate(flags):
            if not flag.startswith("-D"):
                continue
            definition = flags[index + 1] if flag == "-D" else flag[2:]
            name, _, value = definition.partition("=")
            if name in keys:
                assert value == "0", (section, definition)

    for name, key in (
        ("esp32_full", "DESK_ROBOT_STEPPER_HARDWARE_CUTOFF_QUALIFIED"),
        ("esp32_dc_full", "DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED"),
    ):
        assert f"-D{key}=0" in shlex.split(ini[f"env:{name}"]["build_flags"])
    for name in ("esp32_dc_watchdog_lab", "esp32_dc_integrated_lab"):
        lab = ini[f"env:{name}"]
        assert lab["extends"] == "env:esp32_dc_full"
        assert "${env:esp32_dc_full.build_flags}" in lab["build_flags"]


def test_drivetrain_compile_guard_matrix():
    """Exercise the actual firmware preprocessor guards, not a duplicate model."""
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable for firmware guard syntax test")
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    start = main.index("#ifndef DESK_ROBOT_FULL_SENSORS")
    end = main.index('#if DESK_ROBOT_FULL_SENSORS\n#include "CliffGuard.h"', start)
    prelude = main[start:end].replace('#include "MotorHeartbeat.h"', "")
    dc = {"STEPPER": 0, "FULL_SENSORS": 1}
    stepper = {"STEPPER": 1, "FULL_SENSORS": 1}
    legacy = {"STEPPER": 0, "FULL_SENSORS": 0}
    guarded = {**dc, "ENABLE_DC_WATCHDOG": 1, "REQUIRE_DC_NFAULT": 1}
    cases = (
        (legacy, None),
        (stepper, None),
        (guarded, None),
        ({**guarded, "DC_HARDWARE_CUTOFF_QUALIFIED": 1}, None),
        (
            {**dc, "ENABLE_DC_WATCHDOG": 1, "DC_HARDWARE_CUTOFF_QUALIFIED": 1},
            "nFAULT monitor",
        ),
        ({**guarded, "REQUIRE_DC_NFAULT": 0}, "nFAULT monitor"),
        ({**guarded, "REQUIRE_DC_NFAULT": 2}, "nFAULT monitor"),
        (dc, "independent motor watchdog heartbeat"),
        ({**guarded, "ENABLE_DC_WATCHDOG": 0}, "independent motor watchdog heartbeat"),
        ({**guarded, "ENABLE_DC_WATCHDOG": 2}, "independent motor watchdog heartbeat"),
        ({**stepper, "ENABLE_DC_WATCHDOG": 1}, "requires full sensors with DC drive pins"),
        ({**stepper, "STEPPER_HARDWARE_CUTOFF_QUALIFIED": 2}, "must be 0 or 1"),
        ({**guarded, "DC_HARDWARE_CUTOFF_QUALIFIED": -1}, "must be 0 or 1"),
    )
    for flags, error in cases:
        definitions = [f"-DDESK_ROBOT_{key}={value}" for key, value in flags.items()]
        result = subprocess.run(
            [compiler, "-std=c++17", "-x", "c++", "-fsyntax-only", *definitions, "-"],
            input=prelude,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if error is None:
            assert result.returncode == 0, (flags, result.stderr)
        else:
            assert result.returncode != 0 and error in result.stderr, (flags, result.stderr)


@pytest.mark.parametrize(("stepper", "full", "qualified"), [
    (0, 0, 0), (0, 1, 0), (0, 1, 1), (1, 1, 0), (1, 1, 1),
])
def test_drivetrain_output_code_excluded_from_inert_profiles(stepper, full, qualified):
    """Preprocess real firmware branches; this is not a target firmware build."""
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable for firmware preprocessor test")
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    start = main.index("bool pwm_ready = false;")
    end = main.index("void process_input(", start)
    flags = {
        "STEPPER": stepper,
        "FULL_SENSORS": full,
        "DC_HARDWARE_CUTOFF_QUALIFIED": qualified,
        "STEPPER_HARDWARE_CUTOFF_QUALIFIED": qualified,
    }
    definitions = [f"-DDESK_ROBOT_{key}={value}" for key, value in flags.items()]
    result = subprocess.run(
        [compiler, "-E", "-P", "-x", "c++", *definitions, "-"],
        input=main[start:end],
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    output = result.stdout
    assert ("void write_motor_pair(" in output) == bool(not stepper and full and qualified)
    assert ("unsigned servo_duty(" in output) == bool(full)
    assert ("ledcAttachPin(body_pins::kLiftServo" in output) == bool(full)
    assert ("left_stepper.update(" in output) == bool(stepper and qualified)
    assert ("void write_stepper(" in output) == bool(stepper)
    if stepper and not qualified:
        assert "write_stepper(body_pins::kLeftStepperPins, 0);" in output
        assert "write_stepper(body_pins::kRightStepperPins, 0);" in output


def test_dc_motor_writes_coast_and_clear_inactive_channel_first(tmp_path):
    """Execute actual PWM function bodies with a recording LEDC boundary."""
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable for motor output test")
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    pins = (BODY / "include/BodyPins.h").read_text(encoding="utf-8")
    channels = pins.split("constexpr int kMotorChannels[]", 1)[1].split(";", 1)[0]
    functions = []
    for signature in ("void zero_motor_pwm()", "void write_motor_pair("):
        functions.append(signature + main.split(signature, 1)[1].split("\n}", 1)[0] + "\n}")
    source = r'''
#include <array>
#include <cstdlib>
#include <stdexcept>
#define CHECK(expr) do { if (!(expr)) throw std::runtime_error(#expr); } while (false)
#define DESK_ROBOT_STEPPER 0
namespace body_pins { constexpr int kMotorChannels[] CHANNELS; }
std::array<unsigned, 6> duties{};
void ledcWrite(int channel, unsigned duty) {
    CHECK(channel >= 0 && channel < 4);
    CHECK(duty <= 255);
    duties.at(channel) = duty;
    CHECK(!(duties[0] && duties[1]));
    CHECK(!(duties[2] && duties[3]));
}
'''.replace("CHANNELS", channels) + "\n".join(functions) + r'''
int main() {
    for (int pair : {0, 2}) {
        for (int previous : {-100, 0, 100}) {
            for (int next = -100; next <= 100; ++next) {
                duties = {0, 0, 0, 0, 123, 234};
                duties[pair] = previous > 0 ? 255 : 0;
                duties[pair + 1] = previous < 0 ? 255 : 0;
                duties[2 - pair] = 77;
                write_motor_pair(pair, pair + 1, next);
                const unsigned expected = static_cast<unsigned>(std::abs(next) * 255 / 100);
                CHECK(duties[pair] == (next > 0 ? expected : 0));
                CHECK(duties[pair + 1] == (next < 0 ? expected : 0));
                CHECK(duties[2 - pair] == 77 && duties[3 - pair] == 0);
                zero_motor_pwm();
                CHECK((duties == std::array<unsigned, 6>{0, 0, 0, 0, 123, 234}));
            }
        }
    }
}
'''
    binary = tmp_path / "dc_motor_outputs"
    result = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-x", "c++", "-",
         "-o", str(binary)],
        input=source, text=True, capture_output=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 0, result.stderr


def test_motor_output_latch_is_low_before_output_enable(tmp_path):
    """Execute the actual startup helper against a deliberately HIGH latch."""
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable for GPIO ordering test")
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    helper = "void all_motor_inputs_low() {" + main.split(
        "void all_motor_inputs_low() {", 1
    )[1].split("\n}\n", 1)[0] + "\n}"
    harness = r'''
#include <array>
#include <cstdlib>
#include "BodyPins.h"
constexpr int LOW = 0, OUTPUT = 1;
std::array<int, 40> latch{};
std::array<bool, 40> enabled{};
void digitalWrite(int pin, int value) { latch.at(pin) = value; }
void pinMode(int pin, int mode) {
    if (mode != OUTPUT || latch.at(pin) != LOW) std::abort();
    enabled.at(pin) = true;
}
''' + helper + r'''
int main() {
    latch.fill(1);
    all_motor_inputs_low();
    for (int pin : body_pins::kMotorPins)
        if (!enabled.at(pin) || latch.at(pin) != LOW) return 1;
}
'''
    for stepper in (0, 1):
        binary = tmp_path / f"boot_gpio_{stepper}"
        result = subprocess.run(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
             f"-DDESK_ROBOT_STEPPER={stepper}", "-I", str(BODY / "include"),
             "-x", "c++", "-", "-o", str(binary)],
            input=harness, text=True, capture_output=True, timeout=15, check=False,
        )
        assert result.returncode == 0, result.stderr
        result = subprocess.run(
            [str(binary)], capture_output=True, text=True, timeout=5, check=False,
        )
        assert result.returncode == 0, result.stderr


def test_servo_gpio_preloads_before_output_enable_and_pwm_detach():
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    bench = (BODY / "src/servo_center_bench.cpp").read_text(encoding="utf-8")
    for source in (main, bench):
        setup = source.split("void setup() {", 1)[1].split("Serial.begin(", 1)[0]
        servo = setup.split("body_pins::kServoPins) {", 1)[1].split("}", 1)[0]
        assert servo.index("digitalWrite(pin, LOW);") < servo.index("pinMode(pin, OUTPUT);")
        detach = source.split("ledcDetachPin(pin);", 1)
        assert detach[0].rstrip().splitlines()[-1].strip().startswith(
            "digitalWrite(pin, LOW);"
        )
        assert "pinMode(pin, OUTPUT);" in detach[1]


def test_all_dc_environments_require_watchdog_at_compile_time():
    """Compile the real guard with inherited shipping flags, then remove the watchdog."""
    ini = ConfigParser(interpolation=None)
    ini.read_string((BODY / "platformio.ini").read_text(encoding="utf-8"))

    def effective_flags(section):
        flags = []
        for token in shlex.split(ini[section]["build_flags"]):
            if token.startswith("${") and token.endswith(".build_flags}"):
                flags.extend(effective_flags(token[2:-len(".build_flags}")]))
            else:
                flags.append(token)
        return flags

    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable for firmware guard syntax test")
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    start = main.index("#ifndef DESK_ROBOT_FULL_SENSORS")
    end = main.index('#if DESK_ROBOT_FULL_SENSORS\n#include "CliffGuard.h"', start)
    prelude = main[start:end]
    watchdog = "-DDESK_ROBOT_ENABLE_DC_WATCHDOG"
    environments = [name for name in ini.sections() if name.startswith("env:esp32_dc_")]
    assert "env:esp32_dc_full" in environments
    for name in environments:
        flags = effective_flags(name)
        assert "-DDESK_ROBOT_STEPPER=0" in flags, name
        assert "-DDESK_ROBOT_FULL_SENSORS=1" in flags, name
        assert "-DDESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED=0" in flags, name
        assert watchdog + "=1" in flags, name
        without_watchdog = [flag for flag in flags if flag.split("=", 1)[0] != watchdog]
        for definitions, rejected in ((flags, False), (without_watchdog, True)):
            result = subprocess.run(
                [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
                 "-I", str(BODY / "lib/BodyControl"), *definitions, "-x", "c++", "-"],
                input=prelude, text=True, capture_output=True, check=False, timeout=10,
            )
            if rejected:
                assert result.returncode != 0, name
                assert "independent motor watchdog heartbeat" in result.stderr, name
            else:
                assert result.returncode == 0, (name, result.stderr)
