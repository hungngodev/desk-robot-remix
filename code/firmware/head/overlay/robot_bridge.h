#pragma once
#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include "esp_http_server.h"
#include "sdkconfig.h"  // Bench PCM handler is compile gated per private Sense build.
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
    bool dock_lockout = false; // source-latched WROOM contact, never charging proof
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
    CosmeticMood TakeCosmeticMoodCue();

private:
    Camera* camera_;
    AudioCodec* audio_codec_ = nullptr;  // Sense codec only, no second audio owner
    httpd_handle_t server_ = nullptr;
    std::mutex uart_mutex_;
    UrgentStopGate urgent_stop_gate_{};
    std::atomic<bool> body_read_busy_{false};
    bool uart_ready_ = false;
    bool enabled_ = false;
    std::atomic<bool> camera_busy_{false};
    TimedPersonCue person_cue_{};
    CosmeticMoodCue cosmetic_mood_{};
    std::uint32_t camera_sequence_ = 0; // camera_busy ensures one producer
    std::uint32_t boot_nonce_ = 0; // changes across physical Sense reboots
    // Owned by the one Sense face task, not shared with HTTP handlers.
    RealTouchEdges head_touch_edges_{};
    RealTouchEdges body_cap_edges_{};
    static void BodyReadTask(void* context);
    static void CameraTask(void* context);
    static void CameraStreamTask(void* context);
#if defined(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3) && defined(CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED)
    static void BenchPcmTask(void* context);
#endif
    Reply Transact(const std::string& command, bool operator_control);
    bool Authorize(httpd_req_t* req);
    esp_err_t Handle(httpd_req_t* req);
    esp_err_t Json(httpd_req_t* req, int status, const std::string& body);
    static esp_err_t Dispatch(httpd_req_t* req);
    void AddTools();
};
}  // namespace desk_robot
