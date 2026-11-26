"""Exercise the actual DC output ramp, not measured wheel speed or slip."""
import shutil
import subprocess
from pathlib import Path

import pytest

BODY = Path(__file__).resolve().parents[1] / "firmware/body"


def test_dc_duty_ramp(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    source = r'''
#include "DcDutyRamp.h"
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <initializer_list>
#define CHECK(x) do { if (!(x)) return __LINE__; } while (false)
int main() {
    for (int sign : {-1, 1}) {
        desk_robot::DcDutyRamp ramp;
        const auto start = std::numeric_limits<std::uint32_t>::max() - 10000U;
        const int request = sign > 0 ? std::numeric_limits<int>::max()
                                     : std::numeric_limits<int>::min();
        CHECK(ramp.update(start, request, true) == 0);
        for (std::uint32_t elapsed = 1000; elapsed <= 600000; elapsed += 1000) {
            const auto now = start + elapsed;
            const int expected = static_cast<int>(elapsed * 80U / 1000000U);
            const int duty = sign * (expected < 40 ? expected : 40);
            CHECK(ramp.update(now, request, true) == duty);
            CHECK(ramp.update(now, request, true) == duty);
        }
        // A smaller same-direction command must also slew, not jump.
        CHECK(ramp.update(start + 601000U, sign * 10, true) == sign * 39);
        for (std::uint32_t elapsed = 602000; elapsed <= 1100000; elapsed += 1000) {
            const int expected = 40 - static_cast<int>(((elapsed - 600000U) * 80U +
                                                       999999U) / 1000000U);
            const int duty = sign * (expected > 10 ? expected : 10);
            CHECK(ramp.update(start + elapsed, sign * 10, true) == duty);
        }
        const auto reverse = start + 1101000U;
        CHECK(ramp.update(reverse, -sign * 40, true) == 0);
        CHECK(ramp.update(reverse + 12499U, -sign * 40, true) == 0);
        CHECK(ramp.update(reverse + 12500U, -sign * 40, true) == -sign);
        CHECK(ramp.update(reverse + 12600U, 0, true) == 0);
        CHECK(ramp.update(reverse + 12700U, request, true) == 0);
        CHECK(ramp.update(reverse + 1000000U, request, true) == sign);
        CHECK(ramp.update(reverse + 1000001U, request, false) == 0);
        CHECK(ramp.update(reverse + 2000000U, request, true) == 0);
    }
    return EXIT_SUCCESS;
}
'''
    binary = tmp_path / "dc_duty_ramp"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(BODY / "lib/BodyControl"), "-x", "c++", "-", "-o", str(binary)],
        input=source, text=True, capture_output=True, check=True, timeout=15,
    )
    result = subprocess.run([str(binary)], capture_output=True, timeout=5, check=False)
    assert result.returncode == 0, result.returncode
