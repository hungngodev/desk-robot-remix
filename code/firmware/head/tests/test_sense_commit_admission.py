"""Exercise the generated Sense digital receipt gate without the ESP-IDF SDK."""

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_playback_commit_is_serialized_with_reset(tmp_path):
    compiler = shutil.which("g++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("Native C++ compiler unavailable")
    overlay = Path(__file__).resolve().parents[1] / "install_overlay.py"
    blocks = [
        node.value
        for node in ast.walk(ast.parse(overlay.read_text()))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "bool desk_commit_current = false;" in node.value
    ]
    assert len(blocks) == 1
    start = "                desk_wrote = true;\n"
    end = "\n            }\n        }\n\n        if (desk_wrote)"
    gate = blocks[0].split(start, 1)[1].split(end, 1)[0]
    harness = tmp_path / "commit_gate.cc"
    binary = tmp_path / "commit_gate"
    harness.write_text(
        """
#include <atomic>
#include <cassert>
#include <cstdint>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

struct DeskPlaybackPrefix {
    static bool ExactMediaFrame(std::size_t n, int rate, int ms) {
        return n == static_cast<std::size_t>(rate * ms / 1000);
    }
    bool Accept(uint32_t, uint32_t, int, bool complete) { return complete; }
};
struct Codec { int output_sample_rate() { return 32000; } };
struct Task {
    uint32_t playback_id = 1, media_position_ms = 60;
    int desk_frame_duration_ms = 60;
    std::vector<int16_t> pcm = std::vector<int16_t>(1920);
};
int main() {
    std::mutex desk_output_admission_mutex_, audio_queue_mutex_;
    std::atomic<bool> service_stopped_{false};
    uint32_t playback_generation_ = 1;
    Task task;
    Codec codec;
    Codec* codec_ = &codec;
    DeskPlaybackPrefix desk_robot_prefix;
    int transmitted_frames = 1920;
    int calls = 0;
    struct { std::function<void(uint32_t, uint32_t)> on_playback_committed; } callbacks_;
    callbacks_.on_playback_committed = [&](uint32_t, uint32_t) {
        // ResetDecoder acquires this mutex before modifying the generation.
        // A separate thread probes ownership at the actual receipt callback.
        bool reset_can_enter = false;
        std::thread reset([&] {
            reset_can_enter = desk_output_admission_mutex_.try_lock();
            if (reset_can_enter) desk_output_admission_mutex_.unlock();
        });
        reset.join();
        assert(!reset_can_enter);
        ++calls;
    };
    auto commit = [&](uint32_t desk_popped_generation) {
"""
        + gate
        + """
    };
    commit(0);
    assert(calls == 0);
    commit(1);
    assert(calls == 1);
    ++playback_generation_;
    commit(1);
    assert(calls == 1);
    service_stopped_ = true;
    commit(2);
    assert(calls == 1);
}
""",
        encoding="utf-8",
    )
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
            "-fsanitize=address,undefined", *pie_flags, str(harness), "-o", str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, timeout=30, capture_output=True, text=True)
