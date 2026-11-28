import shutil
import subprocess
import sys
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



def test_explicit_pose_version_skew_is_distinct_from_malformed_wire(tmp_path):
    overlay = Path(__file__).resolve().parents[1] / "overlay"
    bridge = (overlay / "robot_bridge.cc").read_text()
    start = bridge.index("bool PoseVersionUnsupported(")
    end = bridge.index("\n}", start) + 2
    gate = 'command.verb == "pose" && json && PoseVersionUnsupported(json.get())'
    transaction = bridge[bridge.index("auto json = Parse(line);"):]
    assert transaction.index(gate) < transaction.index("PoseValid(json.get())")
    assert 'return {501, false, "pose unsupported by body firmware"};' in transaction[
        transaction.index(gate):transaction.index("PoseValid(json.get())")
    ]
    assert 'return {503, false, "malformed or unsupported pose response"};' in transaction
    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++17 compiler required"
    source = tmp_path / "pose_version.cc"
    source.write_text(r'''
#include <cassert>
#include <cstring>
#include <limits>
#include "robot_protocol.h"
using desk_robot::UnsupportedPoseWireVersion;

// Parsed cJSON node fixture: exact types, object membership and duplicate keys.
struct cJSON {
    int type = 0;
    const char* string = nullptr;
    double valuedouble = 0;
    cJSON* child = nullptr;
    cJSON* next = nullptr;
};
bool cJSON_IsObject(const cJSON* p) { return p && p->type == 1; }
bool cJSON_IsNumber(const cJSON* p) { return p && p->type == 2; }
''' + bridge[start:end] + r'''
int main() {
    cJSON version{2, "v", 0};
    cJSON object{1, nullptr, 0, &version};
    for (double value : {0.0, 2.0, 4294967295.0}) {
        version.valuedouble = value;
        assert(PoseVersionUnsupported(&object));
    }
    for (double value : {1.0, -1.0, 0.5, 4294967296.0,
                         std::numeric_limits<double>::infinity(),
                         std::numeric_limits<double>::quiet_NaN()}) {
        version.valuedouble = value;
        assert(!PoseVersionUnsupported(&object));
    }
    version.valuedouble = 0;
    for (int type : {0, 1, 3, 4}) {
        version.type = type;
        assert(!PoseVersionUnsupported(&object));
    }
    version.type = 2;
    version.string = "V";
    assert(!PoseVersionUnsupported(&object));
    version.string = "v";
    cJSON extra{2, "other", 4};
    version.next = &extra;
    assert(PoseVersionUnsupported(&object));
    extra.string = "v";
    assert(!PoseVersionUnsupported(&object));
    object.child = nullptr;
    assert(!PoseVersionUnsupported(&object));
    assert(!PoseVersionUnsupported(nullptr));
    assert(!PoseVersionUnsupported(&version));
}
''')
    binary = tmp_path / "pose_version"
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", *pie_flags, "-I", str(overlay),
         str(source), "-o", str(binary)],
        check=True, timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
