#include "robot_bridge.h"

#include <algorithm>
#include <cstdio>
#include "esp_random.h"
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <string_view>
#include <vector>

#include "cJSON.h"
#include "esp_camera.h"  // Existing esp32-camera sensor identity, no new capture owner.
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "mcp_server.h"
#include "sdkconfig.h"
#if defined(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3)
#include "sense_reference_codec.h"
#endif

namespace desk_robot {
namespace {
constexpr uart_port_t kUart = UART_NUM_1;
constexpr int kTimeoutMs = 350;
constexpr size_t kMaxReply = 1920;  // WROOM 1800-byte JSON and worst-case 1726-byte status fit inside the 2048-byte UART RX ring
constexpr size_t kMaxBody = 160;
const char* kTag = "DeskRobotHead";
using JsonPtr = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
#if defined(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3) && defined(CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED)
struct BenchPcmTransfer {
    httpd_req_t* req;
    desk_robot::SensePcmWindow::Complete pcm;
    uint32_t boot;
    SenseReferenceCodec* codec;
    uint64_t generation;
};
#endif
JsonPtr Parse(const std::string& value) {
    if (!JsonWireBounded(value)) return JsonPtr(nullptr, cJSON_Delete);
    JsonPtr json(cJSON_ParseWithLengthOpts(value.c_str(), value.size() + 1, nullptr, true),
                 cJSON_Delete);
    if (!JsonKeysUnique(json.get(), cJSON_IsObject)) return JsonPtr(nullptr, cJSON_Delete);
    return json;
}
std::string Encode(cJSON* value) {
    char* text = cJSON_PrintUnformatted(value);
    if (!text) return "{}";
    std::string result(text);
    cJSON_free(text);
    return result;
}
std::string EncodeBodyRead(cJSON* body, bool pose, uint32_t head_boot) {
    // The body cannot supply the head's authenticated transport identity.
    // Appending duplicate names would let different consumers disagree.
    if (cJSON_GetObjectItemCaseSensitive(body, "robot_id") ||
        cJSON_GetObjectItemCaseSensitive(body, "head_boot")) return {};
    if (!cJSON_AddStringToObject(body, "robot_id", CONFIG_DESK_ROBOT_ID)) return {};
    // Preserve body fields and bind the transport boot only for pose.
    if (pose) {
        // cJSON prints large doubles with %g, which may round the source
        // timestamp or emit an exponent that Python decodes as a float.
        const auto* sample = cJSON_GetObjectItemCaseSensitive(body, "sample_us");
        if (!cJSON_IsNumber(sample) || !std::isfinite(sample->valuedouble) ||
            std::floor(sample->valuedouble) != sample->valuedouble ||
            sample->valuedouble < 1 || sample->valuedouble > 9007199254740991.0)
            return {};
        const auto decimal = std::to_string(static_cast<std::uint64_t>(sample->valuedouble));
        cJSON_DeleteItemFromObjectCaseSensitive(body, "sample_us");
        if (!cJSON_AddRawToObject(body, "sample_us", decimal.c_str()) ||
            !cJSON_AddNumberToObject(body, "head_boot", head_boot)) return {};
    }
    auto payload = Encode(body);
    return payload == "{}" ? std::string{} : payload;
}
bool StatusValid(cJSON* json) {
    // A partial status can contain plausible motor numbers but omit local
    // safety evidence. Reject it before forwarding sensory MCP observations.
    const auto get = [](cJSON* parent, const char* key) {
        return cJSON_GetObjectItemCaseSensitive(parent, key);
    };
    const auto integer = [](cJSON* item, double low, double high) {
        return cJSON_IsNumber(item) && std::isfinite(item->valuedouble) &&
               item->valuedouble == std::floor(item->valuedouble) &&
               item->valuedouble >= low && item->valuedouble <= high;
    };
    const auto array_of = [get, integer](
        cJSON* obj, const char* key, int count, double low, double high) {
        auto array = get(obj, key);
        if (!cJSON_IsArray(array) || cJSON_GetArraySize(array) != count) return false;
        for (int i = 0; i < count; ++i)
            if (!integer(cJSON_GetArrayItem(array, i), low, high)) return false;
        return true;
    };
    if (!cJSON_IsObject(json) || !cJSON_IsBool(get(json, "armed")) ||
        !integer(get(json, "watchdog_ms"), 0, 500) ||
        !integer(get(json, "protocol"), 2, 2)) return false;
    auto motor = get(json, "motor");
    auto servo = get(json, "servo");
    auto safety = get(json, "safety");
    auto ranges = get(json, "ranges");
    auto touch = get(json, "touch");
    auto imu = get(json, "imu");
    auto side_ranges = get(json, "side_ranges");
    if (!cJSON_IsObject(motor) || !cJSON_IsObject(servo) ||
        !cJSON_IsObject(safety) || !cJSON_IsObject(ranges) ||
        !cJSON_IsObject(touch) || !cJSON_IsObject(imu) ||
        !cJSON_IsObject(side_ranges)) return false;
    // Two independent status sections MUST agree on their source boot.
    auto imu_boot = get(imu, "boot_id");
    auto side_boot = get(side_ranges, "boot_id");
    if (!integer(imu_boot, 1, 4294967295.0) ||
        !integer(side_boot, 1, 4294967295.0) ||
        imu_boot->valuedouble != side_boot->valuedouble) return false;
    for (const char* name : {"m0", "m1"})
        if (!integer(get(motor, name), -40, 40)) return false;
    for (const char* name : {"lift", "grip", "lift_target", "grip_target"})
        if (!integer(get(servo, name), 0, 180)) return false;
    if (!cJSON_IsBool(get(servo, "attached"))) return false;
    auto position_source = get(servo, "position_source");
    if (!cJSON_IsString(position_source) || !position_source->valuestring ||
        std::strcmp(position_source->valuestring, "commanded") != 0) return false;
    auto fault = get(safety, "fault");
    if (!cJSON_IsBool(get(safety, "required")) ||
        !cJSON_IsBool(get(safety, "ready")) ||
        !integer(get(safety, "sensor"), 0, 255) ||
        !cJSON_IsString(fault) || !fault->valuestring ||
        std::strlen(fault->valuestring) == 0 ||
        std::strlen(fault->valuestring) > 48) return false;
    auto present_mask = get(ranges, "present_mask");
    auto valid_mask = get(ranges, "valid_mask");
    if (!integer(present_mask, 0, 31) || !integer(valid_mask, 0, 31) ||
        (valid_mask->valueint & ~present_mask->valueint) != 0 ||
        !array_of(ranges, "mm", 5, 0, 65535) ||
        !array_of(ranges, "age_ms", 5, 0, 4294967295.0)) return false;
    for (int i = 0; i < 5; ++i) {
        if ((valid_mask->valueint & (1 << i)) == 0) continue;
        const double mm = cJSON_GetArrayItem(get(ranges, "mm"), i)->valuedouble;
        const double age = cJSON_GetArrayItem(get(ranges, "age_ms"), i)->valuedouble;
        if (mm < 30 || mm > 1300 || age >= 200) return false;
    }
    if (!cJSON_IsBool(get(touch, "active")) ||
        !integer(get(touch, "count"), 0, 4294967295.0) ||
        !cJSON_IsBool(get(imu, "valid")) ||
        !integer(get(imu, "family"), 0, 4) ||
        !array_of(imu, "acc", 3, -32768, 32767) ||
        !array_of(imu, "gyro", 3, -32768, 32767) ||
        !integer(get(imu, "age_ms"), 0, 4294967295.0))
        return false;
    // Validation is read-only; local WROOM latching remains authoritative.
    return true;
}

bool OpticsValid(cJSON* json) {
    // Same WROOM sample, not a second ToF driver or a motor permission.
    const auto payload = cJSON_GetObjectItemCaseSensitive(json, "optics");
    if (!cJSON_IsObject(payload)) return false;
    const auto get = [payload](const char* key) {
        return cJSON_GetObjectItemCaseSensitive(payload, key);
    };
    const auto integer = [](cJSON* item, double max) {
        return cJSON_IsNumber(item) && std::isfinite(item->valuedouble) &&
               item->valuedouble == std::floor(item->valuedouble) &&
               item->valuedouble >= 0 && item->valuedouble <= max;
    };
    const auto present = get("present_mask"), valid = get("valid_mask");
    if (!integer(present, 255) || !integer(valid, 255) ||
        (valid->valueint & ~present->valueint) != 0 ||
        !cJSON_IsFalse(get("motor_authorized")) ||
        !cJSON_IsFalse(get("physical_qualified"))) return false;
    cJSON* amb = get("ambient_97");
    cJSON* signal = get("signal_97");
    cJSON* ages = get("age_ms");
    if (!cJSON_IsArray(amb) || !cJSON_IsArray(signal) ||
        !cJSON_IsArray(ages) || cJSON_GetArraySize(amb) != 8 ||
        cJSON_GetArraySize(signal) != 8 || cJSON_GetArraySize(ages) != 8)
        return false;
    for (int i = 0; i < 8; ++i) {
        auto age = cJSON_GetArrayItem(ages, i);
        if (!integer(cJSON_GetArrayItem(amb, i), 65535) ||
            !integer(cJSON_GetArrayItem(signal, i), 65535) ||
            !integer(age, 4294967295.0)) return false;
        if ((valid->valueint & (1 << i)) != 0 &&
            (i < 5 ? age->valuedouble >= 200 :
                     age->valuedouble > 350)) return false;
    }
    return true;
}


bool BodyWireByteValid(bool& pending_cr, uint8_t byte) {
    // CR is allowed only immediately before LF, not inside JSON or error text.
    if (pending_cr && byte != '\n') return false;
    pending_cr = byte == '\r';
    return true;
}

bool BodyWireValid(const std::string& line) {
    // cJSON C strings truncate escaped NUL in both keys and values.
    // The body wire protocol never needs embedded NUL in a reply.
    return line.find("\\u0000") == std::string::npos;
}

bool PoseVersionUnsupported(cJSON* json) {
    if (!cJSON_IsObject(json)) return false;
    const cJSON* version = nullptr;
    for (const cJSON* item = json->child; item; item = item->next) {
        if (!item->string || std::strcmp(item->string, "v") != 0) continue;
        if (version) return false;  // ambiguous version, not negotiation
        version = item;
    }
    return cJSON_IsNumber(version) && UnsupportedPoseWireVersion(version->valuedouble);
}

bool PoseValid(cJSON* json) {
    // Guide 20 version 1: validate a complete, exact body-origin sample.
    // The body owns quality and sample_us; the head must not invent either.
    if (!cJSON_IsObject(json) || cJSON_GetArraySize(json) != 9) return false;
    const auto get = [json](const char* key) {
        return cJSON_GetObjectItemCaseSensitive(json, key);
    };
    const auto integer = [](cJSON* item, double low, double high) {
        return cJSON_IsNumber(item) && std::isfinite(item->valuedouble) &&
               std::floor(item->valuedouble) == item->valuedouble &&
               item->valuedouble >= low && item->valuedouble <= high;
    };
    const auto version = get("v");
    const auto body_boot = get("body_boot");
    const auto origin = get("origin");
    const auto seq = get("seq");
    const auto sample_us = get("sample_us");
    const auto quality = get("quality");
    if (!integer(version, 1, 1) ||
        !integer(body_boot, 1, 4294967295.0) ||
        !integer(origin, 0, 4294967295.0) ||
        !integer(seq, 1, 4294967295.0) ||
        !integer(sample_us, 1, 9007199254740991.0) ||
        !integer(get("x_mm"), -1000000.0, 1000000.0) ||
        !integer(get("y_mm"), -1000000.0, 1000000.0) ||
        !integer(get("yaw_mrad"), -3142.0, 3142.0) ||
        !cJSON_IsString(quality) || !quality->valuestring) return false;
    const bool usable = std::strcmp(quality->valuestring, "valid") == 0;
    const bool degraded = std::strcmp(quality->valuestring, "degraded") == 0;
    const bool unavailable = std::strcmp(quality->valuestring, "unavailable") == 0;
    if (!usable && !degraded && !unavailable) return false;
    // Body read stays source-timed even when localization is unavailable;
    // only a valid/degraded pose requires a nonzero continuity origin.
    if ((usable || degraded) && origin->valuedouble == 0) return false;
    return true;
}

bool IrValid(cJSON* json) {
    // Explicit read-only RMT evidence; a matching carrier is not enough to
    // infer a bearing, permit a motor, or certify net cell charging.
    if (!cJSON_IsObject(json)) return false;
    const auto get = [json](const char* key) {
        return cJSON_GetObjectItemCaseSensitive(json, key);
    };
    const auto uint32 = [](cJSON* n) {
        return cJSON_IsNumber(n) && std::isfinite(n->valuedouble) &&
               n->valuedouble == std::floor(n->valuedouble) &&
               n->valuedouble >= 0 && n->valuedouble <= 4294967295.0;
    };
    const auto left = get("left_valid");
    const auto right = get("right_valid");
    const auto matched = get("match");
    const auto ls = get("left_seq"), rs = get("right_seq");
    const auto la = get("left_age_ms"), ra = get("right_age_ms");
    const auto code = get("code");
    if (!cJSON_IsBool(left) || !cJSON_IsBool(right) ||
        !cJSON_IsBool(matched) || !uint32(ls) || !uint32(rs) ||
        !uint32(la) || !uint32(ra) || !uint32(code) ||
        !cJSON_IsFalse(get("motor_authorized")) ||
        !cJSON_IsFalse(get("charging_authorized")) ||
        !cJSON_IsFalse(get("physical_qualified"))) return false;
    if ((cJSON_IsTrue(left) && (ls->valuedouble == 0 || la->valuedouble > 200)) ||
        (cJSON_IsTrue(right) && (rs->valuedouble == 0 || ra->valuedouble > 200)))
        return false;
    return !cJSON_IsTrue(matched) ||
           (cJSON_IsTrue(left) && cJSON_IsTrue(right) &&
            code->valuedouble > 0);
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
    auto dock = group("dock");
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
        (get(force, "jaw_valid") && !cJSON_IsBool(get(force, "jaw_valid"))) ||
        (get(force, "belly_valid") && !cJSON_IsBool(get(force, "belly_valid"))) ||
        (get(force, "belly_seq") && !bounded(get(force, "belly_seq"), 0, 4294967295.0)) ||
        (get(force, "belly_age_ms") && !bounded(get(force, "belly_age_ms"), 0, 4294967295.0)) ||
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
    // Present only on new head/body builds. Previous versions stay read only.
    if (dock) {
        if (!cJSON_IsObject(dock) ||
            !cJSON_IsBool(get(dock, "present")) ||
            !cJSON_IsBool(get(dock, "valid")) ||
            !cJSON_IsBool(get(dock, "left_seated")) ||
            !cJSON_IsBool(get(dock, "right_seated")) ||
            !cJSON_IsBool(get(dock, "input_good")) ||
            !cJSON_IsBool(get(dock, "charge_indicated")) ||
            !cJSON_IsFalse(get(dock, "charging_verified")) ||
            (cJSON_IsTrue(get(dock, "charge_indicated")) &&
             !cJSON_IsTrue(get(dock, "input_good"))))
            return false;
    }
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

Bridge::Bridge(Camera* camera, AudioCodec* audio_codec)
    : camera_(camera), audio_codec_(audio_codec) {}

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
    config.max_uri_handlers = 15;
    config.recv_wait_timeout = 2;
    config.send_wait_timeout = 2;
    // ESP-IDF excludes active asynchronous requests from LRU eviction.
    // Reclaim inactive keep-alive sessions instead of refusing new control clients.
    config.lru_purge_enable = true;
    if (httpd_start(&server_, &config) != ESP_OK) {
        ESP_LOGE(kTag, "HTTP API failed to start");
        return;
    }
    for (const auto& entry : std::vector<std::pair<const char*, httpd_method_t>>{
             {"/api/status", HTTP_GET}, {"/api/aux", HTTP_GET},
             {"/api/ir", HTTP_GET}, {"/api/optics", HTTP_GET},
             {"/api/pose", HTTP_GET},
             {"/api/command", HTTP_POST}, {"/api/face", HTTP_POST},
             {"/api/camera.jpg", HTTP_GET},
             {"/api/camera.mjpg", HTTP_GET},
             {"/api/camera.identity", HTTP_GET},
             {"/api/audio.reference", HTTP_GET}
#if defined(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3) && defined(CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED)
             ,{"/api/audio.capture.start", HTTP_POST},
             {"/api/audio.capture.abort", HTTP_POST},
             {"/api/audio.capture.status", HTTP_GET},
             {"/api/audio.capture.raw", HTTP_GET}
#endif
             }) {
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

bool Bridge::TakePersonCue() {
    return person_cue_.take(
        static_cast<std::uint32_t>(esp_timer_get_time() / 1000));
}

CosmeticMood Bridge::TakeCosmeticMoodCue() {
    return cosmetic_mood_.take(
        static_cast<std::uint32_t>(esp_timer_get_time() / 1000));
}

Reply Bridge::Transact(const std::string& text, bool operator_control) {
    Command command;
    if (!enabled_) return {503, false, "control disabled"};
    if (!ParseCommand(text, operator_control, command)) return {400, false, "invalid or unauthorized command"};
    const bool urgent = command.verb == "stop" || command.verb == "halt";
    const auto admitted_us = esp_timer_get_time();
    // Announce urgent STOP before waiting for the body UART lock.
    UrgentStopGate::Request urgency(urgent_stop_gate_, urgent);
    std::lock_guard<std::mutex> lock(uart_mutex_);
    if (urgency.preempted())
        return {503, false, "body read superseded by urgent stop"};
    if (!uart_ready_) return {503, false, "body UART unavailable"};
    // No retries: an uncertain ACK may still mean that physical movement happened.
    // A failed RX flush cannot establish that a matching line is fresh.
    // Still attempt STOP/HALT; RX failure must not suppress a stop write.
    const bool rx_clean = uart_flush_input(kUart) == ESP_OK;
    if (!rx_clean && !urgent) return {503, false, "body UART receive cleanup failed"};
    const std::string wire = command.wire + "\r\n";
    // A stalled read must not resurrect old operator intent or feed the
    // body watchdog with an aged keepalive. Never expire STOP or HALT.
    if (!ControlQueueFresh(command.verb, admitted_us, esp_timer_get_time()))
        return {503, false, "body control expired before UART write"};
    if (uart_write_bytes(kUart, wire.data(), wire.size()) != static_cast<int>(wire.size()) ||
        uart_wait_tx_done(kUart, pdMS_TO_TICKS(30)) != ESP_OK) return {503, false, "body UART write failed"};
    if (!rx_clean) return {503, false, "body stop sent; ACK uncertain after receive cleanup failure"};
    const auto deadline = esp_timer_get_time() + kTimeoutMs * 1000;
    std::string line;
    bool body_cr_pending = false;
    while (esp_timer_get_time() < deadline) {
        if (urgency.preempted())
            return {503, false, "body response superseded by urgent stop"};
        uint8_t c = 0;
        const int received = uart_read_bytes(kUart, &c, 1, pdMS_TO_TICKS(10));
        if (received < 0) return {503, false, "body UART read failed; command outcome uncertain"};
        if (received != 1) continue;
        if (urgency.preempted())
            return {503, false, "body response superseded by urgent stop"};
        if (!BodyWireByteValid(body_cr_pending, c))
            return {503, false, "malformed body response"};
        if (c == '\r') continue;
        if (c == '\n') {
            if (!BodyWireValid(line))
                return {503, false, "malformed body response"};
            // Old WROOM builds reject this new read-only verb explicitly.
            if (command.verb == "pose" && line == "ERR input unknown_command")
                return {501, false, "pose unsupported by body firmware"};
            if (MatchingError(line, command))
                return {command.verb == "pose" ? 503 : 400, false, line};
            if (command.verb == "status" || command.verb == "aux" ||
                command.verb == "ir" || command.verb == "optics" ||
                command.verb == "pose") {
                auto json = Parse(line);
                if (command.verb == "pose" && json && PoseVersionUnsupported(json.get()))
                    return {501, false, "pose unsupported by body firmware"};
                if (json && (command.verb == "status" ?
                             StatusValid(json.get()) : command.verb == "aux" ?
                             AuxValid(json.get()) : command.verb == "ir" ?
                             IrValid(json.get()) : command.verb == "pose" ?
                             PoseValid(json.get()) : OpticsValid(json.get())))
                    return {200, true, line};
                if (command.verb == "pose" && !line.empty() && line.front() == '{')
                    return {503, false, "malformed or unsupported pose response"};
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
    auto required = cJSON_GetObjectItemCaseSensitive(safety, "required");
    auto ready = cJSON_GetObjectItemCaseSensitive(safety, "ready");
    if (!cJSON_IsObject(touch) || !cJSON_IsNumber(count) ||
        !std::isfinite(count->valuedouble) ||
        count->valuedouble < 0 || count->valuedouble > 4294967295.0 ||
        std::floor(count->valuedouble) != count->valuedouble ||
        !cJSON_IsObject(safety) || !cJSON_IsString(fault) ||
        !cJSON_IsBool(required) || !cJSON_IsBool(ready)) {
        head_touch_edges_.Reset();
        body_cap_edges_.Reset();
        return observation;
    }
    const auto current = static_cast<std::uint32_t>(count->valuedouble);
    // Transact validated the WROOM boot in both source sections. The
    // first sampled nonzero post-reboot counter must not fabricate contact.
    auto imu = cJSON_GetObjectItemCaseSensitive(json.get(), "imu");
    auto boot = cJSON_GetObjectItemCaseSensitive(imu, "boot_id");
    if (!cJSON_IsNumber(boot) || !std::isfinite(boot->valuedouble) ||
        boot->valuedouble < 1 || boot->valuedouble > 4294967295.0 ||
        !head_touch_edges_.AcceptBoot(
            static_cast<std::uint32_t>(boot->valuedouble)))
        return observation;
    const auto body_boot_id = static_cast<std::uint32_t>(boot->valuedouble);
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
        // The optional CAP1188 count shares the same WROOM boot identity.
        if (!body_cap_edges_.AcceptBoot(body_boot_id)) return observation;
        observation.cap_touch_events = body_cap_edges_.Observe(
            static_cast<std::uint32_t>(cap_events->valuedouble));
    } else {
        body_cap_edges_.Reset();
    }
    // A valid status without a REQUIRED and READY WROOM safety profile
    // cannot justify a happy/normal OLED face. Keep sensory events intact,
    // and let the physical body continue to own its independent motor stop.
    observation.fault = BodySafetyUnhealthy(
        cJSON_IsTrue(required), cJSON_IsTrue(ready), fault->valuestring);
    observation.dock_lockout = BodyDockLockoutObserved(
        cJSON_IsTrue(required), cJSON_IsTrue(ready),
        cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(json.get(), "armed")),
        fault->valuestring);
    observation.valid = true;
    return observation;
}

bool Bridge::Authorize(httpd_req_t* req) {
    const size_t length = httpd_req_get_hdr_value_len(req, "Authorization");
    if (!enabled_ || length == 0 || length > 160) return false;
    char header[161] = {};
    if (httpd_req_get_hdr_value_str(req, "Authorization", header, sizeof(header)) != ESP_OK) return false;
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
        case 202: status_text = "202 Accepted"; break;
        case 400: status_text = "400 Bad Request"; break;
        case 409: status_text = "409 Conflict"; break;
        case 401: status_text = "401 Unauthorized"; break;
        case 413: status_text = "413 Content Too Large"; break;
        case 415: status_text = "415 Unsupported Media Type"; break;
        case 501: status_text = "501 Not Implemented"; break;
        case 503: status_text = "503 Service Unavailable"; break;
        case 504: status_text = "504 Gateway Timeout"; break;
    }
    httpd_resp_set_status(req, status_text);
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    // Do not let HTTPD drain an unauthenticated, possibly unbounded body.
    if (status == 401) {
        httpd_resp_set_hdr(req, "Connection", "close");
        (void)httpd_resp_send(req, body.data(), body.size());
        return ESP_FAIL;
    }
    return httpd_resp_send(req, body.data(), body.size());
}

esp_err_t Bridge::Dispatch(httpd_req_t* req) { return static_cast<Bridge*>(req->user_ctx)->Handle(req); }

void Bridge::BodyReadTask(void* context) {
    // The synchronous HTTP handler must remain free to receive urgent STOP
    // even when a body status reply occupies the UART for hundreds of ms.
    auto* req = static_cast<httpd_req_t*>(context);
    auto* bridge = static_cast<Bridge*>(req->user_ctx);
    {
        const bool aux = strcmp(req->uri, "/api/aux") == 0;
        const bool ir = strcmp(req->uri, "/api/ir") == 0;
        const bool optics = strcmp(req->uri, "/api/optics") == 0;
        const bool pose = strcmp(req->uri, "/api/pose") == 0;
        const auto reply = bridge->Transact(
            pose ? "pose" : optics ? "optics" : ir ? "ir" : aux ? "aux" : "status", false);
        if (!reply.ok) {
            bridge->Json(req, reply.status, Envelope(false, reply.text));
        } else {
            auto body = Parse(reply.text);
            if (!body) {
                bridge->Json(req, 503, Envelope(false, "invalid body JSON"));
            } else {
                const auto payload = EncodeBodyRead(body.get(), pose, bridge->boot_nonce_);
                if (payload.empty()) {
                    bridge->Json(req, 503, Envelope(false, "body identity or encoding unavailable"));
                } else {
                    bridge->Json(req, 200, payload);
                }
            }
        }
    }
    bridge->body_read_busy_.store(false, std::memory_order_release);
    httpd_req_async_handler_complete(req);
    vTaskDelete(nullptr);
}

void Bridge::CameraTask(void* context) {
    auto* req = static_cast<httpd_req_t*>(context);
    auto* bridge = static_cast<Bridge*>(req->user_ctx);
    {
        auto jpeg = bridge->camera_->SnapshotJpeg();
        const auto completed = esp_timer_get_time();
        if (!jpeg) {
            bridge->Json(req, 503, Envelope(false, jpeg.error()));
        } else if (!CompleteJpeg(jpeg->data(), jpeg->size())) {
            bridge->Json(req, 503, Envelope(false, "incomplete JPEG capture"));
        } else if (bridge->camera_sequence_ == std::numeric_limits<std::uint32_t>::max() ||
                   completed <= bridge->camera_completed_us_) {
            bridge->Json(req, 503, Envelope(false, "camera provenance clock or sequence exhausted"));
        } else {
            // Completion, not guessed exposure time. The Mac can reject old
            // frames from the same boot without synchronizing ESP32/Mac clocks.
            const std::string nonce = std::to_string(bridge->boot_nonce_);
            // Reserve, but do not consume, a frame sequence until every
            // provenance header is staged. A header allocation failure must
            // never publish an apparently fresh JPEG without its identity.
            const std::string sequence = std::to_string(bridge->camera_sequence_ + 1);
            const std::string completed_us = std::to_string(completed);
            esp_err_t header_status = httpd_resp_set_type(req, "image/jpeg");
            if (header_status == ESP_OK)
                header_status = httpd_resp_set_hdr(req, "Cache-Control", "no-store");
            if (header_status == ESP_OK)
                header_status = httpd_resp_set_hdr(req, "X-Desk-Camera-Robot-Id", CONFIG_DESK_ROBOT_ID);
            if (header_status == ESP_OK)
                header_status = httpd_resp_set_hdr(req, "X-Desk-Camera-Boot", nonce.c_str());
            if (header_status == ESP_OK)
                header_status = httpd_resp_set_hdr(req, "X-Desk-Camera-Sequence", sequence.c_str());
            if (header_status == ESP_OK)
                header_status = httpd_resp_set_hdr(req, "X-Desk-Camera-Complete-Us", completed_us.c_str());
            if (header_status != ESP_OK) {
                bridge->Json(req, 503, Envelope(false, "camera provenance headers unavailable"));
            } else {
                const auto sent = httpd_resp_send(
                    req, reinterpret_cast<const char*>(jpeg->data()), jpeg->size());
                if (sent == ESP_OK) {
                    ++bridge->camera_sequence_;
                    bridge->camera_completed_us_ = completed;
                }
            }
        }
    }  // Destroy JPEG storage before vTaskDelete (which does not unwind C++ locals).
    bridge->camera_busy_.store(false);
    httpd_req_async_handler_complete(req);
    vTaskDelete(nullptr);
}


void Bridge::CameraStreamTask(void* context) {
    // Adapted from Espressif esp32-camera's official multipart MJPEG example.
    // One authenticated long-lived client owns the same native JPEG camera
    // used by /api/camera.jpg. Never allocate an RGB intermediary or block
    // the HTTP server's command/UART handler while waiting for camera frames.
    auto* req = static_cast<httpd_req_t*>(context);
    auto* bridge = static_cast<Bridge*>(req->user_ctx);
    constexpr char kBoundary[] = "--deskrobotframe\r\n";
    esp_err_t status = httpd_resp_set_type(
        req, "multipart/x-mixed-replace; boundary=deskrobotframe");
    if (status == ESP_OK)
        status = httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    if (status == ESP_OK)
        status = httpd_resp_set_hdr(req, "X-Content-Type-Options", "nosniff");
    while (status == ESP_OK) {
        {
            auto jpeg = bridge->camera_->SnapshotJpeg();
            const auto completed = esp_timer_get_time();
            if (!jpeg || !CompleteJpeg(jpeg->data(), jpeg->size())) {
                status = ESP_FAIL; // Never stream a partial camera frame.
            } else if (bridge->camera_sequence_ == std::numeric_limits<std::uint32_t>::max() ||
                       completed <= bridge->camera_completed_us_) {
                status = ESP_FAIL; // Never wrap or publish a regressed source identity.
            } else {
                // Per-part provenance is the same trusted monotonic camera
                // completion metadata as the established snapshot endpoint.
                const auto seq = bridge->camera_sequence_ + 1;
                // Longest legal ID and 64-bit timestamp must fit together.
                char headers[320] = {};
                const int n = snprintf(
                    headers, sizeof(headers),
                    "Content-Type: image/jpeg\r\n"
                    "Content-Length: %zu\r\n"
                    "X-Desk-Camera-Robot-Id: %s\r\n"
                    "X-Desk-Camera-Boot: %u\r\n"
                    "X-Desk-Camera-Sequence: %u\r\n"
                    "X-Desk-Camera-Complete-Us: %lld\r\n\r\n",
                    jpeg->size(), CONFIG_DESK_ROBOT_ID,
                    static_cast<unsigned>(bridge->boot_nonce_),
                    static_cast<unsigned>(seq), static_cast<long long>(completed));
                if (n < 0 || static_cast<std::size_t>(n) >= sizeof(headers)) {
                    status = ESP_FAIL;
                } else {
                    // Only a complete, successfully written part spends a source identity.
                    status = httpd_resp_send_chunk(
                        req, kBoundary, sizeof(kBoundary) - 1);
                    if (status == ESP_OK)
                        status = httpd_resp_send_chunk(req, headers, n);
                    if (status == ESP_OK)
                        status = httpd_resp_send_chunk(
                            req, reinterpret_cast<const char*>(jpeg->data()), jpeg->size());
                    if (status == ESP_OK)
                        status = httpd_resp_send_chunk(req, "\r\n", 2);
                    if (status == ESP_OK) {
                        ++bridge->camera_sequence_;
                        bridge->camera_completed_us_ = completed;
                    }
                }
            }
        } // Release the pinned Xiaozhi JPEG before yielding to audio/other tasks.
        if (status != ESP_OK) break; // Client disconnect closes stream.
        vTaskDelay(pdMS_TO_TICKS(250)); // Max 4 FPS, not 4 VLM inferences/s.
    }
    bridge->camera_busy_.store(false);
    httpd_req_async_handler_complete(req);
    vTaskDelete(nullptr);
}


#if defined(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3) && defined(CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED)
void Bridge::BenchPcmTask(void* context) {
    // Asynchronous HTTP response so 256 KiB raw PCM can never block status,
    // emergency STOP or watchdog requests on the head HTTP dispatcher.
    std::unique_ptr<BenchPcmTransfer> transfer(
        static_cast<BenchPcmTransfer*>(context));
    auto* req = transfer->req;
    const auto& pcm = transfer->pcm;
    const auto source = reinterpret_cast<const char*>(pcm.interleaved);
    const auto still_authorized = [&]() {
        return transfer->codec->BenchPcmGeneration() == transfer->generation;
    };
    char first[32], last[32], boot[24], frames[20], generation[24];
    snprintf(first, sizeof(first), "%lld",
             static_cast<long long>(pcm.first_sample_us));
    snprintf(last, sizeof(last), "%lld",
             static_cast<long long>(pcm.last_sample_us));
    snprintf(boot, sizeof(boot), "%u", static_cast<unsigned>(transfer->boot));
    snprintf(frames, sizeof(frames), "%u", static_cast<unsigned>(pcm.frames));
    snprintf(generation, sizeof(generation), "%llu",
             static_cast<unsigned long long>(transfer->generation));
    esp_err_t status = httpd_resp_set_type(req, "application/octet-stream");
    if (status == ESP_OK) status = httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    if (status == ESP_OK) status = httpd_resp_set_hdr(req, "X-Content-Type-Options", "nosniff");
    if (status == ESP_OK) status = httpd_resp_set_hdr(req, "X-Desk-Audio-Robot-Id", CONFIG_DESK_ROBOT_ID);
    if (status == ESP_OK) status = httpd_resp_set_hdr(req, "X-Desk-Audio-Boot", boot);
    if (status == ESP_OK) status = httpd_resp_set_hdr(req, "X-Desk-Audio-Frames", frames);
    if (status == ESP_OK) status = httpd_resp_set_hdr(req, "X-Desk-Audio-Generation", generation);
    if (status == ESP_OK) status = httpd_resp_set_hdr(req, "X-Desk-Audio-First-Us", first);
    if (status == ESP_OK) status = httpd_resp_set_hdr(req, "X-Desk-Audio-Last-Us", last);
    const int64_t deadline_us = esp_timer_get_time() + 5'000'000;
    for (std::size_t offset = 0;
         status == ESP_OK && offset < desk_robot::SensePcmWindow::kBytes;
         offset += 4096) {
        if (esp_timer_get_time() >= deadline_us || !still_authorized()) {
            status = ESP_FAIL;  // Physical mute or reset revoked this buffer.
            break;
        }
        const auto count = std::min<std::size_t>(
            4096, desk_robot::SensePcmWindow::kBytes - offset);
        status = httpd_resp_send_chunk(req, source + offset, count);
    }
    if (status == ESP_OK && esp_timer_get_time() < deadline_us &&
        still_authorized())
        (void)httpd_resp_send_chunk(req, nullptr, 0);
    // Wipe even after physical BOOT, barge-in, client disconnect or timeout.
    SenseReferenceCodec::ReleaseBenchPcmCapture(pcm.interleaved);
    transfer->codec->EndBenchPcmTransfer();
    httpd_req_async_handler_complete(req);
    transfer.reset();
    vTaskDelete(nullptr);
}
#endif

esp_err_t Bridge::Handle(httpd_req_t* req) {
    if (!Authorize(req)) return Json(req, 401, Envelope(false, "unauthorized"));
    const auto reject = [&](int status, const char* reason) {
        httpd_resp_set_hdr(req, "Connection", "close");
        (void)Json(req, status, Envelope(false, reason));
        return ESP_FAIL; // HTTPD closes instead of draining unread request data.
    };
    // ESP-IDF httpd_req_recv does not support chunked request bodies.
    // Check the original decimal header as well as HTTPD's size_t result:
    // older ESP-IDF parsers can narrow a 64-bit Content-Length on ESP32.
    char transfer_encoding[1] = {};
    if (httpd_req_get_hdr_value_str(req, "Transfer-Encoding", transfer_encoding,
                                    sizeof(transfer_encoding)) != ESP_ERR_NOT_FOUND)
        return reject(400, "transfer encoding unsupported");
    char content_length[24] = {};
    const auto length_status = httpd_req_get_hdr_value_str(
        req, "Content-Length", content_length, sizeof(content_length));
    const auto length_bytes = httpd_req_get_hdr_value_len(req, "Content-Length");
    if (length_status == ESP_ERR_NOT_FOUND) {
        if (req->content_len != 0) return reject(400, "missing content length");
    } else if (length_status != ESP_OK || length_bytes >= sizeof(content_length) ||
               !ContentLengthMatches(std::string_view(content_length, length_bytes),
                                     req->content_len)) {
        return reject(400, "invalid content length");
    }
    if (req->content_len > kMaxBody) return reject(413, "invalid body length");
    const bool json_route = req->method == HTTP_POST &&
        (strcmp(req->uri, "/api/command") == 0 || strcmp(req->uri, "/api/face") == 0);
    if (!json_route && req->content_len != 0)
        return reject(400, "request body not permitted");

#if defined(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3) && defined(CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED)
    // A capture generation is only unique within a head boot. Check both
    // request identities before an old client can consume or cancel a newer
    // private PCM window. The same HTTP dispatcher owns START and these checks.
    const auto matches_capture_boot = [&]() {
        char expected_boot[24] = {};
        char supplied_boot[24] = {};
        snprintf(expected_boot, sizeof(expected_boot), "%u",
                 static_cast<unsigned>(boot_nonce_));
        return httpd_req_get_hdr_value_str(
                   req, "X-Desk-Audio-Boot", supplied_boot,
                   sizeof(supplied_boot)) == ESP_OK &&
               strcmp(expected_boot, supplied_boot) == 0;
    };
    if (strcmp(req->uri, "/api/audio.capture.start") == 0) {
        if (req->content_len != 0)
            return Json(req, 400, Envelope(false, "Bench capture request must be empty"));
        if (!audio_codec_) return Json(req, 503, Envelope(false, "Sense codec unavailable"));
        auto* codec = static_cast<SenseReferenceCodec*>(audio_codec_);
        // A delayed START must not spend consent from another boot or
        // from a later physical mute/unmute cycle. Fence before allocation.
        const uint32_t privacy_epoch =
            codec->GetReferenceDiagnostics().microphone_privacy_epoch;
        char expected_privacy[24] = {};
        char supplied_privacy[24] = {};
        snprintf(expected_privacy, sizeof(expected_privacy), "%u",
                 static_cast<unsigned>(privacy_epoch));
        if (!matches_capture_boot() ||
            httpd_req_get_hdr_value_str(req, "X-Desk-Audio-Privacy-Epoch",
                supplied_privacy, sizeof(supplied_privacy)) != ESP_OK ||
            strcmp(expected_privacy, supplied_privacy) != 0)
            return Json(req, 409, Envelope(false, "Bench START privacy or boot mismatch"));
        JsonPtr started(cJSON_CreateObject(), cJSON_Delete);
        if (!started) return Json(req, 503, Envelope(false, "Bench start reply unavailable"));
        if (!codec->BeginBenchPcmCapture(privacy_epoch))
            return Json(req, 409, Envelope(false, "Bench PCM unavailable or already active"));
        char generation[24];
        snprintf(generation, sizeof(generation), "%llu",
                 static_cast<unsigned long long>(codec->BenchPcmGeneration()));
        cJSON_AddBoolToObject(started.get(), "ok", true);
        cJSON_AddStringToObject(started.get(), "reply", "Private bench PCM capture started");
        cJSON_AddStringToObject(started.get(), "robot_id", CONFIG_DESK_ROBOT_ID);
        cJSON_AddNumberToObject(started.get(), "boot", boot_nonce_);
        cJSON_AddStringToObject(started.get(), "capture_generation", generation);
        return Json(req, 202, Encode(started.get()));
    }
    if (strcmp(req->uri, "/api/audio.capture.abort") == 0) {
        if (req->content_len != 0)
            return Json(req, 400, Envelope(false, "Bench abort request must be empty"));
        if (!audio_codec_) return Json(req, 503, Envelope(false, "Sense codec unavailable"));
        auto* codec = static_cast<SenseReferenceCodec*>(audio_codec_);
        // Check the exact decimal generation, not a model-provided command.
        // Handler serialization prevents another HTTP START between this
        // comparison and the abort. BOOT can still independently invalidate
        // the source, but never grants authority to restore it.
        char expected[24] = {};
        char supplied[24] = {};
        snprintf(expected, sizeof(expected), "%llu",
                 static_cast<unsigned long long>(codec->BenchPcmGeneration()));
        if (!matches_capture_boot() ||
            httpd_req_get_hdr_value_str(
                req, "X-Desk-Audio-Generation", supplied,
                sizeof(supplied)) != ESP_OK ||
            strcmp(expected, supplied) != 0)
            return Json(req, 409, Envelope(false, "Bench capture generation mismatch"));
        codec->AbortBenchPcmCapture(); // Wipe pending PCM; fence HTTP worker.
        return Json(req, 200, Envelope(true, "Private bench PCM capture aborted"));
    }
    if (strcmp(req->uri, "/api/audio.capture.status") == 0) {
        if (!audio_codec_) return Json(req, 503, Envelope(false, "Sense codec unavailable"));
        const auto progress =
            static_cast<SenseReferenceCodec*>(audio_codec_)->GetBenchPcmProgress();
        JsonPtr data(cJSON_CreateObject(), cJSON_Delete);
        if (!data) return Json(req, 503, Envelope(false, "Bench status unavailable"));
        cJSON_AddStringToObject(data.get(), "robot_id", CONFIG_DESK_ROBOT_ID);
        cJSON_AddNumberToObject(data.get(), "boot", boot_nonce_);
        cJSON_AddBoolToObject(data.get(), "active", progress.active);
        cJSON_AddBoolToObject(data.get(), "ready", progress.ready);
        cJSON_AddBoolToObject(data.get(), "failed", progress.failed);
        cJSON_AddNumberToObject(data.get(), "frames", progress.frames);
        // Latched inside the final microphone callback, not guessed from
        // cumulative I2S counters after the private recording ended.
        cJSON_AddBoolToObject(data.get(), "speaker_activity_in_window",
                              progress.speaker_activity_in_window);
        char generation[24];
        snprintf(generation, sizeof(generation), "%llu",
                 static_cast<unsigned long long>(progress.generation));
        cJSON_AddStringToObject(data.get(), "capture_generation", generation);
        cJSON_AddBoolToObject(data.get(), "physical_aec_qualified", false);
        return Json(req, 200, Encode(data.get()));
    }
    if (strcmp(req->uri, "/api/audio.capture.raw") == 0) {
        if (!audio_codec_) return Json(req, 503, Envelope(false, "Sense codec unavailable"));
        auto* codec = static_cast<SenseReferenceCodec*>(audio_codec_);
        const uint64_t generation = codec->BenchPcmGeneration();
        char expected[24] = {};
        char supplied[24] = {};
        snprintf(expected, sizeof(expected), "%llu",
                 static_cast<unsigned long long>(generation));
        if (!matches_capture_boot() ||
            httpd_req_get_hdr_value_str(
                req, "X-Desk-Audio-Generation", supplied,
                sizeof(supplied)) != ESP_OK ||
            strcmp(expected, supplied) != 0)
            return Json(req, 409, Envelope(false, "Bench capture generation mismatch"));
        // Recheck the generation under the codec's buffer lock: BOOT privacy,
        // expiry or a playback reset can invalidate it independently of HTTP.
        const auto pcm = codec->TakeBenchPcmCapture(generation);
        if (!pcm.interleaved || pcm.frames != desk_robot::SensePcmWindow::kFrames)
            return Json(req, 409, Envelope(false, "Bench PCM not complete"));
        httpd_req_t* async_req = nullptr;
        if (httpd_req_async_handler_begin(req, &async_req) != ESP_OK) {
            SenseReferenceCodec::ReleaseBenchPcmCapture(pcm.interleaved);
            codec->EndBenchPcmTransfer();
            return Json(req, 503, Envelope(false, "Bench PCM worker unavailable"));
        }
        auto* transfer = new(std::nothrow) BenchPcmTransfer{
            async_req, pcm, boot_nonce_, codec, generation};
        if (!transfer) {
            SenseReferenceCodec::ReleaseBenchPcmCapture(pcm.interleaved);
            codec->EndBenchPcmTransfer();
            Json(async_req, 503, Envelope(false, "Bench PCM allocation unavailable"));
            httpd_req_async_handler_complete(async_req);
            return ESP_OK;
        }
        if (xTaskCreate(BenchPcmTask, "sense_pcm_once", 6144,
                        transfer, 2, nullptr) != pdPASS) {
            SenseReferenceCodec::ReleaseBenchPcmCapture(pcm.interleaved);
            codec->EndBenchPcmTransfer();
            delete transfer;
            Json(async_req, 503, Envelope(false, "Bench PCM worker failed"));
            httpd_req_async_handler_complete(async_req);
        }
        return ESP_OK;
    }
#endif
    if (strcmp(req->uri, "/api/audio.reference") == 0) {
#if defined(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3)
        if (!audio_codec_) return Json(req, 503, Envelope(false, "Sense audio unavailable"));
        // The Sense board supplies the actual single Xiaozhi audio codec.
        // These are software-integrity counters, NEVER proof of heard TTS.
        const auto d = static_cast<SenseReferenceCodec*>(audio_codec_)
                           ->GetReferenceDiagnostics();
        JsonPtr result(cJSON_CreateObject(), cJSON_Delete);
        if (!result) return Json(req, 503, Envelope(false, "audio status unavailable"));
        cJSON_AddStringToObject(result.get(), "robot_id", CONFIG_DESK_ROBOT_ID);
        cJSON_AddNumberToObject(result.get(), "boot", boot_nonce_);
#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED
        // A speaker reset can invalidate the capture AFTER the raw response.
        // Bind the final authenticated receipt to the same PCM generation.
        char capture_generation[24] = {};
        snprintf(capture_generation, sizeof(capture_generation), "%llu",
                 static_cast<unsigned long long>(
                     static_cast<SenseReferenceCodec*>(audio_codec_)
                         ->BenchPcmGeneration()));
        cJSON_AddStringToObject(result.get(), "capture_generation",
                                capture_generation);
#endif
        cJSON_AddNumberToObject(result.get(), "reference_underflow_reads", d.underflow_reads);
        cJSON_AddNumberToObject(result.get(), "reference_overwrite_reads", d.overwrite_reads);
        cJSON_AddNumberToObject(result.get(), "discarded_stale_writes", d.discarded_stale_writes);
        cJSON_AddNumberToObject(result.get(), "short_output_writes", d.short_output_writes);
        cJSON_AddNumberToObject(result.get(), "short_input_reads", d.short_input_reads);
        cJSON_AddNumberToObject(result.get(), "microphone_frames_read", d.microphone_frames_read);
        cJSON_AddNumberToObject(result.get(), "speaker_frames_accepted", d.speaker_frames_accepted);
        cJSON_AddBoolToObject(result.get(), "microphone_privacy_muted", d.microphone_privacy_muted);
        cJSON_AddNumberToObject(result.get(), "microphone_privacy_epoch", d.microphone_privacy_epoch);
        // Report the actual flashed AEC offset, not the bench command-line
        // intent. Raw acoustic capture requires zero to avoid measuring only
        // the residual lag after the firmware already shifted the reference.
        cJSON_AddNumberToObject(result.get(), "aec_delay_config_ms",
                                CONFIG_DESK_ROBOT_AEC_DELAY_MS);
        cJSON_AddBoolToObject(result.get(), "reference_integrity_failed", d.integrity_failed);
        cJSON_AddBoolToObject(result.get(), "speaker_playback_verified", false);
        cJSON_AddBoolToObject(result.get(), "aec_physically_qualified", false);
        return Json(req, 200, Encode(result.get()));
#else
        return Json(req, 503, Envelope(false, "No Sense reference codec on this board"));
#endif
    }
    if (strcmp(req->uri, "/api/camera.identity") == 0) {
        // Read only the actual sensor ID from Espressif's initialized
        // upstream camera driver. No new camera task, JPEG or UART owner.
        // This authenticated identity is checked against the frame boot
        // nonce and the measured offline calibration before dock movement.
        if (!camera_) return Json(req, 503, Envelope(false, "camera unavailable"));
        const sensor_t* sensor = esp_camera_sensor_get();
        if (!sensor) return Json(req, 503, Envelope(false, "camera sensor unavailable"));
        const auto pid = sensor->id.PID;
        const char* model = pid == OV2640_PID ? "OV2640" :
                            pid == OV3660_PID ? "OV3660" :
                            pid == OV5640_PID ? "OV5640" : nullptr;
        if (!model) return Json(req, 503, Envelope(false, "unsupported camera PID"));
        JsonPtr identity(cJSON_CreateObject(), cJSON_Delete);
        if (!identity) return Json(req, 503, Envelope(false, "camera metadata unavailable"));
        cJSON_AddStringToObject(identity.get(), "robot_id", CONFIG_DESK_ROBOT_ID);
        cJSON_AddStringToObject(identity.get(), "camera_sensor_pid", model);
        cJSON_AddNumberToObject(identity.get(), "camera_pid_raw", pid);
        cJSON_AddNumberToObject(identity.get(), "boot", boot_nonce_);
        return Json(req, 200, Encode(identity.get()));
    }
    if (strcmp(req->uri, "/api/camera.mjpg") == 0) {
        if (!camera_) return Json(req, 503, Envelope(false, "camera unavailable"));
        if (camera_busy_.exchange(true))
            return Json(req, 503, Envelope(false, "camera busy"));
        httpd_req_t* async_req = nullptr;
        if (httpd_req_async_handler_begin(req, &async_req) != ESP_OK) {
            camera_busy_.store(false);
            return Json(req, 503, Envelope(false, "stream worker unavailable"));
        }
        // Optional JPEG work must yield even to Xiaozhi Opus (priority 2).
        if (xTaskCreate(CameraStreamTask, "robot_stream", 8192, async_req,
                        1, nullptr) != pdPASS) {
            Json(async_req, 503, Envelope(false, "stream task unavailable"));
            httpd_req_async_handler_complete(async_req);
            camera_busy_.store(false);
        }
        return ESP_OK;
    }
    if (strcmp(req->uri, "/api/camera.jpg") == 0) {
        if (!camera_) return Json(req, 503, Envelope(false, "camera unavailable"));
        if (camera_busy_.exchange(true)) return Json(req, 503, Envelope(false, "camera busy"));
        // Camera locking/encoding must never block HTTP keepalive or emergency stop.
        httpd_req_t* async_req = nullptr;
        if (httpd_req_async_handler_begin(req, &async_req) != ESP_OK) {
            camera_busy_.store(false);
            return Json(req, 503, Envelope(false, "camera worker unavailable"));
        }
        // Match the stream worker: never outrank the Opus codec task.
        if (xTaskCreate(CameraTask, "robot_camera", 8192, async_req, 1, nullptr) != pdPASS) {
            Json(async_req, 503, Envelope(false, "camera task unavailable"));
            httpd_req_async_handler_complete(async_req);
            camera_busy_.store(false);
        }
        return ESP_OK;
    }
    if (strcmp(req->uri, "/api/status") == 0 ||
        strcmp(req->uri, "/api/aux") == 0 ||
        strcmp(req->uri, "/api/ir") == 0 ||
        strcmp(req->uri, "/api/optics") == 0 ||
        strcmp(req->uri, "/api/pose") == 0) {
        if (body_read_busy_.exchange(true, std::memory_order_acq_rel))
            return Json(req, 503, Envelope(false, "body telemetry busy"));
        httpd_req_t* async_req = nullptr;
        if (httpd_req_async_handler_begin(req, &async_req) != ESP_OK) {
            body_read_busy_.store(false, std::memory_order_release);
            return Json(req, 503, Envelope(false, "body read worker unavailable"));
        }
        if (xTaskCreate(BodyReadTask, "robot_body_read", 8192,
                        async_req, 3, nullptr) != pdPASS) {
            Json(async_req, 503, Envelope(false, "body read task unavailable"));
            httpd_req_async_handler_complete(async_req);
            body_read_busy_.store(false, std::memory_order_release);
        }
        return ESP_OK;
    }
    // The URI matcher may dispatch a path with a query suffix. Never let an
    // unmatched face/GET URI fall through to the operator command handler.
    if (!json_route) return reject(400, "unsupported route");
    if (req->content_len == 0) return reject(400, "invalid body length");
    char content_type[40] = {};
    const auto type_bytes = httpd_req_get_hdr_value_len(req, "Content-Type");
    if (type_bytes >= sizeof(content_type) ||
        httpd_req_get_hdr_value_str(req, "Content-Type", content_type, sizeof(content_type)) != ESP_OK)
        return reject(415, "application/json required");
    const std::string_view type(content_type, type_bytes);
    if (type != "application/json" && type != "application/json; charset=utf-8")
        return reject(415, "application/json required");
    std::string body(req->content_len, '\0');
    size_t got = 0;
    const auto deadline = esp_timer_get_time() + 2'000'000;
    while (got < body.size()) {
        if (esp_timer_get_time() >= deadline)
            return reject(400, "request body deadline exceeded");
        const int n = httpd_req_recv(req, body.data() + got, body.size() - got);
        if (n <= 0 || static_cast<size_t>(n) > body.size() - got)
            return reject(400, "incomplete request body");
        if (esp_timer_get_time() >= deadline)
            return reject(400, "request body deadline exceeded");
        got += static_cast<size_t>(n);
    }
    if (body.find('\0') != std::string::npos || body.find("\\u0000") != std::string::npos) return reject(400, "embedded null");
    auto json = Parse(body);
    if (!json || !cJSON_IsObject(json.get()) || cJSON_GetArraySize(json.get()) != 1)
        return reject(400, "expected one event or command field");
    if (strcmp(req->uri, "/api/face") == 0) {
#if !defined(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3)
        // Only Sense has a local task consuming these queued cues.
        return Json(req, 503, Envelope(false, "face cue consumer unavailable on this board"));
#else
        if (!FaceConsumerAvailable())
            return Json(req, 503, Envelope(false, "face cue consumer unavailable"));
        // The authenticated Mac can offer a bounded *visual* cue only. A
        // language model, OCR frame or tool response cannot send motor text
        // through this route. Latest event wins; no unbounded HTTP queue.
        auto event = cJSON_GetObjectItemCaseSensitive(json.get(), "event");
        if (!cJSON_IsString(event) || !event->valuestring)
            return Json(req, 400, Envelope(false, "unsupported face event"));
        if (strcmp(event->valuestring, "person_detected") != 0) {
            // Only a tiny, allowlisted OLED mood. Never pass untrusted
            // expression text to a motor, TTS, wake or speaker endpoint.
            const CosmeticMood mood = ParseCosmeticMood(event->valuestring);
            if (mood == CosmeticMood::kNone)
                return Json(req, 400, Envelope(false, "unsupported face event"));
            cosmetic_mood_.offer(
                mood, static_cast<std::uint32_t>(esp_timer_get_time() / 1000));
            return Json(req, 200, Envelope(true, "mood cue queued"));
        }
        person_cue_.offer(
            static_cast<std::uint32_t>(esp_timer_get_time() / 1000));
        return Json(req, 200, Envelope(true, "person cue queued"));
#endif
    }
    auto item = cJSON_GetObjectItemCaseSensitive(json.get(), "command");
    if (!cJSON_IsString(item) || !item->valuestring)
        return reject(400, "command must be a string");
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
    // Reuse the existing authenticated WROOM status transaction for the
    // upstream-inspired self.pet sensory MCP schema. This is deliberately a
    // read-only alias, NOT a second UART owner, a cached guessed sensation,
    // a motion permit or a trigger to wake Xiaozhi. The body owns cliff
    // latches and marks unqualified physical measurements in its JSON.
    mcp.AddTool(
        "self.pet.get_sensory_state",
        "Read the current WROOM cliff safety, front and floor ranges, touch, "
        "IMU, battery and accessory observations. Values may be unavailable "
        "or physically unqualified. Never interpret status as motor permission, "
        "charging proof or proof of a camera sighting.",
        PropertyList(),
        [call](const PropertyList&) -> ToolResult { return call("status"); });
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
