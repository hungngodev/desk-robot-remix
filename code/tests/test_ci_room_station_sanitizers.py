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


def test_room_station_runner_discovers_new_sources(tmp_path, monkeypatch):
    station = tmp_path / "station"
    sources = station / "tests"
    sources.mkdir(parents=True)
    includes = station / "src"
    includes.mkdir()
    (includes / "main.cpp").write_text(
        "bool finite_temperature(float) { return true; }\nvoid jsbool();\n"
        "void bme_step(unsigned) {}\nvoid bme_observation();\n"
    )
    (sources / "bme_step_tests.cpp").touch()
    (sources / "new_tests.cpp").touch()
    (sources / "README.md").touch()
    calls = []
    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "c++")
    monkeypatch.setattr(RUNNER.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
    RUNNER.run_tests(station, tmp_path)
    assert len(calls) == 4
    for index, name in enumerate(("bme_step_tests", "new_tests")):
        compile_cmd, compile_options = calls[index * 2]
        run_cmd, run_options = calls[index * 2 + 1]
        assert str(sources / f"{name}.cpp") in compile_cmd
        assert "-fsanitize=address,undefined" in compile_cmd
        assert "-fno-sanitize-recover=undefined" in compile_cmd
        assert "-Wconversion" in compile_cmd
        assert "-Werror" in compile_cmd
        assert compile_options["check"] and run_options["check"]
        assert run_cmd == [str(tmp_path / name)]
    assert "void bme_step(unsigned) {}" in (tmp_path / "bme_step_under_test.h").read_text()


def test_room_station_runner_rejects_empty_suite(tmp_path, monkeypatch):
    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "c++")
    with pytest.raises(RuntimeError, match="No room station C\\+\\+ tests found"):
        RUNNER.run_tests(tmp_path, tmp_path)


def test_room_station_runner_propagates_failed_test(tmp_path, monkeypatch):
    station = tmp_path / "station"
    (station / "tests").mkdir(parents=True)
    (station / "src").mkdir()
    (station / "src/main.cpp").write_text(
        "bool finite_temperature(float) {}\nvoid jsbool();\n"
        "void bme_step(unsigned) {}\nvoid bme_observation();\n"
    )
    (station / "tests/failure.cpp").touch()
    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "c++")

    def fail_on_execution(cmd, **kwargs):
        if len(cmd) == 1:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(RUNNER.subprocess, "run", fail_on_execution)
    with pytest.raises(subprocess.CalledProcessError):
        RUNNER.run_tests(station, tmp_path)
