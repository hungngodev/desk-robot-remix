from __future__ import annotations

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
        args += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
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
    assert "LineReceiver head_receiver;" in body
    assert "process_input(head_uart, head_receiver, head_replies, false);" in body
    assert "process_input(Serial, usb_receiver, usb_replies, true);" in body
