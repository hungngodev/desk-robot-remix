import shutil
import subprocess
from pathlib import Path


def test_pose_wire_rejects_escaped_nul_before_cjson(tmp_path):
    bridge = (Path(__file__).resolve().parents[1] / "overlay/robot_bridge.cc").read_text()
    start = bridge.index("bool PoseWireValid(")
    end = bridge.index("\n}", start) + 2
    predicate = bridge[start:end]
    gate = 'if (command.verb == "pose" && !PoseWireValid(line))'
    assert bridge.index(gate) < bridge.index("auto json = Parse(line);")
    assert 'return {503, false, "malformed or unsupported pose response"};' in bridge[
        bridge.index(gate):bridge.index("auto json = Parse(line);")
    ]
    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++17 compiler required"
    source = tmp_path / "pose_wire.cc"
    source.write_text(
        "#include <cassert>\n#include <string>\n" + predicate + r'''
int main() {
    assert(PoseWireValid(R"({"v":1,"body_boot":9,"origin":2,"seq":1,"sample_us":1234,"x_mm":0,"y_mm":0,"yaw_mrad":0,"quality":"valid"})"));
    assert(!PoseWireValid(R"({"quality":"valid\u0000bogus"})"));
    assert(!PoseWireValid(R"({"quality\u0000bogus":"valid"})"));
    assert(PoseWireValid(R"({"quality":"unavailable"})"));
}
'''
    )
    binary = tmp_path / "pose_wire"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True)
