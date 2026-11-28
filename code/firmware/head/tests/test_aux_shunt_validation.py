"""Exercise the production AuxValid predicate with real cJSON wire values.

Host prerequisite: pkg-config and the cJSON development library (libcjson-dev
on Debian/Ubuntu, cjson on Homebrew). No ESP-IDF or UART hardware is required.
"""

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("standard", ["c++11", "c++17"])
def test_aux_shunt_validity_matches_ina226_range(tmp_path, standard):
    bridge = (Path(__file__).resolve().parents[1] / "overlay/robot_bridge.cc").read_text()
    start = bridge.index("bool AuxValid(cJSON* json)")
    predicate = bridge[start:bridge.index("\n}", start) + 2]
    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++ compiler required"
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "libcjson"], text=True,
    ))
    source = tmp_path / "aux_shunt.cc"
    source.write_text(
        "#include <cassert>\n#include <cmath>\n#include <memory>\n#include <string>\n"
        "#include <cJSON.h>\n" + predicate + r'''
void check(const char* shunt, const char* monitor, bool expected) {
    const std::string wire = R"({
        "pulse":{"present":false,"valid":false,"bpm":null,"medical":false,
                 "part_id":0,"red":0,"ir":0,"age_ms":0},
        "angles":{"present_mask":0,"valid_mask":0,"raw":[0,0,0],"magnet":[0,0,0]},
        "force":{"adc":[0,0],"jaw_seq":0,"valid":false,"calibrated":false},
        "climate":{"temp_centi":0,"rh_centi":0,"valid":false},
        "proximity":{"raw":0,"valid":false,"gesture":0,"gesture_events":0,
                     "physically_qualified":false},
        "power":{"cell_mv":0,"soc_centi":0,"bus_mv":0,"fuel_valid":false,
                 "current_calibrated":false,"shunt_uv":)" + std::string(shunt) +
                 R"(,"monitor_valid":)" + monitor + "}}";
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> json(
        cJSON_ParseWithLengthOpts(wire.c_str(), wire.size() + 1, nullptr, true),
        cJSON_Delete);
    assert(json);
    assert(AuxValid(json.get()) == expected);
}
int main() {
    // Adjacent valid ADC codes and both saturation rails.
    check("-81917", "true", true);
    check("81915", "true", true);
    check("0", "true", true);
    check("-81920", "true", false);
    check("81917", "true", false);
    check("-81918", "true", false);
    check("81916", "true", false);
    check("81920", "true", false);
    // Preserve bounded historical diagnostics without asserting validity.
    check("-81920", "false", true);
    check("81917", "false", true);
    check("81920", "false", true);
    check("-81921", "false", false);
    check("81921", "false", false);
    // Type and integer validation still applies regardless of validity.
    check("1.5", "true", false);
    check("1.5", "false", false);
    check("\"0\"", "true", false);
    check("0", "1", false);
    check("0", "null", false);
}
'''
    )
    binary = tmp_path / "aux_shunt"
    # Linux non-PIE avoids sporadic ASan shadow mapping conflicts.
    non_pie = ["-no-pie"] if sys.platform.startswith("linux") else []
    subprocess.run(
        [compiler, f"-std={standard}", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
         *non_pie, str(source), *flags, "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
