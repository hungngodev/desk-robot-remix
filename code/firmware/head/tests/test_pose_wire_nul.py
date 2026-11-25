import shutil
import subprocess
from pathlib import Path


def test_body_wire_rejects_escaped_nul_before_cjson(tmp_path):
    bridge = (Path(__file__).resolve().parents[1] / "overlay/robot_bridge.cc").read_text()
    start = bridge.index("bool BodyWireValid(")
    end = bridge.index("\n}", start) + 2
    predicate = bridge[start:end]
    gate = "if (!BodyWireValid(line))"
    assert bridge.index(gate) < bridge.index("MatchingError(line, command)")
    assert bridge.index(gate) < bridge.index("auto json = Parse(line);")
    assert 'return {503, false, "malformed body response"};' in bridge[
        bridge.index(gate):bridge.index("auto json = Parse(line);")
    ]
    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++17 compiler required"
    source = tmp_path / "pose_wire.cc"
    source.write_text(
        "#include <cassert>\n#include <string>\n" + predicate + r'''
int main() {
    assert(BodyWireValid(R"({"v":1,"body_boot":9,"origin":2,"seq":1,"sample_us":1234,"x_mm":0,"y_mm":0,"yaw_mrad":0,"quality":"valid"})"));
    assert(!BodyWireValid(R"({"quality":"valid\u0000bogus"})"));
    assert(!BodyWireValid(R"({"quality\u0000bogus":"valid"})"));
    assert(BodyWireValid(R"({"quality":"unavailable"})"));
    assert(!BodyWireValid(R"({"match\u0000spoof":true})"));
    assert(!BodyWireValid(R"({"fault":"none\u0000bad"})"));
    assert(BodyWireValid(R"({"match":false})"));
    assert(BodyWireValid("OK stop"));
}
'''
    )
    binary = tmp_path / "pose_wire"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True)


def test_body_wire_rejects_interior_cr_before_all_reply_matching(tmp_path):
    bridge = (Path(__file__).resolve().parents[1] / "overlay/robot_bridge.cc").read_text()
    start = bridge.index("bool BodyWireByteValid(")
    end = bridge.index("\n}", start) + 2
    gate = "if (!BodyWireByteValid(body_cr_pending, c))"
    assert bridge.index("bool body_cr_pending = false;") < bridge.index(gate)
    assert bridge.index(gate) < bridge.index("if (c == '\\r') continue;")
    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++17 compiler required"
    source = tmp_path / "pose_cr.cc"
    source.write_text(
        "#include <cassert>\n#include <cstdint>\n#include <string>\n" + bridge[start:end] + r'''
bool valid(const std::string& wire) {
    bool pending = false;
    for (unsigned char byte : wire) {
        if (!BodyWireByteValid(pending, byte)) return false;
    }
    return !pending;
}
int main() {
    assert(valid("{\"quality\":\"valid\"}\r\n"));
    assert(valid("{\"quality\":\"valid\"}\n"));
    assert(valid("EVT startup\r\n{}\r\n"));
    assert(!valid("{\"quality\":\"va\rlid\"}\n"));
    assert(!valid("ERR input unknown_\rcommand\n"));
    assert(!valid("{}\r\r\n"));
    assert(!valid("{}\r"));
    assert(!valid("O\rK stop\n"));
    assert(!valid("{\"match\":tr\rue}\n"));
    assert(valid("OK stop\r\n"));
    assert(valid("{\"match\":false}\r\n"));
}
'''
    )
    binary = tmp_path / "pose_cr"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True)
