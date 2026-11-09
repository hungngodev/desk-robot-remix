#include "robot_bridge.h"

#include <algorithm>
#include <cstring>
#include <memory>
#include <string_view>
#include <vector>

#include "cJSON.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "mcp_server.h"
#include "application.h"
#include "board.h"
#include "sdkconfig.h"

namespace desk_robot {
namespace {
constexpr uart_port_t kUart = UART_NUM_1;
constexpr int kTimeoutMs = 350;
constexpr size_t kMaxReply = 768;
constexpr size_t kMaxBody = 160;
const char* kTag = "DeskRobotHead";
using JsonPtr = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
JsonPtr Parse(const std::string& value) {
    return JsonPtr(cJSON_ParseWithLengthOpts(value.c_str(), value.size() + 1, nullptr, true), cJSON_Delete);
}
std::string Encode(cJSON* value) {
    char* text = cJSON_PrintUnformatted(value);
    if (!text) return "{}";
    std::string result(text);
    cJSON_free(text);
    return result;
}
bool StatusValid(cJSON* json) {
    if (!cJSON_IsObject(json) || !cJSON_IsBool(cJSON_GetObjectItemCaseSensitive(json, "armed"))) return false;
    auto motor = cJSON_GetObjectItemCaseSensitive(json, "motor");
    auto servo = cJSON_GetObjectItemCaseSensitive(json, "servo");
    if (!cJSON_IsObject(motor) || !cJSON_IsObject(servo)) return false;
    for (const char* name : {"m0", "m1"}) {
        auto n = cJSON_GetObjectItemCaseSensitive(motor, name);
        if (!cJSON_IsNumber(n) || n->valuedouble != n->valueint || n->valueint < -40 || n->valueint > 40) return false;
    }
    for (const char* name : {"lift", "grip"}) {
        auto n = cJSON_GetObjectItemCaseSensitive(servo, name);
        if (!cJSON_IsNumber(n) || n->valuedouble != n->valueint || n->valueint < 0 || n->valueint > 180) return false;
    }
    auto watchdog = cJSON_GetObjectItemCaseSensitive(json, "watchdog_ms");
    return cJSON_IsNumber(watchdog) && watchdog->valuedouble == watchdog->valueint &&
           watchdog->valueint >= 0 && watchdog->valueint <= 500;
}
std::string Envelope(bool ok, const std::string& reply) {
    auto json = JsonPtr(cJSON_CreateObject(), cJSON_Delete);
    cJSON_AddBoolToObject(json.get(), "ok", ok);
    cJSON_AddStringToObject(json.get(), "reply", reply.c_str());
    cJSON_AddStringToObject(json.get(), "robot_id", CONFIG_DESK_ROBOT_ID);
    return Encode(json.get());
}
bool ValidConfiguration() {
    std::string_view token(CONFIG_DESK_ROBOT_TOKEN);
    std::string_view id(CONFIG_DESK_ROBOT_ID);
    if (token.size() < 32 || token.size() > 128 || id.empty() || id.size() > 48) return false;
    for (unsigned char c : token) if (c <= 32 || c > 126) return false;
    for (unsigned char c : id) if (!(c >= 'a' && c <= 'z') && !(c >= 'A' && c <= 'Z') &&
        !(c >= '0' && c <= '9') && c != '-' && c != '_') return false;
    return token.find("change") == std::string_view::npos && token.find("example") == std::string_view::npos &&
           token.find("default") == std::string_view::npos;
}
}  // namespace

Bridge::Bridge(Camera* camera) : camera_(camera) {}

void Bridge::Start() {
    enabled_ = ValidConfiguration();
    if (!enabled_) {
        ESP_LOGW(kTag, "Robot API and movement tools disabled: configure unique ID and private token (32..128 characters)");
        return;
    }
    uart_config_t cfg = {};
    cfg.baud_rate = 115200;
    cfg.data_bits = UART_DATA_8_BITS;
    cfg.parity = UART_PARITY_DISABLE;
    cfg.stop_bits = UART_STOP_BITS_1;
    cfg.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
    cfg.source_clk = UART_SCLK_DEFAULT;
    uart_ready_ = uart_param_config(kUart, &cfg) == ESP_OK &&
        uart_set_pin(kUart, 2, 1, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE) == ESP_OK &&
        uart_driver_install(kUart, 2048, 0, 0, nullptr, 0) == ESP_OK;
    if (!uart_ready_) ESP_LOGE(kTag, "Body UART initialization failed");
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 8081;
    config.ctrl_port = 32771;
    config.stack_size = 12288;
    config.max_uri_handlers = 4;
    config.recv_wait_timeout = 2;
    config.send_wait_timeout = 2;
    if (httpd_start(&server_, &config) != ESP_OK) {
        ESP_LOGE(kTag, "HTTP API failed to start");
        return;
    }
    for (const auto& entry : std::vector<std::pair<const char*, httpd_method_t>>{
             {"/api/status", HTTP_GET}, {"/api/command", HTTP_POST}, {"/api/camera.jpg", HTTP_GET},
             {"/api/emotion", HTTP_POST}}) {
        httpd_uri_t uri = {};
        uri.uri = entry.first;
        uri.method = entry.second;
        uri.handler = Dispatch;
        uri.user_ctx = this;
        if (httpd_register_uri_handler(server_, &uri) != ESP_OK) {
            httpd_stop(server_);
            server_ = nullptr;
            ESP_LOGE(kTag, "HTTP route registration failed");
            return;
        }
    }
    AddTools();
}

Reply Bridge::Transact(const std::string& text, bool operator_control) {
    Command command;
    if (!enabled_) return {503, false, "control disabled"};
    if (!ParseCommand(text, operator_control, command)) return {400, false, "invalid or unauthorized command"};
    std::lock_guard<std::mutex> lock(uart_mutex_);
    if (!uart_ready_) return {503, false, "body UART unavailable"};
    // No retries: an uncertain ACK may still mean that physical movement happened.
    uart_flush_input(kUart);
    const std::string wire = command.wire + "\r\n";
    if (uart_write_bytes(kUart, wire.data(), wire.size()) != static_cast<int>(wire.size()) ||
        uart_wait_tx_done(kUart, pdMS_TO_TICKS(30)) != ESP_OK) return {503, false, "body UART write failed"};
    const auto deadline = esp_timer_get_time() + kTimeoutMs * 1000;
    std::string line;
    while (esp_timer_get_time() < deadline) {
        uint8_t c = 0;
        if (uart_read_bytes(kUart, &c, 1, pdMS_TO_TICKS(10)) != 1) continue;
        if (c == '\r') continue;
        if (c == '\n') {
            if (MatchingError(line, command)) return {400, false, line};
            if (command.verb == "status") {
                auto json = Parse(line);
                if (json && StatusValid(json.get())) return {200, true, line};
            } else if (line == ExpectedAck(command)) return {200, true, line};
            line.clear();  // EVT, startup output, and unrelated ACKs are never success.
        } else {
            if (c < 32 || c > 126 || line.size() >= kMaxReply) return {503, false, "malformed body response"};
            line.push_back(static_cast<char>(c));
        }
    }
    return {504, false, "body ACK timeout; command outcome uncertain"};
}

bool Bridge::Authorize(httpd_req_t* req) {
    const size_t length = httpd_req_get_hdr_value_len(req, "Authorization");
    if (!enabled_ || length == 0 || length > 160) return false;
    std::vector<char> header(length + 1);
    if (httpd_req_get_hdr_value_str(req, "Authorization", header.data(), header.size()) != ESP_OK) return false;
    const std::string expected = std::string("Bearer ") + CONFIG_DESK_ROBOT_TOKEN;
    unsigned diff = static_cast<unsigned>(length ^ expected.size());
    for (size_t i = 0; i < expected.size(); ++i) diff |= static_cast<unsigned char>(expected[i]) ^
        (i < length ? static_cast<unsigned char>(header[i]) : 0);
    return diff == 0;
}

esp_err_t Bridge::Json(httpd_req_t* req, int status, const std::string& body) {
    const char* status_text = "500 Internal Server Error";
    switch (status) {
        case 200: status_text = "200 OK"; break;
        case 400: status_text = "400 Bad Request"; break;
        case 401: status_text = "401 Unauthorized"; break;
        case 413: status_text = "413 Content Too Large"; break;
        case 415: status_text = "415 Unsupported Media Type"; break;
        case 503: status_text = "503 Service Unavailable"; break;
        case 504: status_text = "504 Gateway Timeout"; break;
    }
    httpd_resp_set_status(req, status_text);
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, body.data(), body.size());
}

esp_err_t Bridge::Dispatch(httpd_req_t* req) { return static_cast<Bridge*>(req->user_ctx)->Handle(req); }

void Bridge::CameraTask(void* context) {
    auto* req = static_cast<httpd_req_t*>(context);
    auto* bridge = static_cast<Bridge*>(req->user_ctx);
    {
        auto jpeg = bridge->camera_->SnapshotJpeg();
        if (!jpeg) {
            bridge->Json(req, 503, Envelope(false, jpeg.error()));
        } else {
            httpd_resp_set_type(req, "image/jpeg");
            httpd_resp_set_hdr(req, "Cache-Control", "no-store");
            httpd_resp_send(req, reinterpret_cast<const char*>(jpeg->data()), jpeg->size());
        }
    }  // Destroy JPEG storage before vTaskDelete (which does not unwind C++ locals).
    bridge->camera_busy_.store(false);
    httpd_req_async_handler_complete(req);
    vTaskDelete(nullptr);
}

esp_err_t Bridge::Handle(httpd_req_t* req) {
    if (!Authorize(req)) return Json(req, 401, Envelope(false, "unauthorized"));
    if (strcmp(req->uri, "/api/camera.jpg") == 0) {
        if (!camera_) return Json(req, 503, Envelope(false, "camera unavailable"));
        if (camera_busy_.exchange(true)) return Json(req, 503, Envelope(false, "camera busy"));
        // Camera locking/encoding must never block HTTP keepalive or emergency stop.
        httpd_req_t* async_req = nullptr;
        if (httpd_req_async_handler_begin(req, &async_req) != ESP_OK) {
            camera_busy_.store(false);
            return Json(req, 503, Envelope(false, "camera worker unavailable"));
        }
        if (xTaskCreate(CameraTask, "robot_camera", 8192, async_req, 3, nullptr) != pdPASS) {
            Json(async_req, 503, Envelope(false, "camera task unavailable"));
            httpd_req_async_handler_complete(async_req);
            camera_busy_.store(false);
        }
        return ESP_OK;
    }
    if (strcmp(req->uri, "/api/status") == 0) {
        auto reply = Transact("status", false);
        if (!reply.ok) return Json(req, reply.status, Envelope(false, reply.text));
        auto json = Parse(reply.text);
        cJSON_AddStringToObject(json.get(), "robot_id", CONFIG_DESK_ROBOT_ID);
        return Json(req, 200, Encode(json.get()));
    }
    if (req->content_len == 0 || req->content_len > kMaxBody) {
        httpd_resp_set_hdr(req, "Connection", "close");
        Json(req, req->content_len > kMaxBody ? 413 : 400, Envelope(false, "invalid body length"));
        return ESP_FAIL;
    }
    char content_type[40] = {};
    if (httpd_req_get_hdr_value_str(req, "Content-Type", content_type, sizeof(content_type)) != ESP_OK ||
        (strcmp(content_type, "application/json") != 0 && strcmp(content_type, "application/json; charset=utf-8") != 0))
        return Json(req, 415, Envelope(false, "application/json required"));
    std::string body(req->content_len, '\0');
    size_t got = 0;
    while (got < body.size()) {
        int n = httpd_req_recv(req, body.data() + got, body.size() - got);
        if (n <= 0) return Json(req, 400, Envelope(false, "incomplete request body"));
        got += n;
    }
    if (body.find('\0') != std::string::npos || body.find("\\u0000") != std::string::npos) return Json(req, 400, Envelope(false, "embedded null"));
    auto json = Parse(body);
    if (!json || !cJSON_IsObject(json.get()) || cJSON_GetArraySize(json.get()) != 1)
        return Json(req, 400, Envelope(false, "expected one command field"));
    if (strcmp(req->uri, "/api/emotion") == 0) {
        auto item = cJSON_GetObjectItemCaseSensitive(json.get(), "emotion");
        if (!cJSON_IsString(item) || !item->valuestring)
            return Json(req, 400, Envelope(false, "one valid emotion required"));
        // Fixed glyph names only. A model cannot send a script or motor command.
        static constexpr const char* kAllowed[] = {
            "neutral", "happy", "thinking", "surprised", "sad", "sleepy"
        };
        bool allowed = false;
        for (const char* value : kAllowed) {
            if (strcmp(item->valuestring, value) == 0) {
                allowed = true;
                break;
            }
        }
        if (!allowed) return Json(req, 400, Envelope(false, "unsupported emotion"));
        std::string emotion(item->valuestring);
        Application::GetInstance().Schedule([emotion = std::move(emotion)]() {
            auto* display = Board::GetInstance().GetDisplay();
            if (display) display->SetEmotion(emotion.c_str());
        });
        return Json(req, 200, Envelope(true, "emotion queued on main task"));
    }
    auto item = cJSON_GetObjectItemCaseSensitive(json.get(), "command");
    if (!cJSON_IsString(item) || !item->valuestring)
        return Json(req, 400, Envelope(false, "command must be a string"));
    auto reply = Transact(item->valuestring, true);
    return Json(req, reply.status, Envelope(reply.ok, reply.text));
}

void Bridge::AddTools() {
    auto& mcp = McpServer::GetInstance();
    const auto call = [this](const std::string& command) -> ToolResult {
        auto reply = Transact(command, false);
        if (!reply.ok) return std::unexpected(reply.text);
        return reply.text;
    };
#ifdef CONFIG_DESK_ROBOT_DIRECT_MOTION_TOOLS
    mcp.AddTool("self.robot.drive", "One wheel pulse, maximum 250 ms; requires operator arm, never auto-arms.",
        PropertyList({Property("left", kPropertyTypeInteger, -100, 100), Property("right", kPropertyTypeInteger, -100, 100),
                      Property("duration_ms", kPropertyTypeInteger, 150, 1, 250)}),
        [call](const PropertyList& p) -> ToolResult { return call("drive " + std::to_string(p["left"].value<int>()) + " " +
            std::to_string(p["right"].value<int>()) + " " + std::to_string(p["duration_ms"].value<int>())); });
    for (const std::string verb : {"lift", "grip"}) {
        mcp.AddTool("self.robot." + verb, "Bounded servo command (60..120 degrees), no measured position or grasp feedback.",
            PropertyList({Property("angle", kPropertyTypeInteger, 60, 120)}),
            [call, verb](const PropertyList& p) -> ToolResult { return call(verb + " " + std::to_string(p["angle"].value<int>())); });
    }
#endif
    for (const std::string verb : {"stop", "status"}) {
#ifndef CONFIG_DESK_ROBOT_DIRECT_MOTION_TOOLS
        // Normal voice stop must cancel the laptop job, so it cannot resume on
        // the next step. The server's desk_robot_stop tool owns that operation.
        if (verb == "stop") continue;
#endif
        mcp.AddTool("self.robot." + verb, verb == "stop" ? "Stop wheels and servo ramp immediately." : "Read body status; does not renew the arm lease.",
            PropertyList(), [call, verb](const PropertyList&) -> ToolResult { return call(verb); });
    }
}
}  // namespace desk_robot
