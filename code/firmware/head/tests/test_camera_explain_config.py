from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("standard", ["c++11", "c++17"])
def test_camera_explain_configuration_is_atomic(tmp_path, standard):
    compiler = shutil.which("c++")
    assert compiler is not None, "A native C++ compiler is required"
    executable = tmp_path / "camera-explain-config"
    pie_flags = ["-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else []
    subprocess.run(
        [
            compiler,
            f"-std={standard}",
            "-Wall",
            "-Wextra",
            "-Wconversion",
            "-Werror",
            "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all",
            *pie_flags,
            "-pthread",
            "-I",
            str(HEAD / "overlay"),
            str(HEAD / "tests/camera_explain_config_test.cc"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True, timeout=15)
