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
#include "lib/TofBus/RangeScanOrder.h"
#include "lib/BodyControl/RangeSampleClock.h"
#include "lib/CliffGuard/CliffGuard.h"
#include <iostream>

// Admission is a scheduler heuristic; it is not a physical latency bound.
static bool check_scan_admission() {
  using desk_robot::RangeScanOrder;
  for (std::uint32_t start : {0U, 0xfffffff0U}) {
    for (unsigned elapsed : {99U, 100U}) {
      RangeScanOrder scan(true);
      for (unsigned lane = 0; lane < 5; ++lane) {
        if (scan.next(start + lane) != lane) return false;
      }
      if (scan.next(start + elapsed) != (elapsed < 100U ? 5U : 0U)) return false;
    }
    for (unsigned expiry = 30; expiry <= 200; ++expiry) {
      for (unsigned elapsed : {expiry / 2U - 1U, expiry / 2U}) {
        RangeScanOrder scan(true);
        for (unsigned lane = 0; lane < 5; ++lane) {
          if (scan.next(start + lane, expiry) != lane) return false;
        }
        if (scan.next(start + elapsed, expiry) != (elapsed < expiry / 2U ? 5U : 0U))
          return false;
      }
    }
  }
  return true;
}

// After a failed critical selection, prioritize two full critical recovery
// sweeps without optional lanes, then preserve the paused side rotation.
static bool check_fault_rotation() {
  desk_robot::RangeScanOrder scan(true);
  for (unsigned lane = 0; lane < 5; ++lane) {
    if (scan.next(lane * 10U) != lane) return false;
  }
  if (scan.next(60) != 5 || scan.next(61) != 0) return false;
  scan.transport_fault();
  for (unsigned now = 70; now < 80; ++now) {
    const auto lane = scan.next(now);
    if (lane >= 5) return false;
    scan.transport_succeeded(lane);
  }
  if (scan.degraded() || scan.next(80) != 6) return false;
  for (unsigned now = 81; now < 86; ++now) {
    if (scan.next(now) != now - 81U) return false;
  }
  if (scan.next(86) != 7) return false;
  for (unsigned now = 87; now < 92; ++now) {
    if (scan.next(now) != now - 87U) return false;
  }
  return scan.next(92) == 5;
}

int main() {
  using namespace desk_robot;
  if (!check_scan_admission()) return 4;
  if (!check_fault_rotation()) return 5;
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
