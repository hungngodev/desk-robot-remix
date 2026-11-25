import importlib.util
import shutil
import subprocess
from pathlib import Path


def _native_cpp_env():
    spec = importlib.util.spec_from_file_location(
        "test_overlay_env", Path(__file__).with_name("test_overlay.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.native_cpp_env()


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
#include <cmath>
#include <cstdint>
#include <limits>
#include <string>
#define CONFIG_DESK_ROBOT_ID "pet1"
struct cJSON {
    bool fail_id = false, fail_boot = false, fail_encode = false;
    bool has_id = false, has_boot = false;
    bool id_added = false, boot_added = false, encoded = false;
    uint32_t boot = 0;
    double valuedouble = 1234;
    bool has_sample = true, numeric_sample = true, fail_raw = false;
    std::string raw_sample;
};
cJSON* cJSON_GetObjectItemCaseSensitive(cJSON* body, const char* key) {
    if (std::string(key) == "robot_id") return body->has_id ? body : nullptr;
    if (std::string(key) == "head_boot") return body->has_boot ? body : nullptr;
    if (std::string(key) == "sample_us") return body->has_sample ? body : nullptr;
    return nullptr;
}
bool cJSON_IsNumber(const cJSON* item) { return item && item->numeric_sample; }
void cJSON_DeleteItemFromObjectCaseSensitive(cJSON* body, const char* key) {
    assert(std::string(key) == "sample_us" && body->has_sample);
    body->has_sample = false;
}
cJSON* cJSON_AddRawToObject(cJSON* body, const char* key, const char* raw) {
    assert(std::string(key) == "sample_us" && !body->has_sample);
    if (body->fail_raw) return nullptr;
    body->has_sample = true;
    body->raw_sample = raw;
    return body;
}
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
    assert(normal.raw_sample == "1234");
    for (const auto n : {999999999999999ULL, 1000000000000000ULL,
                         9007199254740990ULL, 9007199254740991ULL}) {
        cJSON boundary;
        boundary.valuedouble = static_cast<double>(n);
        assert(!EncodeBodyRead(&boundary, true, 123).empty());
        assert(boundary.raw_sample == std::to_string(n));
    }
    for (const double bad : {0.0, -1.0, 1.5, 9007199254740992.0,
                             std::numeric_limits<double>::infinity(),
                             std::numeric_limits<double>::quiet_NaN()}) {
        cJSON invalid;
        invalid.valuedouble = bad;
        assert(EncodeBodyRead(&invalid, true, 123).empty());
        assert(!invalid.boot_added && !invalid.encoded);
    }
    cJSON missing;
    missing.has_sample = false;
    assert(EncodeBodyRead(&missing, true, 123).empty());
    cJSON not_number;
    not_number.numeric_sample = false;
    assert(EncodeBodyRead(&not_number, true, 123).empty());
    cJSON no_raw;
    no_raw.fail_raw = true;
    assert(EncodeBodyRead(&no_raw, true, 123).empty());
    assert(!no_raw.boot_added && !no_raw.encoded);
    cJSON status;
    assert(!EncodeBodyRead(&status, false, 123).empty());
    assert(status.id_added && !status.boot_added && status.encoded);
    assert(status.raw_sample.empty());
    cJSON dup_id;
    dup_id.has_id = true;
    assert(EncodeBodyRead(&dup_id, true, 123).empty());
    assert(!dup_id.id_added && !dup_id.encoded);
    cJSON dup_boot;
    dup_boot.has_boot = true;
    assert(EncodeBodyRead(&dup_boot, true, 123).empty());
    assert(!dup_boot.id_added && !dup_boot.encoded);
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
        env=_native_cpp_env(), check=True,
    )
    subprocess.run([str(binary)], check=True)
