import shutil
import subprocess
import sys
from pathlib import Path


def test_bridge_reclaims_idle_http_sessions():
    source = (Path(__file__).resolve().parents[1] / "overlay/robot_bridge.cc").read_text()
    config = source.split("httpd_config_t config = HTTPD_DEFAULT_CONFIG();", 1)[1]
    config = config.split("httpd_start(&server_, &config)", 1)[0]
    assert "config.lru_purge_enable = true;" in config
    assert "config.recv_wait_timeout = 2;" in config
    assert "config.send_wait_timeout = 2;" in config


def test_malformed_json_closes_only_its_http_session():
    source = (Path(__file__).resolve().parents[1] / "overlay/robot_bridge.cc").read_text()
    handle = source.split("esp_err_t Bridge::Handle(httpd_req_t* req)", 1)[1]
    reject = handle.split("const auto reject =", 1)[1].split("};", 1)[0]
    assert 'httpd_resp_set_hdr(req, "Connection", "close");' in reject
    assert "return ESP_FAIL;" in reject
    assert 'return reject(400, "embedded null");' in handle
    assert 'return reject(400, "expected one event or command field");' in handle
    assert 'return reject(400, "command must be a string");' in handle


def test_http_framing_preserves_admission_and_rejection_order(tmp_path):
    overlay = Path(__file__).resolve().parents[1] / "overlay"
    bridge = (overlay / "robot_bridge.cc").read_text()
    handle = bridge.split("esp_err_t Bridge::Handle(httpd_req_t* req)", 1)[1]
    assert handle.index("if (!Authorize(req))") < handle.index("InspectHttpFraming(req)")
    assert "if (framing.error) return reject(framing.status, framing.error);" in handle
    assert "const bool json_route = framing.json_route;" in handle
    start = bridge.index("struct HttpFraming {")
    end = bridge.index("\n}  // namespace", start)
    source = tmp_path / "http_framing.cc"
    source.write_text(r'''
#include <cassert>
#include <cstring>
#include "robot_protocol.h"
using namespace desk_robot;
constexpr int ESP_OK = 0, ESP_ERR_NOT_FOUND = 1, ESP_ERR_HTTPD_RESULT_TRUNC = 2;
constexpr int HTTP_GET = 0, HTTP_POST = 1;
constexpr std::size_t kMaxBody = 160;
struct httpd_req_t {
    std::size_t content_len = 0;
    int method = HTTP_GET;
    const char* uri = "/api/status";
    const char* length = nullptr;
    const char* encoding = nullptr;
};
const char* header(httpd_req_t* req, const char* name) {
    return strcmp(name, "Content-Length") == 0 ? req->length : req->encoding;
}
std::size_t httpd_req_get_hdr_value_len(httpd_req_t* req, const char* name) {
    const auto* value = header(req, name);
    return value ? strlen(value) : 0;
}
int httpd_req_get_hdr_value_str(httpd_req_t* req, const char* name,
                                char* out, std::size_t capacity) {
    const auto* value = header(req, name);
    if (!value) return ESP_ERR_NOT_FOUND;
    if (strlen(value) >= capacity) return ESP_ERR_HTTPD_RESULT_TRUNC;
    memcpy(out, value, strlen(value) + 1);
    return ESP_OK;
}
''' + bridge[start:end] + r'''
void check(httpd_req_t req, int status, const char* error, bool json = false) {
    const auto result = InspectHttpFraming(&req);
    assert(result.status == status && result.json_route == json);
    if (error) assert(result.error && strcmp(result.error, error) == 0);
    else assert(!result.error);
}
int main() {
    check({}, 200, nullptr);
    check({0, HTTP_POST, "/api/command"}, 200, nullptr, true);
    check({160, HTTP_POST, "/api/face", "0160"}, 200, nullptr, true);
    check({161, HTTP_POST, "/api/command", "161"}, 413, "invalid body length");
    check({1, HTTP_POST, "/api/command"}, 400, "missing content length");
    check({1, HTTP_GET, "/api/status", "1"}, 400, "request body not permitted");
    check({1, HTTP_POST, "/api/command?x", "1"}, 400, "request body not permitted");
    check({0, HTTP_GET, "/api/status", "0"}, 200, nullptr);
    for (const char* bad : {"", "2", "-1", "1,1", "4294967297",
                            "18446744073709551616", "000000000000000000000001"}) {
        check({1, HTTP_POST, "/api/command", bad}, 400, "invalid content length");
    }
    for (const char* encoding : {"", "chunked", "identity"}) {
        check({161, HTTP_POST, "/api/command", nullptr, encoding},
              400, "transfer encoding unsupported");
    }
}
''')
    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++17 compiler required"
    binary = tmp_path / "http_framing"
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Wconversion", "-Werror",
         "-fsanitize=address,undefined", *pie_flags, "-I", str(overlay),
         str(source), "-o", str(binary)],
        check=True, timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
