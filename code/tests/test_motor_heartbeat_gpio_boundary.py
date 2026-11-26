"""Exercise the real WROOM heartbeat GPIO boundary without motor hardware."""

import shutil
import subprocess
from pathlib import Path

import pytest

BODY = Path(__file__).resolve().parents[1] / "firmware/body"

HARNESS = r"""
#include <cstdint>
#include <cstdlib>
#include "MotorHeartbeat.h"
#define CHECK(condition) do { if (!(condition)) std::abort(); } while (false)
constexpr int LOW = 0, HIGH = 1;
namespace body_pins { constexpr int kDcHeartbeatPin = 23; }
struct Control {
    struct State { bool armed = true; int left = 20, right = 20; } drive;
    unsigned trips = 0;
    const State& state() const { return drive; }
    void motor_watchdog_trip() { ++trips; drive.armed = false; }
} control;
bool pwm_ready = true;
desk_robot::MotorHeartbeat motor_heartbeat;
std::uint32_t now = 0;
std::uint32_t millis() { return now; }
int level = LOW;
unsigned writes = 0, rises = 0;
void digitalWrite(int pin, int value) {
    CHECK(pin == body_pins::kDcHeartbeatPin);
    CHECK(value == LOW || value == HIGH);
    ++writes;
    if (level == LOW && value == HIGH) ++rises;
    level = value;
}
void reset(std::uint32_t start) {
    motor_heartbeat.reset(); control = Control{}; pwm_ready = true;
    now = start; level = LOW; writes = rises = 0;
}
"""

TRIAL = r"""
int main() {
    if (!DESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED) {
        reset(0);
        for (now = 0; now < 100; ++now) {
            enforce_motor_heartbeat(true);
            enforce_motor_heartbeat(false);
            CHECK(level == LOW && rises == 0 && control.trips == 0);
        }
        return 0;
    }
    for (std::uint32_t start : {100U, 0xfffffff0U}) {
        for (std::uint32_t high = 15; high <= 44; ++high) {
            for (std::uint32_t low = 15; low <= 44; ++low) {
                reset(start);
                enforce_motor_heartbeat(false);
                CHECK(writes == 0 && rises == 0);
                enforce_motor_heartbeat(true);
                CHECK(level == HIGH && rises == 1);
                // Command/output checks cannot create an edge or refresh its age.
                for (unsigned dt = 1; dt <= high; ++dt) {
                    now = start + dt;
                    enforce_motor_heartbeat(false);
                    CHECK(level == HIGH && writes == 1);
                }
                enforce_motor_heartbeat(true);
                CHECK(level == LOW && rises == 1);
                for (unsigned dt = 1; dt <= low; ++dt) {
                    now = start + high + dt;
                    enforce_motor_heartbeat(false);
                    CHECK(level == LOW && writes == 2);
                }
                enforce_motor_heartbeat(true);
                CHECK(level == HIGH && rises == 2 && control.trips == 0);
                CHECK(now - start >= 30 && now - start <= 88);
            }
        }
        for (bool high : {false, true}) {
            for (bool advance : {false, true}) {
                reset(start);
                enforce_motor_heartbeat(true);
                if (!high) { now += 15; enforce_motor_heartbeat(true); }
                const auto last_edge = now;
                for (unsigned dt = 1; dt < 45; ++dt) {
                    now = last_edge + dt;
                    enforce_motor_heartbeat(false);
                    CHECK(control.trips == 0);
                }
                now = last_edge + 45;
                enforce_motor_heartbeat(advance);
                CHECK(level == LOW && rises == 1 && control.trips > 0);
                control.drive.armed = true;
                ++now;
                enforce_motor_heartbeat(true);
                CHECK(level == LOW && rises == 1);
            }
        }
        reset(start);
        enforce_motor_heartbeat(true);
        for (unsigned dt = 1; dt < 15; ++dt) {
            now = start + dt;
            enforce_motor_heartbeat(true);
            CHECK(level == HIGH && rises == 1);
        }
        control.drive.left = control.drive.right = 0;
        enforce_motor_heartbeat(false);
        CHECK(level == LOW && rises == 1 && control.trips == 0);
        control.drive.left = 20;
        pwm_ready = false;
        enforce_motor_heartbeat(true);
        CHECK(level == LOW && rises == 1);
    }
}
"""


@pytest.mark.parametrize("qualified", [0, 1])
def test_real_motor_heartbeat_gpio_cadence_and_authority(tmp_path, qualified):
    compiler = shutil.which("g++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    source = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    signature = "void enforce_motor_heartbeat(bool advance) {"
    helper = signature + source.split(signature, 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    binary = tmp_path / "heartbeat_gpio"
    result = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         f"-DDESK_ROBOT_DC_HARDWARE_CUTOFF_QUALIFIED={qualified}",
         "-I", str(BODY / "lib/BodyControl"), "-x", "c++", "-", "-o", str(binary)],
        input="#include <initializer_list>\n" + HARNESS + helper + TRIAL,
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 0, result.stderr
