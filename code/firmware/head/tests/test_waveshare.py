from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HEAD = Path(__file__).resolve().parents[1]
ROOT = HEAD.parents[1]
UPSTREAM = ROOT / "upstream/xiaozhi-esp32"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


overlay = load_module("waveshare_overlay", HEAD / "install_overlay.py")
private = load_module("waveshare_private", HEAD / "private_config.py")


@unittest.skipUnless(UPSTREAM.is_dir(), "Pinned upstream fixture unavailable")
class WaveshareOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        names = ["main/Kconfig.projbuild", "main/CMakeLists.txt", "main/mcp_server.cc"]
        names += [
            f"main/boards/common/{name}"
            for name in (
                "camera.h",
                "esp_video.h",
                "esp_video.cc",
                "esp32_camera.h",
                "esp32_camera.cc",
            )
        ]
        names += [
            p.relative_to(UPSTREAM).as_posix()
            for p in (UPSTREAM / "main/boards/m5stack/core-s3").iterdir()
            if p.is_file()
        ]
        self.original = {}
        for name in names:
            content = (UPSTREAM / name).read_bytes()
            self.original[name] = content
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.git = patch.object(
            overlay.subprocess,
            "check_output",
            side_effect=(lambda args, **kwargs: overlay.PIN if "rev-parse" in args else ""),
        )
        self.git.start()

    def tearDown(self):
        self.git.stop()
        self.temp.cleanup()

    def test_physical_reference_and_separate_oled_camera_buses(self):
        overlay.apply(self.root, "waveshare")
        board = self.root / overlay.BOARDS["waveshare"]
        options = json.loads((board / "config.json").read_text())["builds"][0]["sdkconfig_append"]
        for expected in [
            "CONFIG_USE_AUDIO_PROCESSOR=y",
            "CONFIG_USE_DEVICE_AEC=y",
            "CONFIG_USE_SERVER_AEC=n",
            "CONFIG_SCCB_HARDWARE_I2C_PORT1=y",
            "CONFIG_SCCB_HARDWARE_I2C_PORT0=n",
            "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y",
            "CONFIG_ESP_CONSOLE_SECONDARY_NONE=y",
            "CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y",
            'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions/v2/16m.csv"',
        ]:
            self.assertIn(expected, options)
        header = (board / "config.h").read_text()
        pins = {
            key: int(value)
            for key, value in re.findall(r"#define (\w+)\s+GPIO_NUM_(\d+)\b", header)
        }
        self.assertEqual(len(pins), len(set(pins.values())), "Peripheral GPIO collision")
        self.assertFalse(set(pins.values()) & {3, 19, 20, *range(26, 38)})
        expected = {
            "CONTROL_I2C_SDA_PIN": 8,
            "CONTROL_I2C_SCL_PIN": 7,
            "DISPLAY_SDA_PIN": 1,
            "DISPLAY_SCL_PIN": 2,
            "AUDIO_I2S_GPIO_MCLK": 10,
            "AUDIO_I2S_GPIO_BCLK": 11,
            "AUDIO_I2S_GPIO_WS": 12,
            "AUDIO_I2S_GPIO_DIN": 13,
            "AUDIO_I2S_GPIO_DOUT": 14,
            "ROBOT_UART_TX": 43,
            "ROBOT_UART_RX": 44,
        }
        for key, value in expected.items():
            self.assertEqual(pins[key], value)
        self.assertIn("#define AUDIO_INPUT_REFERENCE true", header)
        self.assertIn("#define DISPLAY_I2C_PORT I2C_NUM_0", header)
        self.assertIn("#define CONTROL_I2C_PORT I2C_NUM_1", header)
        self.assertIn("#define CAMERA_SCCB_I2C_PORT CONTROL_I2C_PORT", header)
        source = (board / "desk_robot_waveshare.cc").read_text()
        self.assertIn("BoxAudioCodec audio_codec", source)
        self.assertNotIn("NoAudioCodec", source)
        self.assertIn("AUDIO_INPUT_REFERENCE", source)
        self.assertIn("custom_io_expander_new_i2c_ch32v003", source)
        self.assertIn("IO_EXPANDER_PIN_NUM_4 | IO_EXPANDER_PIN_NUM_6", source)
        self.assertIn("esp_lcd_new_panel_ssd1306", source)
        self.assertNotIn("spi_bus_initialize", source)
        self.assertEqual(source.count("DECLARE_BOARD("), 1)
        self.assertIn("uart_set_pin(kUart, 43, 44,", (board / "robot_bridge.cc").read_text())
        kconfig = (self.root / "main/Kconfig.projbuild").read_text()
        aec = kconfig.split("config USE_DEVICE_AEC", 1)[1].split("config USE_SERVER_AEC", 1)[0]
        self.assertIn("BOARD_TYPE_DESK_ROBOT_WAVESHARE_S3_CAM", aec)
        self.assertNotIn("BOARD_TYPE_DESK_ROBOT_SENSE_S3", aec)
        self.assertNotIn("BOARD_TYPE_DESK_ROBOT_MODULAR_S3", aec)
        for other in ("sense", "modular", "cores3"):
            self.assertFalse((self.root / overlay.BOARDS[other]).exists())

    def test_display_initialization_precedes_ui_and_network_consumers(self):
        """Check installed board startup against the pinned display/application."""
        overlay.apply(self.root, "waveshare")
        board = self.root / overlay.BOARDS["waveshare"]
        source = (board / "desk_robot_waveshare.cc").read_text()
        display = source.split("void InitializeDisplay()", 1)[1].split(
            "void InitializeCamera()", 1
        )[0]
        stages = (
            "i2c_new_master_bus(&config, &display_bus_)",
            "esp_lcd_new_panel_io_i2c(display_bus_",
            "esp_lcd_new_panel_ssd1306(panel_io,",
            "esp_lcd_panel_reset(panel)",
            "esp_lcd_panel_init(panel)",
            "esp_lcd_panel_invert_color(panel, false)",
            "esp_lcd_panel_disp_on_off(panel, true)",
            "display_ = new OledDisplay(",
        )
        positions = [display.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        for stage in stages[:-1]:
            self.assertIn("ESP_ERROR_CHECK(" + stage, display)
        constructor = source.split("DeskRobotWaveshareBoard() :", 1)[1].split(
            "void StartNetwork() override", 1
        )[0]
        startup = (
            "InitializeControlBus();",
            "InitializeExpander();",
            "InitializeDisplay();",
            "InitializeCamera();",
            "boot_button_.OnClick(",
        )
        positions = [constructor.index(stage) for stage in startup]
        self.assertEqual(positions, sorted(positions))
        app = (UPSTREAM / "main/application.cc").read_text()
        initialize = app.split("void Application::Initialize()", 1)[1].split(
            "board.StartNetwork();", 1
        )[0]
        self.assertLess(
            initialize.index("display->SetupUI();"),
            initialize.index("board.SetNetworkEventCallback("),
        )
        oled = (UPSTREAM / "main/display/oled_display.cc").read_text()
        self.assertLess(
            oled.index("display_ = lvgl_port_add_disp("),
            oled.index("void OledDisplay::SetupUI()"),
        )

    def test_reversible_aec_whitelist_and_drift_protection(self):
        overlay.apply(self.root, "waveshare")
        overlay.apply(self.root, "waveshare")
        with self.assertRaisesRegex(ValueError, "different board"):
            overlay.apply(self.root, "sense")
        kconfig = self.root / "main/Kconfig.projbuild"
        valid = kconfig.read_bytes()
        kconfig.write_bytes(valid + b"\n# local AEC change\n")
        with self.assertRaisesRegex(ValueError, "drift"):
            overlay.apply(self.root, "waveshare")
        with self.assertRaisesRegex(ValueError, "changed"):
            overlay.remove(self.root)
        kconfig.write_bytes(valid)
        overlay.remove(self.root)
        self.assertFalse((self.root / overlay.BOARDS["waveshare"]).exists())
        for name, data in self.original.items():
            self.assertEqual((self.root / name).read_bytes(), data)

    def test_aec_anchor_failure_does_not_partially_install(self):
        kconfig = self.root / "main/Kconfig.projbuild"
        kconfig.write_text(
            kconfig.read_text().replace(
                "depends on USE_AUDIO_PROCESSOR && (BOARD_TYPE_ESP32_S3_BOX_3",
                "depends on USE_AUDIO_PROCESSOR && (CHANGED_BOARD",
            )
        )
        with self.assertRaisesRegex(ValueError, "anchor"):
            overlay.apply(self.root, "waveshare")
        self.assertFalse((self.root / overlay.MARKER).exists())
        self.assertFalse((self.root / overlay.BOARDS["waveshare"]).exists())


class WaveshareSelectionTests(unittest.TestCase):
    def test_generic_voice_build_and_private_build_use_distinct_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "scripts/build_head.sh"
            script.parent.mkdir()
            shutil.copy(ROOT / "scripts/build_head.sh", script)
            lock = root / "firmware/head/dependencies.lock"
            lock.parent.mkdir(parents=True)
            shutil.copy(HEAD / "dependencies.lock", lock)
            build = root / "firmware/head/build/xiaozhi-waveshare/scripts/build.py"
            build.parent.mkdir(parents=True)
            build.touch()
            python = root / ".tools/sdk-bootstrap/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text(
                f"#!{sys.executable}\nimport json,os,sys\n"
                'open(os.environ["TRACE_PATH"],"w").write(json.dumps(sys.argv[1:]))\n'
            )
            python.chmod(0o755)
            export = root / ".tools/esp-idf/export.sh"
            export.parent.mkdir(parents=True)
            export.write_text(":\n")
            trace = root / "args.json"
            for extra in ([], ["--private"]):
                subprocess.run(
                    ["bash", str(script), "--board", "waveshare", *extra, "--skip-merge"],
                    env=dict(os.environ, TRACE_PATH=str(trace)),
                    check=True,
                )
                args = json.loads(trace.read_text())
                self.assertEqual(args[0], "firmware/head/build/xiaozhi-waveshare/scripts/build.py")
                self.assertIn("desk-robot/desk-robot-waveshare-s3-cam", args)
                self.assertIn("hiesp", args)
                self.assertNotIn("disabled", args)
                self.assertEqual("config.private.json" in args, bool(extra))

    def test_private_identity_preserves_aec_and_does_not_print_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "fleet.toml"
            config.write_text('[[robots]]\nid="robot-04"\ntoken_env="WAVESHARE_TEST_TOKEN"\n')
            board = (
                root
                / "firmware/head/build/xiaozhi-waveshare/main/boards/desk-robot/desk-robot-waveshare-s3-cam"
            )
            board.mkdir(parents=True)
            source = {
                "builds": [
                    {
                        "sdkconfig_append": [
                            "CONFIG_USE_DEVICE_AEC=y",
                            'CONFIG_DESK_ROBOT_ID="robot-01"',
                            'CONFIG_DESK_ROBOT_TOKEN=""',
                        ]
                    }
                ]
            }
            (board / "config.json").write_text(json.dumps(source))
            args = [
                "private_config.py",
                "--board",
                "waveshare",
                "--robot",
                "robot-04",
                "--server-ip",
                "192.168.1.5",
                "--config",
                str(config),
                "--secrets",
                str(root / "absent.env"),
            ]
            output = io.StringIO()
            token = "private_test_token_" + "x" * 32
            with (
                patch.object(private, "ROOT", root),
                patch.object(sys, "argv", args),
                patch.dict(os.environ, WAVESHARE_TEST_TOKEN=token),
                contextlib.redirect_stdout(output),
            ):
                private.main()
            settings = json.loads((board / "config.private.json").read_text())["builds"][0][
                "sdkconfig_append"
            ]
            self.assertIn('CONFIG_DESK_ROBOT_ID="robot-04"', settings)
            self.assertIn("CONFIG_USE_DEVICE_AEC=y", settings)
            self.assertNotIn(token, output.getvalue())
            self.assertEqual((board / "config.private.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((board / "config.json").read_text()), source)
            self.assertFalse((root / "firmware/head/build/xiaozhi-sense").exists())

    def test_compile_guards_reject_aec_or_console_regression(self):
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "driver").mkdir()
            (root / "driver/gpio.h").write_text(
                "#pragma once\n"
                + "\n".join(f"#define GPIO_NUM_{n} {n}" for n in range(49))
                + "\n#define GPIO_NUM_NC -1\n"
            )
            (root / "driver/i2c_types.h").write_text("#define I2C_NUM_0 0\n#define I2C_NUM_1 1\n")
            source = HEAD / "waveshare/config.h"
            shutil.copy(source, root / "config.h")
            (root / "test.cc").write_text('#include "config.h"\nint main() {}\n')
            valid = [
                "CONFIG_USE_AUDIO_PROCESSOR",
                "CONFIG_USE_DEVICE_AEC",
                "CONFIG_SCCB_HARDWARE_I2C_PORT1",
                "CONFIG_SCCB_HARDWARE_I2C_DRIVER_NEW",
                "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG",
                "CONFIG_ESP_CONSOLE_SECONDARY_NONE",
            ]
            cases = [
                (None, valid),
                ("Device-side AEC", [x for x in valid if x != "CONFIG_USE_DEVICE_AEC"]),
                ("separate camera", [x for x in valid if x != "CONFIG_SCCB_HARDWARE_I2C_PORT1"]),
                (
                    "USB Serial/JTAG",
                    [x for x in valid if x != "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG"],
                ),
            ]
            for expected, options in cases:
                with self.subTest(expected=expected):
                    (root / "sdkconfig.h").write_text("\n".join(f"#define {x} 1" for x in options))
                    run = subprocess.run(
                        [
                            compiler,
                            "-std=c++17",
                            "-fsyntax-only",
                            "-I",
                            str(root),
                            str(root / "test.cc"),
                        ],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(run.returncode == 0, expected is None, run.stderr)
                    if expected:
                        self.assertIn(expected, run.stderr)
            (root / "sdkconfig.h").write_text("\n".join(f"#define {x} 1" for x in valid))
            (root / "config.h").write_text(
                source.read_text().replace(
                    "#define AUDIO_INPUT_REFERENCE true", "#define AUDIO_INPUT_REFERENCE false"
                )
            )
            run = subprocess.run(
                [compiler, "-std=c++17", "-fsyntax-only", "-I", str(root), str(root / "test.cc")],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("physical playback reference", run.stderr)
