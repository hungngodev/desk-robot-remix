"""Prove /api/command does not block HTTPD admission of a concurrent STOP."""

import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def test_http_command_offloads_recv_and_admits_second_connection_stop(tmp_path):
    overlay = Path(__file__).resolve().parents[1] / "overlay"
    bridge = (overlay / "robot_bridge.cc").read_text()

    def extract(signature):
        start = bridge.index(signature)
        return bridge[start:bridge.index("\n}", start) + 2]

    json_alias = next(
        line for line in bridge.splitlines() if line.startswith("using JsonPtr =")
    )
    helpers = "\n".join([
        json_alias,
        *(
            extract(signature)
            for signature in (
                "JsonPtr Parse(",
                "std::string Encode(",
                "std::string Envelope(",
                "bool StatusValid(",
                "bool OpticsValid(",
                "bool PoseVersionUnsupported(",
                "bool PoseValid(",
                "bool IrValid(",
                "bool AuxValid(",
                "struct HttpFraming {",
            )
        ),
    ])
    # Append semicolon to struct HttpFraming definition and remaining helpers.
    helpers += ";\n" + "\n".join([
        *(
            extract(signature)
            for signature in (
                "HttpFraming InspectHttpFraming(",
                "bool BodyWireByteValid(",
                "bool BodyWireValid(",
                "void Bridge::CommandTask(",
                "Reply Bridge::Transact(",
                "Reply Bridge::ReadBodyReply(",
                "esp_err_t Bridge::Handle(",
                "esp_err_t Bridge::HandleCommandBody(",
            )
        ),
    ])

    source = tmp_path / "http_stop_admission.cc"
    source.write_text(
        r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <cJSON.h>
#include "robot_protocol.h"
#include "real_touch_edges.h"

using namespace desk_robot;
using esp_err_t = int;
constexpr esp_err_t ESP_OK = 0;
constexpr esp_err_t ESP_FAIL = -1;
constexpr int ESP_ERR_NOT_FOUND = 1;
[[maybe_unused]] constexpr int HTTP_GET = 0;
constexpr int HTTP_POST = 1;
constexpr int kUart = 1;
constexpr int kTimeoutMs = 350;
constexpr int pdPASS = 1;
constexpr std::size_t kMaxReply = 1920;
constexpr std::size_t kMaxBody = 160;
constexpr std::uint16_t OV2640_PID = 0x26;
constexpr std::uint16_t OV3660_PID = 0x3660;
constexpr std::uint16_t OV5640_PID = 0x5640;
constexpr const char* CONFIG_DESK_ROBOT_ID = "robot-01";
#define pdMS_TO_TICKS(x) (x)

struct sensor_t {
    struct {
        std::uint16_t PID = 0;
    } id;
};
inline const sensor_t* esp_camera_sensor_get() { return nullptr; }

template <typename Predicate>
void wait_until(Predicate ready) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (!ready()) {
        assert(std::chrono::steady_clock::now() < deadline);
        std::this_thread::yield();
    }
}

struct httpd_req_t {
    void* user_ctx = nullptr;
    int method = HTTP_POST;
    const char* uri = "/api/command";
    std::size_t content_len = 0;
    const char* content_type = "application/json";
    std::string payload;
    std::size_t payload_pos = 0;
    bool stall_recv = false;
    std::atomic<bool>* recv_entered = nullptr;
    std::atomic<bool>* release_recv = nullptr;
    std::atomic<bool> done{false};
    std::string response;
    std::string connection_hdr;
};

std::size_t httpd_req_get_hdr_value_len(httpd_req_t* req, const char* name) {
    if (strcmp(name, "Content-Type") == 0)
        return req->content_type ? strlen(req->content_type) : 0;
    if (strcmp(name, "Content-Length") == 0)
        return std::to_string(req->content_len).size();
    return 0;
}

esp_err_t httpd_req_get_hdr_value_str(httpd_req_t* req, const char* name,
                                      char* out, std::size_t cap) {
    if (strcmp(name, "Content-Type") == 0 && req->content_type) {
        const auto n = strlen(req->content_type);
        if (n >= cap) return -1;
        memcpy(out, req->content_type, n + 1);
        return ESP_OK;
    }
    if (strcmp(name, "Content-Length") == 0) {
        const auto s = std::to_string(req->content_len);
        if (s.size() >= cap) return -1;
        memcpy(out, s.c_str(), s.size() + 1);
        return ESP_OK;
    }
    return ESP_ERR_NOT_FOUND;
}

int httpd_req_recv(httpd_req_t* req, char* buf, std::size_t buf_len) {
    if (req->stall_recv && req->payload_pos == 0) {
        req->recv_entered->store(true, std::memory_order_release);
        wait_until([req] { return req->release_recv->load(std::memory_order_acquire); });
    }
    const std::size_t rem = req->payload.size() - req->payload_pos;
    const std::size_t take = std::min(rem, buf_len);
    if (take > 0) memcpy(buf, req->payload.data() + req->payload_pos, take);
    req->payload_pos += take;
    return static_cast<int>(take);
}

esp_err_t httpd_resp_set_hdr(httpd_req_t* req, const char* field, const char* value) {
    if (strcmp(field, "Connection") == 0) req->connection_hdr = value;
    return ESP_OK;
}

esp_err_t httpd_resp_send(httpd_req_t* req, const char* buf, std::size_t len) {
    req->response.assign(buf, len);
    req->done.store(true, std::memory_order_release);
    return ESP_OK;
}

esp_err_t httpd_req_async_handler_begin(httpd_req_t* req, httpd_req_t** out) {
    *out = req;
    return ESP_OK;
}

esp_err_t httpd_req_async_handler_complete(httpd_req_t*) { return ESP_OK; }

int xTaskCreate(void (*fn)(void*), const char*, unsigned, void* ctx, int, void*) {
    std::thread([fn, ctx] { fn(ctx); }).detach();
    return pdPASS;
}
void vTaskDelete(void*) {}

std::atomic<std::int64_t> fake_us{1000};
std::int64_t esp_timer_get_time() { return fake_us.fetch_add(10); }

std::mutex hw_mu;
std::string uart_rx;
std::size_t uart_rx_pos = 0;
bool stall_status_uart = false;
std::atomic<bool> status_uart_entered{false};
std::atomic<bool> release_status_uart{false};
std::atomic<bool> stop_reached_wroom{false};
std::uint32_t last_cmd_tx_id = 0;
std::string last_cmd_inner;

int uart_flush_input(int) { return ESP_OK; }
int uart_wait_tx_done(int, int) { return ESP_OK; }

int uart_write_bytes(int, const char* s, std::size_t n) {
    std::lock_guard<std::mutex> lock(hw_mu);
    std::string wire(s, n);
    if (wire.size() >= 2 && wire.substr(wire.size() - 2) == "\r\n") {
        std::uint32_t tx_id = 0;
        std::string_view inner;
        if (ParseIntegrityFrame(std::string_view(wire.data(), wire.size() - 2), tx_id, inner)) {
            last_cmd_tx_id = tx_id;
            last_cmd_inner.assign(inner);
            if (inner == "stop" || inner == "halt") {
                stop_reached_wroom.store(true, std::memory_order_release);
                uart_rx = FormatIntegrityFrame(tx_id, "OK " + std::string(inner)) + "\r\n";
                uart_rx_pos = 0;
            }
        }
    }
    return static_cast<int>(n);
}

int uart_read_bytes(int, std::uint8_t* c, int, int) {
    bool stall = false;
    {
        std::lock_guard<std::mutex> lock(hw_mu);
        stall = stall_status_uart && last_cmd_inner != "stop" && last_cmd_inner != "halt";
    }
    if (stall) {
        status_uart_entered.store(true, std::memory_order_release);
        wait_until([] { return release_status_uart.load(std::memory_order_acquire); });
        fake_us.fetch_add(10000);
        return 0;
    }
    std::lock_guard<std::mutex> lock(hw_mu);
    if (uart_rx_pos >= uart_rx.size()) {
        fake_us.fetch_add(10000);
        return 0;
    }
    *c = static_cast<std::uint8_t>(uart_rx[uart_rx_pos++]);
    return 1;
}

struct Reply { int status; bool ok; std::string text; };

struct StubCamera {
    std::uint16_t pid() const { return 0; }
};

struct Bridge {
    bool enabled_ = true;
    bool uart_ready_ = true;
    StubCamera* camera_ = nullptr;
    std::uint32_t boot_nonce_ = 1U;
    std::uint32_t next_tx_id_ = 1U;
    std::mutex uart_mutex_;
    UrgentStopGate urgent_stop_gate_{};
    std::atomic<bool> body_read_busy_{false};
    std::atomic<int> command_workers_{0};
    static constexpr int kMaxCommandWorkers = 4;
    std::atomic<bool> camera_busy_{false};
    bool Authorize(httpd_req_t*) { return true; }
    static void BodyReadTask(void*) {}
    static void CameraTask(void*) {}
    static void CameraStreamTask(void*) {}
    static void CommandTask(void* context);
    Reply Transact(const std::string& command, bool operator_control);
    static Reply ReadBodyReply(const Command& command, std::uint32_t expected_tx_id,
                               const UrgentStopGate::Request& urgency);
    esp_err_t Handle(httpd_req_t* req);
    esp_err_t HandleCommandBody(httpd_req_t* req);
    esp_err_t Json(httpd_req_t* req, int, const std::string& body) {
        return httpd_resp_send(req, body.data(), body.size());
    }
};
'''
        + helpers
        + r'''
int main() {
    Bridge bridge;

    // Case 1: slow POST body recv on /api/command does NOT block HTTPD admitting STOP.
    std::atomic<bool> recv1_entered{false};
    std::atomic<bool> release_recv1{false};
    httpd_req_t req1;
    req1.user_ctx = &bridge;
    req1.payload = R"({"command":"ping"})";
    req1.content_len = req1.payload.size();
    req1.stall_recv = true;
    req1.recv_entered = &recv1_entered;
    req1.release_recv = &release_recv1;

    assert(bridge.Handle(&req1) == ESP_OK);
    wait_until([&] { return recv1_entered.load(std::memory_order_acquire); });

    httpd_req_t stop_req;
    stop_req.user_ctx = &bridge;
    stop_req.payload = R"({"command":"stop"})";
    stop_req.content_len = stop_req.payload.size();
    assert(bridge.Handle(&stop_req) == ESP_OK);
    wait_until([&] { return stop_req.done.load(std::memory_order_acquire); });
    assert(stop_reached_wroom.load(std::memory_order_acquire));
    assert(stop_req.response.find(R"("ok":true)") != std::string::npos);
    assert(!req1.done.load(std::memory_order_acquire));
    release_recv1.store(true, std::memory_order_release);
    wait_until([&] { return req1.done.load(std::memory_order_acquire); });
    assert(req1.response.find("body ACK timeout") != std::string::npos);

    // Case 2: ordinary UART-stalled /api/command does NOT block HTTPD admitting STOP.
    stop_reached_wroom.store(false);
    stall_status_uart = true;
    httpd_req_t req_slow_uart;
    req_slow_uart.user_ctx = &bridge;
    req_slow_uart.payload = R"({"command":"drive 20 20 250"})";
    req_slow_uart.content_len = req_slow_uart.payload.size();
    assert(bridge.Handle(&req_slow_uart) == ESP_OK);
    wait_until([&] { return status_uart_entered.load(std::memory_order_acquire); });

    httpd_req_t stop_req2;
    stop_req2.user_ctx = &bridge;
    stop_req2.payload = R"({"command":"stop"})";
    stop_req2.content_len = stop_req2.payload.size();
    assert(bridge.Handle(&stop_req2) == ESP_OK);
    wait_until([&] { return bridge.urgent_stop_gate_.preempts(false); });
    assert(!req_slow_uart.done.load(std::memory_order_acquire));
    release_status_uart.store(true, std::memory_order_release);
    wait_until([&] { return stop_reached_wroom.load(std::memory_order_acquire); });
    wait_until([&] { return stop_req2.done.load(std::memory_order_acquire); });
    wait_until([&] { return req_slow_uart.done.load(std::memory_order_acquire); });
    assert(req_slow_uart.response.find("superseded by urgent stop") != std::string::npos);
    assert(stop_req2.response.find(R"("ok":true)") != std::string::npos);
    return 0;
}
''',
        encoding="utf-8",
    )

    compiler = shutil.which("c++")
    assert compiler is not None, "Native C++17 compiler required"
    flags = shlex.split(
        subprocess.check_output(["pkg-config", "--cflags", "--libs", "libcjson"], text=True)
    )
    binary = tmp_path / "http_stop_admission"
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all",
            *pie_flags,
            "-I",
            str(overlay),
            str(source),
            *flags,
            "-o",
            str(binary),
        ],
        check=True,
        timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
