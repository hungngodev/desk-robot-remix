"""Regression for the Sense OLED's bounded cosmetic I/O path."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

HEAD = Path(__file__).resolve().parents[1]


def test_sense_oled_transfer_timeout_and_camera_bus_isolation():
    source = (HEAD / "sense/desk_robot_sense.cc").read_text()
    pins = (HEAD / "sense/config.h").read_text()
    init = source.split("void InitializeDisplay() {", 1)[1].split(
        "void InitializeCamera() {", 1
    )[0]
    assert "io_config.scl_speed_hz = 400000;" in init
    match = re.search(r"io_config\.transaction_timeout_ms\s*=\s*(\d+)\s*;", init)
    assert match is not None
    # 1024 payload bytes alone take 23.04 ms at 400 kHz (including ACKs).
    assert 24 <= int(match[1]) <= 50
    assert init.index(match[0]) < init.index("esp_lcd_new_panel_io_i2c(")
    assert "bus_config.i2c_port = DISPLAY_I2C_PORT;" in init
    for declaration in (
        "DISPLAY_SDA_PIN GPIO_NUM_5",
        "DISPLAY_SCL_PIN GPIO_NUM_6",
        "DISPLAY_I2C_PORT I2C_NUM_1",
        "CAMERA_SCCB_I2C_PORT I2C_NUM_0",
    ):
        assert f"#define {declaration}" in pins


def test_sense_face_render_guard_drops_contended_frame(tmp_path):
    source = (HEAD / "sense/desk_robot_sense.cc").read_text()
    guard = source.split("class FaceRenderGuard {", 1)[1].split(
        "class DeskRobotSenseBoard", 1
    )[0]
    face = source.split("static void FaceTask(void* context)", 1)[1].split(
        "bool ApplyFacePanelMode(", 1
    )[0]
    assert "FaceRenderGuard render_lock;" in face
    assert "if (!render_lock) {" in face
    assert face.index("if (!render_lock)") < face.index("->SetLocalStatus(local_status)")
    compiler = shutil.which("g++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("Native C++ compiler unavailable")
    native = tmp_path / "guard.cpp"
    native.write_text(
        '#include <cassert>\n'
        'static bool available = false;\n'
        'static int unlocks = 0;\n'
        'bool lvgl_port_lock(unsigned timeout) {\n'
        '    assert(timeout == 1); return available;\n'
        '}\n'
        'void lvgl_port_unlock() { ++unlocks; }\n'
        'class FaceRenderGuard {' + guard + '\n'
        'int main() {\n'
        '    { FaceRenderGuard denied; assert(!denied); }\n'
        '    assert(unlocks == 0);\n'
        '    available = true;\n'
        '    { FaceRenderGuard held; assert(held); }\n'
        '    assert(unlocks == 1);\n'
        '}\n'
    )
    binary = tmp_path / "guard"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(native),
         "-o", str(binary)],
        check=True,
        timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=5)
