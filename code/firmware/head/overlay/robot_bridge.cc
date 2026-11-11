#include "robot_bridge.h"

#include <algorithm>
#include <cstdio>
#include "esp_random.h"
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <string_view>
#include <vector>

#include "cJSON.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "mcp_server.h"
#include "sdkconfig.h"

namespace desk_robot {
namespace {
constexpr uart_port_t kUart = UART_NUM_1;
constexpr int kTimeoutMs = 350;
constexpr size_t kMaxReply = 1152;  // must exceed body kReplyCapacity
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

bool AuxValid(cJSON* json) {
    if (!cJSON_IsObject(json)) return false;
    auto group = [json](const char* key) {
        return cJSON_GetObjectItemCaseSensitive(json, key);
    };
    auto get = [](cJSON* parent, const char* key) {
        return cJSON_GetObjectItemCaseSensitive(parent, key);
    };
    auto bounded = [](cJSON* n, double low, double high) {
        return cJSON_IsNumber(n) && std::isfinite(n->valuedouble) &&
               n->valuedouble == std::floor(n->valuedouble) &&
               n->valuedouble >= low && n->valuedouble <= high;
    };
    auto bounded_array = [get, bounded](cJSON* parent, const char* key,
                                       int expected, double low, double high) {
        auto array = get(parent, key);
        if (!cJSON_IsArray(array) || cJSON_GetArraySize(array) != expected) return false;
        for (int i = 0; i < expected; ++i)
            if (!bounded(cJSON_GetArrayItem(array, i), low, high)) return false;
        return true;
    };
    auto pulse = group("pulse");
    auto angles = group("angles");
    auto force = group("force");
    auto climate = group("climate");
    auto power = group("power");
    auto proximity = group("proximity");
    if (!cJSON_IsObject(pulse) || !cJSON_IsObject(angles) ||
        !cJSON_IsObject(force) || !cJSON_IsObject(climate) ||
        !cJSON_IsObject(power) || !cJSON_IsObject(proximity)) return false;
    if (!cJSON_IsBool(get(pulse, "present")) || !cJSON_IsBool(get(pulse, "valid")) ||
        !cJSON_IsNull(get(pulse, "bpm")) || !cJSON_IsFalse(get(pulse, "medical")) ||
        !bounded(get(pulse, "part_id"), 0, 255) ||
        !bounded(get(pulse, "red"), 0, 262143) ||
        !bounded(get(pulse, "ir"), 0, 262143) ||
        !bounded(get(pulse, "age_ms"), 0, 4294967295.0) ||
        (cJSON_IsTrue(get(pulse, "valid")) && !cJSON_IsTrue(get(pulse, "present"))))
        return false;
    auto present = get(angles, "present_mask");
    auto valid = get(angles, "valid_mask");
    if (!bounded(present, 0, 7) || !bounded(valid, 0, 7) ||
        ((valid->valueint & ~present->valueint) != 0) ||
        !bounded_array(angles, "raw", 3, 0, 4095) ||
        !bounded_array(angles, "magnet", 3, 0, 56)) return false;
    for (int i = 0; i < 3; ++i)
        if ((valid->valueint & (1 << i)) &&
            cJSON_GetArrayItem(get(angles, "magnet"), i)->valueint != 32)
            return false;
    if (!bounded_array(force, "adc", 2, -32768, 32767) ||
        !bounded(get(force, "jaw_seq"), 0, 4294967295.0) ||
        !cJSON_IsBool(get(force, "valid")) ||
        !cJSON_IsFalse(get(force, "calibrated"))) return false;
    if (!bounded(get(climate, "temp_centi"), -4500, 13000) ||
        !bounded(get(climate, "rh_centi"), 0, 10000) ||
        !cJSON_IsBool(get(climate, "valid"))) return false;
    if (!bounded(get(power, "cell_mv"), 0, 4500) ||
        !bounded(get(power, "soc_centi"), 0, 10000) ||
        !bounded(get(power, "bus_mv"), 0, 40959) ||
        !bounded(get(power, "shunt_uv"), -81920, 81920) ||
        !cJSON_IsBool(get(power, "fuel_valid")) ||
        !cJSON_IsBool(get(power, "monitor_valid")) ||
        !cJSON_IsFalse(get(power, "current_calibrated"))) return false;
    if (!bounded(get(proximity, "raw"), 0, 255) ||
        !cJSON_IsBool(get(proximity, "valid")) ||
        !bounded(get(proximity, "gesture"), 0, 4) ||
        !bounded(get(proximity, "gesture_events"), 0, 4294967295.0) ||
        !cJSON_IsFalse(get(proximity, "physically_qualified"))) return false;
    return true;
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
    boot_nonce_ = esp_random();
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
             {"/api/status", HTTP_GET}, {"/api/aux", HTTP_GET},
             {"/api/command", HTTP_POST}, {"/api/camera.jpg", HTTP_GET}}) {
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
            if (command.verb == "status" || command.verb == "aux") {
                auto json = Parse(line);
                if (json && (command.verb == "status" ?
                             StatusValid(json.get()) : AuxValid(json.get())))
                    return {200, true, line};
            } else if (line == ExpectedAck(command)) return {200, true, line};
            line.clear();  // EVT, startup output, and unrelated ACKs are never success.
        } else {
            if (c < 32 || c > 126 || line.size() >= kMaxReply) return {503, false, "malformed body response"};
            line.push_back(static_cast<char>(c));
        }
    }
    return {504, false, "body ACK timeout; command outcome uncertain"};
}

BodyInteraction Bridge::PollInteraction() {
    BodyInteraction observation;
    const Reply reply = Transact("status", false);
    if (!reply.ok) {
        head_touch_edges_.Reset();
        body_cap_edges_.Reset();
        return observation;
    }
    auto json = Parse(reply.text);
    if (!json) {
        head_touch_edges_.Reset();
        body_cap_edges_.Reset();
        return observation;
    }
    auto touch = cJSON_GetObjectItemCaseSensitive(json.get(), "touch");
    auto count = cJSON_GetObjectItemCaseSensitive(touch, "count");
    auto safety = cJSON_GetObjectItemCaseSensitive(json.get(), "safety");
    auto fault = cJSON_GetObjectItemCaseSensitive(safety, "fault");
    if (!cJSON_IsObject(touch) || !cJSON_IsNumber(count) ||
        !std::isfinite(count->valuedouble) ||
        count->valuedouble < 0 || count->valuedouble > 4294967295.0 ||
        std::floor(count->valuedouble) != count->valuedouble ||
        !cJSON_IsObject(safety) || !cJSON_IsString(fault)) {
        head_touch_edges_.Reset();
        body_cap_edges_.Reset();
        return observation;
    }
    const auto current = static_cast<std::uint32_t>(count->valuedouble);
    observation.touch_events = head_touch_edges_.Observe(current);

    // CAP1188 is optional and never replaces the dedicated WROOM touch stop.
    // Explicit device-valid flag, range-checked zone mask and bounded counter
    // avoid producing synthetic petting when wiring is unplugged or rebooted.
    auto extras = cJSON_GetObjectItemCaseSensitive(json.get(), "extras");
    auto cap_ok = cJSON_GetObjectItemCaseSensitive(extras, "cap_ok");
    auto cap_mask = cJSON_GetObjectItemCaseSensitive(extras, "cap");
    auto cap_events = cJSON_GetObjectItemCaseSensitive(extras, "cap_events");
    if (cJSON_IsObject(extras) && cJSON_IsTrue(cap_ok) &&
        cJSON_IsNumber(cap_mask) &&
        std::isfinite(cap_mask->valuedouble) &&
        std::floor(cap_mask->valuedouble) == cap_mask->valuedouble &&
        cap_mask->valuedouble >= 0 && cap_mask->valuedouble <= 255 &&
        cJSON_IsNumber(cap_events) &&
        std::isfinite(cap_events->valuedouble) &&
        std::floor(cap_events->valuedouble) == cap_events->valuedouble &&
        cap_events->valuedouble >= 0 && cap_events->valuedouble <= 4294967295.0) {
        observation.cap_touch_events = body_cap_edges_.Observe(
            static_cast<std::uint32_t>(cap_events->valuedouble));
    } else {
        body_cap_edges_.Reset();
    }
    observation.fault = std::strcmp(fault->valuestring, "none") != 0 &&
                        std::strcmp(fault->valuestring, "not_required") != 0;
    observation.valid = true;
    return observation;
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
            // Completion, not guessed exposure time. The Mac can reject old
            // frames from the same boot without synchronizing ESP32/Mac clocks.
            const std::string nonce = std::to_string(bridge->boot_nonce_);
            const std::string sequence = std::to_string(++bridge->camera_sequence_);
            const std::string completed_us = std::to_string(esp_timer_get_time());
            httpd_resp_set_type(req, "image/jpeg");
            httpd_resp_set_hdr(req, "Cache-Control", "no-store");
            httpd_resp_set_hdr(req, "X-Desk-Camera-Boot", nonce.c_str());
            httpd_resp_set_hdr(req, "X-Desk-Camera-Sequence", sequence.c_str());
            httpd_resp_set_hdr(req, "X-Desk-Camera-Complete-Us", completed_us.c_str());
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
    if (strcmp(req->uri, "/api/status") == 0 ||
        strcmp(req->uri, "/api/aux") == 0) {
        const bool aux = strcmp(req->uri, "/api/aux") == 0;
        auto reply = Transact(aux ? "aux" : "status", false);
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
