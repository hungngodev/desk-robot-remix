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
    auto current = config.Snapshot();
    assert(current.url == "https://camera-two" && current.token == "two");
    current.url = "https://local-copy";
    current.token.clear();
    const auto unchanged = config.Snapshot();
    assert(unchanged.url == "https://camera-two" && unchanged.token == "two");
    assert(old.url == "https://camera-one" && old.token == "one");
    config.Set("", "");
    const auto cleared = config.Snapshot();
    assert(cleared.url.empty() && cleared.token.empty());
    assert(unchanged.url == "https://camera-two" && unchanged.token == "two");

    std::atomic<bool> first_published{false};
    std::atomic<bool> first_observed{false};
    std::atomic<bool> finished{false};
    std::thread writer([&] {
        config.Set("https://camera/0", "0");
        first_published.store(true);
        while (!first_observed.load()) std::this_thread::yield();
        for (int n = 1; n < 10000; ++n) {
            const auto token = std::to_string(n);
            config.Set("https://camera/" + token, token);
        }
        finished.store(true);
    });
    std::thread reader([&] {
        // Force a real publication to be observed before allowing the writer
        // to race with subsequent snapshots. An all-empty read loop is not a pass.
        while (!first_published.load()) std::this_thread::yield();
        const auto first = config.Snapshot();
        assert(first.url == "https://camera/0" && first.token == "0");
        first_observed.store(true);
        unsigned reads = 0;
        do {
            const auto target = config.Snapshot();
            assert(!target.token.empty());
            assert(target.url == "https://camera/" + target.token);
            ++reads;
        } while (reads < 10000 || !finished.load());
        assert(first.url == "https://camera/0" && first.token == "0");
    });
    writer.join();
    reader.join();
    const auto final = config.Snapshot();
    assert(final.url == "https://camera/9999" && final.token == "9999");
}
