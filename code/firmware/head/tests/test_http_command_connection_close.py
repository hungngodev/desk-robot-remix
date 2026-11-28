"""Verify CommandTask/HandleCommandBody sets Connection: close BEFORE sending reject responses."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path


def _native_cpp_env() -> dict[str, str]:
    spec = importlib.util.spec_from_file_location(
        "test_overlay_env_close", Path(__file__).with_name("test_overlay.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.native_cpp_env()


def _cjson_flags() -> list[str]:
    pkg_config = shutil.which("pkg-config")
    if pkg_config is None:
        return ["-lcjson"]
    probe = subprocess.run(
        [pkg_config, "--cflags", "--libs", "libcjson"],
        capture_output=True, text=True, check=False, timeout=5,
    )
    if probe.returncode == 0 and probe.stdout.strip():
        return probe.stdout.strip().split()
    return ["-lcjson"]


def _slice(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def test_async_command_rejection_sets_connection_close_before_httpd_send(tmp_path):
    overlay = Path(__file__).resolve().parents[1] / "overlay"
    bridge = (overlay / "robot_bridge.cc").read_text()

    parse_and_envelope = (
        _slice(bridge, "JsonPtr Parse(", "std::string EncodeBodyRead(")
        + _slice(bridge, "std::string Envelope(", "bool ValidConfiguration()")
    )
    json_fn = _slice(bridge, "esp_err_t Bridge::Json(", "esp_err_t Bridge::Dispatch(")
    command_task_fn = _slice(bridge, "void Bridge::CommandTask(", "void Bridge::CameraTask(")
    handle_command_body_fn = _slice(
        bridge, "esp_err_t Bridge::HandleCommandBody(", "void Bridge::AddTools()"
    )

    # Confirm the static ordering inside HandleCommandBody::reject before compiling.
    assert handle_command_body_fn.index('httpd_resp_set_hdr(req, "Connection", "close");') < (
        handle_command_body_fn.index("Json(req, status, Envelope(false, message));")
    )

    source = tmp_path / "async_command_close.cc"
    source.write_text(
        r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string>
#include <string_view>
#include <utility>
#include <vector>
#include "cJSON.h"
#include "robot_protocol.h"

#define CONFIG_DESK_ROBOT_ID "pet1"
#define CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3 1

using esp_err_t = int;
constexpr esp_err_t ESP_OK = 0;
constexpr esp_err_t ESP_FAIL = -1;

struct httpd_req_t {
    void* user_ctx = nullptr;
    const char* uri = "/api/command";
    std::size_t content_len = 0;
    std::string raw_body;
    std::size_t read_offset = 0;
    std::vector<std::pair<std::string, std::string>> staged_headers;
    std::string sent_status;
    std::string sent_type;
    std::vector<std::pair<std::string, std::string>> sent_headers;
    std::string sent_body;
    bool response_sent = false;
    bool async_completed = false;
    bool connection_closed_after_send = false;
    bool session_reusable = true;
};

esp_err_t httpd_resp_set_status(httpd_req_t* req, const char* status) {
    assert(!req->response_sent);
    req->sent_status = status;
    return ESP_OK;
}
esp_err_t httpd_resp_set_type(httpd_req_t* req, const char* type) {
    assert(!req->response_sent);
    req->sent_type = type;
    return ESP_OK;
}
esp_err_t httpd_resp_set_hdr(httpd_req_t* req, const char* field, const char* value) {
    if (req->response_sent) {
        // Real ESP-IDF HTTPD ignores header writes after httpd_resp_send commits.
        return ESP_OK;
    }
    req->staged_headers.emplace_back(field, value);
    return ESP_OK;
}
esp_err_t httpd_resp_send(httpd_req_t* req, const char* buf, ssize_t buf_len) {
    assert(!req->response_sent);
    req->response_sent = true;
    req->sent_headers = req->staged_headers;
    req->sent_body.assign(buf, static_cast<std::size_t>(buf_len));
    return ESP_OK;
}
int httpd_req_recv(httpd_req_t* req, char* buf, std::size_t buf_len) {
    const std::size_t remaining = req->raw_body.size() - req->read_offset;
    const std::size_t chunk = std::min(buf_len, remaining);
    if (chunk > 0) {
        std::memcpy(buf, req->raw_body.data() + req->read_offset, chunk);
        req->read_offset += chunk;
    }
    return static_cast<int>(chunk);
}
esp_err_t httpd_req_async_handler_complete(httpd_req_t* req) {
    req->async_completed = true;
    for (const auto& [k, v] : req->sent_headers) {
        if (k == "Connection" && v == "close") {
            req->connection_closed_after_send = true;
            req->session_reusable = false;
        }
    }
    return ESP_OK;
}
void vTaskDelete(void*) {}
std::int64_t esp_timer_get_time() { return 1000; }

namespace desk_robot {
struct Reply {
    int status;
    bool ok;
    std::string text;
};

class Bridge {
public:
    std::atomic<int> command_workers_{0};
    TimedPersonCue person_cue_{};
    CosmeticMoodCue cosmetic_mood_{};
    bool face_consumer = true;
    bool uart_allows = true;
    bool FaceConsumerAvailable() const { return face_consumer; }
    static void CommandTask(void* context);
    esp_err_t HandleCommandBody(httpd_req_t* req);
    esp_err_t Json(httpd_req_t* req, int status, const std::string& body);
    Reply Transact(const std::string& command, bool operator_control) {
        if (!uart_allows) return {503, false, "uart unavailable"};
        return {200, true, "OK " + command + (operator_control ? "" : "")};
    }
};

namespace {
using JsonPtr = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
'''
        + parse_and_envelope
        + "\n}  // namespace\n"
        + json_fn
        + command_task_fn
        + handle_command_body_fn
        + r'''
}  // namespace desk_robot

using desk_robot::Bridge;

namespace {
httpd_req_t run_async(Bridge& bridge, const char* uri, std::string body, std::size_t declared_len) {
    bridge.command_workers_.store(1);
    httpd_req_t req;
    req.user_ctx = &bridge;
    req.uri = uri;
    req.content_len = declared_len;
    req.raw_body = std::move(body);
    Bridge::CommandTask(&req);
    assert(bridge.command_workers_.load() == 0);
    assert(req.response_sent && req.async_completed);
    return req;
}
}  // namespace

int main() {
    Bridge bridge;
    // Malformed /api/command payloads executed through CommandTask must commit
    // Connection: close in sent_headers so the keep-alive session is closed.
    for (const auto& bad : {
             std::pair<std::string, std::size_t>{"{not json", 9},
             std::pair<std::string, std::size_t>{R"({"command":123})", 15},
             std::pair<std::string, std::size_t>{R"({"event":"pat"})", 15},
             std::pair<std::string, std::size_t>{std::string("{\"command\":\"stop\0\"}", 19), 19},
             std::pair<std::string, std::size_t>{R"({"command":"stop"})", 40},
         }) {
        auto req = run_async(bridge, "/api/command", bad.first, bad.second);
        assert(req.sent_status.rfind("400", 0) == 0);
        assert(req.connection_closed_after_send);
        assert(!req.session_reusable);
    }

    // Empty / missing-field JSON and overlong bodies close the async session too.
    for (const std::pair<std::string, std::size_t>& bad : {
             std::pair<std::string, std::size_t>{"{}", 2},
             std::pair<std::string, std::size_t>{"", 0},
             std::pair<std::string, std::size_t>{std::string(161, 'x'), 161},
         }) {
        auto req = run_async(bridge, "/api/command", bad.first, bad.second);
        assert(req.sent_status == "400 Bad Request" ||
               req.sent_status == "413 Content Too Large");
        assert(req.sent_body.find("\"ok\":false") != std::string::npos);
        assert(req.connection_closed_after_send);
        assert(!req.session_reusable);
    }

    // Valid command through the async task completes 200 without closing keep-alive.
    {
        auto req = run_async(bridge, "/api/command", R"({"command":"status"})", 20);
        assert(req.sent_status == "200 OK");
        assert(!req.connection_closed_after_send);
        assert(req.session_reusable);
    }

    // Valid /api/face cue returns 200 without closing keep-alive; malformed closes.
    {
        auto ok_face = run_async(bridge, "/api/face", R"({"event":"mood:happy"})", 22);
        assert(ok_face.sent_status == "200 OK");
        assert(ok_face.sent_body.find("mood cue queued") != std::string::npos);
        assert(!ok_face.connection_closed_after_send);
        assert(ok_face.session_reusable);

        bridge.face_consumer = false;
        auto unavailable_face = run_async(bridge, "/api/face", R"({"event":"mood:happy"})", 22);
        assert(unavailable_face.sent_status == "503 Service Unavailable");
        assert(!unavailable_face.connection_closed_after_send);
        assert(unavailable_face.session_reusable);
        bridge.face_consumer = true;

        auto bad_face_json = run_async(bridge, "/api/face", "{bad", 4);
        assert(bad_face_json.sent_status.rfind("400", 0) == 0);
        assert(bad_face_json.connection_closed_after_send);
        assert(!bad_face_json.session_reusable);

        auto unsupported_face = run_async(bridge, "/api/face", R"({"event":42})", 12);
        assert(unsupported_face.sent_status.rfind("400", 0) == 0);
        assert(unsupported_face.sent_body.find("unsupported face event") != std::string::npos);
        assert(!unsupported_face.connection_closed_after_send);
        assert(unsupported_face.session_reusable);
    }
    return 0;
}
'''
    )

    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++17 compiler required"
    binary = tmp_path / "async_command_close"
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", *pie_flags,
            "-I", str(overlay), str(source), *_cjson_flags(), "-o", str(binary),
        ],
        check=True, env=_native_cpp_env(), timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
