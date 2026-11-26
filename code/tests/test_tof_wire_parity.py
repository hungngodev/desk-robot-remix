"""Executable parity for WROOM range limits and Mac optical wire evidence.

Distances are not transmitted in the optics object. A rejected raw distance
(including 8190) must instead clear its valid bit; raw quality remains diagnostic.
The 200 ms critical optical ceiling is not a measured corner revisit latency.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from desk_robot.tof_optics import validate_optics

BODY = Path(__file__).resolve().parents[1] / "firmware/body"

PROBE = r'''
#include "lib/TofBus/TofResult.h"
#include "lib/BodyControl/RangeSampleClock.h"
#include "lib/CliffGuard/CliffGuard.h"
#include <iostream>

int main() {
  using namespace desk_robot;
  for (unsigned mm : {0U, 29U, 30U, 31U, 1299U, 1300U, 1301U, 8190U, 65535U}) {
    CliffConfig config{};
    config.calibrated = true;
    config.freshness_ms = 200;
    for (auto& floor : config.floor) floor = {static_cast<std::uint16_t>(mm),
                                            static_cast<std::uint16_t>(mm)};
    config.front_obstacle_mm = 30;
    config.front_max_mm = 1300;
    CliffGuard guard;
    if (guard.configure(config) != (mm >= 30 && mm <= 1300)) return 1;
    for (unsigned signal : {31U, 32U, 33U}) {
      std::uint8_t raw[12]{};
      raw[0] = 11U << 3;
      raw[7] = static_cast<std::uint8_t>(signal);
      raw[10] = static_cast<std::uint8_t>(mm >> 8);
      raw[11] = static_cast<std::uint8_t>(mm);
      const auto decoded = decode_tof_result(raw);
      if (decoded.distance_mm != mm || decoded.signal_97 != signal ||
          decoded.accepted != (mm >= 30 && mm <= 1300 && signal >= 32)) return 2;
      for (unsigned lane = 0; lane < 8; ++lane) {
        for (unsigned age : {0U, 199U, 200U, 350U, 351U}) {
          const bool fresh = !range_sample_expired(true, lane < 5, age, 0);
          if (fresh != (lane < 5 ? age < 200 : age <= 350)) return 3;
          std::cout << mm << ' ' << signal << ' ' << lane << ' ' << age << ' '
                    << (decoded.accepted && fresh) << '\n';
        }
      }
    }
  }
}
'''


def test_wroom_optical_wire_boundaries(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ required for executable WROOM wire parity")
    source = tmp_path / "tof_wire_probe.cpp"
    source.write_text(PROBE, encoding="utf-8")
    executable = tmp_path / "tof_wire_probe"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(BODY),
         str(source), str(BODY / "lib/CliffGuard/CliffGuard.cpp"), "-o", str(executable)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    result = subprocess.run(
        [str(executable)], check=True, capture_output=True, text=True, timeout=30,
    )
    rows = result.stdout.splitlines()
    assert len(rows) == 9 * 3 * 8 * 5
    for row in rows:
        mm, signal, lane, age, accepted = map(int, row.split())
        mask = 1 << lane
        optics = {
            "ambient_97": [0] * 8, "signal_97": [0] * 8, "age_ms": [0] * 8,
            "present_mask": mask, "valid_mask": mask if accepted else 0,
            "physical_qualified": False, "motor_authorized": False,
        }
        optics["signal_97"][lane] = signal
        optics["age_ms"][lane] = age
        data = {"robot_id": "robot-01", "optics": optics}
        decoded = validate_optics(data, "robot-01")["optics"]
        assert decoded["valid_mask"] == optics["valid_mask"]
        assert decoded["motor_authorized"] is False
        assert decoded["signal_97"][lane] == signal
        # Distance cannot be reconstructed from optical quality. Compare a
        # claimed-valid bit only for an otherwise in-range firmware result.
        if 30 <= mm <= 1300:
            optics["valid_mask"] = mask
            if accepted:
                assert validate_optics(data, "robot-01")["optics"]["valid_mask"] == mask
            else:
                with pytest.raises(ValueError):
                    validate_optics(data, "robot-01")
