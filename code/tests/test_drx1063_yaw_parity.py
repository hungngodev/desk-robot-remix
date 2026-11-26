"""Synthetic signed WROOM yaw and Mac decoding parity, not mount qualification."""

import math
import shutil
import subprocess
from pathlib import Path

import pytest
from desk_robot.handling import raw_mpu6050
from desk_robot.spatial_pose import decode_pose

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''
#include "ImuYawCapture.h"
#include <iostream>
using namespace desk_robot;
int main() {
  for (unsigned axis = 0; axis < 3; ++axis) {
    for (int sign : {-1, 1}) {
      for (int direction : {-1, 1}) {
        ImuYawCapture cap;
        ImuYawCapture::Calibration c{};
        c.axis = axis;
        c.sign = sign;
        c.bias_raw = 262;
        c.max_rate_raw = 20000;
        c.bias_uncertainty_raw = 1;
        c.scale_error_ppm = 1000;
        c.accel_norm_min_raw = 12000;
        c.accel_norm_max_raw = 20000;
        c.temp_min_raw = -1000;
        c.temp_max_raw = 1000;
        c.max_gap_ms = 200;
        c.max_age_ms = 150;
        c.max_yaw_error_urad = 500000;
        if (!cap.configure(c)) return 1;
        BerryReading r{};
        r.model = BerryModel::Mpu6050;
        r.valid = r.low_g_status_valid = true;
        r.accel[axis] = sign * 16384;
        r.gyro[axis] = c.bias_raw + sign * direction * 11790;
        r.at_ms = 100;
        if (cap.observe(r, 100) != ImuYawCapture::Result::Baseline) return 2;
        r.at_ms = 200;
        if (cap.observe(r, 200) != ImuYawCapture::Result::Delta) return 3;
        std::cout << axis << ' ' << sign << ' ' << direction << ' '
                  << r.gyro[axis] << ' ' << cap.yaw_urad() << '\n';
      }
    }
  }
}
'''


def test_signed_yaw_and_unsigned_handling_rate(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ host compiler required for firmware parity")
    source = tmp_path / "yaw.cpp"
    binary = tmp_path / "yaw"
    source.write_text(PROBE, encoding="utf-8")
    lib = ROOT / "firmware/body/lib"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(lib / "BodyControl"), "-I", str(lib / "BerryImu"),
         str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    result = subprocess.run(
        [str(binary)], check=True, capture_output=True, text=True, timeout=10,
    )
    rows = [tuple(map(int, line.split())) for line in result.stdout.splitlines()]
    assert len(rows) == 12
    assert {(a, s, d) for a, s, d, _, _ in rows} == {
        (a, s, d) for a in range(3) for s in (-1, 1) for d in (-1, 1)
    }
    for axis, sign, direction, raw, yaw_urad in rows:
        # +Z body yaw is CCW viewed from above (X forward, Y left).
        # The mounting sign maps sensor axes to that convention exactly once.
        assert yaw_urad == pytest.approx(direction * math.radians(9) * 1e6, abs=1)
        acc, gyro = [0, 0, 0], [0, 0, 0]
        acc[axis], gyro[axis] = sign * 16384, raw
        handling = raw_mpu6050({
            "drive_ms": 0, "motor": {"m0": 0, "m1": 0},
            "imu": {"family": 4, "gyro_id": 104, "valid": True, "age_ms": 0,
                    "boot_id": 1, "sample_ms": 200, "acc": acc, "gyro": gyro},
        })
        assert handling is not None
        gravity, rate = handling
        assert gravity[axis] == sign
        assert rate == pytest.approx(abs(raw) / 131)
        # Match the wire unit/truncation in WheelPoseIntegrator; this test
        # does not claim to execute wheel fusion or real UART serialization.
        pose = decode_pose({
            "robot_id": "robot-01", "v": 1, "body_boot": 1, "origin": 1,
            "seq": 1, "sample_us": 200000, "x_mm": 0, "y_mm": 0,
            "yaw_mrad": math.trunc(yaw_urad / 1000), "quality": "valid",
            "head_boot": 1,
        }, "robot-01", 1.0)
        assert pose.yaw_rad == pytest.approx(direction * 0.157)
