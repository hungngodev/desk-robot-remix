"""Exercise the actual body CMake registration guard with orphan source probes."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "orphan",
    [None, "tests/ordinary_tests.cpp", "tests/singular_test.cpp", "tests/nested/probe.cpp"],
)
def test_body_host_registration_rejects_uncompiled_sources(tmp_path, orphan):
    cmake = shutil.which("cmake")
    if cmake is None:
        pytest.skip("CMake is required to exercise the host registration guard")
    guard = Path(__file__).resolve().parents[1] / "firmware/body/cmake/VerifyHostTests.cmake"
    (tmp_path / "tests/nested").mkdir(parents=True)
    (tmp_path / "tests/main_tests.cpp").write_text("int main() { return 0; }\n")
    (tmp_path / "tests/nested/helper.cpp").write_text("void helper() {}\n")
    if orphan is not None:
        (tmp_path / orphan).write_text("int main() { return 0; }\n")
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\n"
        "project(registration_probe LANGUAGES CXX)\n"
        "enable_testing()\n"
        "add_executable(probe tests/main_tests.cpp tests/nested/helper.cpp)\n"
        "get_property(body_targets DIRECTORY PROPERTY BUILDSYSTEM_TARGETS)\n"
        "add_test(NAME probe COMMAND probe)\n"
        "set_property(DIRECTORY APPEND PROPERTY BODY_CTEST_TARGETS probe)\n"
        f'include("{guard.as_posix()}")\n'
    )
    result = subprocess.run(
        [cmake, "-S", str(tmp_path), "-B", str(tmp_path / "build")],
        capture_output=True, text=True, timeout=30,
    )
    output = result.stdout + result.stderr
    if orphan is None:
        assert result.returncode == 0, output
    else:
        assert result.returncode != 0, output
        assert orphan in output and "has no CTest executable" in output, output
