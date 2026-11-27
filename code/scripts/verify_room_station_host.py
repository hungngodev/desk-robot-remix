"""Compile and run every portable room station C++ test with sanitizers."""

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


def _firmware_section(firmware: str, start: str, end: str) -> str:
    """Extract an exact test excerpt or report a drifted source marker."""
    _, marker, remainder = firmware.partition(start)
    if not marker:
        raise RuntimeError(f"Missing firmware excerpt start: {start!r}")
    section, marker, _ = remainder.partition(end)
    if not marker:
        raise RuntimeError(f"Missing firmware excerpt end: {end!r} after {start!r}")
    return start + section


def run_tests(station: Path, build: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        raise RuntimeError("C++17 compiler is required for station tests")
    includes = station / "src"
    sources = sorted((station / "tests").glob("*.cpp"))
    if not sources:
        raise RuntimeError("No room station C++ tests found")
    firmware = (includes / "main.cpp").read_text()
    temperature = _firmware_section(firmware, "bool finite_temperature(", "void jsbool(")
    step = _firmware_section(firmware, "void bme_step(", "void bme_observation(")
    (build / "bme_step_under_test.h").write_text(temperature + step)
    # Exercise the actual firmware's default, acquisition and JSON paths,
    # without requiring Arduino or duplicating their decision in a test fake.
    if any(source.name == "soil_profile_tests.cpp" for source in sources):
        soil_prefix = "\n".join(
            line for line in firmware.split("namespace {", 1)[0].splitlines()
            if not line.startswith("#include ")
        ) + "\n"
        report_ms = _firmware_section(firmware, "constexpr uint32_t kReportMs", ";") + ";\n"
        jsbool = _firmware_section(firmware, "void jsbool(", "void number(")
        soil = _firmware_section(
            firmware, "#if ROOM_SOIL_FITTED\n", "// The pinned Adafruit AMG88xx"
        )
        (build / "soil_profile_under_test.h").write_text(
            soil_prefix + report_ms + jsbool + soil
        )
    cmd = [
        compiler, "-Wall", "-Wextra", "-Wconversion", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
        "-fno-omit-frame-pointer", f"-I{includes}", f"-I{build}",
    ]
    if platform.system() == "Linux":
        cmd.append("-no-pie")
    if platform.system() == "Darwin":
        for sdk in (
            Path("/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1"),
            Path("/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk/usr/include/c++/v1"),
        ):
            if sdk.exists():
                cmd.extend(["-stdlib=libc++", f"-I{sdk}"])
                break
    for source in sources:
        executable = build / source.stem
        if source.name == "soil_profile_tests.cpp":
            # Expected behavior is independent of the production macro. The
            # default case intentionally has no -DROOM_SOIL_FITTED argument.
            for standard in ("c++11", "c++17"):
                for profile, flags in (
                    ("default", ["-DEXPECT_SOIL_ENABLED=0"]),
                    ("bench", ["-DEXPECT_SOIL_ENABLED=0", "-DROOM_SOIL_FITTED=0"]),
                    ("full", ["-DEXPECT_SOIL_ENABLED=1", "-DROOM_SOIL_FITTED=1"]),
                ):
                    print(f"Sanitizer test: {source.name} {standard} {profile}", flush=True)
                    subprocess.run(
                        [*cmd, f"-std={standard}", *flags, str(source), "-o", str(executable)],
                        check=True, timeout=30,
                    )
                    subprocess.run([str(executable)], check=True, timeout=15)
            continue
        print(f"Sanitizer test: {source.name}", flush=True)
        subprocess.run(
            [*cmd, "-std=c++17", str(source), "-o", str(executable)], check=True, timeout=30
        )
        subprocess.run([str(executable)], check=True, timeout=15)


def main() -> None:
    station = Path(__file__).resolve().parents[1] / "firmware/room_station"
    with tempfile.TemporaryDirectory(prefix="desk-room-host-") as directory:
        run_tests(station, Path(directory))


if __name__ == "__main__":
    main()
