"""Exercise the actual face admission statement against the production mailbox."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]


def test_latest_mood_survives_transient_render_contention(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("Native C++ compiler unavailable")
    face = (HEAD / "sense/desk_robot_sense.cc").read_text()
    statement = "const auto requested_mood =" + face.split(
        "const auto requested_mood =", 1
    )[1].split(";", 1)[0] + ";"
    source = tmp_path / "mood.cc"
    source.write_text(r'''
#include "robot_protocol.h"
#include <cassert>
using namespace desk_robot;
struct Bridge {
    CosmeticMoodCue mailbox;
    uint32_t now = 0;
    CosmeticMood TakeCosmeticMoodCue() { return mailbox.take(now); }
};
struct Board { Bridge* body_bridge_; void* display_; };
struct Guard {
    bool acquired;
    explicit operator bool() const { return acquired; }
};
static CosmeticMood Poll(Board* board, bool lock, bool priority_active,
                         bool face_available, bool voice_link_lost) {
    const Guard render_lock{lock};
    (void)render_lock; (void)priority_active;
    (void)face_available; (void)voice_link_lost;
''' + statement + r'''
    return requested_mood;
}
int main() {
    Bridge bridge;
    Board board{&bridge, &bridge};
    for (unsigned i = 0; i < 1000; ++i) {
        bridge.now = 0xfffffff0U + i * 16U;
        bridge.mailbox.offer(CosmeticMood::kHappy, bridge.now);
        assert(Poll(&board, false, false, true, false) == CosmeticMood::kNone);
        bridge.mailbox.offer(CosmeticMood::kThinking, bridge.now);
        ++bridge.now;
        assert(Poll(&board, false, false, true, false) == CosmeticMood::kNone);
        assert(Poll(&board, true, false, true, false) == CosmeticMood::kThinking);
        assert(Poll(&board, true, false, true, false) == CosmeticMood::kNone);
    }
    bridge.mailbox.offer(CosmeticMood::kHappy, bridge.now);
    assert(Poll(&board, false, false, true, false) == CosmeticMood::kNone);
    bridge.now += 1100;
    assert(Poll(&board, true, false, true, false) == CosmeticMood::kNone);
    for (int blocked = 0; blocked < 4; ++blocked) {
        bridge.mailbox.offer(CosmeticMood::kHappy, bridge.now);
        if (blocked == 3) board.display_ = nullptr;
        // Suppression drains even without the OLED lock. The caller must
        // never render a suppressed decision; it cannot replay on recovery.
        assert(Poll(&board, false, blocked == 0, blocked != 1, blocked == 2)
               == CosmeticMood::kHappy);
        board.display_ = &bridge;
        assert(Poll(&board, true, false, true, false) == CosmeticMood::kNone);
    }
}
''')
    binary = tmp_path / "mood"
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    env = dict(os.environ, UBSAN_OPTIONS="halt_on_error=1", ASAN_OPTIONS="halt_on_error=1")
    subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", *pie_flags,
            "-I", str(HEAD / "overlay"), str(source), "-o", str(binary),
        ],
        check=True, timeout=60, env=env,
    )
    subprocess.run([str(binary)], check=True, timeout=30, env=env)
    # The lock must be attempted before the production expression is evaluated.
    task = face.split("static void FaceTask(void* context)", 1)[1]
    assert task.index("FaceRenderGuard render_lock;") < task.index(statement)
