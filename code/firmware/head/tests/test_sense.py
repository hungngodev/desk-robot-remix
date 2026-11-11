from __future__ import annotations

import importlib.util
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
UPSTREAM = ROOT / 'upstream/xiaozhi-esp32'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


overlay = load_module('sense_overlay', HEAD / 'install_overlay.py')
private = load_module('sense_private', HEAD / 'private_config.py')


@unittest.skipUnless(UPSTREAM.is_dir(), 'Pinned upstream fixture unavailable')
class SenseOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        names = ['main/Kconfig.projbuild', 'main/CMakeLists.txt', 'main/mcp_server.cc',
                 'main/application.cc']
        names += [f'main/boards/common/{name}' for name in (
            'camera.h', 'esp_video.h', 'esp_video.cc', 'esp32_camera.h', 'esp32_camera.cc')]
        names += [p.relative_to(UPSTREAM).as_posix()
                  for p in (UPSTREAM / 'main/boards/m5stack/core-s3').iterdir() if p.is_file()]
        self.original = {}
        for name in names:
            content = (UPSTREAM / name).read_bytes()
            self.original[name] = content
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.git = patch.object(overlay.subprocess, 'check_output', side_effect=(
            lambda args, **kwargs: overlay.PIN if 'rev-parse' in args else ''))
        self.git.start()

    def tearDown(self):
        self.git.stop()
        self.temp.cleanup()

    def test_sense_camera_pdm_pin_budget_and_eight_mb_layout(self):
        overlay.apply(self.root, 'sense')
        board = self.root / overlay.BOARDS['sense']
        config = json.loads((board / 'config.json').read_text())
        self.assertEqual(config['type'], 'desk-robot-sense-s3')
        options = config['builds'][0]['sdkconfig_append']
        self.assertIn('CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y', options)
        self.assertIn('CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions/v2/8m.csv"', options)
        self.assertIn('CONFIG_SPIRAM_MODE_OCT=y', options)
        self.assertIn('CONFIG_SCCB_HARDWARE_I2C_PORT0=y', options)
        header = (board / 'config.h').read_text()
        pins = {key: int(value) for key, value in re.findall(
            r'#define (\w+) GPIO_NUM_(\d+)\b', header)}
        self.assertEqual(len(pins), len(set(pins.values())), 'Peripheral GPIO collision')
        self.assertEqual([pins[f'CAMERA_PIN_D{i}'] for i in range(8)],
                         [15, 17, 18, 16, 14, 12, 11, 48])
        expected = {'CAMERA_PIN_XCLK': 10, 'CAMERA_PIN_PCLK': 13,
                    'CAMERA_PIN_VSYNC': 38, 'CAMERA_PIN_HREF': 47,
                    'CAMERA_PIN_SIOD': 40, 'CAMERA_PIN_SIOC': 39,
                    'AUDIO_PDM_MIC_GPIO_SCK': 42, 'AUDIO_PDM_MIC_GPIO_DIN': 41,
                    'DISPLAY_SDA_PIN': 5, 'DISPLAY_SCL_PIN': 6,
                    'ROBOT_UART_TX': 2, 'ROBOT_UART_RX': 1,
                    'AUDIO_I2S_SPK_GPIO_BCLK': 4, 'AUDIO_I2S_SPK_GPIO_LRCK': 7,
                    'AUDIO_I2S_SPK_GPIO_DOUT': 8, 'SD_CARD_CS_GPIO': 21}
        for key, value in expected.items():
            self.assertEqual(pins[key], value)
        self.assertFalse(set(pins.values()) & {3, 19, 20, 26, 27, 28, 29, 30, 31,
                                              32, 33, 34, 35, 36, 37, 43, 44})
        source = (board / 'desk_robot_sense.cc').read_text()
        self.assertIn('SenseReferenceCodec audio_codec', source)
        kconfig = (self.root / 'main/Kconfig.projbuild').read_text()
        self.assertIn('config DESK_ROBOT_AEC_DELAY_MS', kconfig)
        self.assertIn('range 0 250', kconfig)
        self.assertIn('CONFIG_DESK_ROBOT_AEC_DELAY_MS', (board / 'sense_reference_codec.h').read_text())
        self.assertIn('#include "stackchan_behavior.hpp"', source)
        self.assertIn('HsmBehavior face_behavior_', source)
        self.assertIn('body_bridge_->PollInteraction()', source)
        self.assertIn('Event(EventType::kTouched)', source)
        self.assertIn('body_fault_active_', source)
        self.assertIn('bool last_rendered_fault = false;', source)
        self.assertIn('board->body_fault_active_ = true;', source)
        self.assertIn('board->body_fault_active_ ? "sad" : "neutral"', source)
        self.assertIn('last_was_idle = idle;', source)
        self.assertIn('board->body_fault_active_ ? "sad" : "neutral"', source)
        bridge = (board / 'robot_bridge.cc').read_text()
        self.assertIn('BodyInteraction Bridge::PollInteraction()', bridge)
        self.assertIn('Transact("status", false)', bridge)
        self.assertIn('head_touch_edges_.Observe(current)', bridge)
        self.assertIn('body_cap_edges_.Observe(', bridge)
        self.assertIn('body_cap_edges_.Reset()', bridge)
        self.assertIn('device_state == kDeviceStateIdle', source)
        self.assertIn('board->display_->SetEmotion(MoodName(action.mood))', source)
        self.assertIn('Stackchan', (board / 'stackchan_behavior.hpp').read_text())
        self.assertIn('MIT License', (board / 'stackchan_behavior.hpp').read_text())
        self.assertIn('NoAudioCodecSimplexPdm::Read', (board / 'sense_reference_codec.cc').read_text())
        self.assertNotIn('NoAudioCodecSimplex audio_codec', source)
        self.assertIn('esp_lcd_new_panel_ssd1306', source)
        self.assertIn('#include <esp_lcd_panel_vendor.h>', source)
        self.assertIn('gpio_set_level(SD_CARD_CS_GPIO, 1)', source)
        self.assertIn('new Esp32Camera(config)', source)
        self.assertEqual(source.count('DECLARE_BOARD('), 1)
        cmake = (self.root / 'main/CMakeLists.txt').read_text()
        self.assertIn('CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3', cmake)
        self.assertNotIn('CONFIG_BOARD_TYPE_DESK_ROBOT_MODULAR_S3', cmake)
        self.assertFalse((self.root / overlay.BOARDS['cores3']).exists())
        self.assertFalse((self.root / overlay.BOARDS['modular']).exists())
        self.assertIn('uart_set_pin(kUart, 2, 1,', (board / 'robot_bridge.cc').read_text())
        self.assertEqual((self.root / 'main/boards/common/esp32_camera.cc').read_text()
                         .count('camera_lock(AccessMutex())'), 6)

    def test_sense_reinstall_drift_and_exact_restore(self):
        overlay.apply(self.root, 'sense')
        overlay.apply(self.root, 'sense')
        with self.assertRaisesRegex(ValueError, 'different board'):
            overlay.apply(self.root, 'modular')
        target = self.root / overlay.BOARDS['sense'] / 'config.h'
        original = target.read_bytes()
        target.write_bytes(original + b'\n// local modification\n')
        with self.assertRaisesRegex(ValueError, 'drift'):
            overlay.apply(self.root, 'sense')
        with self.assertRaisesRegex(ValueError, 'changed'):
            overlay.remove(self.root)
        target.write_bytes(original)
        overlay.remove(self.root)
        self.assertFalse((self.root / overlay.BOARDS['sense']).exists())
        for name, value in self.original.items():
            self.assertEqual((self.root / name).read_bytes(), value)


class SenseSelectionTests(unittest.TestCase):
    def test_vendor_stackchan_behavior_compiles_without_motor_framework(self):
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler, "Native C++20 compiler required")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = root / "behavior_test.cc"
            exe = root / "behavior_test"
            code.write_text(
                '#include "stackchan_behavior.hpp"\n'
                'using namespace stackchan::behavior;\n'
                'int main() {\n'
                ' HsmBehavior pet(1);\n'
                ' auto start = pet.update({0});\n'
                ' if (!start.set_mood || pet.state() != State::kIdle) return 1;\n'
                ' pet.pushEvent(Event(EventType::kTouched));\n'
                ' auto touched = pet.update({100});\n'
                ' if (pet.state() != State::kInteracting) return 2;\n'
                ' if (!touched.set_mood || touched.mood != Mood::kSmile) return 3;\n'
                ' if (touched.motion != Motion::kNod) return 4;\n'
                ' return 0;\n'
                '}\n'
            )
            subprocess.run(
                [compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                 "-I", str(HEAD / "overlay"), str(code), "-o", str(exe)],
                check=True,
            )
            subprocess.run([str(exe)], check=True)

    def test_owned_sensor_implementations_remain_single_and_fail_closed(self):
        # Source-level ownership checks supplement real native/ESP32 builds.
        body = ROOT / "firmware/body"
        tof = (body / "lib/TofBus/TofBus.cpp").read_text()
        imu = (body / "lib/BerryImu/BerryImu.cpp").read_text()
        self.assertIn("gyro_matches != 1 || aux_matches != 1", tof)
        self.assertIn("id == 0x73", tof)
        self.assertIn("BerryImu::identify", tof)
        self.assertIn("Unsupported320G", imu)
        self.assertIn("BerryModel::Mpu6050", imu)
        self.assertIn("0x75", tof)
        self.assertIn("mpu_matches != 1", tof)
        self.assertIn("read_register(0x0031, &ready, 1)", tof)
        self.assertIn("(ready & 1U) != 0U", tof)  # active-low data ready
        self.assertIn("(result[0] & 0x1fU) == 9U", tof)  # Pololu ULD valid raw code
        self.assertIn("result[3] > 0", tof)  # reject zero SPAD quality
        self.assertIn("!write_byte(0x0086, 0x01)", tof)  # checked IRQ clear

    def test_sense_build_uses_separate_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'scripts/build_head.sh'
            script.parent.mkdir()
            shutil.copy(ROOT / 'scripts/build_head.sh', script)
            lock = root / 'firmware/head/dependencies.lock'
            lock.parent.mkdir(parents=True)
            shutil.copy(HEAD / 'dependencies.lock', lock)
            build = root / 'firmware/head/build/xiaozhi-sense/scripts/build.py'
            build.parent.mkdir(parents=True)
            build.touch()
            python = root / '.tools/sdk-bootstrap/bin/python'
            python.parent.mkdir(parents=True)
            python.write_text(f'#!{sys.executable}\nimport json,os,sys\n'
                              'open(os.environ["TRACE_PATH"],"w").write(json.dumps(sys.argv[1:]))\n')
            python.chmod(0o755)
            export = root / '.tools/esp-idf/export.sh'
            export.parent.mkdir(parents=True)
            export.write_text(':\n')
            trace = root / 'args.json'
            subprocess.run(['bash', str(script), '--board', 'sense', '--private', '--skip-merge'],
                           env=dict(os.environ, TRACE_PATH=str(trace)), check=True)
            args = json.loads(trace.read_text())
            self.assertEqual(args[0], 'firmware/head/build/xiaozhi-sense/scripts/build.py')
            self.assertIn('desk-robot/desk-robot-sense-s3', args)
            self.assertIn('config.private.json', args)
            self.assertNotIn('disabled', args)

    def test_private_sense_settings_do_not_touch_other_board(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'fleet.toml'
            config.write_text('[[robots]]\nid="robot-05"\ntoken_env="SENSE_TEST_TOKEN"\n')
            board = root / 'firmware/head/build/xiaozhi-sense/main/boards/desk-robot/desk-robot-sense-s3'
            board.mkdir(parents=True)
            source = {'builds': [{'sdkconfig_append': ['CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y',
                       'CONFIG_DESK_ROBOT_ID="robot-01"', 'CONFIG_DESK_ROBOT_TOKEN=""']} ]}
            (board / 'config.json').write_text(json.dumps(source))
            args = ['private_config.py', '--board', 'sense', '--robot', 'robot-05',
                    '--server-ip', '192.168.1.5', '--config', str(config),
                    '--secrets', str(root / 'absent.env')]
            with patch.object(private, 'ROOT', root), patch.object(sys, 'argv', args), \
                    patch.dict(os.environ, SENSE_TEST_TOKEN='x' * 32):
                private.main()
            settings = json.loads((board / 'config.private.json').read_text())['builds'][0]['sdkconfig_append']
            self.assertIn('CONFIG_DESK_ROBOT_ID="robot-05"', settings)
            self.assertIn('CONFIG_DESK_ROBOT_AEC_DELAY_MS=90', settings)
            args.extend(['--aec-delay-ms', '115'])
            with patch.object(private, 'ROOT', root), patch.object(sys, 'argv', args), \
                    patch.dict(os.environ, SENSE_TEST_TOKEN='x' * 32):
                private.main()
            calibrated = json.loads((board / 'config.private.json').read_text())['builds'][0]['sdkconfig_append']
            self.assertIn('CONFIG_DESK_ROBOT_AEC_DELAY_MS=115', calibrated)
            self.assertNotIn('CONFIG_DESK_ROBOT_AEC_DELAY_MS=90', calibrated)
            args[-1] = '251'
            with patch.object(private, 'ROOT', root), patch.object(sys, 'argv', args), \
                    patch.dict(os.environ, SENSE_TEST_TOKEN='x' * 32), \
                    self.assertRaises(SystemExit):
                private.main()
            self.assertIn('CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y', settings)
            self.assertEqual((board / 'config.private.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((board / 'config.json').read_text()), source)
            self.assertFalse((root / 'firmware/head/build/xiaozhi-modular').exists())
