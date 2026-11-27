"""Guard automatic room station C++ test discovery and fatal failures."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_room_station_host.py"
SPEC = importlib.util.spec_from_file_location("verify_room_station_host", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def _assert_compiles_and_runs(calls, sources, build):
    assert sources
    expected_calls = sum(12 if s.name == "soil_profile_tests.cpp" else 2 for s in sources)
    assert len(calls) == expected_calls
    required_flags = {
        "-Wall", "-Wextra", "-Wconversion", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
        "-fno-omit-frame-pointer",
    }
    pos = 0
    for source in sources:
        profiles = [("-std=c++17",)]
        if source.name == "soil_profile_tests.cpp":
            profiles = [
                ("-std=c++11", "-DEXPECT_SOIL_ENABLED=0"),
                ("-std=c++11", "-DEXPECT_SOIL_ENABLED=0", "-DROOM_SOIL_FITTED=0"),
                ("-std=c++11", "-DEXPECT_SOIL_ENABLED=1", "-DROOM_SOIL_FITTED=1"),
                ("-std=c++17", "-DEXPECT_SOIL_ENABLED=0"),
                ("-std=c++17", "-DEXPECT_SOIL_ENABLED=0", "-DROOM_SOIL_FITTED=0"),
                ("-std=c++17", "-DEXPECT_SOIL_ENABLED=1", "-DROOM_SOIL_FITTED=1"),
            ]
        executable = str(build / source.stem)
        for profile in profiles:
            compile_cmd, compile_options = calls[pos]
            run_cmd, run_options = calls[pos + 1]
            pos += 2
            assert compile_cmd[0] == "c++"
            assert required_flags <= set(compile_cmd)
            # Compare the complete profile, including absence of a soil override
            # for the default build. A repeated or conflicting flag must fail.
            assert tuple(
                flag for flag in compile_cmd if flag.startswith(("-std=", "-D", "-U"))
            ) == profile
            assert f"-I{source.parent.parent / 'src'}" in compile_cmd
            assert f"-I{build}" in compile_cmd
            assert compile_cmd[-3:] == [str(source), "-o", executable]
            assert compile_options["check"] and run_options["check"]
            assert compile_options["timeout"] == 30
            assert run_options["timeout"] == 15
            assert run_cmd == [executable]


def test_room_station_runner_discovers_new_sources(tmp_path, monkeypatch):
    station = tmp_path / "station"
    sources = station / "tests"
    sources.mkdir(parents=True)
    includes = station / "src"
    includes.mkdir()
    (includes / "main.cpp").write_text(
        "#ifndef ROOM_SOIL_FITTED\n#define ROOM_SOIL_FITTED 0\n#endif\n"
        "namespace {\nconstexpr uint32_t kReportMs = 1000;\n"
        "bool finite_temperature(float) { return true; }\n"
        "void jsbool(bool value) {}\nvoid number();\n"
        "void bme_step(unsigned) {}\nvoid bme_observation();\n"
        "#if ROOM_SOIL_FITTED\nvoid soil_step() {}\n#endif\n"
        "// The pinned Adafruit AMG88xx\n"
    )
    (sources / "bme_step_tests.cpp").touch()
    (sources / "new_tests.cpp").touch()
    (sources / "probe.cpp").touch()
    (sources / "soil_profile_tests.cpp").touch()
    (sources / "README.md").touch()
    calls = []
    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "c++")
    monkeypatch.setattr(RUNNER.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
    RUNNER.run_tests(station, tmp_path)
    _assert_compiles_and_runs(
        calls,
        [sources / name for name in (
            "bme_step_tests.cpp", "new_tests.cpp", "probe.cpp", "soil_profile_tests.cpp",
        )],
        tmp_path,
    )
    assert "void bme_step(unsigned) {}" in (tmp_path / "bme_step_under_test.h").read_text()


def test_room_station_runner_covers_live_sources(tmp_path, monkeypatch):
    station = SCRIPT.parents[1] / "firmware/room_station"
    # Enumerate independently of the runner's glob so a narrowed pattern,
    # hardcoded inventory, duplicate or skipped execution fails this contract.
    sources = sorted(
        path for path in (station / "tests").iterdir()
        if path.is_file() and path.suffix == ".cpp"
    )
    calls = []
    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "c++")
    monkeypatch.setattr(RUNNER.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
    RUNNER.run_tests(station, tmp_path)
    _assert_compiles_and_runs(calls, sources, tmp_path)


def test_room_station_runner_rejects_empty_suite(tmp_path, monkeypatch):
    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "c++")
    with pytest.raises(RuntimeError, match="No room station C\\+\\+ tests found"):
        RUNNER.run_tests(tmp_path, tmp_path)


@pytest.mark.parametrize("failure_phase", ["compile", "execute"])
def test_room_station_runner_propagates_failed_test(tmp_path, monkeypatch, failure_phase):
    station = tmp_path / "station"
    (station / "tests").mkdir(parents=True)
    (station / "src").mkdir()
    (station / "src/main.cpp").write_text(
        "bool finite_temperature(float) {}\nvoid jsbool();\n"
        "void bme_step(unsigned) {}\nvoid bme_observation();\n"
    )
    (station / "tests/failure.cpp").touch()
    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "c++")
    calls = []

    def fail_on_command(cmd, **kwargs):
        calls.append(cmd)
        if (len(cmd) == 1) == (failure_phase == "execute"):
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(RUNNER.subprocess, "run", fail_on_command)
    with pytest.raises(subprocess.CalledProcessError):
        RUNNER.run_tests(station, tmp_path)
    assert len(calls) == (1 if failure_phase == "compile" else 2)
