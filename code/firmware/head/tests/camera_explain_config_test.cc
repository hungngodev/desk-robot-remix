#include "camera_explain_config.hpp"

#include <atomic>
#include <cassert>
#include <string>
#include <thread>

int main() {
    desk_robot::CameraExplainConfig config;
    const auto initial = config.Snapshot();
    assert(initial.url.empty() && initial.token.empty());
    config.Set("https://camera-one", "one");
    const auto old = config.Snapshot();
    config.Set("https://camera-two", "two");
    assert(old.url == "https://camera-one" && old.token == "one");
    config.Set("", "");
    const auto cleared = config.Snapshot();
    assert(cleared.url.empty() && cleared.token.empty());

    std::atomic<bool> start{false};
    std::thread writer([&] {
        while (!start.load()) std::this_thread::yield();
        for (int n = 0; n < 10000; ++n) {
            const auto token = std::to_string(n);
            config.Set("https://camera/" + token, token);
        }
    });
    std::thread reader([&] {
        start.store(true);
        for (int n = 0; n < 10000; ++n) {
            const auto target = config.Snapshot();
            if (target.url.empty()) assert(target.token.empty());
            else assert(target.url == "https://camera/" + target.token);
        }
    });
    writer.join();
    reader.join();
    const auto final = config.Snapshot();
    assert(final.url == "https://camera/9999" && final.token == "9999");
}
