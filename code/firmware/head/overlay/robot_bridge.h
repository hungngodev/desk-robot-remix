#pragma once
#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include "esp_http_server.h"
#include "camera.h"
#include "robot_protocol.h"
#include "real_touch_edges.h"

class AudioCodec;

namespace desk_robot {
struct Reply {
    int status;
    bool ok;
    std::string text;
};

struct BodyInteraction {
    int touch_events = 0;
    int cap_touch_events = 0; // actual optional eight-zone CAP1188 rise counters
    bool fault = false;
    bool valid = false;
};

class Bridge {
public:
    explicit Bridge(Camera* camera, AudioCodec* audio_codec = nullptr);
    void Start();
    // One bounded local status transaction, no motor authority or second UART.
    BodyInteraction PollInteraction();
    // One cosmetic face cue, consumed ONLY by the local face task.
    // No motor, tool, speech or Xiaozhi conversation authority.
    bool TakePersonCue();

private:
    Camera* camera_;
    AudioCodec* audio_codec_ = nullptr;  // Sense codec only, no second audio owner
    httpd_handle_t server_ = nullptr;
    std::mutex uart_mutex_;
    bool uart_ready_ = false;
    bool enabled_ = false;
    std::atomic<bool> camera_busy_{false};
    std::atomic<bool> person_cue_pending_{false};
    std::uint32_t camera_sequence_ = 0; // camera_busy ensures one producer
    std::uint32_t boot_nonce_ = 0; // changes across physical Sense reboots
    // Owned by the one Sense face task, not shared with HTTP handlers.
    RealTouchEdges head_touch_edges_{};
    RealTouchEdges body_cap_edges_{};
    static void CameraTask(void* context);
    static void CameraStreamTask(void* context);
    Reply Transact(const std::string& command, bool operator_control);
    bool Authorize(httpd_req_t* req);
    esp_err_t Handle(httpd_req_t* req);
    esp_err_t Json(httpd_req_t* req, int status, const std::string& body);
    static esp_err_t Dispatch(httpd_req_t* req);
    void AddTools();
};
}  // namespace desk_robot
