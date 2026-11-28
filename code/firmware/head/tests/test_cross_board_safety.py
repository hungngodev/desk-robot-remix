from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

HEAD = Path(__file__).resolve().parents[1]
BODY = HEAD.parent / "body"


def test_head_parser_and_wroom_leases(tmp_path: Path) -> None:
    """Compile the actual head parser and body state machine in one process."""
    compiler = shutil.which("c++")
    assert compiler is not None, "A native C++17 compiler is required"
    binary = tmp_path / "cross_board_safety"
    args = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror"]
    if sys.platform.startswith("linux"):
        # UBSan is recoverable by default; a printed runtime error must fail pytest.
        args += [
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
            "-fno-omit-frame-pointer", "-no-pie",
        ]
    args += ["-I", str(HEAD / "overlay")]
    for directory in (
        "BodyControl", "CliffGuard", "BerryImu", "PulsePad", "AccessorySensors", "TerminalIr"
    ):
        args += ["-I", str(BODY / "lib" / directory)]
    args += [
        str(HEAD / "tests/cross_board_safety_test.cc"),
        str(BODY / "lib/BodyControl/BodyControl.cpp"),
        str(BODY / "lib/CliffGuard/CliffGuard.cpp"),
        str(BODY / "lib/BerryImu/BerryImu.cpp"),
        "-o",
        str(binary),
    ]
    subprocess.run(args, check=True, timeout=90)
    subprocess.run([str(binary)], check=True, timeout=30)


def test_telemetry_and_reconnect_never_issue_control() -> None:
    """Tie the native protocol exercise to the real production callers."""
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    status = bridge.split("BodyInteraction Bridge::PollInteraction()", 1)[1].split(
        "bool Bridge::Authorize", 1
    )[0]
    assert status.count("Transact(") == 1
    assert 'Transact("status", false)' in status
    reads = bridge.split("void Bridge::BodyReadTask", 1)[1].split(
        "void Bridge::CameraTask", 1
    )[0]
    assert reads.count("Transact(") == 1
    assert 'pose ? "pose" : optics ? "optics" : ir ? "ir" : aux ? "aux" : "status", false' in reads
    camera = bridge.split("void Bridge::CameraTask", 1)[1].split("esp_err_t Bridge::Handle", 1)[0]
    assert "Transact(" not in camera and "uart_write_bytes(" not in camera
    transact = bridge.split("Reply Bridge::Transact", 1)[1].split(
        "BodyInteraction Bridge::PollInteraction", 1
    )[0]
    assert transact.index("ControlQueueFresh(") < transact.index("uart_write_bytes(")
    sense = (HEAD / "sense/desk_robot_sense.cc").read_text()
    reconnect = sense.split("const bool wifi_connected", 1)[1].split(
        "const bool speaking", 1
    )[0]
    assert "app.ToggleChatState()" in reconnect
    assert "body_bridge_" not in reconnect and "Transact(" not in reconnect
    body = (BODY / "src/main.cpp").read_text()
    assert "LineReceiver usb_receiver(true);" in body
    assert "LineReceiver head_receiver(false, true);" in body
    assert "process_input(head_uart, head_receiver, head_replies, false);" in body
    assert "process_input(Serial, usb_receiver, usb_replies, true);" in body


def test_all_body_fault_reasons_fail_closed(tmp_path: Path) -> None:
    """Exercise every WROOM status reason through the real head classifiers."""
    body = (BODY / "lib/BodyControl/BodyControl.cpp").read_text()
    reason_expression = body.split("const char* local_fault =", 1)[1].split(
        "const bool complete =", 1
    )[0]
    cliff = (BODY / "lib/CliffGuard/CliffGuard.cpp").read_text()
    cliff_names = cliff.split("const char* CliffGuard::fault_name(", 1)[1]
    reasons = set(re.findall(r'"([a-z][a-z0-9_]*)"', reason_expression + cliff_names))
    assert {"none", "not_required", "command_timeout_latched", "dock_power_connected",
            "bus_failure", "unknown"} <= reasons
    # Unrecognized or malformed reasons must also remain unhealthy.
    reasons.update({"", "NONE", "future_fault", "dock_power_connected "})
    literals = ", ".join(f'"{reason}"' for reason in sorted(reasons))
    # The board-local freshness struct has no ESP-IDF dependencies. Compile
    # its actual definition, not a host approximation of the disconnect rule.
    sense = (HEAD / "sense/desk_robot_sense.cc").read_text()
    face_status = "struct BodyFaceStatus {" + sense.split(
        "struct BodyFaceStatus {", 1
    )[1].split("class BodyFaceState", 1)[0]
    source = tmp_path / "fault_matrix.cc"
    source.write_text(
        '#include <cassert>\n#include "robot_protocol.h"\n'
        + face_status
        + """
int main() {
    using namespace desk_robot;
    const std::string_view reasons[] = {"""
        + literals
        + """};
    for (const auto reason : reasons) {
        for (const bool required : {false, true}) {
            for (const bool ready : {false, true}) {
                for (const bool armed : {false, true}) {
                    const bool healthy = required && ready && reason == "none";
                    const bool dock = required && !ready && !armed &&
                                      reason == "dock_power_connected";
                    assert(BodySafetyUnhealthy(required, ready, reason) == !healthy);
                    assert(BodyDockLockoutObserved(required, ready, armed, reason) == dock);
                }
            }
        }
    }
    // A cleared observation and an expired formerly healthy observation
    // cannot be presented as fresh after a disconnect or clock regression.
    const BodyFaceStatus missing{};
    assert(!missing.Fresh(1000) && missing.fault && !missing.dock_lockout);
    const BodyFaceStatus healthy{true, false, false, 1000};
    const BodyFaceStatus docked{true, true, true, 1000};
    for (const auto& status : {healthy, docked}) {
        assert(!status.Fresh(999));
        assert(status.Fresh(1000));
        assert(status.Fresh(2200));
        assert(!status.Fresh(2201));
    }
}
"""
    )
    compiler = shutil.which("c++")
    assert compiler is not None, "A native C++17 compiler is required"
    binary = tmp_path / "fault_matrix"
    args = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror"]
    if sys.platform.startswith("linux"):
        args += [
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
            "-fno-omit-frame-pointer", "-no-pie",
        ]
    args += ["-I", str(HEAD / "overlay"), str(source), "-o", str(binary)]
    subprocess.run(args, check=True, timeout=90)
    subprocess.run([str(binary)], check=True, timeout=30)
