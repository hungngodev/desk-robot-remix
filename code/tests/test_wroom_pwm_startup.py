"""Exercise the actual firmware startup PWM block against failed timer setup."""

import shutil
import subprocess
from pathlib import Path

import pytest

BODY = Path(__file__).resolve().parents[1] / "firmware/body"


def test_motor_pwm_attachment_requires_all_timers_ready(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    setup = main.split("void setup() {", 1)[1]
    startup = "pwm_ready = true;" + setup.split("pwm_ready = true;", 1)[1].split(
        "  Serial.begin(", 1
    )[0]
    harness = r'''
#include <array>
#include <cassert>
#define DESK_ROBOT_STEPPER 0
namespace body_pins {
constexpr int kMotorChannels[] = {0, 1, 2, 3};
constexpr int kMotorPins[] = {25, 26, 27, 32};
constexpr int kMotorFrequency = 20000, kMotorResolution = 8;
constexpr int kServoChannels[] = {4, 5};
constexpr int kServoFrequency = 50, kServoResolution = 16;
}
bool pwm_ready;
int failed_channel, configured, attached;
std::array<int, 6> duty;
int ledcSetup(int channel, int frequency, int) {
    ++configured;
    return channel == failed_channel ? 0 : frequency;
}
void ledcWrite(int channel, int value) { duty.at(channel) = value; }
void ledcAttachPin(int pin, int channel) {
    assert(failed_channel == -1);
    assert(configured == 6);
    assert(pin == body_pins::kMotorPins[channel]);
    for (int value : duty) assert(value == 0);
    ++attached;
}
void zero_motor_pwm() {
    for (int channel : body_pins::kMotorChannels) ledcWrite(channel, 0);
}
void initialize() {
''' + startup + r'''
}
int main() {
    for (failed_channel = -1; failed_channel < 6; ++failed_channel) {
        configured = attached = 0;
        duty.fill(255);
        initialize();
        assert(pwm_ready == (failed_channel == -1));
        assert(attached == (failed_channel == -1 ? 4 : 0));
        for (int value : duty) assert(value == 0);
    }
}
'''
    binary = tmp_path / "pwm_startup"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-x", "c++", "-",
         "-o", str(binary)],
        input=harness, text=True, check=True, timeout=30,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
