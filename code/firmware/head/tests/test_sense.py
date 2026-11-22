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
                 'main/audio/audio_service.cc',
                 'main/audio/codecs/no_audio_codec.cc']
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
        assert "std::atomic<uint32_t> sense_audio_failure_epoch_{0};" in header
        assert "const uint32_t failure_epoch = app.GetSenseAudioFailureEpoch();" in face
        assert "failure_epoch != board->last_audio_failure_epoch_seen_" in face
        assert "failed_since_attempt &&" in face
        assert "now_ms - board->last_audio_listen_attempt_ms_ >= 5000U" in face
        assert "board->last_audio_failure_epoch_seen_ = failure_epoch;" in face
        assert "!board->audio_operator_touched_.load()" in face
        assert "device_state == kDeviceStateIdle" in face
        assert "app.ToggleChatState();" in face
        assert "app.StartListening();" not in face
        assert "app.StopListening();" not in face

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
        self.assertIn('config DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED', kconfig)
        self.assertIn('depends on USE_AUDIO_PROCESSOR && USE_DEVICE_AEC', kconfig)
        self.assertIn('#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED', source)
        self.assertIn('app.GetAecMode() == kAecOnDeviceSide', source)
        self.assertIn('app.ToggleChatState();  // existing Xiaozhi realtime listen', source)
        self.assertIn('board->continuous_audio_started_ = true;', source)
        self.assertIn('WifiManager::GetInstance().IsConnected()', source)
        self.assertIn('if (!wifi_connected)', source)
        self.assertIn('board->continuous_audio_started_ = false;', source)
        self.assertIn('&& wifi_connected && now_ms >= 10000', source)
        self.assertLess(
            source.index('if (!board->continuous_audio_started_'),
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
        self.assertIn('body_fault_active_', source)
        self.assertIn('bool last_rendered_fault = false;', source)
        self.assertIn('static void BodyPollTask(void* context)', source)
        self.assertIn('board->body_fault_active_.store(true, std::memory_order_release);', source)
        self.assertIn('board->display_->SetStatus("Body safety stop");', source)
        self.assertNotIn('body_unhealthy ? "sad" :', source)
        self.assertIn('Event(EventType::kPersonDetected)', source)
        self.assertIn('last_was_idle = idle;', source)
        self.assertIn('board->display_->SetStatus("Body safety stop");', source)
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
        self.assertIn('action.set_mood ? MoodName(action.mood) : "neutral"', source)
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
        assert 'board->body_dock_lockout_active_.store(false,' in source
        assert 'body_unhealthy && valid_at != 0 &&' in source
        assert 'now_ms - valid_at <= 1200U &&' in source
        assert 'dock_lockout != last_rendered_dock_lockout' in source
        assert 'board->display_->SetStatus("Dock lock: motors off");' in source
        assert 'board->display_->SetStatus("Body safety stop");' in source
        assert 'if (body_unhealthy || !face_available)' in source
        assert 'if (body_unhealthy)' in source
        assert 'charging' not in source.split(
            'board->display_->SetStatus("Dock lock: motors off");', 1,
        )[0].split('if (body_unhealthy &&', 1)[-1].lower()

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


    def test_latched_body_fault_remains_visible_during_continuous_listening(self):
        """Xiaozhi may overwrite OLED status without an idle transition."""
        source = (HEAD / "sense/desk_robot_sense.cc").read_text()
        face = source.split("static void FaceTask(void* context)", 1)[1]
        face = face.split("void InitializeDisplay()", 1)[0]
        self.assertIn("uint32_t last_fault_status_refresh_ms = 0;", face)
        self.assertIn("now_ms - last_fault_status_refresh_ms >= 750U", face)
        self.assertIn("last_fault_status_refresh_ms = now_ms;", face)
        self.assertIn('board->display_->SetStatus("Body safety stop");', face)
        self.assertIn("if (body_unhealthy &&", face)
        self.assertIn("else if (last_rendered_fault && !body_unhealthy)", face)
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
        self.assertIn('body_last_valid_ms_.store(', poll)
        self.assertIn('body_last_valid_ms_.load(', face)
        self.assertIn('now_ms - valid_at > 1200U', face)
        self.assertNotIn('pending_face_touches_', face)
        self.assertNotIn('Event(EventType::kTouched)', face)
        self.assertIn('TakeCosmeticMoodCue()', face)
        # A body fault now shows a factual status and neutral OLED mood.
        # Model-selected moods are considered only on the healthy branch.
        self.assertIn('if (body_unhealthy) {', face)
        self.assertIn('board->display_->SetEmotion("neutral");', face)
        self.assertIn('else if (requested_mood != desk_robot::CosmeticMood::kNone)', face)
        self.assertLess(
            face.index('if (body_unhealthy) {'),
            face.index('else if (requested_mood != desk_robot::CosmeticMood::kNone)'),
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
        self.assertIn('Sense speaker resampler unavailable: discarding mismatched PCM', audio)
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


    def test_sense_pdm_mic_read_timeout_is_bounded(self):
        """A PDM DMA stall must yield to the existing Xiaozhi audio task.

        The installed Sense upstream build is the test target, not a mock.
        """
        overlay.apply(self.root, 'sense')
        codec = (self.root / 'main/audio/codecs/no_audio_codec.cc').read_text()
        reader = codec.split('int NoAudioCodecSimplexPdm::Read(', 1)[1]
        self.assertIn('#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3', reader)
        self.assertIn('pdMS_TO_TICKS(120)', reader)
        self.assertIn('read_status != ESP_OK', reader)
        self.assertIn('read_status != ESP_ERR_TIMEOUT', reader)
        self.assertIn('return 0;', reader)
        self.assertIn('portMAX_DELAY', reader)  # Other boards unchanged.
        self.assertNotIn(
            'i2s_channel_read(rx_handle_, dest, samples * sizeof(int16_t), '
            '&bytes_read, portMAX_DELAY) != ESP_OK', reader,
        )

    def test_invalid_32khz_opus_offer_does_not_destroy_decoder(self):
        """The 32 kHz DAC clock is not an Opus decode rate (source gate)."""
        overlay.apply(self.root, 'sense')
        audio = (self.root / 'main/audio/audio_service.cc').read_text()
        setter = audio.split('void AudioService::SetDecodeSampleRate(', 1)[1]
        setter = setter.split('void AudioService::PushTaskToEncodeQueue(', 1)[0]
        self.assertIn('sample_rate != 24000', setter)
        self.assertIn('sample_rate != 48000', setter)
        self.assertIn('Rejecting unsupported Sense Opus rate', setter)
        # An invalid frame duration such as 30 ms must be rejected before
        # touching the active decoder, even when its sample rate is valid.
        for duration in (5, 10, 20, 40, 60):
            self.assertIn(f'frame_duration != {duration}', setter)
        self.assertIn('Rejecting unsupported Sense Opus frame duration', setter)
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
        self.assertIn('#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3', setter)
        # 32 kHz remains the DAC rate; Opus decoder should stay at 24 kHz.
        config = (self.root / overlay.BOARDS['sense'] / 'config.h').read_text()
        self.assertIn('#define AUDIO_OUTPUT_SAMPLE_RATE 32000', config)
        self.assertIn('constexpr int initial_decoder_rate = 24000;', audio)

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
        assert "if (body_unhealthy || !face_available) model_mood_active = false;" in face
        # Avoid an every-100ms LVGL write in an unending listening state.
        assert "last_face_available = face_available;" in face
        assert "!last_face_available || action.set_mood" in face
        # Moods are visual only. Xiaozhi's status and safety own the label.
        assert "Lang::Strings::LISTENING" in face
        assert "board->display_->SetStatus(\"Body safety stop\");" in face
        assert "head.command(" not in face
        assert "speaker.say(" not in face

    def test_new_body_fault_neutralizes_emotion_even_while_speaking(self):
        """A status fault cannot leave a happy emoji through a long song."""
        source = (HEAD / "sense/desk_robot_sense.cc").read_text()
        face = source.split("static void FaceTask(void* context)", 1)[1].split(
            "void InitializeDisplay()", 1
        )[0]
        neutral = face.index("if (body_unhealthy && !last_idle_face_fault)")
        available = face.index("if (face_available && board->display_ != nullptr)")
        assert neutral < available
        assert 'board->display_->SetEmotion("neutral");' in face[neutral:available]
        # This cursor advances irrespective of speaking/listening state.
        assert face.index("last_idle_face_fault = body_unhealthy;") > available
        assert face.count("last_idle_face_fault = body_unhealthy;") == 1
        assert "last_fault_status_refresh_ms = now_ms;" in face
        assert "board->display_->SetStatus(\"Body safety stop\");" in face

    def test_sense_server_audio_close_rejoins_only_same_consentful_xiaozhi_channel(self):
        """WiFi may stay connected after WebSocket closes; BOOT still wins."""
        board = (HEAD / "sense/desk_robot_sense.cc").read_text()
        face = board.split("static void FaceTask(void* context)", 1)[1].split(
            "void InitializeDisplay()", 1,
        )[0]
        self.assertIn("last_audio_listen_attempt_ms_ = 0;", board)
        self.assertIn(
            "now_ms - board->last_audio_listen_attempt_ms_ >= 5000U", face,
        )
        self.assertIn("board->last_audio_listen_attempt_ms_ = now_ms;", face)
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
        status = face.index('SetStatus("Body safety stop")')
        idle_mood = face.index("if (face_available && board->display_ != nullptr)")
        self.assertLess(status, idle_mood)
        # A WROOM fault must remain visible even if Xiaozhi rewrites
        # the display while speaking or listening continuously.
        self.assertIn("now_ms - last_fault_status_refresh_ms >= 750U", face)
        self.assertIn("last_fault_status_refresh_ms = now_ms;", face)
        self.assertIn("board->display_->SetStatus(\"Body safety stop\");", face)
        # Continuous listening may never go idle. Restore Xiaozhi's
        # localized speaking/listening status on recovery, not a blank label.
        self.assertIn("else if (last_rendered_fault && !body_unhealthy)", face)
        self.assertIn("Lang::Strings::SPEAKING", face)
        self.assertIn("Lang::Strings::LISTENING", face)
        self.assertIn("else if (idle)", face)
        self.assertIn("last_rendered_fault = false;", face)
        self.assertIn("const Action action = board->face_behavior_.update(obs);", face)
        # The emergency neutral face is immediate, even while speaking.
        self.assertLess(face.index('board->display_->SetEmotion("neutral");'), idle_mood)
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
        assert 'control.sample_range_optics(' in (
            ROOT / "firmware/body/src/main.cpp"
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
        self.assertIn("uint64_t reference_generation_ = 0;", header)
        writer = code.split("int SenseReferenceCodec::Write(", 1)[1]
        writer = writer.split("void SenseReferenceCodec::ClearReference()", 1)[0]
        self.assertLess(
            writer.index("started_generation = reference_generation_;"),
            writer.index("NoAudioCodec::Write(data, samples)"),
        )
        self.assertLess(
            writer.index("NoAudioCodec::Write(data, samples)"),
            writer.index("started_generation == reference_generation_"),
        )
        self.assertIn("if (stale_publish_discards_ != UINT32_MAX) ++stale_publish_discards_;", writer)
        self.assertIn("stale_discards = stale_publish_discards_;", writer)
        self.assertIn("reference_integrity_failed_ = true;", writer)
        self.assertIn("PublishAcceptedLocked(data, accepted, volume", writer)
        clear = code.split("void SenseReferenceCodec::ClearReference()", 1)[1]
        self.assertLess(
            clear.index("++reference_generation_;"),
            clear.index("reference_.fill(0);"),
        )
        self.assertIn('physical TX silence unverified', writer)

    def test_sense_i2s_override_reuses_bounded_upstream_writer(self):
        """Keep only the pinned codec writer, not a second audio stack."""
        writer = (HEAD / "sense/sense_reference_codec.cc").read_text().split(
            "int SenseReferenceCodec::Write(", 1
        )[1].split("void SenseReferenceCodec::ClearReference()", 1)[0]
        installer = (HEAD / "install_overlay.py").read_text()
        assert "NoAudioCodec::Write(data, samples)" in writer
        assert "const int volume = std::clamp(output_volume_, 0, 100);" in writer
        assert "i2s_channel_write(" not in writer
        assert "pdMS_TO_TICKS(120)" in installer
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
        self.assertIn("if (log_short)", writer)
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


    def test_reference_underflow_diagnostics_are_rate_limited(self):
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
        self.assertIn("consecutive_missing >= 32", code)
        self.assertIn("(consecutive_missing - 32U) % 256U == 0U", code)
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
        self.assertIn("newly_overwritten = overwrite_count != previous_overwrites;", code)
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
        self.assertIn("buf[0] != 0xff || buf[1] != 0xd8", snapshot)
        self.assertIn("buf[len - 2] != 0xff || buf[len - 1] != 0xd9", snapshot)
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
        assert "config.max_uri_handlers = 14;" in bridge
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
                ' HsmBehavior picker(2);\n'
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
        self.assertIn("((result[0] & 0x78U) >> 3) == 11U", tof)
        self.assertIn("distance >= 30 && distance <= 1300", tof)
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
    assert 'config.max_uri_handlers = 14;' in bridge
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
    assert 'body_unhealthy || !face_available' in board
    assert 'board->display_->SetStatus("Body safety stop");' in board
    assert 'Event(EventType::kPersonDetected)' in board
    assert 'body_unhealthy ? "sad" :' not in board
    assert 'person_cue_active ? "surprised" :' not in board
    assert 'Transact(event' not in bridge  # never send cue to WROOM


def test_sense_fault_face_overrides_idle_moods_and_recovers_once():
    """The local OLED cannot smile through a current WROOM safety fault."""
    board = (HEAD / "sense/desk_robot_sense.cc").read_text()
    face = board.split("static void FaceTask(void* context)", 1)[1].split(
        "void InitializeDisplay()", 1
    )[0]
    assert 'if (body_unhealthy) {' in face
    fault = face.split('if (body_unhealthy) {', 2)[-1].split(
        '} else if (requested_mood', 1
    )[0]
    # Motor safety is factual; a fault must not force scripted sadness.
    assert 'SetEmotion("neutral")' in fault
    assert 'SetEmotion("sad")' not in fault
    assert 'last_idle_face_fault && !last_face_available' in fault
    assert 'model_mood_active = false;' in fault
    # Recovery must force a neutral/local HSM face refresh even if its
    # idle picker emitted no new mood. No 100 ms continuous OLED spam.
    assert 'if (last_idle_face_fault || model_mood_active ||' in face
    assert 'last_idle_face_fault = body_unhealthy;' in face
    assert 'SetStatus("Body safety stop")' in face



def test_boot_microphone_privacy_has_own_local_oled_status():
    """Physical BOOT mic privacy must not be confused with speaker volume."""
    board = (HEAD / "sense/desk_robot_sense.cc").read_text()
    face = board.split("static void FaceTask(void* context)", 1)[1].split(
        "void InitializeDisplay()", 1
    )[0]
    assert 'audio_operator_muted_.load(' in face
    assert 'SetStatus("Mic privacy ON")' in face
    assert '!body_unhealthy && mic_privacy_on' in face
    assert '!body_unhealthy && !mic_privacy_on' in face
    assert 'last_idle_face_fault ||' in face
    assert 'now_ms - last_mic_privacy_refresh_ms >= 750U' in face
    assert 'last_mic_privacy_overlay = mic_privacy_on;' in face
    assert face.index('SetStatus("Body safety stop")') < face.index(
        'SetStatus("Mic privacy ON")'
    )
    assert 'SetStatus(Lang::Strings::SPEAKING)' in face
    assert 'SetStatus(Lang::Strings::LISTENING)' in face
    assert 'app.ToggleChatState();' not in face.split(
        'const bool mic_privacy_on = ', 1
    )[1].split('last_mic_privacy_overlay = mic_privacy_on;', 1)[0]


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
             "-I", str(HEAD / "sense"),
             str(HEAD / "tests/reference_timeline_test.cc"),
             "-o", str(exe)],
            check=True,
            env=native_cpp_env(),
        )
        subprocess.run([str(exe)], check=True)


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
    assert "kSpeakerRate % kMicRate == 0" in header
    assert "static_assert(AUDIO_INPUT_SAMPLE_RATE == kMicRate" in header
    assert "static_assert(AUDIO_OUTPUT_SAMPLE_RATE == kSpeakerRate" in header
    # The fixed 2:1 ratio permits zero or one publish per output sample,
    # never a misleading loop over unsupported fractional rate profiles.
    assert "if (phase_ < 1.0f)" in codec
    assert "while (phase_ < 1.0f)" not in codec
    assert "phase_ += static_cast<float>(kSpeakerRate) / kMicRate;" in codec
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
    assert "Sense speaker resampler unavailable" in overlay_source
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
    assert 'board->display_->SetStatus("Body safety stop");' in face
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
    assert "if (urgent_stop_gate_.preempts(urgent))" in source
    assert "void Bridge::BodyReadTask(void* context)" in source
    assert 'xTaskCreate(BodyReadTask, "robot_body_read"' in source
    assert "httpd_req_async_handler_begin(req, &async_req)" in source
    assert "httpd_req_async_handler_complete(req);" in source
    assert "class UrgentStopGate" in protocol
    assert "Request(const Request&) = delete;" in protocol

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
    assert "AbortBenchPcmCapture();" in codec.split(
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
    starter = codec.split("bool SenseReferenceCodec::BeginBenchPcmCapture()", 1)[1]
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
    assert "face_available && !body_unhealthy && !model_mood_active" in face
    assert "board->local_eye_display_->ShowEyes(eyes);" in face
    assert face.index("board->local_eye_display_->ShowEyes(eyes);") > face.index(
        "board->display_->SetEmotion(CosmeticMoodName(requested_mood))"
    )
    assert "new desk_robot::LocalEyeDisplay(" in source
    assert "display_ = local_eye_display_;" in source
    assert "face_behavior_.pick_min_ms = 6000;" in source
    assert "face_behavior_.pick_max_ms = 15000;" in source
    assert "void SetupUI() override" in renderer
    assert "OledDisplay::SetupUI();" in renderer
    assert "DisplayLockGuard lock(this);" in renderer
    assert "lv_obj_set_pos(pupil_[i], 4 + frame.x, 5 + frame.y);" in renderer
    # The upstream 128x64 OLED layout centers its 32px emotion cell.
    # Anchoring at x=0 would leave the stock center emotion visible beside
    # the gaze/blink overlay, even though the HSM/animator tests still pass.
    assert 'lv_obj_set_size(eye_layer_, 32, 48);' in renderer
    assert 'lv_obj_align(eye_layer_, LV_ALIGN_TOP_MID, 0, 16);' in renderer
    assert 'lv_obj_set_pos(eye_layer_, 0, 16);' not in renderer
    assert renderer.index('lv_obj_set_size(eye_layer_, 32, 48);') < renderer.index(
        'lv_obj_align(eye_layer_, LV_ALIGN_TOP_MID, 0, 16);'
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
using namespace desk_robot;
using stackchan::behavior::Motion;
int main() {
    FaceEyeAnimator eyes;
    auto left = eyes.Step(1000, Motion::kLookLeft, true);
    assert(left.visible && left.x == -3 && !left.closed);
    assert(!eyes.Step(2200, Motion::kNone, true).visible);
    auto blink = eyes.Step(6000, Motion::kNone, true);
    assert(blink.visible && !blink.closed);
    assert(eyes.Step(6150, Motion::kNone, true).closed);
    assert(!eyes.Step(6400, Motion::kNone, true).visible);
    assert(!eyes.Step(6450, Motion::kLookRight, false).visible);
    assert(!eyes.Step(6500, Motion::kNone, true).visible);
    assert(eyes.Step(6700, Motion::kLookRight, true).x == 3);
    assert(eyes.Step(6800, Motion::kLookUp, true).y == -3);
    assert(eyes.Step(6900, Motion::kNod, true).y == 3);
    assert(eyes.Step(7450, Motion::kNone, true).y == -2);
    assert(!eyes.Step(8101, Motion::kNone, true).visible);
    FaceEyeAnimator rollover;
    assert(rollover.Step(0xfffffff0U, Motion::kLookLeft, true).visible);
    assert(rollover.Step(0x40U, Motion::kNone, true).visible);
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
