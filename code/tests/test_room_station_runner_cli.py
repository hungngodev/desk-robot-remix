"""Exercise the room station runner's real process exit contract."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_room_station_host.py"


@pytest.mark.skipif(shutil.which("c++") is None, reason="C++ compiler unavailable")
@pytest.mark.parametrize(
    ("source", "expected_success", "diagnostic"),
    [
        ("int main() { return 0; }", True, ""),
        ("#error compile failure", False, "compile failure"),
        ("int main() { return 7; }", False, "returned non-zero exit status 7"),
        (
            "int main() { volatile int zero = 0; return 1 / zero; }",
            False,
            "division by zero",
        ),
    ],
    ids=["success", "compile_failure", "test_failure", "undefined_behavior"],
)
def test_room_station_runner_cli_exit(tmp_path, source, expected_success, diagnostic):
    script = tmp_path / "scripts" / SCRIPT.name
    script.parent.mkdir()
    shutil.copyfile(SCRIPT, script)
    station = tmp_path / "firmware/room_station"
    (station / "src").mkdir(parents=True)
    (station / "tests").mkdir()
    (station / "src/main.cpp").write_text(
        "bool finite_temperature(float) { return true; }\nvoid jsbool();\n"
        "void bme_step(unsigned) {}\nvoid bme_observation();\n"
    )
    (station / "tests/a_probe.cpp").write_text(source + "\n")
    (station / "tests/z_probe.cpp").write_text("int main() { return 0; }\n")

    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=120,
    )

    assert (result.returncode == 0) is expected_success, result.stderr
    assert "Sanitizer test: a_probe.cpp" in result.stdout
    assert ("Sanitizer test: z_probe.cpp" in result.stdout) is expected_success
    if diagnostic:
        assert diagnostic in result.stderr
