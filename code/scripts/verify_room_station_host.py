"""Compile and run every portable room station C++ test with sanitizers."""

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


def run_tests(station: Path, build: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        raise RuntimeError("C++17 compiler is required for station tests")
    includes = station / "src"
    sources = sorted((station / "tests").glob("*.cpp"))
    if not sources:
        raise RuntimeError("No room station C++ tests found")
    firmware = (includes / "main.cpp").read_text()
    temperature = "bool finite_temperature(" + firmware.split(
        "bool finite_temperature(", 1
    )[1].split("void jsbool(", 1)[0]
    step = "void bme_step(" + firmware.split(
        "void bme_step(", 1
    )[1].split("void bme_observation(", 1)[0]
    (build / "bme_step_under_test.h").write_text(temperature + step)
    cmd = [
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Wconversion", "-Werror",
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
        print(f"Sanitizer test: {source.name}", flush=True)
        subprocess.run([*cmd, str(source), "-o", str(executable)], check=True, timeout=30)
        subprocess.run([str(executable)], check=True, timeout=15)


def main() -> None:
    station = Path(__file__).resolve().parents[1] / "firmware/room_station"
    with tempfile.TemporaryDirectory(prefix="desk-room-host-") as directory:
        run_tests(station, Path(directory))


if __name__ == "__main__":
    main()
