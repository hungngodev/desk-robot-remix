"""Exercise the exact firmware presence policy without an ESP-IDF or Mac process."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]


def test_offline_presence_status_priority(tmp_path):
    compiler = shutil.which("g++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "presence.cc"
    source.write_text(r'''
#include "face_presence.hpp"
#include <cassert>
#include <initializer_list>
using namespace desk_robot;

int main() {
    // Five minutes plus one tick, with no Mac or voice channel activity.
    for (unsigned elapsed = 0; elapsed <= 300100; elapsed += 100) {
        assert(SelectFaceStatus(false, false, false, true) == FaceStatus::kVoiceLinkLost);
        assert(!FaceStatusBlocksExpression(FaceStatus::kVoiceLinkLost));
        assert(SelectFaceStatus(false, false, false, false) == FaceStatus::kNormal);
    }
    for (bool offline : {false, true}) {
        for (bool privacy : {false, true}) {
            assert(SelectFaceStatus(true, false, privacy, offline) == FaceStatus::kBodyFault);
            assert(SelectFaceStatus(true, true, privacy, offline) == FaceStatus::kDockLock);
        }
        assert(SelectFaceStatus(false, false, true, offline) == FaceStatus::kMicPrivacy);
    }
    assert(FaceStatusBlocksExpression(FaceStatus::kBodyFault));
    assert(FaceStatusBlocksExpression(FaceStatus::kDockLock));
    assert(FaceStatusBlocksExpression(FaceStatus::kMicPrivacy));
    assert(FaceStatusBlocksExpression(FaceStatus::kFaceUnavailable));
    assert(!FaceStatusBlocksExpression(FaceStatus::kNormal));
}
''')
    binary = tmp_path / "presence"
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all", *pie_flags,
        "-I", str(HEAD / "overlay"), str(source), "-o", str(binary),
    ], check=True, capture_output=True, text=True, timeout=60)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=30)
