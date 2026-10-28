#pragma once
#include <mutex>
#include <string>
#include "esp_http_server.h"
#include "camera.h"
#include "robot_protocol.h"

namespace desk_robot {
struct Reply {
    int status;
    bool ok;
    std::string text;
};

class Bridge {
public:
    explicit Bridge(Camera* camera);
    void Start();

private:
    Camera* camera_;
    httpd_handle_t server_ = nullptr;
    std::mutex uart_mutex_;
    bool uart_ready_ = false;
    bool enabled_ = false;
    Reply Transact(const std::string& command, bool operator_control);
    bool Authorize(httpd_req_t* req);
    esp_err_t Handle(httpd_req_t* req);
    esp_err_t Json(httpd_req_t* req, int status, const std::string& body);
    static esp_err_t Dispatch(httpd_req_t* req);
    void AddTools();
};
}  // namespace desk_robot
