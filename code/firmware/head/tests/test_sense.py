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


@unittest.skipUnless(UPSTREAM.is_dir(), 'Pinned upstream fixture unavailable')
class SenseOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        names = ['main/Kconfig.projbuild', 'main/CMakeLists.txt', 'main/mcp_server.cc',
                 'main/application.cc', 'main/audio/audio_service.cc',
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
        self.assertIn('audio_operator_touched_.store(true);', source)
        self.assertIn('CONFIG_DESK_ROBOT_AEC_DELAY_MS', (board / 'sense_reference_codec.h').read_text())
        self.assertIn('#include "stackchan_behavior.hpp"', source)
        self.assertIn('HsmBehavior face_behavior_', source)
        self.assertIn('body_bridge_->PollInteraction()', source)
        self.assertIn('pending_face_touches_.exchange(0', source)
        self.assertIn('Event(EventType::kTouched)', source)
        self.assertIn('body_fault_active_', source)
        self.assertIn('bool last_rendered_fault = false;', source)
        self.assertIn('static void BodyPollTask(void* context)', source)
        self.assertIn('board->body_fault_active_.store(true, std::memory_order_release);', source)
        self.assertIn('body_unhealthy ? "sad" :', source)
        self.assertIn('person_cue_active ? "surprised" : "neutral"', source)
        self.assertIn('last_was_idle = idle;', source)
        self.assertIn('body_unhealthy ? "sad" :', source)
        self.assertIn('person_cue_active ? "surprised" : "neutral"', source)
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
        self.assertIn('pending_face_touches_.exchange(0', face)
        self.assertIn('if (!body_unhealthy)', face)
        self.assertIn('vTaskDelay(pdMS_TO_TICKS(100));', face)
        self.assertIn('xTaskCreate(BodyPollTask, "sense_body_poll"', source)

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
        self.assertIn('Envelope(false, "camera busy")', bridge)
        self.assertIn("vTaskDelay(pdMS_TO_TICKS(250));", bridge)
        self.assertIn("bridge->camera_busy_.store(false);", bridge)
        self.assertIn('"camera_sensor_pid"', bridge)


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
        self.assertIn("ReadReferenceLocked(reference_frame_.data(), frames)", read)
        self.assertNotIn("std::vector<int16_t>", read)


    def test_reference_underflow_diagnostics_are_rate_limited(self):
        """Source-level diagnostic coverage, not acoustic qualification."""
        header = (HEAD / "sense/sense_reference_codec.h").read_text()
        code = (HEAD / "sense/sense_reference_codec.cc").read_text()
        self.assertIn("bool ReadReferenceLocked(int16_t* dest, int frames);", header)
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
        assert "camera_busy_.exchange(true)" in bridge
        assert "camera_busy_.store(false)" in bridge
        assert "vTaskDelay(pdMS_TO_TICKS(250))" in bridge
        assert "httpd_resp_send_chunk(req" in bridge
        assert "X-Desk-Camera-Sequence: %u" in bridge
        assert "X-Desk-Camera-Complete-Us: %lld" in bridge
        assert "config.max_uri_handlers = 9;" in bridge
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
    assert 'config.max_uri_handlers = 9;' in bridge
    assert '"/api/camera.identity", HTTP_GET' in bridge
    assert 'strcmp(event->valuestring, "person_detected") != 0' in bridge
    assert 'person_cue_pending_.store(true' in bridge
    assert 'person_cue_pending_.exchange(false' in bridge
    assert 'bool TakePersonCue();' in header
    assert 'body_bridge_->TakePersonCue()' in board
    assert 'Event(EventType::kPersonDetected)' in board
    assert 'person_cue_active ? "surprised" : "neutral"' in board
    assert 'board->body_fault_active_ ? "sad" :' in board
    assert 'Transact(event' not in bridge  # never send cue to WROOM


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
