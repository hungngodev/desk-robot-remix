from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

HEAD = Path(__file__).resolve().parents[1]


def test_rgb565_frame_bounds(tmp_path):
    compiler = shutil.which("c++")
    assert compiler is not None, "A native C++17 compiler is required"
    executable = tmp_path / "camera-frame-bounds"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(HEAD / "overlay"),
            str(HEAD / "tests/camera_frame_bounds_test.cc"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)
