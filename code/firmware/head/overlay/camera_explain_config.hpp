#pragma once

#include <mutex>
#include <string>
#include <utility>

namespace desk_robot {
struct CameraExplainTarget {
    std::string url;
    std::string token;
};

// MCP initialization can update credentials while a camera task is active.
// Publish URL and bearer token together, without holding the lock during HTTP.
class CameraExplainConfig {
public:
    void Set(std::string url, std::string token) {
        std::lock_guard<std::mutex> lock(mutex_);
        target_ = {std::move(url), std::move(token)};
    }

    CameraExplainTarget Snapshot() {
        std::lock_guard<std::mutex> lock(mutex_);
        return target_;
    }

private:
    std::mutex mutex_;
    CameraExplainTarget target_;
};
}  // namespace desk_robot
