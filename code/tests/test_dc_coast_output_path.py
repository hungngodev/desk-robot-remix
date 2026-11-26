"""Host-only DRV8833 watchdog-to-PWM coast regression (TI truth table 1)."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BODY = Path(__file__).resolve().parents[1] / "firmware/body"


def _function(source, signature):
    return signature + source.split(signature, 1)[1].split("\n}", 1)[0] + "\n}\n"


def test_watchdog_trip_coasts_both_bridges_without_releasing_servo(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    body = (BODY / "lib/BodyControl/BodyControl.cpp").read_text(encoding="utf-8")
    harness = r'''
#include <array>
#include <cassert>
#include <cstdlib>
#include <cstdint>
#define DESK_ROBOT_FULL_SENSORS 1
#define DESK_ROBOT_STEPPER 0
#define DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED 1
#define DESK_ROBOT_ENABLE_DC_WATCHDOG 1
constexpr int LOW = 0, HIGH = 1, OUTPUT = 1;
namespace body_pins {
constexpr int kMotorChannels[] = {0, 1, 2, 3};
constexpr int kServoChannels[] = {4, 5};
constexpr int kServoPins[] = {10, 11};
constexpr int kLiftServo = 10, kGripServo = 11, kDcHeartbeatPin = 23;
}
std::array<unsigned, 6> duties{};
bool pwm_ready = true, servo_attached = true;
int applied_left = 0, applied_right = 0, applied_lift = 40, applied_grip = 60;
void ledcWrite(int channel, unsigned duty) {
    duties.at(channel) = duty;
    assert(!(duties[0] && duties[1]));
    assert(!(duties[2] && duties[3]));
}
void ledcAttachPin(int, int) { std::abort(); }
void ledcDetachPin(int) { std::abort(); }
void pinMode(int, int) {}
void digitalWrite(int, int) {}
void delayMicroseconds(int) { std::abort(); }
unsigned servo_duty(int) { std::abort(); }
unsigned millis() { return 1000; }
unsigned micros() { return 1000000; }
struct DcDutyRamp {
    void reset() {}
    int update(unsigned, int target, bool armed) { return armed ? target : 0; }
} left_duty_ramp, right_duty_ramp;
void sample_raw_bumper() {}
void sample_raw_touch(unsigned) {}
struct State {
    int left = 0, right = 0, lift = 40, grip = 60, lift_target = 40, grip_target = 60;
    bool armed = true, servos_attached = true;
};
struct BodyControl {
    State state_;
    unsigned drive_duration_ms_ = 250, jaw_sample_motion_budget_ = 1;
    bool motor_watchdog_latched_ = false, pose_valid = true;
    const State& state() { return state_; }
    void tick(unsigned) {}
    void force_disarm() { std::abort(); }
    void invalidate_pose_continuity() { pose_valid = false; }
    void stop_motion();
    void motor_watchdog_trip();
} control;
struct Heartbeat {
    bool fault = false;
    bool update(unsigned, bool) { std::abort(); }
    bool check_authority(unsigned, bool allowed) { return allowed && !fault; }
    bool missed_deadline() { return fault; }
} motor_heartbeat;
'''
    for signature in (
        "void BodyControl::stop_motion() {", "void BodyControl::motor_watchdog_trip() {",
    ):
        harness += _function(body, signature)
    for signature in (
        "void zero_motor_pwm() {", "void write_motor_pair(",
        "void enforce_motor_heartbeat(bool advance) {", "void apply_outputs() {",
    ):
        harness += _function(main, signature)
    harness += r'''
int main() {
    for (int left : {-100, 0, 100}) {
        for (int right : {-100, 0, 100}) {
            control = BodyControl{};
            motor_heartbeat.fault = false;
            duties = {0, 0, 0, 0, 123, 234};
            applied_left = applied_right = 0;
            control.state_.left = left;
            control.state_.right = right;
            apply_outputs();
            assert(duties[0] == (left > 0 ? 255U : 0U));
            assert(duties[1] == (left < 0 ? 255U : 0U));
            assert(duties[2] == (right > 0 ? 255U : 0U));
            assert(duties[3] == (right < 0 ? 255U : 0U));
            motor_heartbeat.fault = true;
            for (int pass = 0; pass < 2; ++pass) {
                apply_outputs();
                assert((duties == std::array<unsigned, 6>{0, 0, 0, 0, 123, 234}));
                assert(!control.state_.armed && control.motor_watchdog_latched_);
                assert(!control.pose_valid && !control.drive_duration_ms_);
                assert(control.state_.servos_attached && servo_attached);
            }
        }
    }
}
'''
    binary = tmp_path / "watchdog_coast"
    no_pie = ["-fno-pie", "-no-pie"] if sys.platform == "linux" else []
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", *no_pie, "-x", "c++", "-",
         "-o", str(binary)],
        input=harness, text=True, check=True, capture_output=True, timeout=30,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)


@pytest.mark.parametrize("full", [0, 1])
def test_dc_boot_coasts_even_when_pwm_setup_fails(tmp_path, full):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    harness = r'''
#include <array>
#include <cassert>
constexpr int LOW = 0, HIGH = 1, OUTPUT = 1, INPUT = 0;
#include "BodyPins.h"
static_assert(body_pins::kMotorPins[0] == 25 && body_pins::kMotorPins[1] == 26);
static_assert(body_pins::kMotorPins[2] == 27 && body_pins::kMotorPins[3] == 32);
static_assert(body_pins::kLiftServo == 18 && body_pins::kGripServo == 19);
std::array<int, 40> latch{}, mode{}, attached{};
std::array<int, 6> duties{}, configured{};
int failed_channel = -1;
bool pwm_ready = false;
void digitalWrite(int pin, int value) {
    assert(value == LOW);
    latch.at(pin) = value;
}
void pinMode(int pin, int value) {
    if (value == OUTPUT) assert(latch.at(pin) == LOW);
    mode.at(pin) = value;
}
int ledcSetup(int channel, int frequency, int resolution) {
    for (int pin : body_pins::kMotorPins) {
        assert(mode.at(pin) == OUTPUT && latch.at(pin) == LOW);
    }
    assert(frequency == (channel < 4 ? 20000 : 50));
    assert(resolution == (channel < 4 ? 8 : 16));
    configured.at(channel) = channel != failed_channel;
    return configured.at(channel) ? frequency : 0;
}
void ledcWrite(int channel, int duty) {
    assert(duty == 0);
    duties.at(channel) = duty;
}
void ledcAttachPin(int pin, int channel) {
    assert(channel >= 0 && channel < 4);
    assert(pin == body_pins::kMotorPins[channel]);
    assert(mode.at(pin) == OUTPUT && latch.at(pin) == LOW);
    for (int i = 0; i < 6; ++i) {
        assert(configured.at(i) && duties.at(i) == 0);
    }
    assert(attached.at(pin) == -1);
    attached.at(pin) = channel;
}
unsigned esp_random() { return 1; }
struct Control {
    void set_boot_epoch(unsigned) {
        for (int pin : body_pins::kMotorPins) {
            assert(mode.at(pin) == OUTPUT && latch.at(pin) == LOW);
        }
    }
    void inhibit_unqualified_motor_cutoff() {}
} control;
struct Heartbeat { void reset() {} } motor_heartbeat;
'''
    for signature in ("void all_motor_inputs_low() {", "void zero_motor_pwm() {"):
        harness += _function(main, signature)
    # Exercise the real setup prefix, stopping before unrelated UART/sensor init.
    harness += "void setup() {" + main.split("void setup() {", 1)[1].split(
        "  Serial.begin(", 1
    )[0] + "}\n"
    harness += r'''
int main() {
    for (failed_channel = -1; failed_channel < 6; ++failed_channel) {
        latch.fill(HIGH);
        mode.fill(INPUT);
        attached.fill(-1);
        duties.fill(255);
        configured.fill(0);
        pwm_ready = false;
        setup();
        assert(pwm_ready == (failed_channel == -1));
        for (int i = 0; i < 4; ++i) {
            int pin = body_pins::kMotorPins[i];
            assert(mode.at(pin) == OUTPUT && latch.at(pin) == LOW);
            assert(duties.at(i) == 0);
            assert(attached.at(pin) == (pwm_ready ? i : -1));
        }
        for (int pin : body_pins::kServoPins) assert(attached.at(pin) == -1);
#if DESK_ROBOT_ENABLE_DC_WATCHDOG
        assert(latch.at(23) == LOW && mode.at(23) == OUTPUT);
        assert(attached.at(23) == -1);
#endif
    }
}
'''
    binary = tmp_path / "boot_coast"
    no_pie = ["-fno-pie", "-no-pie"] if sys.platform == "linux" else []
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", *no_pie,
         f"-DDESK_ROBOT_FULL_SENSORS={full}", "-DDESK_ROBOT_STEPPER=0",
         f"-DDESK_ROBOT_ENABLE_DC_WATCHDOG={full}",
         f"-DDESK_ROBOT_ENABLE_BUMPER={full}", "-I", str(BODY / "include"),
         "-DDESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED=0", "-x", "c++", "-",
         "-o", str(binary)],
        input=harness, text=True, check=True, capture_output=True, timeout=30,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)
