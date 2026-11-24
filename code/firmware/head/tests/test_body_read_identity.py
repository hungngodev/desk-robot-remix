import shutil
import subprocess
from pathlib import Path


def test_body_read_metadata_and_encoding_fail_closed(tmp_path):
    bridge = (Path(__file__).resolve().parents[1] / "overlay/robot_bridge.cc").read_text()
    start = bridge.index("std::string EncodeBodyRead(")
    end = bridge.index("\n}", start) + 2
    gate = "const auto payload = EncodeBodyRead(body.get(), pose, bridge->boot_nonce_);"
    assert bridge.index(gate) < bridge.index("if (payload.empty())", bridge.index(gate))
    assert 'bridge->Json(req, 503, Envelope(false, "body identity or encoding unavailable"));' in bridge
    assert "bridge->Json(req, 200, payload);" in bridge
    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++17 compiler required"
    source = tmp_path / "body_read_identity.cc"
    source.write_text(r'''
#include <cassert>
#include <cstdint>
#include <string>
#define CONFIG_DESK_ROBOT_ID "pet1"
struct cJSON {
    bool fail_id = false, fail_boot = false, fail_encode = false;
    bool id_added = false, boot_added = false, encoded = false;
    uint32_t boot = 0;
};
cJSON* cJSON_AddStringToObject(cJSON* body, const char* key, const char* id) {
    assert(std::string(key) == "robot_id" && std::string(id) == "pet1");
    if (body->fail_id) return nullptr;
    body->id_added = true;
    return body;
}
cJSON* cJSON_AddNumberToObject(cJSON* body, const char* key, uint32_t boot) {
    assert(std::string(key) == "head_boot" && body->id_added);
    if (body->fail_boot) return nullptr;
    body->boot_added = true;
    body->boot = boot;
    return body;
}
std::string Encode(cJSON* body) {
    body->encoded = true;
    return body->fail_encode ? "{}" : "{\"robot_id\":\"pet1\"}";
}
''' + bridge[start:end] + r'''
int main() {
    cJSON normal;
    assert(!EncodeBodyRead(&normal, true, 123).empty());
    assert(normal.id_added && normal.boot_added && normal.boot == 123 && normal.encoded);
    cJSON status;
    assert(!EncodeBodyRead(&status, false, 123).empty());
    assert(status.id_added && !status.boot_added && status.encoded);
    cJSON no_id;
    no_id.fail_id = true;
    assert(EncodeBodyRead(&no_id, true, 123).empty());
    assert(!no_id.boot_added && !no_id.encoded);
    cJSON no_boot;
    no_boot.fail_boot = true;
    assert(EncodeBodyRead(&no_boot, true, 123).empty());
    assert(no_boot.id_added && !no_boot.encoded);
    cJSON no_json;
    no_json.fail_encode = true;
    assert(EncodeBodyRead(&no_json, true, 123).empty());
    assert(no_json.id_added && no_json.boot_added && no_json.encoded);
}
''')
    binary = tmp_path / "body_read_identity"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True)
