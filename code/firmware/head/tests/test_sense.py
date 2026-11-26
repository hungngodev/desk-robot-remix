from __future__ import annotations

import base64
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

import pytest

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
test_overlay = load_module('test_overlay', Path(__file__).with_name('test_overlay.py'))
native_cpp_env = test_overlay.native_cpp_env


@unittest.skipUnless(UPSTREAM.is_dir(), 'Pinned upstream fixture unavailable')
class SenseOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        names = ['main/Kconfig.projbuild', 'main/CMakeLists.txt', 'main/mcp_server.cc',
                 'main/application.cc', 'main/application.h',
                 'main/display/oled_display.h',
                 'main/audio/audio_codec.cc', 'main/audio/audio_codec.h',
                 'main/audio/audio_service.cc', 'main/audio/audio_service.h',
                 'main/audio/codecs/no_audio_codec.cc',
                 'main/protocols/protocol.cc', 'main/protocols/protocol.h',
                 'main/protocols/websocket_protocol.cc',
                 'main/protocols/websocket_protocol.h',
                 'scripts/p3_tools/p3_gui_player.py',
                 'scripts/release.py']
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

    def test_sense_application_header_overlay_has_real_fixture_and_reversible_privacy_gate(self):
        """The real pinned header is needed for source patch and exact restore."""
        path = "main/application.h"
        self.assertIn(path, self.original)
        original = self.original[path]
        self.assertEqual((self.root / path).read_bytes(), original)
        overlay.apply(self.root, "sense")
        changed = (self.root / path).read_text()
        self.assertIn("SetSenseMicrophonePrivacyMuted", changed)
        self.assertIn("sense_microphone_privacy_muted_", changed)
        overlay.remove(self.root)
        self.assertEqual((self.root / path).read_bytes(), original)

    def test_sense_oled_subtitle_accessor_is_reversible(self):
        path = "main/display/oled_display.h"
        original = self.original[path]
        overlay.apply(self.root, "sense")
        changed = (self.root / path).read_text()
        self.assertIn("bool HasChatMessageLocked() const", changed)
        self.assertIn("!lv_obj_has_flag(content_right_, LV_OBJ_FLAG_HIDDEN)", changed)
        self.assertIn(r"lv_label_get_text(chat_message_label_)[0] != '\0'", changed)
        overlay.remove(self.root)
        self.assertEqual((self.root / path).read_bytes(), original)

    def test_pinned_xiaozhi_oled_status_and_emotion_are_independent(self):
        """Speaking/listening text must survive the cosmetic face update."""
        oled = (UPSTREAM / "main/display/oled_display.cc").read_text()
        lvgl = (UPSTREAM / "main/display/lvgl_display/lvgl_display.cc").read_text()
        emotion = oled.split("bool OledDisplay::SetEmotion(", 1)[1].split(
            "void OledDisplay::SetTheme(", 1
        )[0]
        status = lvgl.split("void LvglDisplay::SetStatus(", 1)[1].split(
            "void LvglDisplay::ShowNotification(", 1
        )[0]
        self.assertIn("DisplayLockGuard lock(this);", emotion)
        self.assertIn("lv_label_set_text(emotion_label_", emotion)
        self.assertNotIn("status_label_", emotion)
        self.assertIn("DisplayLockGuard lock(this);", status)
        self.assertIn("lv_label_set_text(status_label_, status);", status)
        self.assertNotIn("emotion_label_", status)

    def test_server_audio_failure_uses_real_xiaozhi_epoch_not_idle_poll(self):
        """Reconnect is triggered by transport loss, never arbitrary Idle."""
        overlay.apply(self.root, "sense")
        application = (self.root / "main/application.cc").read_text()
        header = (self.root / "main/application.h").read_text()
        board = (HEAD / "sense/desk_robot_sense.cc").read_text()
        face = board.split("static void FaceTask(void* context)", 1)[1].split(
            "void InitializeDisplay()", 1
        )[0]
        closed = application.split("protocol_->OnAudioChannelClosed(", 1)[1].split(
            "protocol_->OnIncomingJson(", 1
        )[0]
        opener = application.split(
            "void Application::ContinueOpenAudioChannel(", 1
        )[1].split("void Application::HandleStartListeningEvent()", 1)[0]
        assert "sense_audio_failure_epoch_.fetch_add(1" in closed
        assert "sense_audio_failure_epoch_.fetch_add(1" in opener
        assert "sense_microphone_privacy_muted_.load" in closed
        assert "sense_microphone_privacy_muted_.load" in opener
        assert "GetSenseAudioFailureEpoch() const" in header
        assert "GetSenseAudioLinkUnavailable() const" in header
        assert "sense_audio_link_unavailable_.store(true" in closed
        assert "sense_audio_link_unavailable_.store(true" in opener
        assert "sense_audio_link_unavailable_.store(false" in application
        assert "!wifi_connected || app.GetSenseAudioLinkUnavailable()" in face
        assert "std::atomic<uint32_t> sense_audio_failure_epoch_{0};" in header
        assert "const uint32_t failure_epoch = app.GetSenseAudioFailureEpoch();" in face
        assert "failure_epoch != board->last_audio_failure_epoch_seen_" in face
        assert "(!board->continuous_audio_started_ || failed_since_attempt) &&" in face
        assert "AudioListenRetryDue(uptime_ms, board->last_audio_listen_attempt_ms_)" in face
        assert "board->last_audio_failure_epoch_seen_ = failure_epoch;" in face
        assert "!board->audio_operator_touched_.load()" in face
        assert "device_state == kDeviceStateIdle" in face
        assert "app.ToggleChatState();" in face
        assert "app.StartListening();" not in face
        assert "app.StopListening();" not in face

    def test_failed_audio_open_restores_existing_wifi_power_policy(self):
        """Execute both actual overlaid open continuations with a failing transport."""
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("Native C++ compiler unavailable")
        overlay.apply(self.root, "sense")
        app = (self.root / "main/application.cc").read_text()
        normal = "void Application::ContinueOpenAudioChannel(" + app.split(
            "void Application::ContinueOpenAudioChannel(", 1
        )[1].split("void Application::HandleStartListeningEvent()", 1)[0]
        wake = "void Application::ContinueWakeWordInvoke(" + app.split(
            "void Application::ContinueWakeWordInvoke(", 1
        )[1].split("void Application::HandleStateChangedEvent()", 1)[0]
        code = self.root / "wifi_power_policy.cpp"
        binary = self.root / "wifi_power_policy"
        code.write_text(r"""
#include <atomic>
#include <cstdint>
#include <string>
#include <vector>
#define CONFIG_SEND_WAKE_WORD_DATA 0
#define ESP_LOGI(tag, format, argument) (void)(argument)
enum DeviceState { kDeviceStateIdle, kDeviceStateConnecting, kDeviceStateListening };
enum ListeningMode { kListeningModeRealtime };
enum class PowerSaveLevel { LOW_POWER, PERFORMANCE };
struct Board {
    std::vector<PowerSaveLevel> levels;
    static Board& GetInstance() { static Board board; return board; }
    void SetPowerSaveLevel(PowerSaveLevel level) { levels.push_back(level); }
};
struct Protocol {
    bool succeed = false;
    bool opened = false;
    bool IsAudioChannelOpened() const { return opened; }
    bool OpenAudioChannel() { opened = succeed; return opened; }
    void CloseAudioChannel() { opened = false; }
};
struct Application {
    DeviceState state = kDeviceStateConnecting;
    Protocol transport;
    Protocol* protocol_ = &transport;
    std::atomic<bool> sense_microphone_privacy_muted_{false};
    std::atomic<bool> sense_audio_link_unavailable_{false};
    std::atomic<uint32_t> sense_audio_failure_epoch_{0};
    bool play_popup_on_listening_ = false;
    DeviceState GetDeviceState() const { return state; }
    void SetDeviceState(DeviceState value) { state = value; }
    void SetListeningMode(ListeningMode) { state = kDeviceStateListening; }
    ListeningMode GetDefaultListeningMode() const { return kListeningModeRealtime; }
    void ContinueOpenAudioChannel(ListeningMode mode);
    void ContinueWakeWordInvoke(const std::string& wake_word);
};
""" + normal + wake + r"""
int main() {
    using Level = PowerSaveLevel;
    auto& levels = Board::GetInstance().levels;
    // No close callback is simulated: allocation/open failures can occur
    // before a transport exists. The actual continuation owns the rollback.
    for (bool wake : {false, true}) {
        for (bool success : {false, true}) {
            levels.clear();
            Application app;
            app.transport.succeed = success;
            if (wake) app.ContinueWakeWordInvoke("test");
            else app.ContinueOpenAudioChannel(kListeningModeRealtime);
            if (success) {
                if (app.state != kDeviceStateListening) return 1;
                if (levels != std::vector<Level>{Level::PERFORMANCE}) return 2;
            } else {
                if (app.state != kDeviceStateIdle) return 3;
                if (levels != std::vector<Level>{Level::PERFORMANCE, Level::LOW_POWER})
                    return 4;
            }
        }
    }
    levels.clear();
    Application cancelled;
    cancelled.state = kDeviceStateIdle;
    cancelled.ContinueOpenAudioChannel(kListeningModeRealtime);
    cancelled.ContinueWakeWordInvoke("obsolete");
    if (!levels.empty()) return 5;
    return 0;
}
""")
        for flags in ([], ["-DCONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED=1"]):
            subprocess.run(
                [compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror", *flags,
                 str(code), "-o", str(binary)],
                env=native_cpp_env(), check=True, timeout=60,
            )
            subprocess.run([str(binary)], check=True, timeout=10)

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
        debugger_config = kconfig.split('config USE_AUDIO_DEBUGGER\n', 1)[1].split(
            '\nconfig ', 1
        )[0]
        self.assertIn('depends on !BOARD_TYPE_DESK_ROBOT_SENSE_S3', debugger_config)
        self.assertIn('#if CONFIG_USE_AUDIO_DEBUGGER\n#error', source)
        self.assertIn('config DESK_ROBOT_AEC_DELAY_MS', kconfig)
        self.assertIn('range 0 250', kconfig)
        self.assertIn('config DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED', kconfig)
        self.assertIn('depends on USE_AUDIO_PROCESSOR && USE_DEVICE_AEC', kconfig)
        self.assertIn('#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED', source)
        self.assertIn('app.GetAecMode() == kAecOnDeviceSide', source)
        self.assertIn('app.ToggleChatState();  // existing Xiaozhi realtime listen', source)
        self.assertIn('board->continuous_audio_started_ = true;', source)
        self.assertIn('WifiManager::GetInstance().IsConnected()', source)
        self.assertIn('if (!wifi_connected)', source)
        self.assertIn('board->continuous_audio_started_ = false;', source)
        self.assertIn('&& wifi_connected', source)
        self.assertLess(
            source.index('if ((!board->continuous_audio_started_'),
            source.index('app.ToggleChatState();  // existing Xiaozhi realtime listen'),
        )
        self.assertIn('audio_operator_touched_.store(true, std::memory_order_release);', source)
        self.assertIn('std::atomic<bool> audio_operator_muted_{false};', source)
        boot = source.split('boot_button_.OnClick([this]() {', 1)[1].split('void StartNetwork() override', 1)[0]
        self.assertIn('->SetMicrophonePrivacyMuted(now_muted);', boot)
        self.assertIn('app.SetDeviceState(kDeviceStateIdle);', boot)
        self.assertIn('app.SetSenseMicrophonePrivacyMuted(now_muted);', boot)
        self.assertIn('app.StopListening();', boot)
        self.assertLess(boot.index('app.SetSenseMicrophonePrivacyMuted(now_muted);'),
                        boot.index('->SetMicrophonePrivacyMuted(now_muted);'))
        self.assertLess(boot.index('->SetMicrophonePrivacyMuted(now_muted);'),
                        boot.index('app.StopListening();'))
        self.assertIn('if (state == kDeviceStateIdle) app.ToggleChatState();', boot)
        self.assertLess(boot.index('->SetMicrophonePrivacyMuted(now_muted);'),
                        boot.index('if (now_muted)'))
        self.assertIn('CONFIG_DESK_ROBOT_AEC_DELAY_MS', (board / 'sense_reference_codec.h').read_text())
        self.assertIn('#include "stackchan_behavior.hpp"', source)
        self.assertIn('HsmBehavior face_behavior_', source)
        self.assertIn('body_bridge_->PollInteraction()', source)
        # Source-qualified touch contributes to the Mac world model,
        # not a compulsory local smile or nod on every contact.
        self.assertNotIn('pending_face_touches_', source)
        self.assertNotIn('Event(EventType::kTouched)', source)
        self.assertIn('TakeCosmeticMoodCue()', source)
        self.assertIn('BodyFaceState body_face_state_;', source)
        self.assertIn('bool last_priority_active = false;', source)
        self.assertIn('static void BodyPollTask(void* context)', source)
        self.assertIn('board->body_face_state_.Publish({});', source)
        self.assertIn('board->local_eye_display_->SetLocalStatus(local_status);', source)
        self.assertNotIn('body_unhealthy ? "sad" :', source)
        self.assertIn('Event(EventType::kPersonDetected)', source)
        bridge = (board / 'robot_bridge.cc').read_text()
        self.assertIn('BodyInteraction Bridge::PollInteraction()', bridge)
        self.assertIn('Transact("status", false)', bridge)
        self.assertIn('head_touch_edges_.Observe(current)', bridge)
        self.assertIn('body_cap_edges_.Observe(', bridge)
        self.assertIn('body_cap_edges_.Reset()', bridge)
        # A truncated WROOM JSON reply must never become sensory MCP
        # evidence merely because its motors and watchdog look plausible.
        self.assertIn('bool StatusValid(cJSON* json)', bridge)
        for group in ('safety', 'ranges', 'touch', 'imu'):
            self.assertIn('auto ' + group + ' = get(json, "' + group + '");', bridge)
        self.assertIn('valid_mask->valueint & ~present_mask->valueint', bridge)
        self.assertIn('age >= 200', bridge)
        self.assertIn('!cJSON_IsBool(get(safety, "ready"))', bridge)
        self.assertIn('device_state == kDeviceStateIdle', source)
        # The contextual Mac cue has priority; local Stackchan remains an
        # idle fallback rather than directly overwriting the model's mood.
        self.assertIn('SetEmotion(CosmeticMoodName(requested_mood))', source)
        self.assertIn('MoodName(board->face_behavior_.mood())', source)
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

    def test_dock_contact_lockout_ui_keeps_local_stop_and_rejects_stale_status(self):
        """A physical contact latch is not a charging or seating certificate."""
        board = HEAD / 'sense/desk_robot_sense.cc'
        source = board.read_text()
        bridge = (HEAD / 'overlay/robot_bridge.cc').read_text()
        header = (HEAD / 'overlay/robot_bridge.h').read_text()
        protocol = (HEAD / 'overlay/robot_protocol.h').read_text()
        assert 'bool dock_lockout = false;' in header
        assert 'BodyDockLockoutObserved(' in protocol
        assert 'observation.dock_lockout = BodyDockLockoutObserved(' in bridge
        assert 'board->body_face_state_.Publish({});' in source
        assert 'body_fresh && body_unhealthy && body.dock_lockout' in source
        assert 'now_ms - at_ms <= 1200U' in source
        renderer = (HEAD / "overlay/face_eye_display.hpp").read_text()
        assert "body_unhealthy, dock_lockout, mic_privacy_on" in source
        assert 'case FaceStatus::kDockLock: status = "Dock lock: motors off";' in renderer
        assert 'case FaceStatus::kBodyFault: status = "Body safety stop";' in renderer
        assert "charging" not in renderer.split("case FaceStatus::kDockLock:", 1)[1].split(
            "break;", 1
        )[0].lower()
        assert "if (priority_active || !face_available)" in source
        assert "if (priority_active)" in source

    def test_boot_mute_while_speaking_closes_pinned_xiaozhi_channel(self):
        """The BOOT privacy action must close the active speaker session."""
        overlay.apply(self.root, "sense")
        app = (self.root / "main/application.cc").read_text()
        begin = app.index("void Application::StopListening()")
        end = app.index("void Application::HandleWakeWordDetectedEvent()", begin)
        stop = app[begin:end]
        self.assertIn("} else if (state == kDeviceStateSpeaking)", stop)
        self.assertIn("#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED", stop)
        for action in (
            "AbortSpeaking(kAbortReasonNone);",
            "audio_service_.ResetDecoder();",
            "Board::GetInstance().GetAudioCodec()->EnableOutput(false);",
            "protocol_->CloseAudioChannel();",
            "SetDeviceState(kDeviceStateIdle);",
        ):
            self.assertIn(action, stop)
        self.assertLess(
            stop.index("AbortSpeaking(kAbortReasonNone);"),
            stop.index("protocol_->CloseAudioChannel();"),
        )
        board = (self.root / overlay.BOARDS["sense"] / "desk_robot_sense.cc").read_text()
        click = board.split("boot_button_.OnClick([this]()", 1)[1].split(
            "void StartNetwork()", 1
        )[0]
        self.assertIn(
            "audio_operator_touched_.store(true, std::memory_order_release);",
            click,
        )
        self.assertIn("app.SetSenseMicrophonePrivacyMuted(now_muted);", click)
        self.assertIn("->SetMicrophonePrivacyMuted(now_muted);", click)
        self.assertIn("const bool now_muted = !audio_operator_muted_.load(", click)
        self.assertIn("if (now_muted)", click)
        self.assertIn("app.StopListening();", click)
        self.assertIn("if (state == kDeviceStateIdle) app.ToggleChatState();", click)
        self.assertIn("!board->audio_operator_touched_.load()", board)


    def test_sense_display_and_bridge_ready_before_face_and_sensor_tasks(self):
        """Guard startup ordering, without implying physical sensor qualification."""
        overlay.apply(self.root, "sense")
        source = (self.root / overlay.BOARDS["sense"] / "desk_robot_sense.cc").read_text()
        display = source.split("void InitializeDisplay()", 1)[1].split(
            "void InitializeCamera()", 1
        )[0]
        stages = (
            "esp_lcd_panel_reset(panel)",
            "esp_lcd_panel_init(panel)",
            "esp_lcd_panel_disp_on_off(panel, true)",
            "local_eye_display_ = new desk_robot::LocalEyeDisplay(",
            "display_ = local_eye_display_;",
        )
        positions = [display.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        constructor = source.split("DeskRobotSenseBoard() :", 1)[1].split(
            "void StartNetwork() override", 1
        )[0]
        self.assertLess(
            constructor.index("InitializeDisplay();"),
            constructor.index("InitializeCamera();"),
        )
        self.assertLess(
            constructor.index("InitializeCamera();"),
            constructor.index("boot_button_.On"),
        )
        app = (self.root / "main/application.cc").read_text()
        initialize = app.split("void Application::Initialize()", 1)[1].split(
            "board.StartNetwork();", 1
        )
        self.assertEqual(len(initialize), 2)
        self.assertIn("display->SetupUI();", initialize[0])
        startup = source.split("void StartNetwork() override", 1)[1].split(
            "AudioCodec* GetAudioCodec()", 1
        )[0]
        for task in ("xTaskCreate(FaceTask,", "xTaskCreate(BodyPollTask,"):
            for prerequisite in (
                "robot_bridge.Start();",
                "body_bridge_ = &robot_bridge;",
                "face_behavior_.seed(pet_seed);",
                "eye_animator_.Seed(pet_seed);",
            ):
                self.assertLess(startup.index(prerequisite), startup.index(task))
        self.assertIn("bool fault = true;", source)
        self.assertIn("uint64_t at_ms = 0;", source)

    def test_latched_body_fault_remains_visible_during_continuous_listening(self):
        """Xiaozhi may overwrite OLED status without an idle transition."""
        source = (HEAD / "sense/desk_robot_sense.cc").read_text()
        face = source.split("static void FaceTask(void* context)", 1)[1]
        face = face.split("void InitializeDisplay()", 1)[0]
        self.assertIn("body_unhealthy, dock_lockout, mic_privacy_on", face)
        self.assertIn("board->local_eye_display_->SetLocalStatus(local_status);", face)
        self.assertNotIn("last_fault_status_refresh_ms", face)
        # The OLED task must not turn an informational safety cue into
        # speaker traffic, motion, or another blocking body UART poll.
        self.assertNotIn("body_bridge_->PollInteraction()", face)
        self.assertNotIn("ToggleChatState();  // safety fault", face)

    def test_local_oled_scheduler_never_blocks_on_uart_poll(self):
        """Preserve responsive local face when WROOM UART holds 350 ms."""
        source = (HEAD / "sense/desk_robot_sense.cc").read_text()
        poll = source.split("static void BodyPollTask(void* context)", 1)[1]
        poll, face = poll.split("static void FaceTask(void* context)", 1)
        face = face.split("void InitializeDisplay()", 1)[0]
        self.assertIn('body_bridge_->PollInteraction()', poll)
        self.assertNotIn('body_bridge_->PollInteraction()', face)
        self.assertNotIn('uart_', face)
        self.assertIn('body_face_state_.Publish(', poll)
        self.assertIn('body_face_state_.Read()', face)
        self.assertIn('!body_fresh || body.fault', face)
        self.assertNotIn('pending_face_touches_', face)
        self.assertNotIn('Event(EventType::kTouched)', face)
        self.assertIn('TakeCosmeticMoodCue()', face)
        # A body fault now shows a factual status and neutral OLED mood.
        # Model-selected moods are considered only on the healthy branch.
        self.assertIn('if (priority_active) {', face)
        renderer = (HEAD / "overlay/face_eye_display.hpp").read_text()
        self.assertIn('OledDisplay::SetEmotion("neutral");', renderer)
        mood_gate = ('else if (!voice_link_lost && '
                     'requested_mood != desk_robot::CosmeticMood::kNone)')
        normalized_face = ' '.join(face.split())
        self.assertIn(mood_gate, normalized_face)
        self.assertLess(
            normalized_face.index('if (priority_active) {'),
            normalized_face.index(mood_gate),
        )
        self.assertIn('vTaskDelay(pdMS_TO_TICKS(100));', face)
        self.assertIn('xTaskCreate(BodyPollTask, "sense_body_poll"', source)

    def test_head_never_displays_healthy_body_for_unready_or_unguarded_status(self):
        """Status may be structurally valid but still lack a safe motion guard."""
        source = (HEAD / "overlay/robot_bridge.cc").read_text()
        protocol = (HEAD / "overlay/robot_protocol.h").read_text()
        poll = source.split("BodyInteraction Bridge::PollInteraction()", 1)[1]
        poll = poll.split("bool Bridge::Authorize(", 1)[0]
        self.assertIn('auto required = cJSON_GetObjectItemCaseSensitive(safety, "required")', poll)
        self.assertIn('auto ready = cJSON_GetObjectItemCaseSensitive(safety, "ready")', poll)
        self.assertIn('!cJSON_IsBool(required) || !cJSON_IsBool(ready)', poll)
        self.assertIn('observation.fault = BodySafetyUnhealthy(', poll)
        self.assertIn('cJSON_IsTrue(required), cJSON_IsTrue(ready), fault->valuestring', poll)
        self.assertIn('return !required || !ready || fault != "none";', protocol)
        self.assertNotIn('std::strcmp(fault->valuestring, "not_required") != 0', poll)

    def test_urgent_barge_flush_can_play_subsequent_tts(self):
        """Pinned Xiaozhi output worker reopens the codec for the next PCM."""
        overlay.apply(self.root, 'sense')
        application = (self.root / 'main/application.cc').read_text()
        audio = (self.root / 'main/audio/audio_service.cc').read_text()
        self.assertIn('constexpr int initial_decoder_rate = 24000;', audio)
        self.assertIn('decoder_sample_rate_ = initial_decoder_rate;', audio)
        self.assertIn('esp_ae_rate_cvt_open(&cfg, &output_resampler_);', audio)
        self.assertIn('Speaker resampler unavailable: discarding mismatched PCM', audio)
        self.assertIn('task.pcm.clear();', audio)
        self.assertIn('decoded = !task.pcm.empty();', audio)
        self.assertIn('OPUS_DEC_CFG(initial_decoder_rate, OPUS_FRAME_DURATION_MS)', audio)
        # An interrupted reply urgently clears both queued decoder data and
        # the hardware output. The next queued *new* reply must turn it on.
        self.assertIn('audio_service_.ResetDecoder();', application)
        self.assertIn('GetAudioCodec()->EnableOutput(false);', application)
        worker = audio.split('void AudioService::AudioOutputTask()', 1)[1]
        worker = worker.split('void AudioService::', 1)[0]
        self.assertLess(
            worker.index('if (!codec_->output_enabled())'),
            worker.index('codec_->EnableOutput(true);'),
        )
        self.assertLess(
            worker.index('codec_->EnableOutput(true);'),
            worker.index('codec_->OutputData(task.pcm);'),
        )


    def test_sense_websocket_playback_identity_rejects_fractional_id(self):
        """Nonintegral IDs cannot alias a different playback on the real overlay."""
        overlay.apply(self.root, "sense")
        source = (
            self.root / "main/protocols/websocket_protocol.cc"
        ).read_text()
        assert "desk_playback_id_ = 0;" in source
        assert 'strcmp(state->valuestring, "start") == 0' in source
        assert "playback_id->valuedouble >= 1" in source
        assert "playback_id->valuedouble <= 2147483647" in source
        assert (
            "playback_id->valuedouble == static_cast<double>("
            in source
        )
        assert (
            "static_cast<uint32_t>(playback_id->valuedouble))) {"
            in source
        )
        assert source.index("playback_id->valuedouble <= 2147483647") < (
            source.index("playback_id->valuedouble == static_cast<double>(")
        )
        assert source.index("playback_id->valuedouble == static_cast<double>(") < (
            source.index("desk_playback_id_ =\n")
        )
        assert 'strcmp(state->valuestring, "stop") == 0' in source
        # The affected path is Sense-only. The original upstream copy is
        # inspected but never rewritten by the disposable overlay installer.
        original = (UPSTREAM / "main/protocols/websocket_protocol.cc").read_text()
        assert 'desk_playback_id_' not in original

    def test_sense_websocket_audio_frame_bounds(self):
        """Compile the actual installed parser against malformed wire frames."""
        overlay.apply(self.root, "sense")
        source = (self.root / "main/protocols/websocket_protocol.cc").read_text()
        parser = "static bool ParseDeskAudioFrame(" + source.split(
            "static bool ParseDeskAudioFrame(", 1
        )[1].split("WebsocketProtocol::WebsocketProtocol()", 1)[0]
        receive = source.split("websocket_->OnData(", 1)[1].split(
            "// Parse JSON data", 1
        )[0]
        assert receive.index("!ParseDeskAudioFrame(") < receive.index(
            "desk_playback_position_ms_ += frame_ms"
        )
        rejected = receive.split("!ParseDeskAudioFrame(", 1)[1].split(
            "if (on_incoming_audio_ == nullptr)", 1
        )[0]
        assert "desk_playback_id_ = 0;" in rejected
        assert "desk_playback_position_ms_ = 0;" in rejected
        assert "return;" in rejected
        assert "payload + (len - payload_offset)" in receive
        assert "BinaryProtocol2*" not in receive
        assert "BinaryProtocol3*" not in receive
        compiler = shutil.which("g++") or shutil.which("c++")
        if compiler is None:
            self.skipTest("Native C++ compiler unavailable")
        program = self.root / "audio_frame_bounds.cc"
        executable = self.root / "audio_frame_bounds"
        program.write_text(
            "#include <cassert>\n#include <cstddef>\n#include <cstdint>\n" + parser + r"""
int main() {
    size_t offset = 999;
    uint32_t timestamp = 999;
    const char v1[] = {1};
    const char v2[] = {0,2,0,0,0,0,0,0,0,0,1,44,0,0,0,1,7};
    const char v3[] = {0,0,0,1,7};
    assert(ParseDeskAudioFrame(1, v1, sizeof(v1), offset, timestamp));
    assert(offset == 0 && timestamp == 0);
    assert(!ParseDeskAudioFrame(1, nullptr, 1, offset, timestamp));
    assert(!ParseDeskAudioFrame(1, v1, 0, offset, timestamp));
    assert(!ParseDeskAudioFrame(9, v1, 1, offset, timestamp));
    for (size_t len = 0; len < sizeof(v2); ++len)
        assert(!ParseDeskAudioFrame(2, v2, len, offset, timestamp));
    for (size_t len = 0; len < sizeof(v3); ++len)
        assert(!ParseDeskAudioFrame(3, v3, len, offset, timestamp));
    assert(ParseDeskAudioFrame(2, v2, sizeof(v2), offset, timestamp));
    assert(offset == 16 && timestamp == 300 && v2[11] == 44);
    assert(ParseDeskAudioFrame(3, v3, sizeof(v3), offset, timestamp));
    assert(offset == 4 && timestamp == 0);
    const char oversized[] = {0,0,0,2,7};
    const char trailing[] = {0,0,0,1,7,8};
    const char wrong_type[] = {1,0,0,1,7};
    const char wrong_version[] = {0,3,0,0,0,0,0,0,0,0,0,0,0,0,0,1,7};
    assert(!ParseDeskAudioFrame(3, oversized, sizeof(oversized), offset, timestamp));
    assert(!ParseDeskAudioFrame(3, trailing, sizeof(trailing), offset, timestamp));
    assert(!ParseDeskAudioFrame(3, wrong_type, sizeof(wrong_type), offset, timestamp));
    assert(!ParseDeskAudioFrame(2, wrong_version, sizeof(wrong_version), offset, timestamp));
}
"""
        )
        subprocess.run(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
             str(program), "-o", str(executable)],
            check=True, capture_output=True, text=True, env=native_cpp_env(),
        )
        subprocess.run([str(executable)], check=True, capture_output=True, text=True)

    def test_sense_pdm_mic_read_timeout_is_bounded(self):
        """A PDM DMA stall must yield to the existing Xiaozhi audio task.

        The installed Sense upstream build is the test target, not a mock.
        """
        overlay.apply(self.root, 'sense')
        codec = (self.root / 'main/audio/codecs/no_audio_codec.cc').read_text()
        reader = codec.split('int NoAudioCodecSimplexPdm::Read(', 1)[1]
        self.assertIn('#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3', reader)
        sense_read = reader.split('#else', 1)[0]
        self.assertIn('&bytes_read,\n        120);', sense_read)
        self.assertNotIn('pdMS_TO_TICKS', sense_read)
        self.assertIn('read_status != ESP_OK', reader)
        sense_error = reader.split('// All Sense read errors return no samples.', 1)[1]
        self.assertNotIn('ESP_LOG', sense_error.split('#else', 1)[0])
        self.assertIn('return 0;', reader)
        self.assertIn('portMAX_DELAY', reader)  # Other boards unchanged.
        self.assertNotIn(
            'i2s_channel_read(rx_handle_, dest, samples * sizeof(int16_t), '
            '&bytes_read, portMAX_DELAY) != ESP_OK', reader,
        )

    def test_sense_pdm_tx_clock_is_explicit_and_checked_before_init(self):
        """Inspect the effective pinned codec, not just the board rate macro."""
        overlay.apply(self.root, "sense")
        path = "main/audio/codecs/no_audio_codec.cc"
        codec = (self.root / path).read_text()
        tx = codec.split("i2s_std_config_t tx_std_cfg = {", 1)[1].split(
            "ESP_ERROR_CHECK(i2s_channel_init_std_mode(tx_handle_, &tx_std_cfg));", 1
        )[0]
        assert ".sample_rate_hz = (uint32_t)output_sample_rate_" in tx
        assert ".mclk = I2S_GPIO_UNUSED" in tx
        assert "tx_std_cfg.slot_cfg.slot_bit_width = I2S_SLOT_BIT_WIDTH_32BIT;" in tx
        for check in (
            "tx_std_cfg.clk_cfg.sample_rate_hz == 32000",
            "tx_std_cfg.clk_cfg.mclk_multiple == I2S_MCLK_MULTIPLE_256",
            "tx_std_cfg.slot_cfg.data_bit_width == I2S_DATA_BIT_WIDTH_32BIT",
            "tx_std_cfg.slot_cfg.ws_width == 32",
            "tx_std_cfg.slot_cfg.slot_mode == I2S_SLOT_MODE_MONO",
            "tx_std_cfg.slot_cfg.bit_shift",
        ):
            assert check in tx
        assert "? ESP_OK : ESP_ERR_INVALID_ARG" in tx
        assert tx.index("#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3") < tx.index(
            "tx_std_cfg.slot_cfg.slot_bit_width = I2S_SLOT_BIT_WIDTH_32BIT;"
        )
        overlay.remove(self.root)
        assert (self.root / path).read_bytes() == self.original[path]

    def test_decoder_integrity_shared_across_s3_variants(self):
        """The alternate S3 heads must retain the same decoder safety gate."""
        path = "main/audio/audio_service.cc"
        sources = {
            board: overlay.planned_files(self.root, board)[path].decode()
            for board in ("sense", "modular", "waveshare")
        }
        setters = {
            board: source.split("void AudioService::SetDecodeSampleRate(", 1)[1].split(
                "void AudioService::PushTaskToEncodeQueue(", 1
            )[0]
            for board, source in sources.items()
        }
        self.assertEqual(setters["sense"], setters["modular"])
        self.assertEqual(setters["sense"], setters["waveshare"])
        for board, source in sources.items():
            with self.subTest(board=board):
                setter = setters[board]
                self.assertNotIn("#ifdef CONFIG_BOARD_TYPE", setter)
                self.assertLess(setter.index("sample_rate != 48000"),
                                setter.index("esp_opus_dec_open("))
                self.assertLess(setter.index("frame_duration != 60"),
                                setter.index("esp_opus_dec_open("))
                self.assertLess(setter.index("if (proposed_decoder == nullptr)"),
                                setter.index("esp_opus_dec_close(previous_decoder)"))
                gate = (
                    "if (opus_decoder_ != nullptr &&\n"
                    "                decoder_sample_rate_ == packet->sample_rate &&\n"
                    "                decoder_duration_ms_ == packet->frame_duration) {"
                )
                worker = source.split("void AudioService::OpusCodecTask()", 1)[1].split(
                    "void AudioService::SetDecodeSampleRate(", 1
                )[0]
                self.assertLess(worker.index(gate), worker.index("esp_opus_dec_decode("))
                self.assertIn("Speaker resampler unavailable: discarding mismatched PCM", worker)
                self.assertIn("decoded = !task.pcm.empty();", worker)

    def test_invalid_32khz_opus_offer_does_not_destroy_decoder(self):
        """The 32 kHz DAC clock is not an Opus decode rate (source gate)."""
        overlay.apply(self.root, 'sense')
        audio = (self.root / 'main/audio/audio_service.cc').read_text()
        setter = audio.split('void AudioService::SetDecodeSampleRate(', 1)[1]
        setter = setter.split('void AudioService::PushTaskToEncodeQueue(', 1)[0]
        self.assertIn('sample_rate != 24000', setter)
        self.assertIn('sample_rate != 48000', setter)
        self.assertIn('Rejecting unsupported Opus rate', setter)
        # An invalid frame duration such as 30 ms must be rejected before
        # touching the active decoder, even when its sample rate is valid.
        for duration in (5, 10, 20, 40, 60):
            self.assertIn(f'frame_duration != {duration}', setter)
        self.assertIn('Rejecting unsupported Opus frame duration', setter)
        self.assertLess(setter.index('frame_duration != 60'),
                        setter.index('esp_opus_dec_open('))
        # Invalid rates are rejected before any replacement is attempted.
        # A successful replacement is opened first, then atomically
        # published under decoder_mutex_ and only then the old decoder
        # is closed. The previous close(opus_decoder_) expectation was
        # stale after switching to the safer previous_decoder swap.
        self.assertLess(setter.index('sample_rate != 24000'),
                        setter.index('esp_opus_dec_open('))
        self.assertLess(setter.index('esp_opus_dec_open('),
                        setter.index('if (proposed_decoder == nullptr)'))
        self.assertLess(setter.index('if (proposed_decoder == nullptr)'),
                        setter.index('opus_decoder_ = proposed_decoder;'))
        self.assertLess(setter.index('opus_decoder_ = proposed_decoder;'),
                        setter.index('esp_opus_dec_close(previous_decoder);'))
        self.assertIn('Failed to create replacement decoder, keeping prior decoder',
                      setter)
        self.assertIn('std::lock_guard<std::mutex> decoder_lock(decoder_mutex_);',
                      setter)
        self.assertIn('void* previous_decoder = opus_decoder_;', setter)
        self.assertIn('decoder_duration_ms_ == frame_duration && opus_decoder_ != nullptr',
                      setter)
        self.assertNotIn('#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3', setter)
        # 32 kHz remains the DAC rate; Opus decoder should stay at 24 kHz.
        config = (self.root / overlay.BOARDS['sense'] / 'config.h').read_text()
        self.assertIn('#define AUDIO_OUTPUT_SAMPLE_RATE 32000', config)
        self.assertIn('constexpr int initial_decoder_rate = 24000;', audio)

    def test_rejected_decoder_format_never_reaches_preserved_decoder(self):
        """A failed decoder change must not play a packet in the old format."""
        overlay.apply(self.root, "sense")
        audio = (self.root / "main/audio/audio_service.cc").read_text()
        worker = audio.split("void AudioService::OpusCodecTask()", 1)[1].split(
            "void AudioService::SetDecodeSampleRate(", 1
        )[0]
        gate = (
            "if (opus_decoder_ != nullptr &&\n"
            "                decoder_sample_rate_ == packet->sample_rate &&\n"
            "                decoder_duration_ms_ == packet->frame_duration) {"
        )
        assert worker.index("SetDecodeSampleRate(packet->sample_rate, packet->frame_duration)") < (
            worker.index(gate)
        ) < worker.index("esp_opus_dec_decode(")
        assert worker.index(gate) < worker.index("task.pcm.resize(decoder_frame_size_);")
        assert "if (decoded && generation == playback_generation_" in worker
        setter = audio.split("void AudioService::SetDecodeSampleRate(", 1)[1].split(
            "void AudioService::PushTaskToEncodeQueue(", 1
        )[0]
        retry = setter.split("decoder_duration_ms_ == frame_duration && opus_decoder_ != nullptr", 1)[1]
        retry = retry.split("esp_opus_dec_cfg_t opus_dec_cfg", 1)[0]
        assert "sample_rate != codec->output_sample_rate() && output_resampler_ == nullptr" in retry
        assert retry.index("esp_ae_rate_cvt_open(&cfg, &output_resampler_)") < retry.index("return;")
        assert "esp_opus_dec_open(" not in retry
        assert "esp_opus_dec_close(" not in retry

    def test_digital_playback_receipt_cannot_skip_missing_decoded_pcm(self):
        """Compile the real generated prefix guard and verify its output-task wiring."""
        overlay.apply(self.root, "sense")
        header = (self.root / "main/audio/audio_service.h").read_text()
        source = (self.root / "main/audio/audio_service.cc").read_text()
        assert "task.desk_frame_duration_ms = packet->frame_duration;" in source
        output = source.split("void AudioService::AudioOutputTask()", 1)[1].split(
            "void AudioService::OpusCodecTask()", 1
        )[0]
        assert "DeskPlaybackPrefix desk_robot_prefix;" in output
        assert output.index("codec_->OutputData(task.pcm)") < output.index(
            "desk_robot_prefix.Accept("
        ) < output.index("callbacks_.on_playback_committed(")
        assert "task.desk_frame_duration_ms," in output
        assert "transmitted_frames == static_cast<int>(task.pcm.size())" in output
        assert "!task.pcm.empty()" in output
        assert "DeskPlaybackPrefix::ExactMediaFrame(" in output
        assert "task.pcm.size(), codec_->output_sample_rate()," in output
        guard = "struct DeskPlaybackPrefix {" + header.split(
            "struct DeskPlaybackPrefix {", 1
        )[1].split("struct DebugStatistics {", 1)[0]
        compiler = shutil.which("c++")
        assert compiler is not None, "Native C++ compiler required"
        harness = self.root / "prefix_test.cc"
        binary = self.root / "prefix_test"
        harness.write_text(
            "#include <cstdint>\n#include <cassert>\n" + guard + """
int main() {
    DeskPlaybackPrefix prefix;
    assert(prefix.ExactMediaFrame(1920, 32000, 60));
    assert(!prefix.ExactMediaFrame(1919, 32000, 60));
    assert(!prefix.ExactMediaFrame(1921, 32000, 60));
    assert(!prefix.ExactMediaFrame(960, 32000, 60));
    assert(!prefix.ExactMediaFrame(0, 32000, 60));
    assert(!prefix.ExactMediaFrame(1920, 0, 60));
    assert(!prefix.ExactMediaFrame(1920, 32000, -60));
    assert(!prefix.ExactMediaFrame(1, 1, 1));
    assert(prefix.Accept(1, 60, 60, true));
    assert(!prefix.Accept(1, 180, 60, true));
    assert(!prefix.Accept(1, 240, 60, true));
    assert(!prefix.Accept(2, 120, 60, true));
    assert(!prefix.Accept(2, 180, 60, true));
    assert(prefix.Accept(3, 60, 60, true));
    assert(!prefix.Accept(3, 120, 60, false));
    assert(!prefix.Accept(3, 180, 60, true));
    assert(prefix.Accept(4, 20, 20, true));
    assert(prefix.Accept(4, 60, 40, true));
    assert(!prefix.Accept(4, 60, 40, true));
    assert(!prefix.Accept(4, 100, 40, true));
    assert(!prefix.Accept(0, 0, 0, true));
    assert(prefix.Accept(5, 60, 60, true));
    assert(!prefix.Accept(5, 120, 0, true));
    assert(!prefix.Accept(5, 180, 60, true));
}
"""
        )
        subprocess.run(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
             str(harness), "-o", str(binary)],
            check=True, env=native_cpp_env(),
        )
        subprocess.run([str(binary)], check=True)

    def test_stream_camera_configuration_and_single_client_ownership(self):
        """Source budget, not measured frame rate or audio contention."""
        board = (HEAD / "sense/desk_robot_sense.cc").read_text()
        bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
        for expected in (
            "config.pixel_format = PIXFORMAT_JPEG;",
            "config.frame_size = FRAMESIZE_VGA;",
            "config.jpeg_quality = 12;",
            "config.fb_count = 2;",
            "config.fb_location = CAMERA_FB_IN_PSRAM;",
            "config.grab_mode = CAMERA_GRAB_LATEST;",
        ):
            self.assertIn(expected, board)
        self.assertIn("camera_busy_.exchange(true)", bridge)
        self.assertIn('httpd_resp_set_hdr(req, "X-Desk-Camera-Robot-Id"', bridge)
        self.assertIn('"X-Desk-Camera-Robot-Id: %s', bridge)
        self.assertIn('jpeg->size(), CONFIG_DESK_ROBOT_ID,', bridge)
        self.assertIn('char headers[320] = {};', bridge)
        self.assertIn('Envelope(false, "camera busy")', bridge)
        self.assertIn("vTaskDelay(pdMS_TO_TICKS(250));", bridge)
        self.assertIn("bridge->camera_busy_.store(false);", bridge)
        self.assertIn('"camera_sensor_pid"', bridge)
        # Older XIAO Sense OV2640 reports 0x26, not 0x2640.
        # Recognition is not dock calibration or motion permission.
        self.assertIn('pid == OV2640_PID ? "OV2640" :', bridge)


    def test_continuous_listening_can_render_mood_without_touching_voice(self):
        """Always listening is not ordinary Idle; keep the OLED expressive."""
        source = (HEAD / "sense/desk_robot_sense.cc").read_text()
        face = source.split("static void FaceTask(void* context)", 1)[1].split(
            "void InitializeDisplay()", 1
        )[0]
        assert "#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED" in face
        assert "face_available = idle || device_state == kDeviceStateListening;" in face
        assert "const bool face_available = idle;" in face
        assert "if (face_available && board->display_ != nullptr)" in face
        assert "if (priority_active || !face_available) model_mood_active = false;" in face
        # Avoid an every-100ms LVGL write in an unending listening state.
        assert "last_face_available = face_available;" in face
        assert "!last_face_available || action.set_mood" in face
        # Moods are visual only. Xiaozhi's status and safety own the label.
        assert "board->local_eye_display_->SetLocalStatus(local_status);" in face
        assert "head.command(" not in face
        assert "speaker.say(" not in face

    def test_new_body_fault_neutralizes_emotion_even_while_speaking(self):
        """A status fault cannot leave a happy emoji through a long song."""
        source = (HEAD / "sense/desk_robot_sense.cc").read_text()
        face = source.split("static void FaceTask(void* context)", 1)[1].split(
            "void InitializeDisplay()", 1
        )[0]
        renderer = (HEAD / "overlay/face_eye_display.hpp").read_text()
        neutral = face.index("board->local_eye_display_->SetLocalStatus(local_status);")
        available = face.index("if (face_available && board->display_ != nullptr)")
        assert neutral < available
        assert 'OledDisplay::SetEmotion("neutral");' in renderer
        assert face.index("last_priority_active = priority_active;") > available
        assert face.count("last_priority_active = priority_active;") == 1

    def test_sense_server_audio_close_rejoins_only_same_consentful_xiaozhi_channel(self):
        """WiFi may stay connected after WebSocket closes; BOOT still wins."""
        board = (HEAD / "sense/desk_robot_sense.cc").read_text()
        face = board.split("static void FaceTask(void* context)", 1)[1].split(
            "void InitializeDisplay()", 1,
        )[0]
        self.assertIn("last_audio_listen_attempt_ms_ = 0;", board)
        # Both initial/reconnect and failure paths must share the throttle.
        self.assertIn(
            "if ((!board->continuous_audio_started_ || failed_since_attempt) &&\n"
            "                    AudioListenRetryDue(uptime_ms, "
            "board->last_audio_listen_attempt_ms_))",
            face,
        )
        self.assertIn(
            "AudioListenRetryDue(uptime_ms, board->last_audio_listen_attempt_ms_)", face,
        )
        self.assertIn("board->last_audio_listen_attempt_ms_ = uptime_ms;", face)
        self.assertIn("if (!wifi_connected)", face)
        self.assertIn("device_state == kDeviceStateIdle", face)
        self.assertIn("!board->audio_operator_touched_.load()", face)
        self.assertIn("app.GetAecMode() == kAecOnDeviceSide", face)
        self.assertIn("app.ToggleChatState();  // existing Xiaozhi realtime listen", face)
        self.assertEqual(face.count("app.ToggleChatState();"), 1)
        # A physical BOOT press disables all automatic reopen attempts.
        self.assertIn("audio_operator_touched_.store(true", board)


    def test_sense_safety_status_remains_visible_during_speech(self):
        """A factual WROOM fault cannot wait for the idle expression owner."""
        board = (HEAD / "sense/desk_robot_sense.cc").read_text()
        face = board.split("static void FaceTask(void* context)", 1)[1].split(
            "void InitializeDisplay()", 1,
        )[0]
        status = face.index("board->local_eye_display_->SetLocalStatus(local_status);")
        idle_mood = face.index("if (face_available && board->display_ != nullptr)")
        self.assertLess(status, idle_mood)
        renderer = (HEAD / "overlay/face_eye_display.hpp").read_text()
        self.assertIn('OledDisplay::SetEmotion("neutral");', renderer)
        self.assertIn("OledDisplay::SetStatus(normal_status_);", renderer)
        self.assertIn("const Action action = board->face_behavior_.update(obs);", face)
        # A model mood is still permitted only through the healthy face owner.
        self.assertGreater(
            face.index("board->display_->SetEmotion(CosmeticMoodName(requested_mood))"),
            idle_mood,
        )


    def test_tof_optics_read_only_bridge_validation_and_one_uart_owner(self):
        """Eight optical raw words never become a second motion sensor owner."""
        protocol = (HEAD / "overlay/robot_protocol.h").read_text()
        bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
        body = (ROOT / "firmware/body/lib/BodyControl/BodyControl.cpp").read_text()
        assert '"optics"' in protocol
        assert 'bool OpticsValid(cJSON* json)' in bridge
        assert 'cJSON_IsFalse(get("motor_authorized"))' in bridge
        assert 'cJSON_IsFalse(get("physical_qualified"))' in bridge
        assert 'cJSON_GetArraySize(amb) != 8' in bridge
        assert 'cJSON_GetArraySize(signal) != 8' in bridge
        assert 'cJSON_GetArraySize(ages) != 8' in bridge
        assert 'command.verb == "optics"' in bridge
        assert '"/api/optics"' in bridge
        assert 'Transact(' in bridge
        assert 'std::strcmp(command, "optics")' in body
        assert '"motor_authorized":false' not in body  # JSON is C++ escaped
        assert 'desk_robot::publish_range_telemetry(' in (
            ROOT / "firmware/body/src/main.cpp"
        ).read_text()
        assert 'control.sample_range_optics(' in (
            ROOT / "firmware/body/lib/TofBus/RangeTelemetry.h"
        ).read_text()


    def test_physical_boot_privacy_discards_live_and_calibration_pcm(self):
        """BOOT closes the genuine microphone path, not merely a UI label."""
        header = (HEAD / "sense/sense_reference_codec.h").read_text()
        code = (HEAD / "sense/sense_reference_codec.cc").read_text()
        read = code.split("int SenseReferenceCodec::Read(", 1)[1].split(
            "int SenseReferenceCodec::Write(", 1
        )[0]
        self.assertIn("microphone_privacy_muted_.exchange(", header)
        self.assertIn("microphone_privacy_epoch_.fetch_add(", header)
        self.assertIn("if (muted) AbortBenchPcmCapture();", header)
        self.assertIn("const uint32_t privacy_epoch =", read)
        self.assertIn("if (microphone_privacy_muted_.load(", read)
        self.assertIn("std::fill_n(dest, samples, 0);", read)
        self.assertIn("std::fill_n(microphone_frame_.begin(), frames, 0);", read)
        self.assertIn("bench_window_.offer(", read)
        self.assertLess(read.index("microphone_privacy_epoch_.load("),
                        read.index("NoAudioCodecSimplexPdm::Read("))
        self.assertLess(read.index("std::fill_n(dest, samples, 0);"),
                        read.index("bench_window_.offer("))
        self.assertGreater(read.count("privacy_epoch != microphone_privacy_epoch_"), 1)

    def test_reference_generation_fence_prevents_stale_barge_audio(self):
        """Source contract only; physical DMA silence still needs A2 trials."""
        header = (HEAD / "sense/sense_reference_codec.h").read_text()
        code = (HEAD / "sense/sense_reference_codec.cc").read_text()
        self.assertIn("SenseSpeakerActivity speaker_activity_", header)
        self.assertIn('#include "sense_speaker_activity.hpp"', header)
        writer = code.split("int SenseReferenceCodec::Write(", 1)[1]
        writer = writer.split("void SenseReferenceCodec::ClearReference()", 1)[0]
        self.assertLess(
            writer.index("started_generation = speaker_activity_.generation();"),
            writer.index("NoAudioCodec::Write(data, samples)"),
        )
        self.assertLess(
            writer.index("NoAudioCodec::Write(data, samples)"),
            writer.index("speaker_activity_.RecordAccepted("),
        )
        self.assertLess(
            writer.index("speaker_activity_.RecordAccepted("),
            writer.index("started_generation == speaker_activity_.generation()"),
        )
        self.assertIn("started_generation, accepted, accepted_at_us);", writer)
        self.assertIn("if (stale_publish_discards_ != UINT32_MAX) ++stale_publish_discards_;", writer)
        self.assertIn("stale_write = true;", writer)
        self.assertIn("return stale_write ? 0 : accepted;", writer)
        self.assertIn("reference_integrity_failed_ = true;", writer)
        self.assertIn("PublishAcceptedLocked(sense_tx_scratch_, accepted, accepted_at_us)", writer)
        clear = code.split("void SenseReferenceCodec::ClearReference()", 1)[1]
        self.assertLess(
            clear.index("speaker_activity_.Reset();"),
            clear.index("reference_.fill(0);"),
        )

    def test_sense_i2s_override_reuses_bounded_upstream_writer(self):
        """Keep only the pinned codec writer, not a second audio stack."""
        writer = (HEAD / "sense/sense_reference_codec.cc").read_text().split(
            "int SenseReferenceCodec::Write(", 1
        )[1].split("void SenseReferenceCodec::ClearReference()", 1)[0]
        installer = (HEAD / "install_overlay.py").read_text()
        assert "NoAudioCodec::Write(data, samples)" in writer
        assert "std::lock_guard<std::mutex> output_lock(output_write_mutex_);" in writer
        assert "output_volume_" not in writer
        assert "PublishAcceptedLocked(sense_tx_scratch_, accepted, accepted_at_us)" in writer
        assert "i2s_channel_write(" not in writer
        tx = installer.split("const esp_err_t err = i2s_channel_write(", 1)[1].split(
            "#else", 1
        )[0]
        assert "&bytes_written, 120);" in tx
        assert "pdMS_TO_TICKS" not in tx
        assert "bytes_written = 0;" in installer
        assert "bytes_written % sizeof(int32_t) != 0" in installer
        assert "bytes_written > static_cast<size_t>(samples)" in installer

    def test_partial_i2s_speaker_output_is_a_sticky_integrity_failure(self):
        """An I2S timeout is not a completed spoken turn or valid AEC frame."""
        header = (HEAD / "sense/sense_reference_codec.h").read_text()
        code = (HEAD / "sense/sense_reference_codec.cc").read_text()
        writer = code.split("int SenseReferenceCodec::Write(", 1)[1].split(
            "void SenseReferenceCodec::ClearReference()", 1
        )[0]
        self.assertIn("uint32_t short_output_writes;", header)
        self.assertIn("uint32_t short_output_writes_ = 0;", header)
        self.assertIn("uint32_t microphone_frames_read_ = 0;", header)
        self.assertIn("uint32_t speaker_frames_accepted_ = 0;", header)
        self.assertIn("microphone_frames_read_ += std::min(", code)
        self.assertIn("speaker_frames_accepted_ += std::min(", writer)
        self.assertIn("if (accepted != samples)", writer)
        self.assertLess(
            writer.index("if (accepted != samples)"),
            writer.index("if (accepted > 0 && started_generation"),
        )
        self.assertIn("if (short_output_writes_ != UINT32_MAX)", writer)
        self.assertIn("reference_integrity_failed_ = true;", writer)
        self.assertNotIn("ESP_LOG", writer)
        self.assertIn("stale_publish_discards_, short_output_writes_", code)
        clear = code.split("void SenseReferenceCodec::ClearReference()", 1)[1].split(
            "SenseReferenceCodec::ReferenceDiagnostics", 1
        )[0]
        self.assertNotIn("short_output_writes_ = 0", clear)

    def test_reference_capture_reuses_bounded_scratch_without_heap_churn(self):
        """Static ownership contract; firmware compile verifies C++ integration."""
        header = (HEAD / "sense/sense_reference_codec.h").read_text()
        code = (HEAD / "sense/sense_reference_codec.cc").read_text()
        read = code.split("int SenseReferenceCodec::Read(", 1)[1].split(
            "int SenseReferenceCodec::Write(", 1
        )[0]
        self.assertIn("static constexpr int kMaxReadFrames = 2048;", header)
        self.assertIn("std::array<int16_t, kMaxReadFrames> microphone_frame_{};", header)
        self.assertIn("std::array<int16_t, kMaxReadFrames> reference_frame_{};", header)
        self.assertIn("std::lock_guard<std::mutex> input_lock(input_read_mutex_);", read)
        self.assertIn("if (frames > kMaxReadFrames) return 0;", read)
        self.assertIn("NoAudioCodecSimplexPdm::Read(microphone_frame_.data(), frames)", read)
        self.assertIn("reference_frame_.data(), frames, capture_end_us)", read)
        helper = code.split("bool SenseReferenceCodec::ReadReferenceLocked(", 1)[1].split(
            "int SenseReferenceCodec::Read(", 1
        )[0]
        self.assertIn("reference_clock_.future_reference_frames(", helper)
        self.assertIn("now_us, kRingSize", helper)
        self.assertNotIn("std::vector<int16_t>", read)


    def test_reference_underflow_diagnostics_are_nonblocking(self):
        """Source-level diagnostic coverage, not acoustic qualification."""
        header = (HEAD / "sense/sense_reference_codec.h").read_text()
        code = (HEAD / "sense/sense_reference_codec.cc").read_text()
        self.assertIn("bool ReadReferenceLocked(int16_t* dest, int frames, int64_t now_us);", header)
        self.assertIn("uint32_t missing_reference_reads_ = 0;", header)
        self.assertIn("uint32_t consecutive_missing_reference_reads_ = 0;", header)
        self.assertIn("required > kRingSize || write_index_ < required", code)
        self.assertIn("++missing_reference_reads_;", code)
        self.assertIn("++consecutive_missing_reference_reads_;", code)
        self.assertIn("std::fill_n(dest, frames, 0);", code)
        self.assertIn("consecutive_missing_reference_reads_ = 0;", code)
        self.assertIn("consecutive_missing_reference_reads_ >= 32", code)
        self.assertNotIn("ESP_LOG", code)
        # A diagnostic must not unilaterally mark hardware AEC as qualified.
        self.assertNotIn("aec_physically_verified = true", code)

    def test_reference_ring_lap_is_a_failed_aec_integrity_event(self):
        """Source contract for real codec counters, not an acoustic result."""
        header = (HEAD / "sense/sense_reference_codec.h").read_text()
        code = (HEAD / "sense/sense_reference_codec.cc").read_text()
        self.assertIn("uint32_t reference_overwrite_reads_ = 0;", header)
        self.assertIn("bool reference_integrity_failed_ = false;", header)
        self.assertIn("GetReferenceDiagnostics()", header)
        self.assertIn("GetReferenceDiagnostics()", code)
        self.assertIn(
            "write_index_ - last_reference_read_write_index_ >= kRingSize", code
        )
        self.assertIn("reference_integrity_failed_ = true;", code)
        self.assertIn("++reference_overwrite_reads_;", code)
        self.assertIn("last_reference_read_write_index_ = 0;", code)
        # Cancellation resets session tracking, not lifetime failures.
        clear = code.split("void SenseReferenceCodec::ClearReference()", 1)[1].split(
            "SenseReferenceCodec::ReferenceDiagnostics", 1
        )[0]
        self.assertNotIn("reference_overwrite_reads_ = 0;", clear)
        self.assertNotIn("reference_integrity_failed_ = false;", clear)

    def test_overlay_journal_rejects_parent_escape_before_any_restore(self):
        """Untrusted recovery path cannot edit files outside the build clone."""
        overlay.apply(self.root, 'sense')
        marker = self.root / overlay.MARKER
        state = json.loads(marker.read_text())
        known_path = 'main/audio/audio_service.cc'
        valid_bytes = (self.root / known_path).read_bytes()
        state['main/../../outside-overwrite.txt'] = state[known_path]
        marker.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'Invalid head overlay journal'):
            overlay.remove(self.root)
        with self.assertRaisesRegex(ValueError, 'Invalid head overlay journal'):
            overlay.apply(self.root, 'sense')
        self.assertTrue(marker.is_file())
        self.assertEqual((self.root / known_path).read_bytes(), valid_bytes)
        del state['main/../../outside-overwrite.txt']
        marker.write_text(json.dumps(state))
        overlay.remove(self.root)

    def test_overlay_journal_rejects_invalid_original_or_external_symlink(self):
        """A forged original or symlinked source cannot become a restore target."""
        overlay.apply(self.root, 'sense')
        marker = self.root / overlay.MARKER
        state = json.loads(marker.read_text())
        known_path = 'main/audio/audio_service.cc'
        old_original = state[known_path]['original']
        state[known_path]['original'] = 'not base64 *'
        marker.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'Invalid original bytes'):
            overlay.remove(self.root)
        state[known_path]['original'] = old_original
        marker.write_text(json.dumps(state))
        with tempfile.TemporaryDirectory() as outside:
            victim = Path(outside) / 'unrelated.cc'
            victim.write_bytes(b'private unrelated source')
            location = self.root / known_path
            location.unlink()
            location.symlink_to(victim)
            with self.assertRaisesRegex(ValueError, 'path escapes pinned checkout'):
                overlay.remove(self.root)
            self.assertEqual(victim.read_bytes(), b'private unrelated source')
            location.unlink()
            location.write_bytes(
                base64.b64decode(old_original)
            )
        overlay.remove(self.root)

    def test_forced_process_exit_leaves_recoverable_overlay_journal(self):
        """A real child process termination must not strand half-patched XiaoZhi."""
        script = """
import importlib.util
import os
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('killed_overlay', sys.argv[1])
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)
root = Path(sys.argv[2])
overlay.subprocess.check_output = (
    lambda args, **kwargs: overlay.PIN if 'rev-parse' in args else ''
)
real_write = overlay.atomic_replace_bytes
def killed_write(path, data):
    real_write(path, data)
    if path != root / overlay.MARKER:
        os._exit(73)
overlay.atomic_replace_bytes = killed_write
overlay.apply(root, 'sense')
"""
        killed = subprocess.run(
            [sys.executable, "-c", script, str(HEAD / "install_overlay.py"),
             str(self.root)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(killed.returncode, 73, killed.stderr)
        marker = self.root / overlay.MARKER
        self.assertTrue(marker.is_file())
        state = json.loads(marker.read_text())
        self.assertTrue(any(
            (self.root / name).is_file()
            and overlay.digest((self.root / name).read_bytes()) == info['sha256']
            for name, info in state.items()
        ))
        overlay.remove(self.root)
        self.assertFalse(marker.exists())
        for name, original in self.original.items():
            self.assertEqual((self.root / name).read_bytes(), original)
        overlay.apply(self.root, 'sense')
        overlay.remove(self.root)

    def test_overlay_journal_precedes_atomic_file_update_and_rolls_back(self):
        """A failed patch must leave neither altered upstream nor an orphan marker."""
        marker = self.root / overlay.MARKER
        writer = overlay.atomic_replace_bytes
        observed = []

        def fail_after_one_replace(path, data):
            writer(path, data)
            if path != marker and not observed:
                self.assertTrue(marker.is_file())
                observed.append(path)
                raise OSError('synthetic write failure after atomic replacement')

        with patch.object(overlay, 'atomic_replace_bytes',
                          side_effect=fail_after_one_replace):
            with self.assertRaisesRegex(OSError, 'synthetic write failure'):
                overlay.apply(self.root, 'sense')
        self.assertEqual(len(observed), 1)
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / overlay.BOARDS['sense']).exists())
        for name, original in self.original.items():
            self.assertEqual((self.root / name).read_bytes(), original)

    def test_partial_overlay_install_removes_original_and_missing_new_files(self):
        """A crash after marker creation must not strand the pinned clone."""
        overlay.apply(self.root, 'sense')
        marker = self.root / overlay.MARKER
        state = json.loads(marker.read_text())
        # A half-applied transaction left a patched upstream file untouched
        # and a brand-new board file uncreated.
        restored = 'main/audio/audio_service.cc'
        self.assertIn(restored, state)
        self.assertIsNotNone(state[restored]['original'])
        (self.root / restored).write_bytes(
            base64.b64decode(state[restored]['original'])
        )
        new_file = next(
            name for name, info in state.items()
            if info['original'] is None and name.endswith('/config.h')
        )
        (self.root / new_file).unlink()
        # A killed atomic replacement may strand a private partial temp.
        staging = (self.root / new_file).with_name(
            '.config.h.desk-overlay-synthetic'
        )
        staging.write_bytes(b'partial unpublished bytes')
        with self.assertRaisesRegex(ValueError, 'drift'):
            overlay.apply(self.root, 'sense')
        overlay.remove(self.root)
        self.assertFalse(marker.exists())
        self.assertFalse(staging.exists())
        self.assertFalse((self.root / overlay.BOARDS['sense']).exists())
        for name, original in self.original.items():
            self.assertEqual((self.root / name).read_bytes(), original)
        # Recovery permits the exact same pinned overlay to be applied again.
        overlay.apply(self.root, 'sense')
        self.assertTrue((self.root / new_file).is_file())
        overlay.remove(self.root)

    def test_partial_overlay_recovery_rejects_foreign_modification_atomically(self):
        """Recovery may not overwrite a true local edit in any overlay file."""
        overlay.apply(self.root, 'sense')
        marker = self.root / overlay.MARKER
        state = json.loads(marker.read_text())
        restored = 'main/audio/audio_service.cc'
        (self.root / restored).write_bytes(
            base64.b64decode(state[restored]['original'])
        )
        changed = self.root / 'main/application.cc'
        changed.write_bytes(changed.read_bytes() + b'// changed locally\\n')
        old_bytes = (self.root / restored).read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed'):
            overlay.remove(self.root)
        self.assertTrue(marker.exists())
        self.assertEqual((self.root / restored).read_bytes(), old_bytes)

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
    def test_native_jpeg_sensor_path_keeps_aec_and_camera_buffers_bounded(self):
        # This source contract checks the pinned Xiaozhi JPEG passthrough.
        # It does NOT measure real ESP32 PSRAM, capture FPS or audio glitches.
        board = (HEAD / "sense/desk_robot_sense.cc").read_text()
        snapshot = (HEAD / "modular_snapshot.inc").read_text()
        installer = (HEAD / "install_overlay.py").read_text()
        self.assertIn("config.pixel_format = PIXFORMAT_JPEG;", board)
        self.assertNotIn("config.pixel_format = PIXFORMAT_RGB565;", board)
        self.assertIn("config.frame_size = FRAMESIZE_VGA;", board)
        self.assertIn("config.fb_count = 2;", board)
        self.assertIn("config.fb_location = CAMERA_FB_IN_PSRAM;", board)
        self.assertIn("config.grab_mode = CAMERA_GRAB_LATEST;", board)
        self.assertIn("current_fb_->format == PIXFORMAT_JPEG", snapshot)
        self.assertIn("desk_robot::ValidJpegFrame(buf, len)", snapshot)
        self.assertIn("desk_robot::ValidJpegFrame(jpeg, len)", snapshot)
        self.assertIn("return std::vector<uint8_t>(buf, buf + len);", snapshot)
        # Overlay is generated into an isolated pinned Xiaozhi copy.
        self.assertIn('(HERE / "modular_snapshot.inc").read_text()', installer)

    def test_authenticated_stream_reuses_single_camera_and_keeps_http_control_live(self):
        bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
        header = (HEAD / "overlay/robot_bridge.h").read_text()
        assert '"/api/camera.mjpg", HTTP_GET' in bridge
        assert "if (!Authorize(req))" in bridge
        assert 'multipart/x-mixed-replace; boundary=deskrobotframe' in bridge
        assert "httpd_req_async_handler_begin(req, &async_req)" in bridge
        assert "httpd_req_async_handler_complete(req)" in bridge
        assert "CameraStreamTask" in bridge and "CameraStreamTask" in header
        assert bridge.count("camera_->SnapshotJpeg()") == 2
        # Both HTTP routes must reject invalid JPEG framing before publication.
        assert "else if (!CompleteJpeg(jpeg->data(), jpeg->size()))" in bridge
        assert "if (!jpeg || !CompleteJpeg(jpeg->data(), jpeg->size()))" in bridge
        assert "camera_busy_.exchange(true)" in bridge
        assert "camera_busy_.store(false)" in bridge
        assert "vTaskDelay(pdMS_TO_TICKS(250))" in bridge
        assert "httpd_resp_send_chunk(req" in bridge
        assert "X-Desk-Camera-Sequence: %u" in bridge
        assert "X-Desk-Camera-Complete-Us: %lld" in bridge
        assert 'config.max_uri_handlers = 15;' in bridge
        assert '{"/api/pose", HTTP_GET}' in bridge
        assert '"/api/camera.identity", HTTP_GET' in bridge

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
                # A timer scheduled just before uint32 wrap must not fire
                # immediately, nor become stuck when its deadline wraps to 0.
                ' HsmBehavior picker(6);\n'
                ' picker.pick_min_ms = 200; picker.pick_max_ms = 200;\n'
                ' picker.update({0xfffffff0u});\n'
                ' if (!picker.update({0xfffffff1u}).empty()) return 5;\n'
                # The picker may select a smile, which has no physical motion.
                # Seed 2 deliberately selects that non-motion idle action.
                ' if (picker.update({0x000000b8u}).empty()) return 6;\n'
                ' HsmBehavior mood(4);\n'
                ' mood.pick_min_ms = 10000; mood.pick_max_ms = 10000;\n'
                ' mood.surprised_ms = 32;\n'
                ' mood.update({0xfffffff0u});\n'
                ' mood.pushEvent(Event(EventType::kLoudSound));\n'
                ' if (mood.update({0xfffffff0u}).mood != Mood::kSurprised) return 7;\n'
                ' if (!mood.update({0xfffffff1u}).empty()) return 8;\n'
                ' auto ended = mood.update({0x00000010u});\n'
                ' if (!ended.set_mood || ended.mood != Mood::kNeutral) return 9;\n'
                ' HsmBehavior exactly_zero(4);\n'
                ' exactly_zero.pick_min_ms = 10000; exactly_zero.pick_max_ms = 10000;\n'
                ' exactly_zero.surprised_ms = 16;\n'
                ' exactly_zero.update({0xfffffff0u});\n'
                ' exactly_zero.pushEvent(Event(EventType::kLoudSound));\n'
                ' exactly_zero.update({0xfffffff0u});\n'
                ' auto at_zero = exactly_zero.update({0u});\n'
                ' if (!at_zero.set_mood || at_zero.mood != Mood::kNeutral) return 10;\n'
                # Five minutes without a Mac or human event must preserve
                # local expression and silence. Physical OLED timing still
                # needs to be measured on the assembled Sense head.
                ' HsmBehavior offline(23);\n'
                ' offline.update({1u});\n'
                ' bool changed = false;\n'
                ' for (uint32_t ms = 101; ms <= 300001; ms += 100) {\n'
                '   auto a = offline.update({ms});\n'
                '   if (a.set_speech || a.speech[0] != 0) return 11;\n'
                '   changed = changed || a.set_mood;\n'
                ' }\n'
                ' if (!changed) return 12;\n'
                # A real visual cue must wake the sleeping OLED, but cannot
                # start speech or override a low-battery state.
                ' HsmBehavior seen(31);\n'
                ' seen.sleep_after_ms = 1000;\n'
                ' seen.pick_min_ms = 10000; seen.pick_max_ms = 10000;\n'
                ' seen.update({10u});\n'
                ' seen.update({1110u});\n'
                ' if (seen.state() != State::kSleeping) return 13;\n'
                ' seen.pushEvent(Event(EventType::kPersonDetected));\n'
                ' auto awake = seen.update({1210u});\n'
                ' if (seen.state() != State::kAttentive) return 14;\n'
                ' if (!awake.set_mood || awake.mood != Mood::kNeutral) return 15;\n'
                ' if (awake.set_speech || awake.speech[0] != 0) return 16;\n'
                ' HsmBehavior low(32);\n'
                ' low.update({0u});\n'
                ' low.pushEvent(Event(EventType::kBatteryLow));\n'
                ' low.update({100u});\n'
                ' low.pushEvent(Event(EventType::kPersonDetected));\n'
                ' low.update({200u});\n'
                ' if (low.state() != State::kLowBattery) return 17;\n'
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
        # The selected inexpensive VL53L0X uses 8-bit registers. The
        # earlier VL53L4CD ULD 16-bit addresses were superseded and must
        # not be used by the actual safety scanner.
        self.assertIn("read_register(0x13, &ready, 1)", tof)
        self.assertIn("(ready & 0x07U) == 0", tof)
        self.assertIn("read_register(0x14, result, kMaxSampleBytes)", tof)
        result_header = (body / "lib/TofBus/TofResult.h").read_text()
        limits_header = (body / "include/TofWireLimits.h").read_text()
        self.assertIn("decode_tof_result(result)", tof)
        self.assertIn("((status & 0x78U) >> 3) == 11U", result_header)
        self.assertIn("tof_range_in_bounds(distance)", result_header)
        self.assertIn("constexpr std::uint16_t kTofMinRangeMm = 30U;", limits_header)
        self.assertIn("constexpr std::uint16_t kTofMaxRangeMm = 1300U;", limits_header)
        self.assertIn("!write_byte(0x0B, 0x01)", tof)
        self.assertNotIn("read_register(0x0031", tof)
        self.assertNotIn("!write_byte(0x0086", tof)

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
            python.write_text(
                f'#!{sys.executable}\nimport json,os,sys\n'
                'if sys.argv[1:2]==["-c"]:\n exec(sys.argv[2])\nelse:\n'
                ' open(os.environ["TRACE_PATH"],"w").write(json.dumps(sys.argv[1:]))\n'
            )
            python.chmod(0o755)
            export = root / '.tools/esp-idf/export.sh'
            export.parent.mkdir(parents=True)
            export.write_text(':\n')
            sdk = export.parent
            subprocess.run(['git', '-C', str(sdk), 'init', '-q'], check=True)
            subprocess.run(['git', '-C', str(sdk), 'add', 'export.sh'], check=True)
            subprocess.run(
                [
                    'git', '-C', str(sdk),
                    '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                    'commit', '-qm', 'locked SDK',
                ],
                check=True,
            )
            sdk_commit = subprocess.check_output(
                ['git', '-C', str(sdk), 'rev-parse', 'HEAD'], text=True
            ).strip()
            (root / 'toolchain-lock.json').write_text(
                json.dumps({'esp_idf': {'commit': sdk_commit}})
            )
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
            self.assertIn('CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED=n', settings)
            self.assertIn('CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED=n', settings)
            args.extend(['--aec-delay-ms', '115'])
            with patch.object(private, 'ROOT', root), patch.object(sys, 'argv', args), \
                    patch.dict(os.environ, SENSE_TEST_TOKEN='x' * 32):
                private.main()
            calibrated = json.loads((board / 'config.private.json').read_text())['builds'][0]['sdkconfig_append']
            self.assertIn('CONFIG_DESK_ROBOT_AEC_DELAY_MS=115', calibrated)
            self.assertNotIn('CONFIG_DESK_ROBOT_AEC_DELAY_MS=90', calibrated)
            # The operator must opt in to always listening on every private
            # build. A prior opt in must not silently survive regeneration.
            args.append('--continuous-audio')
            with patch.object(private, 'ROOT', root), patch.object(sys, 'argv', args), \
                    patch.dict(os.environ, SENSE_TEST_TOKEN='x' * 32):
                private.main()
            live = json.loads((board / 'config.private.json').read_text())['builds'][0]['sdkconfig_append']
            self.assertIn('CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED=y', live)
            self.assertIn('CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED=n', live)
            args.pop()
            with patch.object(private, 'ROOT', root), patch.object(sys, 'argv', args), \
                    patch.dict(os.environ, SENSE_TEST_TOKEN='x' * 32):
                private.main()
            muted = json.loads((board / 'config.private.json').read_text())['builds'][0]['sdkconfig_append']
            self.assertIn('CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED=n', muted)
            args[-1] = '251'
            with patch.object(private, 'ROOT', root), patch.object(sys, 'argv', args), \
                    patch.dict(os.environ, SENSE_TEST_TOKEN='x' * 32), \
                    self.assertRaises(SystemExit):
                private.main()
            self.assertIn('CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y', settings)
            self.assertEqual((board / 'config.private.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((board / 'config.json').read_text()), source)
            self.assertFalse((root / 'firmware/head/build/xiaozhi-modular').exists())


def test_authenticated_mac_person_face_cue_is_cosmetic_only():
    """Verify overlay contract; firmware compile tests the actual C++ path."""
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    header = (HEAD / "overlay/robot_bridge.h").read_text()
    board = (HEAD / "sense/desk_robot_sense.cc").read_text()
    assert '{"/api/face", HTTP_POST}' in bridge
    assert 'config.max_uri_handlers = 15;' in bridge
    assert '{"/api/pose", HTTP_GET}' in bridge
    assert '{"/api/audio.reference", HTTP_GET}' in bridge
    assert '{"/api/audio.capture.abort", HTTP_POST}' in bridge
    assert '"speaker_playback_verified", false' in bridge
    assert '"aec_physically_qualified", false' in bridge
    assert '"short_output_writes", d.short_output_writes' in bridge
    assert '"microphone_frames_read", d.microphone_frames_read' in bridge
    assert '"speaker_frames_accepted", d.speaker_frames_accepted' in bridge
    assert '"boot", boot_nonce_' in bridge
    assert 'Bridge robot_bridge(camera_, GetAudioCodec())' in board
    assert '"/api/camera.identity", HTTP_GET' in bridge
    assert 'strcmp(event->valuestring, "person_detected") != 0' in bridge
    # The upstream overlay now uses a bounded one-second atomic timestamp
    # instead of a replayable boolean; match the actual producer/consumer.
    assert 'person_cue_.offer(' in bridge
    assert 'person_cue_.take(' in bridge
    assert 'TimedPersonCue person_cue_{};' in header
    assert 'class TimedPersonCue' in (HEAD / "overlay/robot_protocol.h").read_text()
    assert 'bool TakePersonCue();' in header
    assert 'body_bridge_->TakePersonCue()' in board
    assert 'Event(EventType::kPersonDetected)' in board
    assert 'CosmeticMood Bridge::TakeCosmeticMoodCue()' in bridge
    assert 'cosmetic_mood_.offer(' in bridge
    assert 'CosmeticMoodName(requested_mood)' in board
    assert 'now_ms - model_mood_started_ms >= 1600U' in board
    assert 'priority_active || !face_available' in board
    assert 'board->local_eye_display_->SetLocalStatus(local_status);' in board
    assert 'Event(EventType::kPersonDetected)' in board
    assert 'body_unhealthy ? "sad" :' not in board
    assert 'person_cue_active ? "surprised" :' not in board
    assert 'Transact(event' not in bridge  # never send cue to WROOM


def test_face_dispatch_requires_live_sense_consumer():
    """Compile and exercise the actual route branch for each head profile."""
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    start = bridge.index('    if (strcmp(req->uri, "/api/face") == 0) {')
    end = bridge.index('    auto item = cJSON_GetObjectItemCaseSensitive(json.get(), "command");', start)
    route = bridge[start:end]
    harness = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
struct Request { const char* uri = "/api/face"; };
struct Event { const char* valuestring; };
struct Document { Event event; Event* get() { return &event; } };
Event* cJSON_GetObjectItemCaseSensitive(Event* event, const char*) { return event; }
bool cJSON_IsString(Event* event) { return event != nullptr; }
enum class CosmeticMood { kNone, kHappy };
CosmeticMood ParseCosmeticMood(const char* event) {
    return std::strcmp(event, "mood:happy") == 0 ? CosmeticMood::kHappy : CosmeticMood::kNone;
}
std::int64_t esp_timer_get_time() { return 1000; }
bool Envelope(bool ok, const char*) { return ok; }
int Json(Request*, int status, bool ok) { assert(ok == (status == 200)); return status; }
struct Cue {
    int count = 0;
    template <typename... Args> void offer(Args...) { ++count; }
};
struct Harness {
    Cue person_cue_, cosmetic_mood_;
    std::atomic<bool> face_consumer_available_{false};
    void SetFaceConsumerAvailable(bool available) {
        face_consumer_available_.store(available, std::memory_order_release);
    }
    bool FaceConsumerAvailable() const {
        return face_consumer_available_.load(std::memory_order_acquire);
    }
    int dispatch(const char* value) {
        Request request;
        auto* req = &request;
        [[maybe_unused]] Document json{{value}};
''' + route + r'''
        return 500;
    }
};
int main() {
    Harness bridge;
    assert(bridge.dispatch("person_detected") == 503);
    assert(bridge.dispatch("mood:happy") == 503);
    assert(bridge.person_cue_.count == 0 && bridge.cosmetic_mood_.count == 0);
    bridge.SetFaceConsumerAvailable(true);
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
    assert(bridge.dispatch("person_detected") == 200);
    assert(bridge.dispatch("mood:happy") == 200);
    assert(bridge.dispatch("not_a_cue") == 400);
    assert(bridge.person_cue_.count == 1 && bridge.cosmetic_mood_.count == 1);
    bridge.SetFaceConsumerAvailable(false);
    assert(bridge.dispatch("person_detected") == 503);
    assert(bridge.dispatch("mood:happy") == 503);
    assert(bridge.person_cue_.count == 1 && bridge.cosmetic_mood_.count == 1);
#else
    assert(bridge.dispatch("person_detected") == 503);
    assert(bridge.dispatch("mood:happy") == 503);
    assert(bridge.person_cue_.count == 0 && bridge.cosmetic_mood_.count == 0);
#endif
}
'''
    compiler = shutil.which("c++")
    assert compiler is not None, "A native C++ compiler is required"
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    with tempfile.TemporaryDirectory() as temp:
        source = Path(temp) / "face_profile.cc"
        exe = Path(temp) / "face_profile"
        source.write_text(harness)
        for profile in ("SENSE_S3", "MODULAR_S3", "WAVESHARE_S3_CAM", "CORE_S3"):
            subprocess.run(
                [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                 "-fsanitize=address,undefined", *pie_flags,
                 f"-DCONFIG_BOARD_TYPE_DESK_ROBOT_{profile}=1", str(source), "-o", str(exe)],
                check=True, env=native_cpp_env(),
            )
            subprocess.run([str(exe)], check=True)


def test_sense_fault_face_overrides_idle_moods_and_recovers_once():
    """The local OLED cannot smile through a current WROOM safety fault."""
    board = (HEAD / "sense/desk_robot_sense.cc").read_text()
    face = board.split("static void FaceTask(void* context)", 1)[1].split(
        "void InitializeDisplay()", 1
    )[0]
    assert 'if (priority_active) {' in face
    fault = face.split('if (priority_active) {', 2)[-1].split(
        '} else if (!voice_link_lost', 1
    )[0]
    # Motor safety is factual; a fault must not force scripted sadness.
    assert 'SetEmotion("sad")' not in fault
    renderer = (HEAD / "overlay/face_eye_display.hpp").read_text()
    assert "if (!lock || status == local_status_) return;" in renderer
    assert 'OledDisplay::SetEmotion("neutral");' in renderer
    assert 'model_mood_active = false;' in fault
    # Recovery must force a neutral/local HSM face refresh even if its
    # idle picker emitted no new mood. No 100 ms continuous OLED spam.
    assert 'if (last_priority_active || model_mood_active ||' in face
    assert 'last_priority_active = priority_active;' in face
    assert "board->local_eye_display_->SetLocalStatus(local_status);" in face



def test_boot_microphone_privacy_has_own_local_oled_status():
    """Physical BOOT mic privacy must not be confused with speaker volume."""
    board = (HEAD / "sense/desk_robot_sense.cc").read_text()
    face = board.split("static void FaceTask(void* context)", 1)[1].split(
        "void InitializeDisplay()", 1
    )[0]
    renderer = (HEAD / "overlay/face_eye_display.hpp").read_text()
    assert 'audio_operator_muted_.load(' in face
    assert 'body_unhealthy, dock_lockout, mic_privacy_on' in face
    assert 'case FaceStatus::kMicPrivacy: status = "Mic privacy ON";' in renderer
    assert "face_available && !priority_active && !model_mood_active" in face
    assert "priority_active || !isAwake(board->face_behavior_.state())" in face
    assert "app.ToggleChatState();" not in face.split(
        "const bool mic_privacy_on = ", 1
    )[1]



def test_playback_reference_clock_native_cpp_regression():
    """Compile the same pure C++ clock the Sense firmware uses, not a Python model."""
    compiler = shutil.which("c++")
    assert compiler is not None, "A native C++17 compiler is required"
    # Reuse the head protocol test's existing tested macOS SDK resolution.
    # Apple clang may find c++ but lack libc++ includes without xcrun.
    native_cpp_env = load_module(
        "sense_native_cpp_env", HEAD / "tests/test_overlay.py"
    ).native_cpp_env
    with tempfile.TemporaryDirectory() as temp:
        exe = Path(temp) / "reference_timeline_test"
        subprocess.run(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
             *test_overlay.native_cpp_sanitizer_flags(),
             "-I", str(HEAD / "sense"),
             str(HEAD / "tests/reference_timeline_test.cc"),
             "-o", str(exe)],
            check=True,
            env=native_cpp_env(),
        )
        subprocess.run([str(exe)], check=True)


def test_reference_decimator_native_cpp_regression(tmp_path):
    """Run the same fixed point FIR as the Sense codec against spectral and state invariants."""
    compiler = shutil.which("c++")
    assert compiler is not None, "A native C++17 compiler is required"
    executable = tmp_path / "reference_decimator"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         *test_overlay.native_cpp_sanitizer_flags(),
         "-I", str(HEAD / "sense"),
         str(HEAD / "tests/reference_decimator_test.cc"),
         "-o", str(executable)],
        check=True, env=native_cpp_env(),
    )
    subprocess.run([str(executable)], check=True)


def test_max98357a_output_rate_and_aec_reference_contract():
    """The selected generic MAX98357A excludes 24 kHz LRCLK; preserve AEC timing."""
    config = (HEAD / "sense/config.h").read_text()
    header = (HEAD / "sense/sense_reference_codec.h").read_text()
    codec = (HEAD / "sense/sense_reference_codec.cc").read_text()
    rates = dict(re.findall(r"#define (AUDIO_(?:INPUT|OUTPUT)_SAMPLE_RATE) (\d+)", config))
    output = int(rates["AUDIO_OUTPUT_SAMPLE_RATE"])
    microphone = int(rates["AUDIO_INPUT_SAMPLE_RATE"])
    # Analog Devices MAX98357A/MAX98357B data sheet, Rev 16, page 16.
    assert output in {8000, 16000, 32000, 44100, 48000, 88200, 96000}
    assert output == 32000 and microphone == 16000
    assert "static constexpr uint32_t kSpeakerRate = 32000;" in header
    assert "static constexpr uint32_t kMicRate = 16000;" in header
    assert "kSpeakerRate == 2 * kMicRate" in header
    assert "static_assert(AUDIO_INPUT_SAMPLE_RATE == kMicRate" in header
    assert "static_assert(AUDIO_OUTPUT_SAMPLE_RATE == kSpeakerRate" in header
    # The fixed 2:1 ratio permits zero or one publish per output sample,
    # never a misleading loop over unsupported fractional rate profiles.
    assert "reference_decimator_.Push(scaled, filtered)" in codec
    assert "reference_decimator_.ClearHistory();" in codec
    assert "reference_decimator_.Reset();" in codec
    assert "samples > static_cast<int>(kSpeakerRate)" in codec
    # Audio chunks have a virtual playback END, so the 10 ms Read cadence
    # cannot count the 60 ms reference data a second time.
    assert "last_write_us_" not in codec
    assert "reference_clock_.silence_frames(now_us, kMaxGapSamples)" in codec
    assert "reference_clock_.accepted_output_frames(samples)" in codec
    assert "reference_clock_.reset()" in codec
    assert "future_reference_frames(" in (HEAD / "sense/reference_timeline.h").read_text()
    assert "const uint64_t required =" in codec
    assert '#include "reference_timeline.h"' in header

    def accepted_reference_samples(read_period_ms):
        end_us = 0
        pushed = 0
        for now_us in range(0, 60_000_000, read_period_ms * 1000):
            # Model the same virtual end clock for the Read/Write operations.
            if now_us > end_us:
                pushed += (now_us - end_us) * 16000 // 1_000_000
                end_us = now_us
            if now_us % 60_000 == 0:
                pushed += 960
                end_us += 60_000
        return pushed

    for cadence_ms in (10, 20, 30, 60):
        assert accepted_reference_samples(cadence_ms) == 960_000
    overlay_source = (HEAD / "install_overlay.py").read_text()
    assert "initial_decoder_rate = 24000" in overlay_source
    assert "esp_ae_rate_cvt_open(&cfg, &output_resampler_)" in overlay_source
    assert "Speaker resampler unavailable" in overlay_source
    # Runtime resampling uses the pinned Xiaozhi decoder, not another audio stack.
    if UPSTREAM.is_dir():
        upstream = (UPSTREAM / "main/audio/audio_service.cc").read_text()
        assert "SetDecodeSampleRate(packet->sample_rate, packet->frame_duration)" in upstream
        assert "RATE_CVT_CFG(decoder_sample_rate_, codec->output_sample_rate()" in upstream

def test_sense_face_discards_person_cues_received_during_body_fault():
    """Consume cues during a WROOM fault without replaying after recovery."""
    board = (HEAD / "sense/desk_robot_sense.cc").read_text()
    face = board.split("static void FaceTask(void* context)", 1)[1].split(
        "void InitializeDisplay()", 1
    )[0]
    # Short circuit left to right: TakePersonCue must run even when the
    # body is unhealthy, and the HSM may see an event only for a good body.
    assert (
        "board->body_bridge_->TakePersonCue() &&\\n"
        "                !body_unhealthy"
    ).replace("\\n", "\n") in face
    assert "Event(EventType::kPersonDetected)" in face
    # Do not regress to a fixed surprise response or stale cue timer.
    assert "person_cue_until_ms" not in face
    assert 'person_cue_active ? "surprised"' not in face
    # A local status fault stays factual and never becomes a motor command.
    assert 'board->local_eye_display_->SetLocalStatus(local_status);' in face
    assert "Transact(event" not in (HEAD / "overlay/robot_bridge.cc").read_text()

def test_body_status_is_async_and_urgent_stop_preempts_uart_telemetry():
    """A body read cannot monopolize the HTTP handler or STOP priority."""
    source = (HEAD / "overlay/robot_bridge.cc").read_text()
    header = (HEAD / "overlay/robot_bridge.h").read_text()
    protocol = (HEAD / "overlay/robot_protocol.h").read_text()
    assert "UrgentStopGate urgent_stop_gate_" in header
    assert "std::atomic<bool> body_read_busy_" in header
    assert "UrgentStopGate::Request urgency(urgent_stop_gate_, urgent);" in source
    assert source.index("UrgentStopGate::Request urgency") < source.index(
        "std::lock_guard<std::mutex> lock(uart_mutex_)"
    )
    assert source.count("if (urgency.preempted())") == 3
    assert source.index("if (urgency.preempted())") < source.index("uart_write_bytes(")
    assert "void Bridge::BodyReadTask(void* context)" in source
    assert 'xTaskCreate(BodyReadTask, "robot_body_read"' in source
    assert "httpd_req_async_handler_begin(req, &async_req)" in source
    assert "httpd_req_async_handler_complete(req);" in source
    assert "class UrgentStopGate" in protocol
    assert "Request(const Request&) = delete;" in protocol


def test_reference_silence_gap_retires_filter_history(tmp_path):
    """Exercise the actual publishing methods with the production reference clock."""
    codec = (HEAD / "sense/sense_reference_codec.cc").read_text()
    methods = "void SenseReferenceCodec::PushLocked(" + codec.split(
        "void SenseReferenceCodec::PushLocked(", 1
    )[1].split("bool SenseReferenceCodec::ReadReferenceLocked(", 1)[0]
    harness = r"""
#include "reference_timeline.h"
#include "reference_decimator.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>

struct SenseReferenceCodec {
    static constexpr uint32_t kRingSize = 16384, kMaxGapSamples = kRingSize;
    static constexpr uint32_t kSpeakerRate = 32000, kMicRate = 16000;
    std::array<int16_t, kRingSize> reference_{};
    uint64_t write_index_ = 0;
    bool reference_integrity_failed_ = false;
    desk_robot::PlaybackReferenceClock reference_clock_{};
    struct SpeechLevelStub {
        void Reset() {}
        void Publish(uint64_t, int, int64_t) {}
    } speech_level_;
    desk_robot::ReferenceDecimator reference_decimator_{};
    void PushLocked(int16_t sample);
    void FillSilenceLocked(int64_t now_us);
    void PublishAcceptedLocked(const int32_t* source, int samples, int64_t now_us);
};
""" + methods + r"""
int main() {
    std::array<int32_t, 1920> loud{}, quiet{};
    loud.fill(16000 * 65536);
    SenseReferenceCodec gap;
    gap.PublishAcceptedLocked(loud.data(), loud.size(), 1000000);
    assert(gap.write_index_ == 960);
    assert(gap.reference_[959] == 16000);
    // A PDM read fills the 40 ms gap before a subsequent write arrives.
    gap.FillSilenceLocked(1100000);
    gap.PublishAcceptedLocked(quiet.data(), quiet.size(), 1100000);
    assert(gap.write_index_ == 2560);
    assert(std::all_of(gap.reference_.begin() + 960,
                       gap.reference_.begin() + 2560,
                       [](int16_t sample) { return sample == 0; }));
    // Partial odd-sized acceptance: the unaccepted suffix must never enter
    // the reference. A later gap is digital silence, not comfort noise.
    for (int polarity : {-1, 1}) {
        std::array<int32_t, 1920> packet{}, quiet{};
        packet.fill(-polarity * 16000 * 65536);
        std::fill_n(packet.begin(), 959, polarity * 16000 * 65536);
        SenseReferenceCodec partial;
        partial.PublishAcceptedLocked(packet.data(), 959, 1000000);
        assert(partial.write_index_ == 480);
        assert(partial.reference_[479] == polarity * 16000);
        partial.FillSilenceLocked(1040000);
        assert(partial.write_index_ == 640);
        partial.PublishAcceptedLocked(quiet.data(), 1, 1040000);
        assert(partial.write_index_ == 640);
        partial.PublishAcceptedLocked(quiet.data() + 1, 1919, 1040000);
        assert(partial.write_index_ == 1600);
        assert(std::all_of(partial.reference_.begin() + 480,
                           partial.reference_.begin() + 1600,
                           [](int16_t sample) { return sample == 0; }));
    }
    // No gap: chunk boundaries, even odd-sized writes, must preserve phase
    // and filter history. Compare against one uninterrupted accepted chunk.
    SenseReferenceCodec whole, split;
    whole.PublishAcceptedLocked(loud.data(), loud.size(), 1000000);
    split.PublishAcceptedLocked(loud.data(), 1, 1000000);
    split.PublishAcceptedLocked(loud.data() + 1, loud.size() - 1, 1000000);
    assert(whole.write_index_ == split.write_index_);
    assert(whole.reference_ == split.reference_);
}
"""
    source = tmp_path / "reference_gap.cc"
    source.write_text(harness)
    compiler = shutil.which("c++")
    assert compiler is not None, "A native C++17 compiler is required"
    executable = tmp_path / "reference_gap"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-I", str(HEAD / "sense"), str(source), "-o", str(executable)],
        check=True, env=native_cpp_env(),
    )
    subprocess.run([str(executable)], check=True)


def test_reference_ring_lap_is_checked_even_on_unavailable_reads(tmp_path):
    """Execute the production ring read method with deterministic clock and ring state."""
    codec = (HEAD / "sense/sense_reference_codec.cc").read_text()
    method = "bool SenseReferenceCodec::ReadReferenceLocked(" + codec.split(
        "bool SenseReferenceCodec::ReadReferenceLocked(", 1
    )[1].split("int SenseReferenceCodec::Read(", 1)[0]
    harness = r"""
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
struct SenseReferenceCodec {
    static constexpr uint64_t kRingSize = 16384, kDelaySamples = 0;
    struct Clock {
        uint64_t future = 0;
        uint64_t future_reference_frames(int64_t, uint64_t cap) const {
            return std::min(future, cap);
        }
    } reference_clock_;
    uint64_t write_index_ = 0, last_reference_read_write_index_ = 0;
    uint32_t missing_reference_reads_ = 0, consecutive_missing_reference_reads_ = 0;
    uint32_t reference_overwrite_reads_ = 0;
    bool reference_integrity_failed_ = false, reference_read_seen_ = false;
    std::array<int16_t, kRingSize> reference_{};
    bool ReadReferenceLocked(int16_t* dest, int frames, int64_t now_us);
};
""" + method + r"""
int main() {
    constexpr uint64_t ring = SenseReferenceCodec::kRingSize;
    std::array<int16_t, 160> out{};
    SenseReferenceCodec codec;
    codec.reference_.fill(123);
    codec.write_index_ = 160;
    assert(codec.ReadReferenceLocked(out.data(), out.size(), 10000));
    assert(out[0] == 123);
    codec.write_index_ += ring;
    codec.reference_clock_.future = ring;
    assert(!codec.ReadReferenceLocked(out.data(), out.size(), 20000));
    assert(codec.reference_overwrite_reads_ == 1);
    assert(codec.missing_reference_reads_ == 1);
    assert(codec.reference_integrity_failed_);
    assert(std::all_of(out.begin(), out.end(), [](auto v) { return v == 0; }));
    codec.reference_clock_.future = 0;
    assert(codec.ReadReferenceLocked(out.data(), out.size(), 30000));
    assert(codec.reference_overwrite_reads_ == 1);
    assert(codec.reference_integrity_failed_);
    SenseReferenceCodec startup;
    startup.reference_clock_.future = ring;
    assert(!startup.ReadReferenceLocked(out.data(), out.size(), 10000));
    startup.write_index_ = ring;
    assert(!startup.ReadReferenceLocked(out.data(), out.size(), 20000));
    assert(startup.reference_overwrite_reads_ == 1);
    assert(startup.reference_integrity_failed_);
    SenseReferenceCodec consecutive;
    consecutive.reference_clock_.future = ring;
    for (uint64_t i = 0; i < 3; ++i) {
        consecutive.write_index_ = i * (ring / 2);
        assert(!consecutive.ReadReferenceLocked(out.data(), out.size(), 10000));
    }
    consecutive.reference_clock_.future = 0;
    assert(consecutive.ReadReferenceLocked(out.data(), out.size(), 20000));
    assert(consecutive.reference_overwrite_reads_ == 0);

    // Distinct values and a window straddling the physical ring boundary
    // expose indexing bugs that a ring filled with a constant cannot.
    SenseReferenceCodec wrapped;
    for (uint64_t i = 0; i < ring; ++i)
        wrapped.reference_[i] = static_cast<int16_t>(i + 1);
    wrapped.write_index_ = ring + 80;
    std::array<int16_t, 162> guarded{};
    guarded.fill(-1);
    assert(wrapped.ReadReferenceLocked(guarded.data() + 1, 160, 10000));
    for (uint64_t i = 0; i < 160; ++i)
        assert(guarded[i + 1] == static_cast<int16_t>(((ring - 80 + i) & (ring - 1)) + 1));
    assert(guarded.front() == -1 && guarded.back() == -1);
    // A full lap with an otherwise available window must zero only the
    // requested output and keep the failure latch after later recovery.
    wrapped.write_index_ += ring;
    assert(!wrapped.ReadReferenceLocked(guarded.data() + 1, 160, 20000));
    assert(wrapped.reference_overwrite_reads_ == 1);
    assert(wrapped.missing_reference_reads_ == 0);
    assert(wrapped.reference_integrity_failed_);
    assert(std::all_of(guarded.begin() + 1, guarded.end() - 1,
                       [](auto v) { return v == 0; }));
    assert(guarded.front() == -1 && guarded.back() == -1);
    assert(wrapped.ReadReferenceLocked(guarded.data() + 1, 160, 30000));
    assert(wrapped.reference_integrity_failed_);
    // Tight reads must survive multiple physical wraps. A lag of ring-1
    // is still valid; ring and larger lags must never publish stale PCM.
    SenseReferenceCodec chase;
    chase.reference_.fill(4321);
    for (uint64_t i = 1; i <= 400; ++i) {
        chase.write_index_ = i * out.size();
        assert(chase.ReadReferenceLocked(out.data(), out.size(), i * 10000));
        assert(std::all_of(out.begin(), out.end(), [](auto v) { return v == 4321; }));
    }
    chase.write_index_ += ring - 1;
    assert(chase.ReadReferenceLocked(out.data(), out.size(), 4010000));
    assert(chase.reference_overwrite_reads_ == 0);
    assert(!chase.reference_integrity_failed_);
    for (uint64_t lag : {ring, ring + 1, 3 * ring + 17}) {
        chase.write_index_ += lag;
        out.fill(-1);
        assert(!chase.ReadReferenceLocked(out.data(), out.size(), 4020000));
        assert(std::all_of(out.begin(), out.end(), [](auto v) { return v == 0; }));
        chase.write_index_ += out.size();
        assert(chase.ReadReferenceLocked(out.data(), out.size(), 4030000));
        assert(std::all_of(out.begin(), out.end(), [](auto v) { return v == 4321; }));
    }
    assert(chase.reference_overwrite_reads_ == 3);
    assert(chase.reference_integrity_failed_);
    assert(chase.missing_reference_reads_ == 0);
    // A startup underflow is allowed briefly, not indefinitely.
    SenseReferenceCodec underflow;
    for (int i = 0; i < 31; ++i)
        assert(!underflow.ReadReferenceLocked(out.data(), out.size(), 10000));
    assert(!underflow.reference_integrity_failed_);
    assert(!underflow.ReadReferenceLocked(out.data(), out.size(), 10000));
    assert(underflow.reference_integrity_failed_);
    assert(underflow.missing_reference_reads_ == 32);
    underflow.missing_reference_reads_ = UINT32_MAX;
    underflow.consecutive_missing_reference_reads_ = UINT32_MAX;
    assert(!underflow.ReadReferenceLocked(out.data(), out.size(), 10000));
    assert(underflow.missing_reference_reads_ == UINT32_MAX);
    assert(underflow.consecutive_missing_reference_reads_ == UINT32_MAX);
    underflow.write_index_ = 160;
    assert(underflow.ReadReferenceLocked(out.data(), out.size(), 20000));
    assert(underflow.consecutive_missing_reference_reads_ == 0);
    assert(underflow.reference_integrity_failed_);
}
"""
    source = tmp_path / "ring_lap.cc"
    source.write_text(harness)
    compiler = shutil.which("c++")
    assert compiler is not None, "A native C++17 compiler is required"
    executable = tmp_path / "ring_lap"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         str(source), "-o", str(executable)],
        check=True, env=native_cpp_env(),
    )
    subprocess.run([str(executable)], check=True)


def test_sense_pcm_window_native_cpp_regression():
    """Compile the same bounded 4s PCM window used by the real Sense codec."""
    compiler = shutil.which("c++")
    assert compiler is not None, "A native C++17 compiler is required"
    native_cpp_env = load_module(
        "sense_pcm_native_env", HEAD / "tests/test_overlay.py"
    ).native_cpp_env
    with tempfile.TemporaryDirectory() as directory:
        exe = Path(directory) / "sense_pcm_window_test"
        subprocess.run(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
             "-I", str(HEAD / "sense"),
             str(HEAD / "tests/sense_pcm_window_test.cc"),
             "-o", str(exe)],
            check=True,
            env=native_cpp_env(),
        )
        subprocess.run([str(exe)], check=True)

def test_sense_pcm_capture_reuses_the_actual_pdm_read_end_clock():
    """Reference selection and private PCM window must share one source time."""
    codec = (HEAD / "sense/sense_reference_codec.cc").read_text()
    read = codec.split("int SenseReferenceCodec::Read(", 1)[1].split(
        "int SenseReferenceCodec::Write(", 1
    )[0]
    timestamp = "const int64_t capture_end_us = esp_timer_get_time();"
    assert read.count(timestamp) == 1
    assert read.index(timestamp) < read.index(
        "std::lock_guard<std::mutex> lock(reference_mutex_);"
    )
    assert "reference_frame_.data(), frames, capture_end_us" in read
    assert "static_cast<uint32_t>(frames), capture_end_us," in read
    # A second later wall-clock read could mask source gaps or overlap.
    assert "static_cast<uint32_t>(frames), esp_timer_get_time()" not in read


def test_short_pdm_read_invalidates_the_private_pcm_window():
    """A known device read failure must not disappear into tolerated timing jitter."""
    codec = (HEAD / "sense/sense_reference_codec.cc").read_text()
    read = codec.split("int SenseReferenceCodec::Read(", 1)[1].split(
        "int SenseReferenceCodec::Write(", 1
    )[0]
    short_read = read.split("if (mic_read != frames) {", 1)[1].split(
        "return 0;", 1
    )[0]
    assert "#ifdef CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED" in short_read
    assert "const int64_t failed_read_us = esp_timer_get_time();" in short_read
    assert short_read.index("failed_read_us = esp_timer_get_time()") < short_read.index(
        "std::lock_guard<std::mutex> lock(bench_mutex_);"
    )
    assert "bench_window_.invalidate_read(failed_read_us);" in short_read
    assert "std::fill_n(microphone_frame_.begin(), frames, 0);" in short_read


def test_private_sense_pcm_bench_requires_explicit_fresh_consent():
    """No private image may inherit earlier raw microphone capture permission."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = root / "fleet.toml"
        config.write_text(
            '[[robots]]\nid="robot-01"\ntoken_env="BENCH_SENSE_TOKEN"\n'
        )
        board = (
            root / "firmware/head/build/xiaozhi-sense/main/boards/"
            "desk-robot/desk-robot-sense-s3"
        )
        board.mkdir(parents=True)
        original = {"builds": [{"sdkconfig_append": ["CONFIG_UNRELATED=y"]}]}
        (board / "config.json").write_text(json.dumps(original))
        base = [
            "private_config.py", "--board", "sense", "--robot", "robot-01",
            "--config", str(config), "--secrets", str(root / "missing.env"),
            "--server-ip", "192.168.1.15",
        ]
        env = {"BENCH_SENSE_TOKEN": "x" * 40}

        def invoke(args):
            with patch.object(private, "ROOT", root), (
                patch.object(sys, "argv", args)
            ), patch.dict(os.environ, env):
                private.main()

        # The capture option alone cannot activate any microphone or output.
        with unittest.TestCase().assertRaises(SystemExit):
            invoke(base + ["--bench-aec-capture"])
        with unittest.TestCase().assertRaises(SystemExit):
            invoke(base + [
                "--continuous-audio", "--bench-aec-capture",
            ])
        with unittest.TestCase().assertRaises(SystemExit):
            invoke(base + [
                "--aec-delay-ms", "0", "--bench-aec-capture",
            ])
        assert not (board / "config.private.json").exists()

        invoke(base + [
            "--continuous-audio", "--aec-delay-ms", "0",
            "--bench-aec-capture",
        ])
        target = board / "config.private.json"
        enabled = json.loads(target.read_text())["builds"][0]["sdkconfig_append"]
        assert "CONFIG_DESK_ROBOT_AEC_DELAY_MS=0" in enabled
        assert "CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED=y" in enabled
        assert "CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED=y" in enabled
        assert target.stat().st_mode & 0o777 == 0o600

        # Regeneration is explicit opt-in each time, even on the same head.
        invoke(base + ["--continuous-audio", "--aec-delay-ms", "0"])
        disabled = json.loads(target.read_text())["builds"][0]["sdkconfig_append"]
        assert "CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED=n" in disabled
        assert "CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED=y" not in disabled
        assert json.loads((board / "config.json").read_text()) == original

def test_private_sense_settings_reject_symlink_without_leaking_device_token():
    """Never follow an attacker-selected output symlink when writing secrets."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = root / "fleet.toml"
        config.write_text(
            '[[robots]]\nid="robot-01"\ntoken_env="BENCH_SENSE_TOKEN"\n'
        )
        board = (
            root / "firmware/head/build/xiaozhi-sense/main/boards/"
            "desk-robot/desk-robot-sense-s3"
        )
        board.mkdir(parents=True)
        (board / "config.json").write_text(json.dumps({
            "builds": [{"sdkconfig_append": ["CONFIG_UNRELATED=y"]}]
        }))
        protected = root / "must-not-receive-token.txt"
        protected.write_text("safe")
        target = board / "config.private.json"
        target.symlink_to(protected)
        args = [
            "private_config.py", "--board", "sense", "--robot", "robot-01",
            "--server-ip", "192.168.1.15", "--config", str(config),
            "--secrets", str(root / "missing.env"),
        ]
        with patch.object(private, "ROOT", root), (
            patch.object(sys, "argv", args)
        ), patch.dict(os.environ, BENCH_SENSE_TOKEN="x" * 40):
            with unittest.TestCase().assertRaises(SystemExit):
                private.main()
        assert target.is_symlink()
        assert protected.read_text() == "safe"
        assert list(board.glob(".config.private.*.tmp")) == []


def test_private_sense_settings_write_failure_keeps_previous_secret_file():
    """A failed atomic swap must preserve the last complete private config."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = root / "fleet.toml"
        config.write_text(
            '[[robots]]\nid="robot-01"\ntoken_env="BENCH_SENSE_TOKEN"\n'
        )
        board = (
            root / "firmware/head/build/xiaozhi-sense/main/boards/"
            "desk-robot/desk-robot-sense-s3"
        )
        board.mkdir(parents=True)
        (board / "config.json").write_text(json.dumps({
            "builds": [{"sdkconfig_append": ["CONFIG_UNRELATED=y"]}]
        }))
        target = board / "config.private.json"
        target.write_text('{"previous":"valid"}')
        target.chmod(0o600)
        args = [
            "private_config.py", "--board", "sense", "--robot", "robot-01",
            "--server-ip", "192.168.1.15", "--config", str(config),
            "--secrets", str(root / "missing.env"),
        ]
        with patch.object(private, "ROOT", root), (
            patch.object(sys, "argv", args)
        ), patch.dict(os.environ, BENCH_SENSE_TOKEN="x" * 40), (
            patch.object(private.os, "replace", side_effect=OSError("disk failed"))
        ):
            with unittest.TestCase().assertRaisesRegex(OSError, "disk failed"):
                private.main()
        assert target.read_text() == '{"previous":"valid"}'
        assert list(board.glob(".config.private.*.tmp")) == []


def test_private_aec_capture_returns_true_http_accept_and_conflict_codes():
    """Successful START and already-active trials cannot masquerade as 500s."""
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    assert 'case 202: status_text = "202 Accepted"; break;' in bridge
    assert 'case 409: status_text = "409 Conflict"; break;' in bridge
    assert '"/api/audio.capture.start"' in bridge
    assert 'return Json(req, 202, Encode(started.get()));' in bridge
    assert 'cJSON_AddStringToObject(started.get(), "capture_generation", generation)' in bridge
    assert 'cJSON_AddStringToObject(data.get(), "capture_generation", generation)' in bridge
    assert '"X-Desk-Audio-Generation"' in bridge
    assert 'Json(req, 409, Envelope(false, "Bench PCM unavailable or already active"))' in bridge
    # Private raw audio must remain behind a selected Sense build flag.
    assert 'defined(CONFIG_DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED)' in bridge

def test_private_pcm_transfer_revoked_by_boot_mute_and_reference_reset():
    """Transferred PCM cannot keep streaming after a consent cancellation."""
    header = (HEAD / "sense/sense_reference_codec.h").read_text()
    codec = (HEAD / "sense/sense_reference_codec.cc").read_text()
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    assert "uint64_t BenchPcmGeneration() const noexcept" in header
    assert "bench_capture_generation_.fetch_add(" in codec
    assert "if (muted) AbortBenchPcmCapture();" in header
    assert "AbortBenchPcmCapture(false);" in codec.split(
        "void SenseReferenceCodec::ClearReference()", 1
    )[1].split("void SenseReferenceCodec::", 1)[0]
    worker = bridge.split("void Bridge::BenchPcmTask(", 1)[1].split(
        "esp_err_t Bridge::Handle(", 1
    )[0]
    assert "transfer->codec->BenchPcmGeneration() == transfer->generation" in worker
    assert "esp_timer_get_time() >= deadline_us || !still_authorized()" in worker
    assert "transfer->codec->EndBenchPcmTransfer();" in worker
    assert "ReleaseBenchPcmCapture(pcm.interleaved)" in worker
    # New raw buffers cannot overlap an outstanding moved HTTP transfer,
    # nor be opened after a physical BOOT privacy mute.
    starter = codec.split("bool SenseReferenceCodec::BeginBenchPcmCapture(", 1)[1]
    starter = starter.split("SenseReferenceCodec::BenchCaptureProgress", 1)[0]
    assert "bench_transfer_active_" in starter
    assert "microphone_privacy_muted_.load(" in starter


def test_sense_hsm_gaze_and_blink_reach_local_locked_oled_without_motor_motion():
    """Native policy regression plus real FaceTask and pinned LVGL ownership checks."""
    source = (HEAD / "sense/desk_robot_sense.cc").read_text()
    renderer = (HEAD / "overlay/face_eye_display.hpp").read_text()
    face = source.split("static void FaceTask(void* context)", 1)[1].split(
        "void InitializeDisplay()", 1
    )[0]
    assert "const Action action = board->face_behavior_.update(obs);" in face
    assert "board->eye_animator_.Step(" in face
    assert "now_ms, action.motion," in face
    assert "face_available && !priority_active && !model_mood_active" in face
    assert "priority_active || !isAwake(board->face_behavior_.state())" in face
    assert "board->local_eye_display_->ShowEyes(eyes);" in face
    assert face.index("board->local_eye_display_->ShowEyes(eyes);") > face.index(
        "board->display_->SetEmotion(CosmeticMoodName(requested_mood))"
    )
    assert "new desk_robot::LocalEyeDisplay(" in source
    assert "display_ = local_eye_display_;" in source
    assert "face_behavior_.pick_min_ms = 6000;" in source
    assert "face_behavior_.pick_max_ms = 15000;" in source
    assert "eye_animator_.Seed(pet_seed);" in source
    assert "void SetupUI() override" in renderer
    assert "OledDisplay::SetupUI();" in renderer
    assert "DisplayLockGuard lock(this);" in renderer
    assert "lv_obj_set_pos(pupil_[i], PupilX(frame.x), PupilY(height, frame.y));" in renderer
    # The upstream 128x64 OLED layout centers its 32px emotion cell.
    # Anchoring at x=0 would leave the stock center emotion visible beside
    # the gaze/blink overlay, even though the HSM/animator tests still pass.
    assert 'lv_obj_set_size(eye_layer_, kSlotWidth, kSlotHeight);' in renderer
    assert 'lv_obj_align(eye_layer_, LV_ALIGN_TOP_MID, 0, kStatusHeight);' in renderer
    assert 'lv_obj_set_pos(eye_layer_, 0, 16);' not in renderer
    assert renderer.index('lv_obj_set_size(eye_layer_, kSlotWidth, kSlotHeight);') < renderer.index(
        'lv_obj_align(eye_layer_, LV_ALIGN_TOP_MID, 0, kStatusHeight);'
    )
    assert not any(word in renderer for word in (
        "command_drive", "MotorDriver", "servo", "uart_write_bytes"
    ))
    compiler = shutil.which("g++") or shutil.which("c++")
    if compiler is None:
        raise unittest.SkipTest("Native C++ compiler unavailable")
    native = r"""
#include "face_eye_animator.hpp"
#include <cassert>
#include <initializer_list>
using namespace desk_robot;
using stackchan::behavior::Motion;
int main() {
    FaceEyeAnimator eyes;
    auto left = eyes.Step(1000, Motion::kLookLeft, true);
    assert(left.visible && left.x == -3 && !left.closed);
    assert(!eyes.Step(2200, Motion::kNone, true).visible);
    uint32_t blink_at = 0;
    for (uint32_t t = 2300; t <= 7000; t += 100) {
        const auto blink = eyes.Step(t, Motion::kNone, true);
        if (blink.visible) {
            assert(!blink.closed);
            blink_at = t;
            break;
        }
    }
    assert(blink_at >= 4000 && blink_at <= 7000);
    assert(eyes.Step(blink_at + 150, Motion::kNone, true).closed);
    assert(!eyes.Step(blink_at + 900, Motion::kNone, true).visible);
    FaceEyeAnimator gaze;
    assert(!gaze.Step(6450, Motion::kLookRight, false).visible);
    assert(!gaze.Step(6500, Motion::kNone, true).visible);
    assert(gaze.Step(6700, Motion::kLookRight, true).x == 3);
    // Interrupting an active gaze eases over kRetargetMs (200 ms) from prior axis.
    assert(gaze.Step(6800, Motion::kLookUp, true).y == 0);
    assert(gaze.Step(7000, Motion::kNone, true).y == -3);
    assert(gaze.Step(7100, Motion::kNod, true).y == -3);
    assert(gaze.Step(7300, Motion::kNone, true).y == 3);
    assert(gaze.Step(7650, Motion::kNone, true).y == -2);
    assert(!gaze.Step(8301, Motion::kNone, true).visible);
    FaceEyeAnimator rollover;
    assert(rollover.Step(0xfffffff0U, Motion::kLookLeft, true).visible);
    assert(rollover.Step(0x40U, Motion::kNone, true).visible);
    // Five offline minutes, including uint32 rollover, at the real task cadence.
    for (uint32_t seed = 0; seed < 1000; ++seed) {
        FaceEyeAnimator offline;
        offline.Seed(seed);
        unsigned blinks = 0;
        bool was_closed = false;
        for (uint32_t elapsed = 0; elapsed <= 300000U; elapsed += 100U) {
            auto frame = offline.Step(0xfffff000U + elapsed, Motion::kNone, true);
            assert(frame.x == 0 && frame.y == 0);
            if (frame.closed && !was_closed) ++blinks;
            assert(!frame.closed || frame.visible);
            was_closed = frame.closed;
        }
        assert(blinks >= 50 && blinks <= 100);
        for (auto motion : {Motion::kLookLeft, Motion::kLookRight, Motion::kLookUp,
                            Motion::kLookDown, Motion::kNod, Motion::kShake}) {
            auto frame = offline.Step(300100U, motion, true);
            assert(frame.visible && frame.x >= -3 && frame.x <= 3);
            assert(frame.y >= -3 && frame.y <= 3);
            assert(!offline.Step(300101U, motion, false).visible);
            assert(!offline.Step(300102U, Motion::kNone, true).visible);
        }
    }
    // The 5s voice reconnect throttle must not starve a longer blink timer.
    using namespace stackchan::behavior;
    HsmBehavior pet(1000);
    pet.pick_min_ms = 6000;
    pet.pick_max_ms = 15000;
    FaceEyeAnimator reconnecting;
    reconnecting.Seed(1000);
    unsigned blink_ticks = 0, gaze_ticks = 0;
    for (uint32_t elapsed = 0; elapsed <= 300000U; elapsed += 100U) {
        const uint32_t now = 0xfffff000U + elapsed;
        const auto action = pet.update({now});
        const bool allowed = elapsed % 5000U < 4500U;
        const auto frame = reconnecting.Step(now, action.motion, allowed);
        assert(!action.set_speech && action.speech[0] == '\0');
        assert(allowed || !frame.visible);
        assert(frame.x >= -3 && frame.x <= 3 && frame.y >= -3 && frame.y <= 3);
        blink_ticks += frame.closed;
        gaze_ticks += frame.visible && (frame.x || frame.y);
    }
    assert(blink_ticks > 20 && gaze_ticks > 0);
    assert(pet.state() == State::kIdle);
    pet.update({0xfffff000U + 300100U});
    assert(pet.state() == State::kSleeping);
    pet.pushEvent(Event(EventType::kPersonDetected));
    const auto awake = pet.update({0xfffff000U + 300200U});
    assert(pet.state() == State::kAttentive && !awake.set_speech);
}
"""
    with tempfile.TemporaryDirectory() as temp:
        cpp = Path(temp) / "eyes.cpp"
        binary = Path(temp) / "eyes"
        cpp.write_text(native)
        subprocess.run([
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I", str(HEAD / "overlay"), str(cpp), "-o", str(binary),
        ], check=True, capture_output=True, text=True, env=native_cpp_env())
        subprocess.run([str(binary)], check=True, capture_output=True, text=True)

def test_sense_builder_readme_matches_selected_local_expression_consumer():
    """Do not call the landed HSM/gaze renderer an unselected stock face."""
    board = (HEAD / "sense/desk_robot_sense.cc").read_text()
    renderer = (HEAD / "overlay/face_eye_display.hpp").read_text()
    instructions = (HEAD / "sense/README.md").read_text()
    assert "const Action action = board->face_behavior_.update(obs);" in board
    assert "now_ms, action.motion," in board
    assert "board->local_eye_display_->ShowEyes(eyes);" in board
    assert "DisplayLockGuard lock(this);" in renderer
    assert "`overlay/face_eye_animator.hpp`" in instructions
    assert "`overlay/face_eye_display.hpp`" in instructions
    assert "GPL RoboEyes" in instructions
    assert "Gate A1 and feature G001 remain open" in instructions
    assert "No new camera/audio driver, RoboEyes/GPL face code or custom" not in instructions
    assert "Stock OLED emotion/text UI is used initially." not in instructions


def test_authenticated_pose_bridge_is_read_only_bounded_and_versioned():
    """Guide 30 pose remains a separate validated telemetry command, not a UART tunnel."""
    import json
    import re

    protocol = (HEAD / "overlay/robot_protocol.h").read_text()
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    assert 'v == "pose"' in protocol
    assert '{"/api/pose", HTTP_GET}' in bridge
    assert 'strcmp(req->uri, "/api/pose") == 0' in bridge
    assert 'pose ? "pose" : optics ? "optics"' in bridge
    assert 'bool PoseValid(cJSON* json)' in bridge
    assert 'cJSON_GetArraySize(json) != 9' in bridge
    for field in ('"v"', '"body_boot"', '"origin"', '"seq"', '"sample_us"',
                  '"x_mm"', '"y_mm"', '"yaw_mrad"', '"quality"'):
        assert field in bridge.split("bool PoseValid(cJSON* json)", 1)[1].split("bool IrValid(", 1)[0]
    assert 'command.verb == "pose" && line == "ERR input unknown_command"' in bridge
    assert 'return {501, false, "pose unsupported by body firmware"};' in bridge
    assert 'command.verb == "pose" && !line.empty() && line.front() == \'{\'' in bridge
    assert 'const bool urgent = command.verb == "stop" || command.verb == "halt";' in bridge
    assert 'urgency.preempted()' in bridge
    assert 'body_read_busy_.exchange(true, std::memory_order_acq_rel)' in bridge
    assert 'if (!Authorize(req)) return Json(req, 401' in bridge
    assert 'if (!cJSON_AddStringToObject(body, "robot_id", CONFIG_DESK_ROBOT_ID))' in bridge
    assert 'cJSON_AddRawToObject(body, "sample_us", decimal.c_str())' in bridge
    assert '!cJSON_AddNumberToObject(body, "head_boot", head_boot)' in bridge
    assert 'EncodeBodyRead(body.get(), pose, bridge->boot_nonce_)' in bridge
    guide = (HEAD.parents[2] / "docs/guides/interfaces.md").read_text()
    examples = guide.split("### Read-only pose v1", 1)[1]
    fixtures = re.findall(r'`({"v":1,"body_boot".+?})`', examples)
    assert len(fixtures) == 4
    valid, same_origin, reboot, unavailable = map(json.loads, fixtures)
    assert valid["quality"] == "valid" and same_origin["quality"] == "degraded"
    assert (valid["body_boot"], valid["origin"]) == (
        same_origin["body_boot"], same_origin["origin"])
    assert valid["seq"] < same_origin["seq"]
    assert (valid["body_boot"], valid["origin"]) != (
        reboot["body_boot"], reboot["origin"])
    assert reboot["quality"] == "valid" and reboot["seq"] == 1
    assert unavailable["quality"] == "unavailable" and unavailable["origin"] == 0
    assert unavailable["seq"] > reboot["seq"] and unavailable["sample_us"] > reboot["sample_us"]
    assert '!integer(seq, 1, 4294967295.0)' in bridge
    assert '!integer(sample_us, 1, 9007199254740991.0)' in bridge
    assert '!integer(get("x_mm"), -1000000.0, 1000000.0)' in bridge
    assert '!integer(get("y_mm"), -1000000.0, 1000000.0)' in bridge
    assert '!integer(get("yaw_mrad"), -3142.0, 3142.0)' in bridge
    assert set(valid) == set(same_origin) == set(reboot) == set(unavailable) == {
        "v", "body_boot", "origin", "seq", "sample_us",
        "x_mm", "y_mm", "yaw_mrad", "quality",
    }

def test_camera_snapshot_never_sends_jpeg_on_provenance_header_failure():
    """The accepted source sequence is committed only after all headers stage."""
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    task = bridge.split("void Bridge::CameraTask(void* context) {", 1)[1].split(
        "void Bridge::CameraStreamTask(void* context) {", 1
    )[0]
    assert 'else if (!CompleteJpeg(jpeg->data(), jpeg->size()))' in task
    assert 'esp_err_t header_status = httpd_resp_set_type(req, "image/jpeg");' in task
    assert task.count("if (header_status == ESP_OK)") == 5
    for name in (
        "Cache-Control",
        "X-Desk-Camera-Robot-Id",
        "X-Desk-Camera-Boot",
        "X-Desk-Camera-Sequence",
        "X-Desk-Camera-Complete-Us",
    ):
        assert f'header_status = httpd_resp_set_hdr(req, "{name}", ' in task
    failure = task.index("if (header_status != ESP_OK) {")
    reject = task.index('bridge->Json(req, 503, Envelope(false, "camera provenance headers unavailable"));')
    guarded_success = task.index("} else {", failure)
    advance = task.index("++bridge->camera_sequence_;")
    jpeg_send = task.index("const auto sent = httpd_resp_send(")
    send_ok = task.index("if (sent == ESP_OK)", jpeg_send)
    assert failure < reject < guarded_success < jpeg_send < send_ok < advance
    assert "++bridge->camera_sequence_" not in task[:failure]

def test_camera_stream_never_spends_sequence_on_invalid_provenance_headers():
    """A failed MJPEG multipart identity must not advance the source sequence."""
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    stream = bridge.split("void Bridge::CameraStreamTask(void* context) {", 1)[1].split(
        "#if defined(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3)", 1
    )[0]
    reserve = stream.index("const auto seq = bridge->camera_sequence_ + 1;")
    format_headers = stream.index("const int n = snprintf(")
    invalid = stream.index("if (n < 0 || static_cast<std::size_t>(n) >= sizeof(headers)) {")
    reject = stream.index("status = ESP_FAIL;", invalid)
    valid = stream.index("} else {", reject)
    advance = stream.index("++bridge->camera_sequence_;")
    send = stream.index("status = httpd_resp_send_chunk(", valid)
    final_chunk = stream.index('status = httpd_resp_send_chunk(req, "\\r\\n", 2);', send)
    send_ok = stream.index("if (status == ESP_OK) {", final_chunk)
    assert reserve < format_headers < invalid < reject < valid < send < final_chunk
    assert final_chunk < send_ok < advance
    assert "++bridge->camera_sequence_" not in stream[:invalid]


def test_local_eye_display_arbitrates_faults_subtitles_and_malformed_coordinates():
    """Exercise renderer geometry and cross-thread arbitration with a lock-checking fake."""
    source = (HEAD / "sense/desk_robot_sense.cc").read_text()
    assert "board->local_eye_display_->SetLocalStatus(local_status);" in source
    compiler = shutil.which("g++") or shutil.which("c++")
    if compiler is None:
        raise unittest.SkipTest("Native C++ compiler unavailable")
    fake = r"""
#pragma once
#include <algorithm>
#include <cassert>
#include <string>
#include <vector>
#include <mutex>
inline std::recursive_mutex lvgl_mutex;
inline thread_local int lock_depth = 0;
struct lv_obj_t {
    bool hidden = false;
    int x = 0, y = 0, w = 0, h = 0;
    int radius = -1;
    lv_obj_t* parent = nullptr;
    std::vector<lv_obj_t*> children;
    std::string text;
};
inline lv_obj_t screen;
inline const char* lv_label_get_text(lv_obj_t* n) { assert(lock_depth > 0); return n->text.c_str(); }
inline lv_obj_t* lv_screen_active() { assert(lock_depth > 0); return &screen; }
inline lv_obj_t* lv_obj_create(lv_obj_t* parent) {
    assert(lock_depth > 0);
    auto* node = new lv_obj_t;
    node->parent = parent;
    parent->children.push_back(node);
    return node;
}
inline void lv_obj_del(lv_obj_t* node) {
    assert(lock_depth > 0);
    while (!node->children.empty()) lv_obj_del(node->children.back());
    auto& siblings = node->parent->children;
    siblings.erase(std::find(siblings.begin(), siblings.end(), node));
    delete node;
}
inline void lv_obj_move_foreground(lv_obj_t* node) {
    assert(lock_depth > 0);
    auto& siblings = node->parent->children;
    siblings.erase(std::find(siblings.begin(), siblings.end(), node));
    siblings.push_back(node);
}
inline void lv_obj_set_size(lv_obj_t* n, int w, int h) { assert(lock_depth > 0); n->w = w; n->h = h; }
inline void lv_obj_set_pos(lv_obj_t* n, int x, int y) { assert(lock_depth > 0); n->x = x; n->y = y; }
inline void lv_obj_align(lv_obj_t* n, int, int x, int y) {
    assert(lock_depth > 0);
    n->x = (128 - n->w) / 2 + x;
    n->y = y;
}
inline void lv_obj_add_flag(lv_obj_t* n, int) { assert(lock_depth > 0); n->hidden = true; }
inline void lv_obj_remove_flag(lv_obj_t* n, int) { assert(lock_depth > 0); n->hidden = false; }
inline bool lv_obj_has_flag(lv_obj_t* n, int) { assert(lock_depth > 0); return n->hidden; }
inline constexpr int LV_ALIGN_TOP_MID = 0, LV_RADIUS_CIRCLE = 1, LV_OPA_COVER = 2;
inline constexpr int LV_SCROLLBAR_MODE_OFF = 3, LV_OBJ_FLAG_HIDDEN = 4;
inline int lv_color_white() { return 1; }
inline int lv_color_black() { return 0; }
inline void lv_obj_set_style_radius(lv_obj_t* n, int radius, int) {
    assert(lock_depth > 0);
    n->radius = radius;
}
inline void lv_obj_set_style_pad_all(lv_obj_t*, int, int) { assert(lock_depth > 0); }
inline void lv_obj_set_style_border_width(lv_obj_t*, int, int) { assert(lock_depth > 0); }
inline void lv_obj_set_style_bg_color(lv_obj_t*, int, int) { assert(lock_depth > 0); }
inline void lv_obj_set_style_bg_opa(lv_obj_t*, int, int) { assert(lock_depth > 0); }
inline void lv_obj_set_scrollbar_mode(lv_obj_t*, int) { assert(lock_depth > 0); }
class OledDisplay;
class DisplayLockGuard {
public:
    explicit DisplayLockGuard(OledDisplay*) { lvgl_mutex.lock(); ++lock_depth; }
    ~DisplayLockGuard() { assert(lock_depth > 0); --lock_depth; lvgl_mutex.unlock(); }
    DisplayLockGuard(const DisplayLockGuard&) = delete;
    DisplayLockGuard& operator=(const DisplayLockGuard&) = delete;
    explicit operator bool() const { return true; }
};
class OledDisplay {
public:
    virtual ~OledDisplay() {
        DisplayLockGuard lock(this);
        if (low_battery_popup_) lv_obj_del(low_battery_popup_);
    }
    virtual void SetupUI() {
        DisplayLockGuard lock(this);
        status_label_ = &status_storage_;
        status_label_->text = "Initializing";
        if (!low_battery_popup_) {
            low_battery_popup_ = lv_obj_create(&screen);
            lv_obj_set_size(low_battery_popup_, 115, 24);
            lv_obj_add_flag(low_battery_popup_, LV_OBJ_FLAG_HIDDEN);
        }
    }
    int width() const { return 128; }
    int height() const { return 64; }
    virtual void SetStatus(const char* value) {
        DisplayLockGuard lock(this);
        if (!status_label_) return;
        ++status_writes;
        status_label_->text = value;
        status_label_->hidden = false;
        notification_text.clear();
    }
    virtual void ShowNotification(const char* value, int = 3000) {
        DisplayLockGuard lock(this);
        if (!status_label_) return;
        status_label_->hidden = true;
        notification_text = value;
    }
    virtual void ShowNotification(const std::string& value, int duration = 3000) {
        ShowNotification(value.c_str(), duration);
    }
    std::string Status() const { return status_label_->text; }
    bool StatusVisible() const { return !status_label_->hidden; }
    int status_writes = 0;
    std::string notification_text;
    virtual bool SetEmotion(const char* value) {
        DisplayLockGuard lock(this);
        emotion_text = value;
        return true;
    }
    virtual void SetChatMessage(const char*, const char* value) {
        DisplayLockGuard lock(this);
        assert(value);
        if (!*value) {
            subtitle_visible_ = false;
            return;  // pinned 128x64 OLED hides the row but retains its label
        }
        subtitle_text = value;
        std::replace(subtitle_text.begin(), subtitle_text.end(), '\n', ' ');
        subtitle_visible_ = true;
    }
    virtual void RemoveChatMessage(const char*, const char* value) {
        DisplayLockGuard lock(this);
        std::string text = value;
        std::replace(text.begin(), text.end(), '\n', ' ');
        if (text == subtitle_text) {
            subtitle_text.clear();
            subtitle_visible_ = false;
        }
    }
    lv_obj_t* BatteryPopup() const { return low_battery_popup_; }
    std::string emotion_text, subtitle_text;
protected:
    bool HasChatMessageLocked() const {
        assert(lock_depth > 0);
        return subtitle_visible_ && !subtitle_text.empty();
    }
    bool subtitle_visible_ = false;
    lv_obj_t status_storage_;
    lv_obj_t* status_label_ = nullptr;
    lv_obj_t* low_battery_popup_ = nullptr;
};
"""
    native = r"""
#include "face_eye_display.hpp"
#include <array>
#include <cassert>
#include <thread>
using Framebuffer = std::array<unsigned char, 128 * 64>;

// A conservative rectangular footprint, not a replacement LVGL rasterizer.
// Check absolute bounds before each simulated framebuffer write.
static void PaintBounds(const lv_obj_t* node, int parent_x, int parent_y,
                        Framebuffer& pixels) {
    if (node->hidden) return;
    const int x = parent_x + node->x;
    const int y = parent_y + node->y;
    assert(node->w > 0 && node->h > 0);
    assert(x >= 48 && x <= 80 && node->w <= 80 - x);
    assert(y >= 16 && y <= 64 && node->h <= 64 - y);
    for (int row = y; row < y + node->h; ++row)
        for (int col = x; col < x + node->w; ++col)
            pixels[static_cast<size_t>(row) * 128 + col] = 1;
    for (const auto* child : node->children) PaintBounds(child, x, y, pixels);
}

int main() {
    using desk_robot::FaceStatus;
    using desk_robot::SelectFaceStatus;
    for (bool fault : {false, true}) {
        for (bool dock : {false, true}) {
            for (bool privacy : {false, true}) {
                assert(SelectFaceStatus(fault, dock, privacy) ==
                    (fault ? (dock ? FaceStatus::kDockLock : FaceStatus::kBodyFault)
                           : (privacy ? FaceStatus::kMicPrivacy : FaceStatus::kNormal)));
            }
        }
    }
    {
        desk_robot::LocalEyeDisplay early;
        early.SetLocalStatus(FaceStatus::kFaceUnavailable);
        early.SetStatus("Connecting");
        early.SetupUI();
        assert(early.Status() == "Face task unavailable");
        early.SetLocalStatus(FaceStatus::kNormal);
        assert(early.Status() == "Connecting");
    }
    {
        using desk_robot::FacePanelMode;
        desk_robot::LocalEyeDisplay resting;
        resting.SetupUI();
        std::vector<FacePanelMode> modes;
        auto apply = [&](FacePanelMode mode) {
            assert(lock_depth > 0);
            modes.push_back(mode);
            return true;
        };
        resting.UpdateIdlePower(0, true, false, apply);
        resting.UpdateIdlePower(60000, true, false, apply);
        resting.UpdateIdlePower(300000, true, true, apply);
        assert(modes.back() == FacePanelMode::kDim);
        resting.UpdateIdlePower(301000, true, true, apply);
        assert(modes.size() == 4 && modes.back() == FacePanelMode::kOff);
        resting.SetLocalStatus(FaceStatus::kBodyFault);
        resting.UpdateIdlePower(301001, true, true, apply);
        assert(modes.size() == 5 && modes.back() == FacePanelMode::kAwake);
        resting.SetLocalStatus(FaceStatus::kNormal);
        resting.UpdateIdlePower(301002, true, true, apply);
        resting.UpdateIdlePower(361002, true, true, apply);
        resting.UpdateIdlePower(362002, true, true, apply);
        resting.UpdateIdlePower(363002, true, true, apply);
        assert(modes.back() == FacePanelMode::kOff);
        resting.SetChatMessage("user", "wake");
        resting.UpdateIdlePower(363003, true, true, apply);
        assert(modes.back() == FacePanelMode::kAwake);
        resting.SetChatMessage("user", nullptr);
        resting.UpdateIdlePower(363004, true, true, apply);
        resting.UpdateIdlePower(423004, true, true, apply);
        resting.UpdateIdlePower(424004, true, true, apply);
        resting.UpdateIdlePower(425004, true, true, apply);
        assert(modes.back() == FacePanelMode::kOff);
        {
            DisplayLockGuard lock(&resting);
            lv_obj_remove_flag(resting.BatteryPopup(), LV_OBJ_FLAG_HIDDEN);
        }
        resting.UpdateIdlePower(425005, true, true, apply);
        assert(modes.back() == FacePanelMode::kAwake);
    }
    desk_robot::LocalEyeDisplay display;
    OledDisplay* upstream = &display;
    display.SetupUI();
    auto* popup = display.BatteryPopup();
    assert(screen.children.size() == 2 && screen.children.back() == popup);
    auto* layer = screen.children.at(0);
    assert(layer != popup);
    assert(layer->x == 48 && layer->y == 16 && layer->w == 32 && layer->h == 48);
    assert(layer->children.size() == 3);
    auto* pupil = layer->children.at(0)->children.at(0);
    auto* mouth = layer->children.at(2);
    assert(layer->hidden && mouth->hidden);
    {
        DisplayLockGuard lock(&display);
        lv_obj_remove_flag(popup, LV_OBJ_FLAG_HIDDEN);
    }
    display.ShowEyes({true, false, -127, 127});
    assert(!popup->hidden && !layer->hidden && pupil->x == 1 && pupil->y == 8 && mouth->hidden);
    assert(screen.children.size() == 2 && screen.children.back() == popup);
    Framebuffer composite{};
    for (const auto* child : screen.children) {
        if (child->hidden) continue;
        const unsigned char tag = child == popup ? 2 : 1;
        for (int row = child->y; row < child->y + child->h; ++row)
            for (int col = child->x; col < child->x + child->w; ++col)
                composite[static_cast<size_t>(row) * 128 + col] = tag;
    }
    for (int row = 16; row < 24; ++row)
        for (int col = 48; col < 80; ++col)
            assert(composite[static_cast<size_t>(row) * 128 + col] == 2);
    {
        DisplayLockGuard lock(&display);
        lv_obj_add_flag(popup, LV_OBJ_FLAG_HIDDEN);
    }
    for (uint8_t height : {1, 3, 5, 7, 255}) {
        display.ShowEyes({true, false, 0, 0, 14, height});
        assert(!layer->hidden && !mouth->hidden);
        assert(mouth->w == 10 && mouth->h == std::min<int>(height, 12));
        assert(mouth->x >= 0 && mouth->x + mouth->w <= layer->w);
        assert(mouth->y >= 31 && mouth->y + mouth->h <= layer->h);
    }
    upstream->SetChatMessage("assistant", "first\nline");
    assert(layer->hidden && display.subtitle_text == "first line");
    display.ShowEyes({true, false, 3, 0, 14, 7});
    assert(layer->hidden);
    upstream->RemoveChatMessage("assistant", "old");
    display.ShowEyes({true, false, 3, 0});
    assert(layer->hidden);
    upstream->RemoveChatMessage("assistant", "first\nline");
    display.ShowEyes({true, false, 3, 0});
    assert(!layer->hidden && pupil->x == 7 && mouth->hidden);
    const std::string long_caption = std::string(1024, 'x') + "\nlast";
    const std::string stale_caption = std::string(1024, 'x') + "\nold";
    upstream->SetChatMessage("assistant", long_caption.c_str());
    assert(layer->hidden && display.subtitle_text == std::string(1024, 'x') + " last");
    upstream->RemoveChatMessage("assistant", stale_caption.c_str());
    display.ShowEyes({true, false, 3, 0});
    assert(layer->hidden);
    upstream->RemoveChatMessage("assistant", long_caption.c_str());
    display.ShowEyes({true, false, 3, 0});
    assert(!layer->hidden);
    upstream->SetChatMessage("user", long_caption.c_str());
    upstream->SetChatMessage("user", nullptr);
    assert(!display.subtitle_text.empty());
    display.ShowEyes({true, false, 3, 0});
    assert(!layer->hidden);
    const std::string fitting_status(255, 's');
    const std::string overflow_status(256, 't');
    display.SetLocalStatus(FaceStatus::kBodyFault);
    upstream->SetStatus(fitting_status.c_str());
    assert(display.Status() == "Body safety stop");
    display.SetLocalStatus(FaceStatus::kNormal);
    assert(display.Status() == fitting_status);
    display.SetLocalStatus(FaceStatus::kBodyFault);
    upstream->SetStatus(overflow_status.c_str());
    assert(display.Status() == "Body safety stop");
    display.SetLocalStatus(FaceStatus::kNormal);
    assert(display.Status() == "Status unavailable");
    display.SetLocalStatus(FaceStatus::kMicPrivacy);
    upstream->SetStatus(overflow_status.c_str());
    upstream->SetStatus("12:34");
    display.SetLocalStatus(FaceStatus::kNormal);
    assert(display.Status() == "12:34");
    display.ShowEyes({true, false, 0, 0, 14, 7});
    assert(!mouth->hidden);
    assert(upstream->SetEmotion("happy"));
    upstream->SetStatus("Speaking");
    upstream->ShowNotification("Earlier notification");
    assert(!display.StatusVisible());
    display.SetLocalStatus(FaceStatus::kBodyFault);
    assert(layer->hidden && display.emotion_text == "neutral");
    assert(display.StatusVisible() && display.Status() == "Body safety stop");
    const int fault_writes = display.status_writes;
    for (int i = 0; i < 12; ++i) {
        upstream->SetStatus("Listening");
        upstream->ShowNotification("Volume changed");
        upstream->ShowNotification(std::string("Network event"));
        display.SetLocalStatus(FaceStatus::kBodyFault);
        display.ShowEyes({true, true, 0, 0});
        assert(display.StatusVisible() && display.Status() == "Body safety stop");
        assert(display.notification_text.empty() && layer->hidden);
        assert(display.status_writes == fault_writes);
    }
    assert(!upstream->SetEmotion("happy"));
    assert(!upstream->SetEmotion(nullptr));
    assert(display.emotion_text == "neutral");
    display.ShowEyes({true, false, 3, 0});
    assert(layer->hidden);
    upstream->SetChatMessage("user", "new");
    display.SetLocalStatus(SelectFaceStatus(true, true, true));
    assert(display.Status() == "Dock lock: motors off");
    display.SetLocalStatus(SelectFaceStatus(false, false, true));
    assert(display.Status() == "Mic privacy ON");
    upstream->SetStatus("12:34");
    upstream->ShowNotification("Ignore while muted");
    assert(!upstream->SetEmotion("happy"));
    display.ShowEyes({true, true, 0, 0});
    assert(display.StatusVisible() && display.Status() == "Mic privacy ON" && layer->hidden);
    display.SetLocalStatus(FaceStatus::kNormal);
    assert(display.StatusVisible() && display.Status() == "12:34");
    upstream->ShowNotification("Normal again");
    assert(!display.StatusVisible() && display.notification_text == "Normal again");
    display.ShowEyes({true, false, 3, 0});
    assert(layer->hidden);
    upstream->SetChatMessage("user", nullptr);
    display.ShowEyes({true, true, 0, 0});
    assert(!layer->hidden && pupil->hidden);
    assert(upstream->SetEmotion("happy"));
    // The voice status is factual and cannot be overwritten by clock or notices.
    // Local expressions and the panel stay available beyond five offline minutes.
    display.SetLocalStatus(FaceStatus::kVoiceLinkLost);
    std::vector<desk_robot::FacePanelMode> offline_modes;
    for (uint64_t elapsed = 0; elapsed <= 300100; elapsed += 100) {
        upstream->SetStatus("Connecting");
        upstream->ShowNotification("Network retry");
        assert(upstream->SetEmotion("happy"));
        display.ShowEyes({true, elapsed % 1000 == 0, 0, 0});
        display.UpdateIdlePower(elapsed, true, true, [&](desk_robot::FacePanelMode mode) {
            offline_modes.push_back(mode);
            return true;
        });
        assert(!layer->hidden && display.StatusVisible());
        assert(display.Status() == "Voice offline");
    }
    assert(offline_modes.size() == 1 &&
           offline_modes.back() == desk_robot::FacePanelMode::kAwake);
    display.SetLocalStatus(SelectFaceStatus(true, false, false, true));
    display.ShowEyes({true, false, 0, 0});
    assert(layer->hidden && display.Status() == "Body safety stop");
    display.SetLocalStatus(SelectFaceStatus(false, false, false, true));
    display.ShowEyes({true, false, 0, 0});
    assert(!layer->hidden && display.Status() == "Voice offline");
    display.SetLocalStatus(FaceStatus::kNormal);
    assert(display.Status() == "Connecting");
    // The upstream status bar unhides its existing popup; it does not reorder it.
    { DisplayLockGuard lock(&display); lv_obj_remove_flag(popup, LV_OBJ_FLAG_HIDDEN); }
    assert(!layer->hidden && !popup->hidden);
    assert(screen.children.back() == popup);
    assert(layer->radius == 0);
    assert(mouth->radius == LV_RADIUS_CIRCLE);
    for (int i = 0; i < 2; ++i) {
        auto* eye = layer->children.at(i);
        assert(eye->radius == LV_RADIUS_CIRCLE);
        assert(eye->children.at(0)->radius == LV_RADIUS_CIRCLE);
    }
    for (int x : {-128, -3, 0, 3, 127}) {
        for (int y : {-128, -3, 0, 3, 127}) {
            for (bool closed : {false, true}) {
                display.ShowEyes({true, closed, static_cast<int8_t>(x), static_cast<int8_t>(y)});
                Framebuffer pixels{};
                PaintBounds(layer, 0, 0, pixels);
                assert(std::count(pixels.begin(), pixels.end(), 1) == 32 * 48);
            }
        }
    }
    display.ShowEyes({});
    Framebuffer hidden_pixels{};
    PaintBounds(layer, 0, 0, hidden_pixels);
    assert(std::count(hidden_pixels.begin(), hidden_pixels.end(), 1) == 0);
    for (int x = -128; x <= 127; ++x) {
        for (int y = -128; y <= 127; ++y) {
            for (bool closed : {false, true}) {
                display.ShowEyes({true, closed, static_cast<int8_t>(x), static_cast<int8_t>(y)});
                assert(screen.children.back() == popup);
                assert(mouth->hidden);
                for (int i = 0; i < 2; ++i) {
                    auto* eye = layer->children.at(i);
                    assert(eye->x >= 0 && eye->x + eye->w <= layer->w);
                    assert(eye->y >= 0 && eye->y + eye->h <= layer->h);
                    auto* dot = eye->children.at(0);
                    assert(dot->hidden == closed);
                    if (!closed) {
                        assert(dot->x >= 0 && dot->x + dot->w <= eye->w);
                        assert(dot->y >= 0 && dot->y + dot->h <= eye->h);
                    }
                }
            }
        }
    }
    // FaceTask and Xiaozhi are separate callers. A recursive mutex and
    // thread-local ownership check must guard every fake LVGL access.
    upstream->SetChatMessage("assistant", "caption before fault");
    display.SetLocalStatus(FaceStatus::kBodyFault);
    assert(display.StatusVisible() && display.Status() == "Body safety stop");
    std::thread upstream_writer([&] {
        for (int i = 0; i < 10000; ++i) {
            upstream->SetStatus("Listening");
            upstream->ShowNotification("Ignored");
            upstream->SetChatMessage("assistant", "current caption");
            upstream->RemoveChatMessage("assistant", "caption before fault");
            assert(!upstream->SetEmotion("happy"));
        }
        assert(lock_depth == 0);
    });
    std::thread face_writer([&] {
        for (int i = 0; i < 10000; ++i)
            display.ShowEyes({true, false, 3, 3, 14, 7});
        assert(lock_depth == 0);
    });
    upstream_writer.join();
    face_writer.join();
    assert(layer->hidden && display.StatusVisible());
    assert(display.Status() == "Body safety stop" && display.notification_text.empty());
    assert(display.subtitle_text == "current caption");
    display.SetLocalStatus(FaceStatus::kNormal);
    assert(display.Status() == "Listening");
    assert(display.subtitle_text == "current caption");
    assert(lock_depth == 0);
}
"""
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    env = native_cpp_env()
    env.update(ASAN_OPTIONS="halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "display").mkdir()
        (root / "display/oled_display.h").write_text(fake)
        cpp = root / "face_display_test.cc"
        binary = root / "face_display_test"
        cpp.write_text(native)
        subprocess.run([
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Wshadow", "-Werror",
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
            "-fno-omit-frame-pointer", "-pthread", *pie_flags,
            "-I", str(root), "-I", str(HEAD / "overlay"), str(cpp), "-o", str(binary),
        ], check=True, capture_output=True, text=True, env=env, timeout=60)
        subprocess.run([str(binary)], check=True, capture_output=True, text=True,
                       env=env, timeout=30)


def test_body_face_snapshot_is_coherent_and_expires_across_clock_rollover():
    """Compile the actual board helper, not an independent implementation."""
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        raise unittest.SkipTest("Native C++ compiler unavailable")
    board = (HEAD / "sense/desk_robot_sense.cc").read_text()
    helper = "struct BodyFaceStatus {" + board.split(
        "struct BodyFaceStatus {", 1
    )[1].split("class DeskRobotSenseBoard", 1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "body_face_state.cpp"
        binary = Path(tmp) / "body_face_state"
        source.write_text(
            "#include <cassert>\n#include <cstdint>\n#include <mutex>\n"
            "#include <atomic>\n#include <thread>\n"
            "inline bool lvgl_port_lock(int) { return true; }\n"
            "inline void lvgl_port_unlock() {}\n"
            + helper + r"""
int main() {
    BodyFaceState state;
    assert(!state.Read().Fresh(0));
    state.Publish({true, false, false, 0});
    assert(state.Read().Fresh(1200));
    assert(!state.Read().Fresh(1201));
    const uint64_t boundary = 1ULL << 32;
    state.Publish({true, true, true, boundary - 10});
    assert(state.Read().Fresh(boundary + 10));
    assert(!state.Read().Fresh(boundary + 1191));
    assert(!state.Read().Fresh(boundary - 11));
    state.Publish({});
    assert(!state.Read().Fresh(boundary));
    assert(!AudioListenRetryDue(9999, 0));
    assert(AudioListenRetryDue(10000, 0));
    assert(!AudioListenRetryDue(14999, 10000));
    assert(AudioListenRetryDue(15000, 10000));
    assert(!AudioListenRetryDue(boundary + 100, boundary - 4899));
    assert(AudioListenRetryDue(boundary + 101, boundary - 4899));
    assert(!AudioListenRetryDue(boundary - 1, boundary));
    std::atomic<bool> done{false};
    std::thread writer([&] {
        for (uint64_t i = 1; i <= 100000; ++i) {
            const bool fault = i % 2 == 0;
            state.Publish({true, fault, fault, i});
        }
        done.store(true);
    });
    do {
        const auto sample = state.Read();
        if (sample.valid) {
            assert(sample.fault == (sample.at_ms % 2 == 0));
            assert(sample.fault == sample.dock_lockout);
        }
    } while (!done.load());
    writer.join();
}
"""
        )
        pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
        subprocess.run(
            [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
             "-fsanitize=address,undefined", *pie_flags,
             str(source), "-o", str(binary)],
            check=True, capture_output=True, text=True, env=native_cpp_env(),
        )
        subprocess.run([str(binary)], check=True, timeout=30, env=native_cpp_env())


def test_camera_receipt_exhaustion_and_monotonic_completion_are_fail_closed():
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    camera = bridge.split("void Bridge::CameraTask(void* context) {", 1)[1].split(
        "#if defined(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3)", 1
    )[0]
    snapshot, stream = camera.split("void Bridge::CameraStreamTask(void* context) {", 1)
    for worker in (snapshot, stream):
        capture = worker.index("SnapshotJpeg();")
        stamp = worker.index("const auto completed = esp_timer_get_time();", capture)
        exhausted = worker.index("std::numeric_limits<std::uint32_t>::max()", stamp)
        monotonic = worker.index("completed <= bridge->camera_completed_us_", exhausted)
        reserve = worker.index("bridge->camera_sequence_ + 1", monotonic)
        commit = worker.index("++bridge->camera_sequence_;", reserve)
        complete = worker.index("bridge->camera_completed_us_ = completed;", commit)
        assert capture < stamp < exhausted < monotonic < reserve < commit < complete
        assert worker.count("++bridge->camera_sequence_;") == 1


def test_camera_workers_fault_injection(tmp_path):
    """Compile the actual workers against deterministic capture/HTTP fakes."""
    compiler = shutil.which("g++") or shutil.which("c++")
    if compiler is None:
        raise unittest.SkipTest("Native C++ compiler unavailable")
    bridge = (HEAD / "overlay/robot_bridge.cc").read_text()
    start = bridge.index("void Bridge::CameraTask(void* context) {")
    end = bridge.index("#if defined(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3)", start)
    workers = bridge[start:end]
    prefix = r"""
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <string>
#include <vector>
using esp_err_t = int;
constexpr int ESP_OK = 0, ESP_FAIL = -1;
#define CONFIG_DESK_ROBOT_ID "robot-01"
#define pdMS_TO_TICKS(x) (x)
struct httpd_req_t { void* user_ctx; };
int calls = 0, fail_at = 0, completed_req = 0, errors = 0;
std::int64_t now = 100;
int result() { return ++calls == fail_at ? ESP_FAIL : ESP_OK; }
int httpd_resp_set_type(httpd_req_t*, const char*) { return result(); }
int httpd_resp_set_hdr(httpd_req_t*, const char*, const char*) { return result(); }
int httpd_resp_send(httpd_req_t*, const char*, size_t) { return result(); }
int httpd_resp_send_chunk(httpd_req_t*, const char*, size_t) { return result(); }
void httpd_req_async_handler_complete(httpd_req_t*) { ++completed_req; }
void vTaskDelete(void*) {}
void vTaskDelay(int) {}
std::int64_t esp_timer_get_time() { return now; }
std::string Envelope(bool, const std::string& msg) { return msg; }
bool CompleteJpeg(const uint8_t* bytes, size_t n) {
    return n >= 4 && bytes[0] == 255 && bytes[1] == 216 &&
           bytes[n-2] == 255 && bytes[n-1] == 217;
}
struct Capture {
    bool valid;
    std::vector<uint8_t> bytes;
    explicit operator bool() const { return valid; }
    std::string error() const { return "bad capture"; }
    const std::vector<uint8_t>* operator->() const { return &bytes; }
};
struct Camera {
    int left = 1;
    bool malformed = false;
    Capture SnapshotJpeg() {
        return {left-- > 0, malformed ? std::vector<uint8_t>{255,216,0,0}
                                     : std::vector<uint8_t>{255,216,255,217}};
    }
};
struct Bridge {
    Camera* camera_;
    uint32_t camera_sequence_ = 0, boot_nonce_ = 7;
    int64_t camera_completed_us_ = 0;
    std::atomic<bool> camera_busy_{true};
    void Json(httpd_req_t*, int, const std::string&) { ++errors; }
    static void CameraTask(void*);
    static void CameraStreamTask(void*);
};
"""
    suffix = r"""
int main() {
    for (bool stream : {false, true}) {
        auto worker = stream ? Bridge::CameraStreamTask : Bridge::CameraTask;
        for (int fail = 0; fail <= 7; ++fail) {
            Camera cam;
            Bridge bridge{&cam};
            httpd_req_t req{&bridge};
            calls = completed_req = errors = 0; fail_at = fail;
            worker(&req);
            assert(bridge.camera_sequence_ == (fail == 0 ? 1U : 0U));
            assert(bridge.camera_completed_us_ == (fail == 0 ? now : 0));
            assert(!bridge.camera_busy_ && completed_req == 1);
        }
        for (int scenario = 0; scenario < 4; ++scenario) {
            Camera cam;
            Bridge bridge{&cam};
            httpd_req_t req{&bridge};
            calls = completed_req = errors = 0; fail_at = 0;
            if (scenario == 0) cam.left = 0;
            if (scenario == 1) cam.malformed = true;
            if (scenario == 2) bridge.camera_sequence_ = UINT32_MAX;
            if (scenario == 3) bridge.camera_completed_us_ = now;
            const auto seq = bridge.camera_sequence_;
            const auto stamp = bridge.camera_completed_us_;
            worker(&req);
            assert(bridge.camera_sequence_ == seq && bridge.camera_completed_us_ == stamp);
            assert(!bridge.camera_busy_ && completed_req == 1);
        }
    }
}
"""
    source = tmp_path / "camera_worker.cc"
    source.write_text(prefix + workers + suffix)
    binary = tmp_path / "camera_worker"
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", *pie_flags, str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True, env=native_cpp_env(), timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=10, env=native_cpp_env())

def test_sense_network_task_startup_failure_and_retry(tmp_path):
    """Exercise the production startup method with injected allocation failures."""
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        raise unittest.SkipTest("Native C++ compiler unavailable")
    board = (HEAD / "sense/desk_robot_sense.cc").read_text()
    startup = "    void StartNetwork() override {" + board.split(
        "    void StartNetwork() override {", 1
    )[1].split("\n    AudioCodec* GetAudioCodec()", 1)[0]
    source = tmp_path / "sense_startup.cpp"
    binary = tmp_path / "sense_startup"
    source.write_text(r"""
#include <cassert>
#include <cstdint>
#include <mutex>
#include <string_view>
#define CONFIG_DESK_ROBOT_ID "pet-1"
static int errors = 0, starts = 0, attempts = 0;
#define ESP_LOGE(tag, ...) (++errors)
constexpr int pdPASS = 1;
static bool fail_face = true, fail_poll = true;
using TaskHandle_t = void*;
int xTaskCreate(void (*)(void*), const char* name, int, void* context,
                int, TaskHandle_t* out) {
    ++attempts;
    if (std::string_view(name) == "stackchan_idle_face" ? fail_face : fail_poll)
        return -1;
    *out = context;
    return pdPASS;
}
struct WifiBoard { virtual void StartNetwork() {} };
struct AudioCodec {};
namespace desk_robot {
enum class FaceStatus { kFaceUnavailable };
struct Bridge {
    Bridge(void*, AudioCodec*) {}
    void Start() { ++starts; }
    bool face_available = false;
    void SetFaceConsumerAvailable(bool available) { face_available = available; }
};
}
struct Face {
    int seeds = 0;
    void seed(uint32_t) { ++seeds; }
    void Seed(uint32_t) { ++seeds; }
};
struct Display {
    int statuses = 0;
    bool fault = false;
    void SetLocalStatus(desk_robot::FaceStatus value) {
        fault = value == desk_robot::FaceStatus::kFaceUnavailable;
        ++statuses;
    }
};
struct BodyFaceStatus {};
struct BodyFaceState {
    int invalidations = 0;
    void Publish(BodyFaceStatus) { ++invalidations; }
};
class DeskRobotSenseBoard : public WifiBoard {
public:
    void* camera_ = nullptr;
    AudioCodec codec;
    AudioCodec* GetAudioCodec() { return &codec; }
    std::mutex network_tasks_mutex_;
    desk_robot::Bridge* body_bridge_ = nullptr;
    Face face_behavior_, eye_animator_;
    TaskHandle_t face_task_ = nullptr, body_poll_task_ = nullptr;
    Display screen;
    Display* local_eye_display_ = &screen;
    Display* display_ = &screen;
    BodyFaceState body_face_state_;
    static void FaceTask(void*) {}
    static void BodyPollTask(void*) {}
""" + startup + r"""
};
int main() {
    DeskRobotSenseBoard board;
    board.StartNetwork();
    assert(attempts == 2 && errors == 2 && starts == 1);
    assert(!board.face_task_ && !board.body_poll_task_);
    assert(!board.body_bridge_->face_available);
    assert(board.screen.fault && board.screen.statuses == 1);
    assert(board.body_face_state_.invalidations == 1);
    fail_face = false;
    board.StartNetwork();
    assert(board.face_task_ && !board.body_poll_task_);
    assert(board.body_bridge_->face_available);
    assert(attempts == 4 && errors == 3 && starts == 1);
    fail_poll = false;
    board.StartNetwork();
    assert(board.face_task_ && board.body_poll_task_);
    assert(attempts == 5 && errors == 3 && starts == 1);
    board.StartNetwork();
    assert(attempts == 5 && errors == 3 && starts == 1);
    assert(board.face_behavior_.seeds == 1 && board.eye_animator_.seeds == 1);
}
""")
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
         "-fsanitize=address,undefined", *pie_flags, str(source), "-o", str(binary)],
        check=True, capture_output=True, text=True, env=native_cpp_env(),
    )
    subprocess.run([str(binary)], check=True, timeout=30, env=native_cpp_env())


def test_generated_audio_output_task_rejects_flushed_popped_task_before_reenable(
    tmp_path,
):
    """Exercise generated AudioOutputTask vs ResetDecoder race under ASan/UBSan."""
    compiler = shutil.which("g++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("Native C++ compiler unavailable")
    upstream_copy = tmp_path / "upstream"
    shutil.copytree(UPSTREAM, upstream_copy, dirs_exist_ok=True)
    overlay.apply(upstream_copy, "sense")
    service_h = (upstream_copy / "main/audio/audio_service.h").read_text()
    service_cc = (upstream_copy / "main/audio/audio_service.cc").read_text()
    assert "std::mutex desk_output_admission_mutex_;" in service_h
    output_fn = "void AudioService::AudioOutputTask() {" + service_cc.split(
        "void AudioService::AudioOutputTask() {", 1
    )[1].split("\nvoid AudioService::", 1)[0]
    reset_fn = "void AudioService::ResetDecoder() {" + service_cc.split(
        "void AudioService::ResetDecoder() {", 1
    )[1].split("\nbool AudioService::IsPlaybackDrainedLocked()", 1)[0]
    prefix_struct = "struct DeskPlaybackPrefix {" + service_h.split(
        "struct DeskPlaybackPrefix {", 1
    )[1].split("struct DebugStatistics {", 1)[0]

    # Inject a deterministic pause right after pop_front + unlock on the first task.
    needle = (
        "        output_in_flight_ = true;\n"
        "        audio_queue_cv_.notify_all();\n"
        "        lock.unlock();"
    )
    assert output_fn.count(needle) == 1
    instrumented_output = output_fn.replace(
        needle,
        needle + "\n        if (pause_after_pop_once.exchange(false)) {\n"
        "            popped_reached.store(true);\n"
        "            pause_cv.notify_all();\n"
        "            std::unique_lock<std::mutex> pause_lock(pause_mu);\n"
        "            pause_cv.wait(pause_lock, [&]{ return release_popped.load(); });\n"
        "        }",
        1,
    )

    cpp = tmp_path / "audio_output_race.cc"
    binary = tmp_path / "audio_output_race"
    cpp.write_text(
        """
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

#define TAG "AudioService"
#define ESP_LOGW(tag, fmt, ...) ((void)0)
#define AUDIO_POWER_CHECK_INTERVAL_MS 1000
inline void esp_timer_stop(void*) {}
inline void esp_timer_start_periodic(void*, int64_t) {}
inline void esp_opus_dec_reset(void*) {}
inline void* opus_decoder_ = nullptr;
std::mutex decoder_mutex_;

""" + prefix_struct + """
struct AudioTask {
    std::vector<int16_t> pcm;
    uint32_t timestamp = 0;
    uint32_t playback_id = 0;
    uint32_t media_position_ms = 0;
    int desk_frame_duration_ms = 0;
};
struct FakeCodec {
    std::atomic<bool> enabled{false};
    std::atomic<int> enable_true_calls{0};
    std::atomic<int> enable_false_calls{0};
    std::atomic<int> output_data_calls{0};
    bool output_enabled() const { return enabled.load(); }
    int output_sample_rate() const { return 32000; }
    void EnableOutput(bool v) {
        enabled.store(v);
        if (v) ++enable_true_calls; else ++enable_false_calls;
    }
    int OutputData(std::vector<int16_t>& pcm) {
        ++output_data_calls;
        return static_cast<int>(pcm.size());
    }
};
struct Callbacks {
    std::atomic<int> progress_calls{0};
    std::atomic<int> committed_calls{0};
    std::atomic<int> drained_calls{0};
    std::function<void(uint32_t, uint32_t)> on_playback_progress =
        [this](uint32_t, uint32_t) { ++progress_calls; };
    std::function<void(uint32_t, uint32_t)> on_playback_committed =
        [this](uint32_t, uint32_t) { ++committed_calls; };
    std::function<void(void)> on_playback_drained =
        [this]() { ++drained_calls; };
};
struct ServiceHarness {
    FakeCodec codec_obj;
    FakeCodec* codec_ = &codec_obj;
    Callbacks callbacks_;
    void* audio_power_timer_ = nullptr;
    std::mutex audio_queue_mutex_;
    std::mutex desk_output_admission_mutex_;
    std::condition_variable audio_queue_cv_;
    std::deque<AudioTask> audio_decode_queue_;
    std::deque<AudioTask> audio_playback_queue_;
    std::deque<AudioTask> audio_testing_queue_;
    std::deque<uint32_t> timestamp_queue_;
    bool decode_in_flight_ = false;
    bool output_in_flight_ = false;
    bool playback_drained_notified_ = true;
    uint32_t playback_generation_ = 0;
    std::atomic<bool> service_stopped_{false};
    std::chrono::steady_clock::time_point last_output_time_;
    struct { uint32_t playback_count = 0; } debug_statistics_;

    std::atomic<bool> pause_after_pop_once{true};
    std::atomic<bool> popped_reached{false};
    std::atomic<bool> release_popped{false};
    std::mutex pause_mu;
    std::condition_variable pause_cv;

    bool IsPlaybackDrainedLocked() const {
        return audio_decode_queue_.empty() && audio_playback_queue_.empty() &&
               !decode_in_flight_ && !output_in_flight_;
    }
    bool MarkPlaybackDrainedLocked() {
        if (!IsPlaybackDrainedLocked() || playback_drained_notified_) return false;
        playback_drained_notified_ = true;
        return true;
    }
    bool IsPlaybackIdle() {
        std::lock_guard<std::mutex> lock(audio_queue_mutex_);
        return IsPlaybackDrainedLocked();
    }
    void AudioOutputTask();
    void ResetDecoder();
};
#define AudioService ServiceHarness
""" + instrumented_output + "\n" + reset_fn + """
#undef AudioService
int main() {
    ServiceHarness svc;
    std::thread worker([&]() { svc.AudioOutputTask(); });
    {
        std::lock_guard<std::mutex> lock(svc.audio_queue_mutex_);
        svc.playback_drained_notified_ = false;
        svc.audio_playback_queue_.push_back(AudioTask{
            std::vector<int16_t>(1920, 42), 0, 1, 60, 60,
        });
        svc.audio_queue_cv_.notify_all();
    }
    {
        std::unique_lock<std::mutex> pl(svc.pause_mu);
        svc.pause_cv.wait(pl, [&]{ return svc.popped_reached.load(); });
    }
    // Urgent STOP occurs right after AudioOutputTask popped + unlocked.
    svc.ResetDecoder();
    svc.codec_->EnableOutput(false);
    {
        std::lock_guard<std::mutex> pl(svc.pause_mu);
        svc.release_popped.store(true);
    }
    svc.pause_cv.notify_all();
    while (!svc.IsPlaybackIdle()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    assert(svc.codec_obj.output_data_calls.load() == 0);
    assert(svc.codec_obj.enable_true_calls.load() == 0);
    assert(!svc.codec_obj.output_enabled());
    assert(svc.callbacks_.progress_calls.load() == 0);
    assert(svc.callbacks_.committed_calls.load() == 0);
    assert(svc.debug_statistics_.playback_count == 0);

    // Next fresh TTS utterance in new generation plays and commits normally.
    {
        std::lock_guard<std::mutex> lock(svc.audio_queue_mutex_);
        svc.playback_drained_notified_ = false;
        svc.audio_playback_queue_.push_back(AudioTask{
            std::vector<int16_t>(1920, 99), 0, 2, 60, 60,
        });
        svc.audio_queue_cv_.notify_all();
    }
    while (svc.callbacks_.committed_calls.load() == 0 || !svc.IsPlaybackIdle()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    assert(svc.codec_obj.output_data_calls.load() == 1);
    assert(svc.codec_obj.enable_true_calls.load() == 1);
    assert(svc.codec_obj.output_enabled());
    assert(svc.callbacks_.progress_calls.load() == 1);
    assert(svc.debug_statistics_.playback_count == 1);

    svc.service_stopped_.store(true);
    svc.audio_queue_cv_.notify_all();
    worker.join();
}
""",
        encoding="utf-8",
    )
    pie_flags = [] if sys.platform == "darwin" else ["-fno-pie", "-no-pie"]
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
         "-fsanitize=address,undefined", *pie_flags, str(cpp), "-o", str(binary)],
        check=True, capture_output=True, text=True, env=native_cpp_env(),
    )
    subprocess.run([str(binary)], check=True, timeout=30, env=native_cpp_env())

def test_sense_dma_callbacks_never_log_synchronously():
    """Check the wrapper and Sense-only generated driver error paths."""
    codec = (HEAD / "sense/sense_reference_codec.cc").read_text()
    callbacks = codec.split("int SenseReferenceCodec::Read(", 1)[1].split(
        "void SenseReferenceCodec::ClearReference()", 1
    )[0]
    installer = (HEAD / "install_overlay.py").read_text()
    tx = installer.split("const esp_err_t err = i2s_channel_write(", 1)[1].split(
        "#else", 1
    )[0]
    rx = installer.split("// All Sense read errors return no samples.", 1)[1].split(
        "#else", 1
    )[0]
    for section in (callbacks, tx, rx):
        assert not re.search(r"\b(?:ESP_LOG\w*|printf|fprintf|uart_write_bytes)\s*\(", section)
    assert "if (err != ESP_OK)" in tx
    assert "bytes_written = 0;" in tx
    assert "++short_input_reads_" in callbacks
    assert "++short_output_writes_" in callbacks
    assert "++stale_publish_discards_" in callbacks
    assert "return stale_write ? 0 : accepted;" in callbacks

