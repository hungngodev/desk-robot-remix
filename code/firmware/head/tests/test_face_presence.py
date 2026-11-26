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
    // All sixteen input combinations, including a stray dock bit without fault.
    for (bool fault : {false, true}) {
        for (bool dock : {false, true}) {
            for (bool privacy : {false, true}) {
                for (bool offline : {false, true}) {
                    const auto expected = fault ?
                        (dock ? FaceStatus::kDockLock : FaceStatus::kBodyFault) :
                        privacy ? FaceStatus::kMicPrivacy :
                        offline ? FaceStatus::kVoiceLinkLost : FaceStatus::kNormal;
                    const auto actual = SelectFaceStatus(fault, dock, privacy, offline);
                    assert(actual == expected);
                    assert(FaceStatusBlocksExpression(actual) == (fault || privacy));
                }
            }
        }
    }
    // Clearing each higher priority input reveals the remaining live status.
    assert(SelectFaceStatus(true, true, true, true) == FaceStatus::kDockLock);
    assert(SelectFaceStatus(true, false, true, true) == FaceStatus::kBodyFault);
    assert(SelectFaceStatus(false, false, true, true) == FaceStatus::kMicPrivacy);
    assert(SelectFaceStatus(false, false, false, true) == FaceStatus::kVoiceLinkLost);
    assert(SelectFaceStatus(false, false, false, false) == FaceStatus::kNormal);
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
