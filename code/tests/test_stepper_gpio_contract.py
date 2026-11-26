"""Host GPIO trace for the real stepper output and scheduling functions."""

import shutil
import subprocess
from pathlib import Path

import pytest

BODY = Path(__file__).resolve().parents[1] / "firmware/body"


def test_stepper_gpio_coast_and_invalid_masks(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    main = (BODY / "src/main.cpp").read_text(encoding="utf-8")
    signature = "void write_stepper(const int (&pins)[4], std::uint8_t mask) {"
    writer = signature + main.split(signature, 1)[1].split("\n}", 1)[0] + "\n}\n"
    harness = r'''
#include "StepperDrive.h"
#include <array>
#include <cassert>
#include <cstdint>
constexpr int LOW = 0, HIGH = 1;
constexpr int pins[] = {0, 1, 2, 3};
constexpr std::array<unsigned, 8> phases{1, 3, 2, 6, 4, 12, 8, 9};
unsigned levels = 0;
unsigned writes = 0;
bool saw_high = false;
void digitalWrite(int pin, int level) {
    assert(pin >= 0 && pin < 4);
    if (level == HIGH) {
        saw_high = true;
        levels |= 1U << pin;
    } else {
        assert(level == LOW && !saw_high);
        levels &= ~(1U << pin);
    }
    ++writes;
}
WRITER
void check_write(unsigned mask, unsigned expected) {
    writes = 0;
    saw_high = false;
    write_stepper(pins, static_cast<std::uint8_t>(mask));
    assert(levels == expected && writes == 4);
    assert(saw_high == (expected != 0));
}
int main() {
    for (unsigned mask = 0; mask < 256; ++mask) {
        bool valid = false;
        for (auto phase : phases) valid |= mask == phase;
        levels = 15;
        check_write(mask, valid ? mask : 0);
    }
    for (int direction : {-40, 40}) {
        for (auto phase : phases) {
            for (bool disabled : {false, true}) {
                desk_robot::StepperDrive drive;
                std::uint32_t now = UINT32_MAX - 50000U;
                auto mask = drive.update(now, direction, true);
                for (int i = 0; i < 1000 && mask != phase; ++i) {
                    now += 1000;
                    mask = drive.update(now, direction, true);
                }
                assert(mask == phase);
                check_write(mask, phase);
                // No need to wait for the next electrical step deadline.
                check_write(drive.update(now, disabled ? direction : 0, !disabled), 0);
                assert(drive.mask() == 0 && drive.rate_milli_steps_per_second() == 0);
                check_write(drive.update(now + 250000U, direction, false), 0);
                check_write(drive.update(now + 250001U, direction, true), phase);
            }
        }
    }
}
'''.replace("WRITER", writer)
    source = tmp_path / "stepper_gpio.cpp"
    source.write_text(harness, encoding="utf-8")
    binary = tmp_path / "stepper_gpio"
    drive = BODY / "lib/StepperDrive"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
         "-fno-sanitize-recover=all", "-I", str(drive), str(source),
         str(drive / "StepperDrive.cpp"), "-o", str(binary)],
        check=True, timeout=30,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
