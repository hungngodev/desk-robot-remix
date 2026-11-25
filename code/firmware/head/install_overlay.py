#!/usr/bin/env python3
"""Apply a version-pinned, reversible Xiaozhi board overlay; never changes the source clone."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

PIN = "c435f99a88066029ec2dbd2d758c8cc9d051565b"
BOARD = "main/boards/desk-robot/desk-robot-core-s3"
BOARDS = {
    "cores3": BOARD,
    "modular": "main/boards/desk-robot/desk-robot-modular-s3",
    "sense": "main/boards/desk-robot/desk-robot-sense-s3",
    "waveshare": "main/boards/desk-robot/desk-robot-waveshare-s3-cam",
}
MARKER = ".desk-robot-head-overlay.json"
HERE = Path(__file__).resolve().parent


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Upstream patch anchor changed: {old[:80]!r}")
    return text.replace(old, new, 1)


def harden_release_tooling(source: str) -> str:
    """Require remote digest evidence, not only the uploaded byte count."""
    source = replace_once(
        source,
        '    if {a["name"] for a in remote["assets"]} != set(expected):',
        '    if (len(remote["assets"]) != len(expected)\n'
        '            or {a["name"] for a in remote["assets"]} != set(expected)):',
    )
    return replace_once(
        source,
        '        if digest and digest != "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest():',
        '        if digest != "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest():',
    )


def instrument_p3_player(source: str) -> str:
    """Instrument the pinned host-only blocking PortAudio player."""
    source = replace_once(
        source,
        '    stream.start()\n',
        '''    metrics = {
        "submitted_frames": 0,
        "write_calls": 0,
        "underflow_reports": 0,  # All PortAudio reports, including startup/pause.
        "underflow_reports_first_write": 0,
        "underflow_reports_after_pause": 0,
        "underflow_reports_active": 0,  # Neither startup nor immediately after pause.
        "output_overrun_reports": None,  # Not exposed by blocking OutputStream.
        "writes_exceeding_available_frames": 0,
        "min_write_available_frames": None,
        "output_latency_estimate_ms": None,
        "stream_start_to_first_write_return_ms": None,
        "max_write_ms": None,
        "termination": "stopped",
    }
    started_at = time.monotonic()
    paused_since_write = False
    stream_started = False
''',
    )
    source = replace_once(
        source,
        "    try:\n        with open(input_file, 'rb') as f:\n",
        "    try:\n        stream.start()\n        stream_started = True\n"
        "        with open(input_file, 'rb') as f:\n",
    )
    source = replace_once(
        source,
        '                if pause_event and pause_event.is_set():\n',
        '                if pause_event and pause_event.is_set():\n'
        '                    paused_since_write = True\n',
    )
    source = replace_once(
        source,
        '                if not header or len(header) < 4:\n                    break\n',
        '''                if not header:
                    metrics["termination"] = "eof" if metrics["write_calls"] else "empty"
                    break
                if len(header) != 4:
                    raise ValueError("Truncated P3 packet header")
''',
    )
    source = replace_once(
        source,
        "                packet_type, reserved, data_len = struct.unpack('>BBH', header)\n",
        '''                packet_type, reserved, data_len = struct.unpack('>BBH', header)
                if packet_type != 0 or reserved != 0 or data_len == 0:
                    raise ValueError("Invalid P3 audio packet header")
''',
    )
    source = replace_once(
        source,
        '                if not opus_data or len(opus_data) < data_len:\n'
        '                    break\n',
        '''                if len(opus_data) != data_len:
                    raise ValueError("Truncated P3 Opus payload")
''',
    )
    source = replace_once(
        source,
        '                pcm_data = decoder.decode(opus_data, frame_size)\n',
        '''                pcm_data = decoder.decode(opus_data, frame_size)
                if not pcm_data or len(pcm_data) % 2 or len(pcm_data) > 2 * frame_size:
                    raise ValueError("Invalid decoded P3 PCM frame")
''',
    )
    source = replace_once(
        source,
        '                stream.write(audio_array)\n',
        '''                # Headroom is not an overrun or a count of queued frames.
                available = stream.write_available
                previous_min = metrics["min_write_available_frames"]
                metrics["min_write_available_frames"] = (
                    available if previous_min is None else min(previous_min, available)
                )
                write_started = time.monotonic()
                underflowed = stream.write(audio_array)
                write_finished = time.monotonic()
                write_ms = (write_finished - write_started) * 1000
                previous_max = metrics["max_write_ms"]
                metrics["max_write_ms"] = (
                    write_ms if previous_max is None else max(previous_max, write_ms)
                )
                first_write = metrics["write_calls"] == 0
                if first_write:
                    metrics["output_latency_estimate_ms"] = stream.latency * 1000
                    metrics["stream_start_to_first_write_return_ms"] = (
                        write_finished - started_at
                    ) * 1000
                metrics["write_calls"] += 1
                metrics["submitted_frames"] += len(audio_array)
                metrics["writes_exceeding_available_frames"] += int(
                    len(audio_array) > available
                )
                if underflowed:
                    metrics["underflow_reports"] += 1
                    metrics["underflow_reports_first_write"] += int(first_write)
                    metrics["underflow_reports_after_pause"] += int(paused_since_write)
                    metrics["underflow_reports_active"] += int(
                        not first_write and not paused_since_write
                    )
                paused_since_write = False
''',
    )
    source = replace_once(
        source,
        "        stream.stop()\n        stream.close()\n",
        "        try:\n            if stream_started:\n                stream.stop()\n"
        "        finally:\n            stream.close()\n",
    )
    source = replace_once(
        source,
        '        print("播放完成")\n',
        '    print("P3 host playback metrics (not acoustic latency):", metrics)\n'
        '    return metrics\n',
    )
    return replace_once(
        source,
        "            play_p3_file(file, self.stop_event, self.pause_event)\n",
        '''            try:
                result = play_p3_file(file, self.stop_event, self.pause_event)
                if result["termination"] == "empty":
                    raise ValueError("Empty P3 audio file")
            except Exception as exc:
                print(f"P3 playback failed: {exc}")
                self.is_playing = False
                self.is_paused = False
                self.update_status(f"P3 playback failed: {exc}", "red")
                return
''',
    )


def patch_camera_explain_config(header: str, source: str) -> tuple[str, str]:
    """Take one coherent endpoint snapshot per request, without holding a network lock."""
    header = replace_once(
        header,
        '#include "camera.h"',
        '#include "camera.h"\n#include "desk_robot_camera_explain_config.hpp"',
    )
    header = replace_once(
        header,
        "    std::string explain_url_;\n    std::string explain_token_;",
        "    desk_robot::CameraExplainConfig explain_config_;",
    )
    source = replace_once(
        source,
        "    explain_url_ = url;\n    explain_token_ = token;",
        "    explain_config_.Set(url, token);",
    )
    source = replace_once(
        source,
        "    if (explain_url_.empty()) {",
        "    const auto explain_target = explain_config_.Snapshot();\n"
        "    if (explain_target.url.empty()) {",
    )
    source = replace_once(source, "!explain_token_.empty()", "!explain_target.token.empty()")
    source = replace_once(source, '"Bearer " + explain_token_', '"Bearer " + explain_target.token')
    source = replace_once(source, 'http->Open("POST", explain_url_)',
                          'http->Open("POST", explain_target.url)')
    return header, source


def cores3_files(target: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    stock = target / "main/boards/m5stack/core-s3"
    for name in ("config.h", "cores3_audio_codec.h", "cores3_audio_codec.cc"):
        files[f"{BOARD}/{name}"] = (stock / name).read_bytes()
    source = (stock / "m5stack_core_s3.cc").read_text()
    source = source.replace("M5StackCoreS3Board", "DeskRobotCoreS3Board")
    source = replace_once(
        source, '#include "wifi_board.h"', '#include "wifi_board.h"\n#include "robot_bridge.h"'
    )
    source = replace_once(
        source,
        "    virtual AudioCodec* GetAudioCodec() override {",
        """    void StartNetwork() override {
        // WiFi initialization creates lwIP before HTTP sockets can be opened.
        // The constructor has already initialized the stock camera/display/audio.
        WifiBoard::StartNetwork();
        static desk_robot::Bridge robot_bridge(camera_);
        static std::once_flag bridge_once;
        std::call_once(bridge_once, [] { robot_bridge.Start(); });
    }

    virtual AudioCodec* GetAudioCodec() override {""",
    )
    files[f"{BOARD}/desk_robot_core_s3.cc"] = source.encode()
    for path in (HERE / "overlay").iterdir():
        if path.suffix in (".h", ".cc", ".hpp"):
            files[f"{BOARD}/{path.name}"] = path.read_bytes()
    config = json.loads((stock / "config.json").read_text())
    config["manufacturer"] = "desk-robot"
    config["type"] = "desk-robot-core-s3"
    config["builds"][0]["name"] = "desk-robot-core-s3"
    config["builds"][0]["sdkconfig_append"].extend(
        [
            'CONFIG_DESK_ROBOT_ID="robot-01"',
            'CONFIG_DESK_ROBOT_TOKEN=""',
        ]
    )
    files[f"{BOARD}/config.json"] = (json.dumps(config, indent=2) + "\n").encode()
    files[f"{BOARD}/README.md"] = (HERE / "BOARD_README.md").read_bytes()

    path = "main/Kconfig.projbuild"
    text = (target / path).read_text()
    text = replace_once(
        text,
        "    config BOARD_TYPE_DF_S3_AI_CAM\n",
        '    config BOARD_TYPE_DESK_ROBOT_CORE_S3\n        bool "Desk robot CoreS3 Lite"\n        depends on IDF_TARGET_ESP32S3\n    config BOARD_TYPE_DF_S3_AI_CAM\n',
    )
    text += """\nmenu "Desk robot private settings"
    depends on BOARD_TYPE_DESK_ROBOT_CORE_S3
config DESK_ROBOT_ID
    string "Unique robot ID"
    default "robot-01"
config DESK_ROBOT_TOKEN
    string "Private LAN bearer token (32..128 characters; empty disables robot bridge)"
    default ""
config DESK_ROBOT_DIRECT_MOTION_TOOLS
    bool "Expose low-level drive/lift/grip MCP tools (bench debugging only)"
    default n
endmenu
"""
    files[path] = text.encode()
    path = "main/CMakeLists.txt"
    text = (target / path).read_text()
    branch = """elseif(CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3)
    set(BOARD_DIR "desk-robot/desk-robot-core-s3")
    set(BUILTIN_TEXT_FONT font_noto_sans_basic_20_4)
    set(BUILTIN_ICON_FONT font_material_symbols_20_4)
    set(DEFAULT_EMOJI_COLLECTION noto-color-emoji_64)
"""
    text = replace_once(
        text,
        "elseif(CONFIG_BOARD_TYPE_M5STACK_CORE_S3)\n",
        branch + "elseif(CONFIG_BOARD_TYPE_M5STACK_CORE_S3)\n",
    )
    text = replace_once(
        text,
        'set(MAIN_PRIV_REQUIRES_EXTRA "")',
        'set(MAIN_PRIV_REQUIRES_EXTRA "")\nif(CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3)\n    list(APPEND MAIN_PRIV_REQUIRES_EXTRA esp_http_server)\nendif()',
    )
    files[path] = text.encode()

    path = "main/boards/common/camera.h"
    text = (target / path).read_text()
    text = replace_once(
        text,
        "#include <expected>",
        '#include <expected>\n#include "sdkconfig.h"\n#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n#include <mutex>\n#include <vector>\n#endif',
    )
    text = replace_once(
        text,
        "    virtual ~Camera() = default;",
        """    virtual ~Camera() = default;
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3
    // Capture+Explain must hold the same lock as HTTP snapshots across both calls.
    std::recursive_mutex& AccessMutex() { return access_mutex_; }
    virtual std::expected<std::vector<uint8_t>, std::string> SnapshotJpeg() {
        return std::unexpected("Snapshot not supported by this camera");
    }
private:
    std::recursive_mutex access_mutex_;
public:
#endif""",
    )
    files[path] = text.encode()
    path = "main/boards/common/esp_video.h"
    text = (target / path).read_text()
    text = replace_once(
        text,
        "    virtual bool Capture();",
        "    virtual bool Capture();\n#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n    std::expected<std::vector<uint8_t>, std::string> SnapshotJpeg() override;\n#endif",
    )
    files[path] = text.encode()
    path = "main/boards/common/esp_video.cc"
    text = (target / path).read_text()
    header_path = "main/boards/common/esp_video.h"
    header, text = patch_camera_explain_config(files[header_path].decode(), text)
    files[header_path] = header.encode()
    files["main/boards/common/desk_robot_camera_explain_config.hpp"] = (
        HERE / "overlay/camera_explain_config.hpp"
    ).read_bytes()
    for anchor in (
        "bool EspVideo::Capture() {",
        "std::expected<std::string, std::string> EspVideo::Explain(const std::string& question) {",
    ):
        text = replace_once(
            text,
            anchor,
            anchor
            + "\n#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n    std::lock_guard<std::recursive_mutex> camera_lock(AccessMutex());\n#endif",
        )
    text += """
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3
std::expected<std::vector<uint8_t>, std::string> EspVideo::SnapshotJpeg() {
    std::lock_guard<std::recursive_mutex> camera_lock(AccessMutex());
    if (!Capture() || !frame_.data || !frame_.len)
        return std::unexpected("Fresh camera capture failed");
    uint8_t* jpeg = nullptr;
    size_t len = 0;
    const bool ok = image_to_jpeg(frame_.data, frame_.len, frame_.width, frame_.height,
                                  frame_.format, 80, &jpeg, &len);
    if (!ok || !jpeg || len < 4 || len > 512 * 1024) {
        free(jpeg);
        return std::unexpected("JPEG encoding failed");
    }
    std::vector<uint8_t> result(jpeg, jpeg + len);
    free(jpeg);
    return result;
}
#endif
"""
    files[path] = text.encode()
    path = "main/mcp_server.cc"
    text = (target / path).read_text()
    text = replace_once(
        text,
        "                    if (!camera->Capture()) {",
        "#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3\n                    std::lock_guard<std::recursive_mutex> camera_lock(camera->AccessMutex());\n#endif\n                    if (!camera->Capture()) {",
    )
    files[path] = text.encode()
    return files


def planned_files(target: Path, board: str = "cores3") -> dict[str, bytes]:
    """Reuse the bridge/locking overlay, replacing only the selected board adapter."""
    if board not in BOARDS:
        raise ValueError(f"Unknown board: {board}")
    if board == "waveshare":
        # Keep all existing variants unchanged. This physical-reference candidate
        # reuses their common camera/HTTP locking, but no Sense PDM adapter.
        files = {
            name: data.replace(b"DESK_ROBOT_MODULAR_S3", b"DESK_ROBOT_WAVESHARE_S3_CAM")
            .replace(
                b"Desk robot modular S3 (Freenove N16R8)",
                b"Desk robot Waveshare S3 CAM (hardware reference)",
            )
            .replace(b"desk-robot/desk-robot-modular-s3", b"desk-robot/desk-robot-waveshare-s3-cam")
            for name, data in planned_files(target, "modular").items()
            if not name.startswith(BOARDS["modular"] + "/")
        }
        for folder in (HERE / "waveshare", HERE / "overlay"):
            for path in folder.iterdir():
                if path.is_file() and path.suffix in (".cc", ".h", ".hpp", ".json", ".md"):
                    files[f"{BOARDS[board]}/{path.name}"] = path.read_bytes()
        path = "main/Kconfig.projbuild"
        files[path] = replace_once(
            files[path].decode(),
            "depends on USE_AUDIO_PROCESSOR && (BOARD_TYPE_ESP32_S3_BOX_3",
            "depends on USE_AUDIO_PROCESSOR && (BOARD_TYPE_DESK_ROBOT_WAVESHARE_S3_CAM || BOARD_TYPE_ESP32_S3_BOX_3",
        ).encode()
        path = f"{BOARDS[board]}/robot_bridge.cc"
        files[path] = replace_once(
            files[path].decode(), "uart_set_pin(kUart, 2, 1,", "uart_set_pin(kUart, 43, 44,"
        ).encode()
        return files
    if board == "sense":
        # Reuse the tested common camera/bridge changes without changing either
        # existing board adapter or its separate build copy.
        files = {
            name: data.replace(b"DESK_ROBOT_MODULAR_S3", b"DESK_ROBOT_SENSE_S3")
            .replace(b"Desk robot modular S3 (Freenove N16R8)", b"Desk robot XIAO ESP32S3 Sense")
            .replace(b"desk-robot/desk-robot-modular-s3", b"desk-robot/desk-robot-sense-s3")
            for name, data in planned_files(target, "modular").items()
            if not name.startswith(BOARDS["modular"] + "/")
        }
        for folder in (HERE / "sense", HERE / "overlay"):
            for path in folder.iterdir():
                if path.is_file() and path.suffix in (".cc", ".h", ".hpp", ".json", ".md"):
                    files[f"{BOARDS[board]}/{path.name}"] = path.read_bytes()
        # Only Sense has a real playback reference. Permit Xiaozhi's existing
        # ESP-SR AFE device AEC for this exact board, without enabling it for
        # any other profile or modifying the pristine upstream clone.
        path = "main/Kconfig.projbuild"
        files[path] = replace_once(
            files[path].decode(),
            "depends on USE_AUDIO_PROCESSOR && (BOARD_TYPE_ESP32_S3_BOX_3",
            "depends on USE_AUDIO_PROCESSOR && (BOARD_TYPE_DESK_ROBOT_SENSE_S3 || BOARD_TYPE_ESP32_S3_BOX_3",
        ).encode()
        # Add only to the selected Sense menu. The upstream remains untouched.
        files[path] = replace_once(
            files[path].decode(),
            'config DESK_ROBOT_DIRECT_MOTION_TOOLS\n    bool "Expose low-level drive/lift/grip MCP tools (bench debugging only)"\n    default n\nendmenu\n',
            'config DESK_ROBOT_DIRECT_MOTION_TOOLS\n    bool "Expose low-level drive/lift/grip MCP tools (bench debugging only)"\n    default n\nconfig DESK_ROBOT_AEC_DELAY_MS\n    int "Sense playback reference delay in milliseconds (measure physically)"\n    range 0 250\n    default 90\nconfig DESK_ROBOT_RGB_HEART_ENABLED\n    bool "Enable GPIO9 RGB heart only after physical SD J3 isolation and logic/power approval"\n    default n\nconfig DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED\n    bool "Opt in: start continuous Xiaozhi realtime microphone listening on boot"\n    depends on USE_AUDIO_PROCESSOR && USE_DEVICE_AEC\n    default n\nconfig DESK_ROBOT_AEC_PCM_CAPTURE_ENABLED\n    bool "Private one-shot PCM bench capture of microphone and AEC reference"\n    depends on DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED && USE_DEVICE_AEC\n    default n\nendmenu\n',
        ).encode()
        # The PINNED Xiaozhi NoAudioCodec::Write holds data_if_mutex_
        # during i2s_channel_write(... portMAX_DELAY). An urgent flush then
        # waits for that mutex indefinitely if the I2S driver wedges.
        # Modify ONLY the disposable Sense build copy, preserving the
        # upstream codec and its accepted-sample return contract. A failed
        # or partial write returns the actual accepted frames, so the
        # Sense MIC+REFERENCE bridge never invents unheard PCM samples.
        path = "main/audio/codecs/no_audio_codec.cc"
        codec_source = (target / path).read_text()
        codec_source = replace_once(
            codec_source,
            '#include "no_audio_codec.h"',
            '#include "no_audio_codec.h"\\n#include <algorithm>\\n#include "sdkconfig.h"'.replace('\\n', '\n'),
        )
        codec_source = replace_once(
            codec_source,
            '    size_t bytes_written;\\n'
            '    ESP_ERROR_CHECK(i2s_channel_write(tx_handle_, buffer.data(), samples * sizeof(int32_t), &bytes_written, portMAX_DELAY));\\n'
            '    return bytes_written / sizeof(int32_t);'.replace('\\n', '\n'),
            '''    size_t bytes_written = 0;
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
    // Bound urgent-stop latency when the underlying TX channel does not
    // drain. A 120 ms ceiling reserves time for VAD, bridge dispatch and
    // decoder flush within the 500 ms acoustic interruption budget.
    // Physical trials must still measure underruns and audible STOP.
    // Do not ESP_ERROR_CHECK(timeout): a transient stalled TX must not
    // reboot the face or erase evidence from the microphone task.
    const esp_err_t err = i2s_channel_write(
        tx_handle_, buffer.data(), samples * sizeof(int32_t),
        &bytes_written, pdMS_TO_TICKS(120));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "Sense speaker I2S write timeout/error (%d), %u bytes uncertain",
                 static_cast<int>(err), static_cast<unsigned>(bytes_written));
        // The driver may have queued a partial frame before its error.
        // Do not publish uncertain PCM as a confirmed AEC reference.
        bytes_written = 0;
    }
    if (bytes_written > static_cast<size_t>(samples) * sizeof(int32_t) ||
        bytes_written % sizeof(int32_t) != 0) {
        ESP_LOGE(TAG, "Sense I2S reported invalid output byte count");
        bytes_written = 0;
    }
#else
    ESP_ERROR_CHECK(i2s_channel_write(
        tx_handle_, buffer.data(), samples * sizeof(int32_t),
        &bytes_written, portMAX_DELAY));
#endif
    return static_cast<int>(bytes_written / sizeof(int32_t));''',
        )
        # Only the selected Sense amplifier may accept bounded volume.
        # NVS and upstream SetOutputVolume do not cap values above 100;
        # the unbounded squared gain can overflow its int32 PCM factor.
        codec_source = replace_once(
            codec_source,
            '    int32_t volume_factor = pow(double(output_volume_) / 100.0, 2) * 65536;',
            '''#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
    const int safe_volume = std::clamp(output_volume(), 0, 100);
    int32_t volume_factor = pow(double(safe_volume) / 100.0, 2) * 65536;
#else
    int32_t volume_factor = pow(double(output_volume_) / 100.0, 2) * 65536;
#endif''',
        )
        # Sense PDM is the SAME existing Xiaozhi microphone reader, not a
        # new capture task. A disconnected or wedged I2S DMA channel must
        # not hold the input task indefinitely after STOP or opt-out.
        # Keep the original unbounded behavior in all other build profiles.
        codec_source = replace_once(
            codec_source,
            '    if (i2s_channel_read(rx_handle_, dest, samples * sizeof(int16_t), &bytes_read, portMAX_DELAY) != ESP_OK) {',
            '''#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
    // Sense PDM read timeout: bound a missing microphone DMA period while
    // retaining the stock 16 kHz PDM capture and AEC ownership. This is
    // a software fault fence, not a measured acoustic interruption time.
    const esp_err_t read_status = i2s_channel_read(
        rx_handle_, dest, samples * sizeof(int16_t), &bytes_read,
        pdMS_TO_TICKS(120));
#else
    const esp_err_t read_status = i2s_channel_read(
        rx_handle_, dest, samples * sizeof(int16_t), &bytes_read, portMAX_DELAY);
#endif
    if (read_status != ESP_OK) {''',
        )
        codec_source = replace_once(
            codec_source,
            '        ESP_LOGE(TAG, "Read Failed!");\\n        return 0;'.replace('\\n', '\n'),
            '''#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
        // A stalled microphone returns no fabricated samples. Repeated
        // expected timeouts must not flood the realtime task's UART logs.
        if (read_status != ESP_ERR_TIMEOUT) ESP_LOGE(TAG, "Read Failed!");
#else
        ESP_LOGE(TAG, "Read Failed!");
#endif
        return 0;''',
        )
        # The upstream TX writer allocates a vector for every PCM callback.
        # The selected Sense owns one startup scratch buffer instead.
        codec_source = replace_once(
            codec_source,
            "    std::vector<int32_t> buffer(samples);",
            '''#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
    // Reuse the codec's startup-allocated PSRAM scratch under the existing
    // TX mutex. Missing memory or an invalid request must not reach I2S.
    if (data == nullptr || samples <= 0 || samples > kSenseTxScratchSamples ||
        sense_tx_scratch_ == nullptr) return 0;
    int32_t* buffer = sense_tx_scratch_;
#else
    std::vector<int32_t> buffer(samples);
#endif''',
        )
        codec_source = replace_once(
            codec_source,
            "        tx_handle_, buffer.data(), samples * sizeof(int32_t),\n"
            "        &bytes_written, pdMS_TO_TICKS(120));",
            "        tx_handle_, buffer, samples * sizeof(int32_t),\n"
            "        &bytes_written, pdMS_TO_TICKS(120));",
        )
        files[path] = codec_source.encode()

        # Preserve upstream notification progress semantics. Add a separate
        # selected Sense completion callback sourced from the blocking I2S
        # write result. This is digital output progress, not acoustic proof.
        path = "main/audio/audio_codec.h"
        codec_header = (target / path).read_text()
        codec_header = replace_once(
            codec_header,
            "    virtual void OutputData(std::vector<int16_t>& data);",
            "    virtual int OutputData(std::vector<int16_t>& data);",
        )
        codec_header = replace_once(
            codec_header,
            '#include "board.h"',
            '#include "board.h"\n#include "sdkconfig.h"\n#include <atomic>',
        )
        codec_header = replace_once(
            codec_header,
            "    int output_volume_ = 70;",
            """#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
    // Volume is changed by control callbacks while the TX task is running.
    std::atomic<int> output_volume_{70};
#else
    int output_volume_ = 70;
#endif""",
        )
        codec_header = replace_once(
            codec_header,
            "    float input_gain_ = 0.0;",
            """    float input_gain_ = 0.0;
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
    // Preserve the Sense wrapper's existing maximum of one second at 32 kHz.
    static constexpr int kSenseTxScratchSamples = 32000;
    int32_t* sense_tx_scratch_ = nullptr;
#endif""",
        )
        files[path] = codec_header.encode()

        path = "main/audio/audio_codec.cc"
        codec_base = (target / path).read_text()
        codec_base = replace_once(
            codec_base,
            """void AudioCodec::OutputData(std::vector<int16_t>& data) {
    Write(data.data(), data.size());
}""",
            """int AudioCodec::OutputData(std::vector<int16_t>& data) {
    return Write(data.data(), data.size());
}""",
        )
        codec_base = replace_once(
            codec_base,
            "#include <esp_log.h>",
            """#include <esp_log.h>
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
#include <esp_heap_caps.h>
#endif""",
        )
        codec_base = replace_once(
            codec_base,
            """AudioCodec::AudioCodec() {
}

AudioCodec::~AudioCodec() {
}""",
            """AudioCodec::AudioCodec() {
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
    // Allocate once at codec construction, never in the realtime TX path.
    // I2S copies this CPU-readable PSRAM source into its own DMA buffers.
    sense_tx_scratch_ = static_cast<int32_t*>(heap_caps_malloc(
        kSenseTxScratchSamples * sizeof(int32_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!sense_tx_scratch_) ESP_LOGE(TAG, "Sense TX scratch unavailable");
#endif
}

AudioCodec::~AudioCodec() {
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
    if (sense_tx_scratch_) heap_caps_free(sense_tx_scratch_);
#endif
}""",
        )
        # Read volume once for startup diagnostics and use the actual setter
        # argument for logging/NVS. Never pass an atomic object to varargs.
        codec_base = replace_once(
            codec_base,
            '    output_volume_ = settings.GetInt("output_volume", output_volume_);',
            '    output_volume_ = settings.GetInt("output_volume", output_volume());',
        )
        codec_base = replace_once(
            codec_base,
            '    if (output_volume_ <= 0) {',
            '    if (const int saved_volume = output_volume(); saved_volume <= 0) {',
        )
        codec_base = replace_once(
            codec_base,
            'setting to default (10)", output_volume_);',
            'setting to default (10)", saved_volume);',
        )
        codec_base = replace_once(
            codec_base,
            'ESP_LOGI(TAG, "Set output volume to %d", output_volume_);',
            'ESP_LOGI(TAG, "Set output volume to %d", volume);',
        )
        codec_base = replace_once(
            codec_base,
            'settings.SetInt("output_volume", output_volume_);',
            'settings.SetInt("output_volume", volume);',
        )
        files[path] = codec_base.encode()

        path = "main/audio/audio_service.h"
        service_header = (target / path).read_text()
        service_header = replace_once(
            service_header,
            "    std::function<void(uint32_t playback_id, uint32_t media_position_ms)> on_playback_progress;",
            """    std::function<void(uint32_t playback_id, uint32_t media_position_ms)> on_playback_progress;
    // Selected Sense progress after a complete blocking I2S transmit.
    // This proves digital output progress, not acoustic diaphragm playback.
    std::function<void(uint32_t playback_id, uint32_t media_position_ms)> on_playback_committed;""",
        )
        service_header = replace_once(
            service_header,
            """    uint32_t media_position_ms = 0;
};

struct DebugStatistics {""",
            """    uint32_t media_position_ms = 0;
    int desk_frame_duration_ms = 0;
};

// Digital I2S acceptance can certify only an uninterrupted media prefix.
// Missing decode/queue output is visible as a gap in the next position.
struct DeskPlaybackPrefix {
    uint32_t id = 0;
    uint32_t end_ms = 0;
    bool failed = false;

    static bool ExactMediaFrame(uint64_t samples, int rate, int duration_ms) {
        if (samples == 0 || rate <= 0 || duration_ms <= 0) return false;
        const uint64_t scaled = static_cast<uint64_t>(rate) * duration_ms;
        return scaled % 1000U == 0 && samples == scaled / 1000U;
    }

    bool Accept(uint32_t playback_id, uint32_t position_ms,
                int duration_ms, bool fully_written) {
        if (playback_id == 0) return false;
        if (id != playback_id) {
            id = playback_id;
            end_ms = 0;
            failed = false;
        }
        if (failed || !fully_written || duration_ms <= 0 ||
            position_ms <= end_ms ||
            position_ms - end_ms != static_cast<uint32_t>(duration_ms)) {
            failed = true;
            return false;
        }
        end_ms = position_ms;
        return true;
    }
};

struct DebugStatistics {""",
        )
        files[path] = service_header.encode()

        path = "main/protocols/protocol.h"
        protocol_header = (target / path).read_text()
        protocol_header = replace_once(
            protocol_header,
            "    virtual void SendMcpMessage(const std::string& message);",
            """    virtual void SendMcpMessage(const std::string& message);
    void SendI2sProgress(uint32_t playback_id, uint32_t media_position_ms);""",
        )
        files[path] = protocol_header.encode()

        path = "main/protocols/protocol.cc"
        protocol_source = (target / path).read_text()
        protocol_source = replace_once(
            protocol_source,
            r"""void Protocol::SendMcpMessage(const std::string& payload) {
    std::string message =
        "{\"session_id\":\"" + session_id_ + "\",\"type\":\"mcp\",\"payload\":" + payload + "}";
    SendText(message);
}

bool Protocol::IsTimeout() const {""",
            r"""void Protocol::SendMcpMessage(const std::string& payload) {
    std::string message =
        "{\"session_id\":\"" + session_id_ + "\",\"type\":\"mcp\",\"payload\":" + payload + "}";
    SendText(message);
}

void Protocol::SendI2sProgress(uint32_t playback_id, uint32_t media_position_ms) {
    if (playback_id == 0 || media_position_ms == 0) {
        return;
    }
    std::string message =
        "{\"session_id\":\"" + session_id_ +
        "\",\"type\":\"desk_robot_i2s_progress\",\"playback_id\":" +
        std::to_string(playback_id) + ",\"committed_ms\":" +
        std::to_string(media_position_ms) + "}";
    SendText(message);
}

bool Protocol::IsTimeout() const {""",
        )
        files[path] = protocol_source.encode()

        path = "main/protocols/websocket_protocol.h"
        websocket_header = (target / path).read_text()
        websocket_header = replace_once(
            websocket_header,
            """    std::shared_ptr<WebSocket> websocket_;
    int version_ = 1;""",
            """    std::shared_ptr<WebSocket> websocket_;
    int version_ = 1;
    uint32_t desk_playback_id_ = 0;
    uint32_t desk_playback_position_ms_ = 0;""",
        )
        files[path] = websocket_header.encode()

        path = "main/protocols/websocket_protocol.cc"
        websocket_source = (target / path).read_text()
        websocket_source = replace_once(
            websocket_source,
            '#define TAG "WS"\n\n',
            '''#define TAG "WS"

// Validate the pinned Xiaozhi binary wire layouts before any payload access.
static bool ParseDeskAudioFrame(int version, const char* data, size_t len,
                                size_t& offset, uint32_t& timestamp) {
    offset = 0;
    timestamp = 0;
    if (data == nullptr || len == 0) return false;
    const auto* bytes = reinterpret_cast<const uint8_t*>(data);
    if (version == 1) return true;
    if (version == 2) {
        if (len <= 16 || bytes[0] != 0 || bytes[1] != 2 ||
            bytes[2] != 0 || bytes[3] != 0) return false;
        const auto read32 = [bytes](size_t pos) {
            return (uint32_t(bytes[pos]) << 24) |
                   (uint32_t(bytes[pos + 1]) << 16) |
                   (uint32_t(bytes[pos + 2]) << 8) |
                   uint32_t(bytes[pos + 3]);
        };
        if (read32(12) != len - 16) return false;
        offset = 16;
        timestamp = read32(8);
        return true;
    }
    if (version == 3) {
        if (len <= 4 || bytes[0] != 0) return false;
        const size_t payload_size = (size_t(bytes[2]) << 8) | bytes[3];
        if (payload_size != len - 4) return false;
        offset = 4;
        return true;
    }
    return false;
}

''',
        )
        # Keep the original wire formats, but do not cast a receive buffer
        # to mutable packed headers or trust its advertised payload length.
        websocket_source = replace_once(
            websocket_source,
            """        if (binary) {
            if (on_incoming_audio_ != nullptr) {
                if (version_ == 2) {
                    BinaryProtocol2* bp2 = (BinaryProtocol2*)data;
                    bp2->version = ntohs(bp2->version);
                    bp2->type = ntohs(bp2->type);
                    bp2->timestamp = ntohl(bp2->timestamp);
                    bp2->payload_size = ntohl(bp2->payload_size);
                    auto payload = (uint8_t*)bp2->payload;
                    on_incoming_audio_(std::make_unique<AudioStreamPacket>(AudioStreamPacket{
                        .sample_rate = server_sample_rate_,
                        .frame_duration = server_frame_duration_,
                        .timestamp = bp2->timestamp,
                        .payload = std::vector<uint8_t>(payload, payload + bp2->payload_size)}));
                } else if (version_ == 3) {
                    BinaryProtocol3* bp3 = (BinaryProtocol3*)data;
                    bp3->type = bp3->type;
                    bp3->payload_size = ntohs(bp3->payload_size);
                    auto payload = (uint8_t*)bp3->payload;
                    on_incoming_audio_(std::make_unique<AudioStreamPacket>(AudioStreamPacket{
                        .sample_rate = server_sample_rate_,
                        .frame_duration = server_frame_duration_,
                        .timestamp = 0,
                        .payload = std::vector<uint8_t>(payload, payload + bp3->payload_size)}));
                } else {
                    on_incoming_audio_(std::make_unique<AudioStreamPacket>(AudioStreamPacket{
                        .sample_rate = server_sample_rate_,
                        .frame_duration = server_frame_duration_,
                        .timestamp = 0,
                        .payload = std::vector<uint8_t>((uint8_t*)data, (uint8_t*)data + len)}));
                }
            }
""",
            """        if (binary) {
            size_t payload_offset = 0;
            uint32_t timestamp = 0;
            if (!ParseDeskAudioFrame(version_, data, len, payload_offset, timestamp)) {
                // A missing/invalid frame cannot later be credited as played.
                desk_playback_id_ = 0;
                desk_playback_position_ms_ = 0;
                return;
            }
            if (on_incoming_audio_ == nullptr) return;
            uint32_t playback_id = 0;
            uint32_t media_position_ms = 0;
            if (desk_playback_id_ != 0 && server_frame_duration_ > 0) {
                const uint32_t frame_ms = static_cast<uint32_t>(server_frame_duration_);
                if (desk_playback_position_ms_ <= 0xffffffffu - frame_ms) {
                    desk_playback_position_ms_ += frame_ms;
                    playback_id = desk_playback_id_;
                    media_position_ms = desk_playback_position_ms_;
                } else {
                    desk_playback_id_ = 0;
                    desk_playback_position_ms_ = 0;
                }
            }
            const auto* payload = reinterpret_cast<const uint8_t*>(data) + payload_offset;
            on_incoming_audio_(std::make_unique<AudioStreamPacket>(AudioStreamPacket{
                .sample_rate = server_sample_rate_,
                .frame_duration = server_frame_duration_,
                .timestamp = timestamp,
                .playback_id = playback_id,
                .media_position_ms = media_position_ms,
                .payload = std::vector<uint8_t>(payload, payload + (len - payload_offset))}));
""",
        )
        websocket_source = replace_once(
            websocket_source,
            """            if (cJSON_IsString(type)) {
                if (strcmp(type->valuestring, "hello") == 0) {""",
            """            if (cJSON_IsString(type)) {
                if (strcmp(type->valuestring, "tts") == 0) {
                    auto state = cJSON_GetObjectItem(root, "state");
                    if (cJSON_IsString(state) && strcmp(state->valuestring, "start") == 0) {
                        desk_playback_id_ = 0;
                        desk_playback_position_ms_ = 0;
                        auto playback_id = cJSON_GetObjectItem(root, "desk_playback_id");
                        if (cJSON_IsNumber(playback_id) &&
                            playback_id->valuedouble >= 1 &&
                            playback_id->valuedouble <= 2147483647 &&
                            // Never truncate a fractional server ID into
                            // another response's completed playback lease.
                            playback_id->valuedouble == static_cast<double>(
                                static_cast<uint32_t>(playback_id->valuedouble))) {
                            desk_playback_id_ =
                                static_cast<uint32_t>(playback_id->valuedouble);
                        }
                    } else if (cJSON_IsString(state) &&
                               strcmp(state->valuestring, "stop") == 0) {
                        desk_playback_id_ = 0;
                        desk_playback_position_ms_ = 0;
                    }
                }
                if (strcmp(type->valuestring, "hello") == 0) {""",
        )
        files[path] = websocket_source.encode()

        # An I2S DAC at 32 kHz must not force an invalid 32 kHz Opus
        # decoder. Reuse Xiaozhi's existing Opus and ESP-AE rate converter
        # on the isolated Sense build; do not modify the pinned upstream.
        path = "main/audio/audio_service.cc"
        service = (target / path).read_text()
        service = replace_once(
            service,
            "    esp_opus_dec_cfg_t opus_dec_cfg =\n        OPUS_DEC_CFG(codec->output_sample_rate(), OPUS_FRAME_DURATION_MS);",
            "#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3\n    // MAX98357A accepts 32 kHz LRCLK, but Opus has no 32 kHz decoder mode.\n    // Open a valid 24 kHz decoder and resample to the 32 kHz I2S speaker.\n    constexpr int initial_decoder_rate = 24000;\n#else\n    const int initial_decoder_rate = codec->output_sample_rate();\n#endif\n    esp_opus_dec_cfg_t opus_dec_cfg =\n        OPUS_DEC_CFG(initial_decoder_rate, OPUS_FRAME_DURATION_MS);",
        )
        service = replace_once(
            service,
            "        decoder_sample_rate_ = codec->output_sample_rate();",
            "        decoder_sample_rate_ = initial_decoder_rate;",
        )
        service = replace_once(
            service,
            "    }\n    esp_opus_enc_config_t opus_enc_cfg = AS_OPUS_ENC_CONFIG();",
            "    }\n#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3\n    // The first packet may use the same Opus rate. Initialize the output\n    // converter NOW so SetDecodeSampleRate's equal-rate fast path cannot\n    // accidentally send 24 kHz PCM to the 32 kHz MAX98357A output.\n    if (opus_decoder_ && decoder_sample_rate_ != codec->output_sample_rate()) {\n        if (output_resampler_ != nullptr) {\n            esp_ae_rate_cvt_close(output_resampler_);\n            output_resampler_ = nullptr;\n        }\n        esp_ae_rate_cvt_cfg_t cfg = RATE_CVT_CFG(\n            decoder_sample_rate_, codec->output_sample_rate(), ESP_AUDIO_MONO);\n        auto resampler_ret = esp_ae_rate_cvt_open(&cfg, &output_resampler_);\n        if (output_resampler_ == nullptr) {\n            ESP_LOGE(TAG, \"Sense Opus output resampler startup failed: %d\",\n                     resampler_ret);\n        }\n    }\n#endif\n    esp_opus_enc_config_t opus_enc_cfg = AS_OPUS_ENC_CONFIG();",
        )
        # Never play at the wrong speed when the output rate converter
        # could not be created. The original Xiaozhi code silently forwarded
        # 24 kHz PCM to the 32 kHz I2S DAC when output_resampler_ was null.
        service = replace_once(
            service,
            '''                    if (decoder_sample_rate_ != codec_->output_sample_rate() &&
                        output_resampler_ != nullptr) {''',
            '''                    if (decoder_sample_rate_ != codec_->output_sample_rate() &&
                        output_resampler_ == nullptr) {
                        ESP_LOGE(TAG, "Sense speaker resampler unavailable: discarding mismatched PCM");
                        task.pcm.clear();
                    } else if (decoder_sample_rate_ != codec_->output_sample_rate() &&
                        output_resampler_ != nullptr) {''',
        )
        service = replace_once(
            service,
            '''                    decoded = true;
                } else {
                    ESP_LOGE(TAG, "Failed to decode audio after resize, error code: %d", ret);''',
            '''                    decoded = !task.pcm.empty();
                } else {
                    ESP_LOGE(TAG, "Failed to decode audio after resize, error code: %d", ret);''',
        )
        # Reject a backend's unsupported Opus rate BEFORE closing the live
        # decoder. 32 kHz is a valid MAX98357A DAC clock but not an Opus
        # decoder rate; a malformed TTS event must not permanently silence
        # subsequent conforming 24 kHz replies. The decoder can also be
        # reopened after a genuine failed open even when the last rate matches.
        service = replace_once(
            service,
            """void AudioService::SetDecodeSampleRate(int sample_rate, int frame_duration) {
    if (decoder_sample_rate_ == sample_rate && decoder_duration_ms_ == frame_duration) {""",
            """void AudioService::SetDecodeSampleRate(int sample_rate, int frame_duration) {
#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3
    // Valid Opus PCM decode rates: 8, 12, 16, 24 or 48 kHz. Reject a bad
    // remote format without closing the functioning device decoder.
    if (sample_rate != 8000 && sample_rate != 12000 &&
        sample_rate != 16000 && sample_rate != 24000 &&
        sample_rate != 48000) {
        ESP_LOGE(TAG, "Rejecting unsupported Sense Opus rate %d", sample_rate);
        return;
    }
    // The ESP32 decoder API takes whole milliseconds. Reject an invalid
    // Opus frame duration BEFORE replacing a working decoder.
    if (frame_duration != 5 && frame_duration != 10 &&
        frame_duration != 20 && frame_duration != 40 &&
        frame_duration != 60) {
        ESP_LOGE(TAG, "Rejecting unsupported Sense Opus frame duration %d", frame_duration);
        return;
    }
#endif
    if (decoder_sample_rate_ == sample_rate &&
        decoder_duration_ms_ == frame_duration && opus_decoder_ != nullptr) {""",
        )
        # Preserving an old decoder on a rejected format is not permission
        # to decode the rejected packet with that decoder.
        service = replace_once(
            service,
            """            SetDecodeSampleRate(packet->sample_rate, packet->frame_duration);
            bool decoded = false;
            if (opus_decoder_ != nullptr) {""",
            """            SetDecodeSampleRate(packet->sample_rate, packet->frame_duration);
            bool decoded = false;
            if (opus_decoder_ != nullptr &&
                decoder_sample_rate_ == packet->sample_rate &&
                decoder_duration_ms_ == packet->frame_duration) {""",
        )
        # Retry the existing converter if its allocation failed at startup
        # or on the previous rate change, without replacing a healthy decoder.
        service = replace_once(
            service,
            """    if (decoder_sample_rate_ == sample_rate &&
        decoder_duration_ms_ == frame_duration && opus_decoder_ != nullptr) {
        return;
    }""",
            """    if (decoder_sample_rate_ == sample_rate &&
        decoder_duration_ms_ == frame_duration && opus_decoder_ != nullptr) {
        auto codec = Board::GetInstance().GetAudioCodec();
        if (sample_rate != codec->output_sample_rate() && output_resampler_ == nullptr) {
            esp_ae_rate_cvt_cfg_t cfg =
                RATE_CVT_CFG(sample_rate, codec->output_sample_rate(), ESP_AUDIO_MONO);
            auto resampler_ret = esp_ae_rate_cvt_open(&cfg, &output_resampler_);
            if (output_resampler_ == nullptr) {
                ESP_LOGE(TAG, "Failed to recover output resampler, error code: %d", resampler_ret);
            }
        }
        return;
    }""",
        )
        # Replace the pinned upstream's close-then-open decoder transition
        # only in the selected disposable Sense overlay. A malformed packet
        # or failed replacement allocation must not destroy a working decoder.
        # The decode thread and ResetDecoder use decoder_mutex_ for this swap.
        service = replace_once(
            service,
            """    std::unique_lock<std::mutex> decoder_lock(decoder_mutex_);
    if (opus_decoder_ != nullptr) {
        esp_opus_dec_close(opus_decoder_);
        opus_decoder_ = nullptr;
    }
    decoder_lock.unlock();
    esp_opus_dec_cfg_t opus_dec_cfg = OPUS_DEC_CFG(sample_rate, frame_duration);
    auto ret = esp_opus_dec_open(&opus_dec_cfg, sizeof(esp_opus_dec_cfg_t), &opus_decoder_);
    if (opus_decoder_ == nullptr) {
        ESP_LOGE(TAG, "Failed to create audio decoder, error code: %d", ret);
        return;
    }
    decoder_sample_rate_ = sample_rate;""",
            """    esp_opus_dec_cfg_t opus_dec_cfg = OPUS_DEC_CFG(sample_rate, frame_duration);
    void* proposed_decoder = nullptr;
    auto ret = esp_opus_dec_open(&opus_dec_cfg, sizeof(esp_opus_dec_cfg_t), &proposed_decoder);
    if (proposed_decoder == nullptr) {
        ESP_LOGE(TAG, "Failed to create replacement decoder, keeping prior decoder: %d", ret);
        return;
    }
    {
        std::lock_guard<std::mutex> decoder_lock(decoder_mutex_);
        void* previous_decoder = opus_decoder_;
        opus_decoder_ = proposed_decoder;
        if (previous_decoder != nullptr) {
            esp_opus_dec_close(previous_decoder);
        }
    }
    decoder_sample_rate_ = sample_rate;""",
        )
        service = replace_once(
            service,
            "            task.media_position_ms = packet->media_position_ms;",
            """            task.media_position_ms = packet->media_position_ms;
            task.desk_frame_duration_ms = packet->frame_duration;""",
        )
        service = replace_once(
            service,
            """void AudioService::AudioOutputTask() {
    while (true) {""",
            """void AudioService::AudioOutputTask() {
    // A cumulative media position is only trustworthy while every prior
    // frame in this playback lease completed its blocking I2S write.
    DeskPlaybackPrefix desk_robot_prefix;
    while (true) {""",
        )
        service = replace_once(
            service,
            "        codec_->OutputData(task.pcm);",
            """        const int transmitted_frames = codec_->OutputData(task.pcm);
        if (desk_robot_prefix.Accept(
                task.playback_id, task.media_position_ms,
                task.desk_frame_duration_ms,
                !task.pcm.empty() &&
                    DeskPlaybackPrefix::ExactMediaFrame(
                        task.pcm.size(), codec_->output_sample_rate(),
                        task.desk_frame_duration_ms) &&
                    transmitted_frames == static_cast<int>(task.pcm.size())) &&
            callbacks_.on_playback_committed) {
            callbacks_.on_playback_committed(
                task.playback_id, task.media_position_ms);
        }""",
        )
        files[path] = service.encode()
        # Urgent stop is an extension to the existing Xiaozhi TTS state event,
        # not a second decoder or audio transport. Normal TTS stops retain the
        # upstream behavior; flush=true explicitly discards queued decoder PCM
        # and disables I2S TX so its DMA no longer plays obsolete audio.
        path = "main/application.cc"
        text = (target / path).read_text()
        text = replace_once(
            text,
            """    callbacks.on_playback_progress = [this](uint32_t playback_id, uint32_t media_position_ms) {
        notify_player_.OnPlaybackProgress(playback_id, media_position_ms);
    };
    audio_service_.SetCallbacks(callbacks);""",
            """    callbacks.on_playback_progress = [this](uint32_t playback_id, uint32_t media_position_ms) {
        notify_player_.OnPlaybackProgress(playback_id, media_position_ms);
    };
    callbacks.on_playback_committed = [this](uint32_t playback_id, uint32_t media_position_ms) {
        Schedule([this, playback_id, media_position_ms]() {
            if (protocol_) {
                protocol_->SendI2sProgress(playback_id, media_position_ms);
            }
        });
    };
    audio_service_.SetCallbacks(callbacks);""",
        )
        text = replace_once(
            text,
            """} else if (strcmp(state->valuestring, "stop") == 0) {
                Schedule([this]() {
                    if (GetDeviceState() == kDeviceStateSpeaking) {""",
            """} else if (strcmp(state->valuestring, "stop") == 0) {
                const bool urgent_flush = cJSON_IsTrue(cJSON_GetObjectItem(root, "flush"));
                Schedule([this, urgent_flush]() {
                    if (urgent_flush) {
                        audio_service_.ResetDecoder();
                        Board::GetInstance().GetAudioCodec()->EnableOutput(false);
                    }
                    if (GetDeviceState() == kDeviceStateSpeaking) {""",
        )
        # BOOT privacy stop must also work while Xiaozhi is speaking.
        # Its stock StopListening() handles only the Listening state, which
        # would leave realtime microphone upload alive after a spoken reply.
        # Patch only the selected Sense board and only with explicit opt in.
        text = replace_once(
            text,
            """        SetDeviceState(kDeviceStateIdle);
    }
}

void Application::HandleWakeWordDetectedEvent() {""",
            """        SetDeviceState(kDeviceStateIdle);
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
    } else if (state == kDeviceStateSpeaking) {
        AbortSpeaking(kAbortReasonNone);
        audio_service_.ResetDecoder();
        Board::GetInstance().GetAudioCodec()->EnableOutput(false);
        if (protocol_) {
            protocol_->CloseAudioChannel();
        }
        SetDeviceState(kDeviceStateIdle);
#endif
    }
}

void Application::HandleWakeWordDetectedEvent() {""",
        )
        # A physical BOOT mute can cancel an in-flight channel open.
        # The upstream helper only checks state BEFORE blocking on network.
        # Recheck it after transport open so a stale callback cannot start
        # the microphone once BOOT has changed the device to idle.
        text = replace_once(
            text,
            """    SetListeningMode(mode);
}

void Application::HandleStartListeningEvent() {""",
            """#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
    // BOOT privacy may have cancelled while OpenAudioChannel blocked.
    if (GetDeviceState() != kDeviceStateConnecting) {
        protocol_->CloseAudioChannel();
        return;
    }
#endif
    SetListeningMode(mode);
}

void Application::HandleStartListeningEvent() {""",
        )
        # Physical BOOT privacy is an APPLICATION audio-send fence as well as
        # a codec PDM fence. Never send already-queued Opus after opt out.
        text = replace_once(
            text,
            """        if (bits & MAIN_EVENT_SEND_AUDIO) {
            while (auto packet = audio_service_.PopPacketFromSendQueue()) {
                if (protocol_ && !protocol_->SendAudio(std::move(packet))) {""",
            """        if (bits & MAIN_EVENT_SEND_AUDIO) {
            while (auto packet = audio_service_.PopPacketFromSendQueue()) {
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
                if (sense_microphone_privacy_muted_.load(std::memory_order_acquire)) {
                    while (audio_service_.PopPacketFromSendQueue()) {}
                    break;
                }
#endif
                if (protocol_ && !protocol_->SendAudio(std::move(packet))) {""",
        )
        text = replace_once(
            text,
            """void Application::HandleToggleChatEvent() {
    auto state = GetDeviceState();""",
            """void Application::HandleToggleChatEvent() {
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
    if (sense_microphone_privacy_muted_.load(std::memory_order_acquire)) return;
#endif
    auto state = GetDeviceState();""",
        )
        text = replace_once(
            text,
            """void Application::HandleStartListeningEvent() {
    auto state = GetDeviceState();""",
            """void Application::HandleStartListeningEvent() {
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
    if (sense_microphone_privacy_muted_.load(std::memory_order_acquire)) return;
#endif
    auto state = GetDeviceState();""",
        )
        text = replace_once(
            text,
            """void Application::HandleStopListeningEvent() {
    auto state = GetDeviceState();""",
            """void Application::HandleStopListeningEvent() {
    auto state = GetDeviceState();
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
    if (sense_microphone_privacy_muted_.load(std::memory_order_acquire)) {
        // Physical BOOT has already gated PDM. Drop encoded packets that
        // were in the original Xiaozhi queue before the button event.
        while (audio_service_.PopPacketFromSendQueue()) {}
        if (state == kDeviceStateSpeaking) {
            AbortSpeaking(kAbortReasonNone);
            audio_service_.ResetDecoder();
            Board::GetInstance().GetAudioCodec()->EnableOutput(false);
        }
        if (protocol_ && protocol_->IsAudioChannelOpened())
            protocol_->CloseAudioChannel();
        if (GetDeviceState() == kDeviceStateConnecting ||
            GetDeviceState() == kDeviceStateListening ||
            GetDeviceState() == kDeviceStateSpeaking)
            SetDeviceState(kDeviceStateIdle);
        return;
    }
#endif""",
        )
        text = replace_once(
            text,
            """void Application::StartListeningAudio() {
    // Runs in the main loop, either directly from HandleStateChangedEvent or""",
            """void Application::StartListeningAudio() {
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
    if (sense_microphone_privacy_muted_.load(std::memory_order_acquire)) return;
#endif
    // Runs in the main loop, either directly from HandleStateChangedEvent or""",
        )
        # After a blocked audio channel open, BOOT may have set Idle or
        # explicitly muted even when the old state still appears Connecting.
        text = replace_once(
            text,
            """if (GetDeviceState() != kDeviceStateConnecting) {
        protocol_->CloseAudioChannel();
        return;
    }
#endif
    SetListeningMode(mode);""",
            """if (GetDeviceState() != kDeviceStateConnecting ||
        sense_microphone_privacy_muted_.load(std::memory_order_acquire)) {
        protocol_->CloseAudioChannel();
        return;
    }
#endif
    SetListeningMode(mode);""",
        )
        # A server transport failure is independent of WiFi association.
        # Report it from the ONE Xiaozhi audio owner rather than interpreting
        # every ordinary Idle state as a socket loss. No new microphone task.
        text = replace_once(
            text,
            """    protocol_->OnAudioChannelClosed([this, &board]() {
        board.SetPowerSaveLevel(PowerSaveLevel::LOW_POWER);""",
            """    protocol_->OnAudioChannelClosed([this, &board]() {
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
        if (!sense_microphone_privacy_muted_.load(std::memory_order_acquire))
            sense_audio_failure_epoch_.fetch_add(1, std::memory_order_acq_rel);
#endif
        board.SetPowerSaveLevel(PowerSaveLevel::LOW_POWER);""",
        )
        text = replace_once(
            text,
            """void Application::ContinueOpenAudioChannel(ListeningMode mode) {
    // Check state again in case it was changed during scheduling
    if (GetDeviceState() != kDeviceStateConnecting) {
        return;
    }

    // Switch to performance mode before connecting to reduce latency
    auto& board = Board::GetInstance();
    board.SetPowerSaveLevel(PowerSaveLevel::PERFORMANCE);

    if (!protocol_->IsAudioChannelOpened()) {
        if (!protocol_->OpenAudioChannel()) {""",
            """void Application::ContinueOpenAudioChannel(ListeningMode mode) {
    // Check state again in case it was changed during scheduling
    if (GetDeviceState() != kDeviceStateConnecting) {
        return;
    }

    // Switch to performance mode before connecting to reduce latency
    auto& board = Board::GetInstance();
    board.SetPowerSaveLevel(PowerSaveLevel::PERFORMANCE);

    if (!protocol_->IsAudioChannelOpened()) {
        if (!protocol_->OpenAudioChannel()) {
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
            if (!sense_microphone_privacy_muted_.load(std::memory_order_acquire))
                sense_audio_failure_epoch_.fetch_add(1, std::memory_order_acq_rel);
#endif""",
        )
        # The pinned application raises WiFi performance before opening audio.
        # Allocation failure can return false without ever firing OnAudioChannelClosed.
        # Restore the existing low-power policy in both explicit failure branches.
        for failure_comment in (
            """            // Return to idle so the device is not stuck in the connecting
            // state (not every failure path reports a network error)""",
            """            // Return to idle so the device is not stuck in the connecting
            // state (not every failure path reports a network error), and
            // wake word detection is re-enabled by the idle state handler.""",
        ):
            failure = failure_comment + "\n            SetDeviceState(kDeviceStateIdle);"
            text = replace_once(
                text, failure,
                failure_comment
                + "\n            board.SetPowerSaveLevel(PowerSaveLevel::LOW_POWER);"
                + "\n            SetDeviceState(kDeviceStateIdle);",
            )
        files[path] = text.encode()
        # Only the disposable Sense clone changes upstream Application
        # declarations, so every other Xiaozhi board retains original code.
        header_path = "main/application.h"
        header = (target / header_path).read_text()
        header = replace_once(
            header,
            """#include <functional>
#include <cstdint>""",
            """#include <functional>
#include <atomic>
#include <cstdint>""",
        )
        header = replace_once(
            header,
            """    void ToggleChatState();

    /**""",
            """    void ToggleChatState();
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
    void SetSenseMicrophonePrivacyMuted(bool muted) {
        sense_microphone_privacy_muted_.store(muted, std::memory_order_release);
    }
    uint32_t GetSenseAudioFailureEpoch() const {
        return sense_audio_failure_epoch_.load(std::memory_order_acquire);
    }
#endif

    /**""",
        )
        header = replace_once(
            header,
            """    AudioService audio_service_;
    NotifyPlayer notify_player_;""",
            """    AudioService audio_service_;
#ifdef CONFIG_DESK_ROBOT_CONTINUOUS_AUDIO_ENABLED
    std::atomic<bool> sense_microphone_privacy_muted_{false};
    std::atomic<uint32_t> sense_audio_failure_epoch_{0};
#endif
    NotifyPlayer notify_player_;""",
        )
        files[header_path] = header.encode()
        # Host-only diagnostics for the pinned P3 player, not firmware latency.
        path = "scripts/p3_tools/p3_gui_player.py"
        files[path] = instrument_p3_player((target / path).read_text()).encode()
        # Replace the pinned unauthenticated, unbounded UDP bench receiver.
        path = "scripts/audio_debug_server.py"
        files[path] = (HERE / "audio_debug_server.py").read_bytes()
        path = "scripts/release.py"
        files[path] = harden_release_tooling((target / path).read_text()).encode()
        return files
    files = cores3_files(target)
    if board == "cores3":
        return files

    # Keep the original CoreS3 source and build copy independent. The selected
    # integration guard is used by camera.h, EspVideo and the MCP capture lock.
    files = {
        name: data.replace(b"CONFIG_BOARD_TYPE_DESK_ROBOT_CORE_S3", b"CONFIG_BOARD_TYPE_DESK_ROBOT_MODULAR_S3")
        .replace(b"BOARD_TYPE_DESK_ROBOT_CORE_S3", b"BOARD_TYPE_DESK_ROBOT_MODULAR_S3")
        .replace(b'Desk robot CoreS3 Lite', b'Desk robot modular S3 (Freenove N16R8)')
        .replace(b"desk-robot/desk-robot-core-s3", b"desk-robot/desk-robot-modular-s3")
        for name, data in files.items()
        if not name.startswith(BOARD + "/")
    }
    cmake = files["main/CMakeLists.txt"].decode()
    cmake = replace_once(
        cmake,
        '    set(BOARD_DIR "desk-robot/desk-robot-modular-s3")\n'
        '    set(BUILTIN_TEXT_FONT font_noto_sans_basic_20_4)\n'
        '    set(BUILTIN_ICON_FONT font_material_symbols_20_4)\n'
        '    set(DEFAULT_EMOJI_COLLECTION noto-color-emoji_64)\n',
        '    set(BOARD_DIR "desk-robot/desk-robot-modular-s3")\n'
        '    set(BUILTIN_TEXT_FONT font_noto_sans_basic_14_1)\n'
        '    set(BUILTIN_ICON_FONT font_material_symbols_14_1)\n',
    )
    files["main/CMakeLists.txt"] = cmake.encode()
    for path in (HERE / "modular").iterdir():
        if path.is_file() and path.suffix in (".cc", ".h", ".hpp", ".json", ".md"):
            files[f"{BOARDS[board]}/{path.name}"] = path.read_bytes()
    for path in (HERE / "overlay").iterdir():
        if path.suffix in (".h", ".cc", ".hpp"):
            files[f"{BOARDS[board]}/{path.name}"] = path.read_bytes()

    guard = "#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_MODULAR_S3"
    path = "main/boards/common/esp32_camera.h"
    header = (target / path).read_text()
    header = replace_once(
        header, "    virtual bool Capture() override;",
        "    virtual bool Capture() override;\n" + guard +
        "\n    std::expected<std::vector<uint8_t>, std::string> SnapshotJpeg() override;\n#endif",
    )
    files[path] = header.encode()
    path = "main/boards/common/esp32_camera.cc"
    source = (target / path).read_text()
    header, source = patch_camera_explain_config(header, source)
    files["main/boards/common/esp32_camera.h"] = header.encode()
    bounds_header = "main/boards/common/desk_robot_camera_frame_bounds.hpp"
    files[bounds_header] = (HERE / "overlay/camera_frame_bounds.hpp").read_bytes()
    source = replace_once(
        source,
        '#include "esp32_camera.h"',
        '#include "esp32_camera.h"\n#include "desk_robot_camera_frame_bounds.hpp"',
    )
    source = replace_once(
        source,
        "    if (current_fb_->format == PIXFORMAT_RGB565) {\n"
        "        size_t pixel_count = current_fb_->width * current_fb_->height;",
        """    if (current_fb_->format == PIXFORMAT_RGB565) {
        if (!current_fb_->buf || !desk_robot::ValidRgb565Frame(
                current_fb_->width, current_fb_->height, current_fb_->len)) {
            ESP_LOGE(TAG, "Invalid RGB565 frame dimensions or length");
            esp_camera_fb_return(current_fb_);
            current_fb_ = nullptr;
            return false;
        }
        size_t pixel_count = current_fb_->width * current_fb_->height;""",
    )
    # Capacity may exceed the current frame after a smaller capture.
    source = replace_once(
        source, "jpeg_src_len = encode_buf_size_;", "jpeg_src_len = current_fb_->len;"
    )
    for anchor in (
        "bool Esp32Camera::Capture() {",
        "std::expected<std::string, std::string> Esp32Camera::Explain(const std::string& question) {",
        "bool Esp32Camera::SetHMirror(bool enabled) {",
        "bool Esp32Camera::SetVFlip(bool enabled) {",
        "bool Esp32Camera::SetSwapBytes(bool enabled) {",
    ):
        source = replace_once(source, anchor, anchor + "\n" + guard +
                              "\n    std::lock_guard<std::recursive_mutex> camera_lock(AccessMutex());\n#endif")
    source += "\n" + guard + "\n" + (HERE / "modular_snapshot.inc").read_text() + "\n#endif\n"
    files[path] = source.encode()
    return files


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_replace_bytes(path: Path, contents: bytes) -> None:
    """Replace one source atomically so interrupted writes retain old/new bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=f".{path.name}.desk-overlay-", dir=path.parent,
        delete=False,
    ) as stream:
        staged = Path(stream.name)
        try:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
    try:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        staged.chmod(mode)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def overlay_recipe_digest(board: str) -> str:
    """Fingerprint the installer and local source inputs for this board."""
    inputs = {HERE / "install_overlay.py", HERE / "BOARD_README.md"}
    if board == "sense":
        inputs.add(HERE / "audio_debug_server.py")
    folders = [HERE / "overlay"]
    if board != "cores3":
        inputs.add(HERE / "modular_snapshot.inc")
        folders.append(HERE / "modular")
        if board != "modular":
            folders.append(HERE / board)
    for folder in folders:
        checked_overlay_path(HERE, folder.relative_to(HERE).as_posix())
        if not folder.is_dir():
            raise ValueError("Overlay recipe source directory is missing or invalid")
        inputs.update(
            path for path in folder.iterdir()
            if path.suffix in (".cc", ".h", ".hpp", ".json", ".md")
        )
    manifest = {}
    for path in sorted(inputs):
        name = path.relative_to(HERE).as_posix()
        checked_overlay_path(HERE, name, regular_file=True)
        manifest[name] = digest(path.read_bytes())
    return digest(json.dumps({"pin": PIN, "board": board, "inputs": manifest},
                             sort_keys=True).encode())


def checked_overlay_path(target: Path, name: str, *, regular_file: bool = False) -> Path:
    """Reject links and incompatible existing objects before any content IO."""
    path = target
    parts = name.split("/")
    for index, part in enumerate(parts):
        path = path / part
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError(
                f"Overlay path escapes pinned checkout or aliases another path via symlink: {name}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise ValueError(f"Overlay path has a non-directory intermediate: {name}")
        if index == len(parts) - 1 and regular_file and not stat.S_ISREG(mode):
            raise ValueError(f"Overlay path must be a regular file: {name}")
    return path


def unique_journal_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Invalid head overlay journal: duplicate key")
        result[key] = value
    return result


def overlay_journal_digest(state: dict) -> str:
    """Detect journal entry loss or corruption, independent of JSON order."""
    payload = {
        name: {key: value for key, value in info.items() if key != "manifest_sha256"}
        for name, info in state.items()
    }
    return digest(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def read_overlay_journal(target: Path, marker: Path) -> dict:
    """Reject malformed or escaping recovery journals before any file IO."""
    if not marker.is_file() or marker.is_symlink() or marker.stat().st_size > 16_000_000:
        raise ValueError("Invalid head overlay journal")
    state = json.loads(marker.read_text(), object_pairs_hook=unique_journal_object)
    if not isinstance(state, dict) or not state:
        raise ValueError("Invalid head overlay journal")
    root = target.resolve()
    for name, info in state.items():
        if (not isinstance(name, str) or not (name.startswith("main/")
                    or name in ("scripts/p3_tools/p3_gui_player.py",
                                "scripts/audio_debug_server.py", "scripts/release.py"))
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)
                or "\\" in name or any(part in ("", ".", "..") for part in name.split("/"))
                or not isinstance(info, dict)
                or set(info) not in ({"sha256", "original"},
                                     {"sha256", "original", "recipe_sha256"},
                                     {"sha256", "original", "recipe_sha256", "manifest_sha256"})
                or type(info["sha256"]) is not str
                or len(info["sha256"]) != 64
                or any(ch not in "0123456789abcdef" for ch in info["sha256"])
                or (info["original"] is not None and
                    type(info["original"]) is not str)):
            raise ValueError("Invalid head overlay journal entry")
        if "recipe_sha256" in info:
            recipe = info["recipe_sha256"]
            if (type(recipe) is not str or len(recipe) != 64
                    or any(ch not in "0123456789abcdef" for ch in recipe)):
                raise ValueError("Invalid head overlay journal recipe digest")
        if "manifest_sha256" in info:
            manifest = info["manifest_sha256"]
            if (type(manifest) is not str or len(manifest) != 64
                    or any(ch not in "0123456789abcdef" for ch in manifest)):
                raise ValueError("Invalid head overlay journal manifest digest")
        parts = name.split("/")
        if any("/".join(parts[:i]) in state for i in range(1, len(parts))):
            raise ValueError("Invalid head overlay journal: overlapping paths")
        path = checked_overlay_path(target, name, regular_file=True)
        if not path.parent.resolve().is_relative_to(root):
            raise ValueError("Overlay journal path escapes pinned checkout")
        if info["original"] is not None:
            try:
                base64.b64decode(info["original"], validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise ValueError("Invalid original bytes in overlay journal") from exc
    if len({info.get("recipe_sha256") for info in state.values()}) != 1:
        raise ValueError("Invalid head overlay journal: mixed recipe digests")
    manifests = {info.get("manifest_sha256") for info in state.values()}
    if len(manifests) != 1:
        raise ValueError("Invalid head overlay journal: mixed manifest digests")
    manifest = next(iter(manifests))
    if manifest is not None and manifest != overlay_journal_digest(state):
        raise ValueError("Invalid head overlay journal manifest digest")
    return state


def remove(target: Path) -> None:
    marker = checked_overlay_path(target, MARKER, regular_file=True)
    if not marker.exists():
        return
    state = read_overlay_journal(target, marker)
    for name in BOARDS.values():
        checked_overlay_path(target, name)
    # The marker is committed before the overlaid files. A killed installer
    # can leave any file at its pinned original bytes, its overlaid bytes,
    # or (for a new board file) not yet created. Those are recoverable.
    # Reject all other content before changing even one file, so an actual
    # user edit is never destroyed by a partial-install recovery.
    for name, info in state.items():
        path = target / name
        original = info["original"]
        if not path.is_file():
            if original is None and not path.exists():
                continue
            raise ValueError(f"Refusing removal: overlaid file was changed: {name}")
        current = digest(path.read_bytes())
        original_digest = digest(base64.b64decode(original)) if original is not None else None
        if current != info["sha256"] and current != original_digest:
            raise ValueError(f"Refusing removal: overlaid file was changed: {name}")
    for name, info in state.items():
        path = target / name
        if info["original"] is None:
            if path.is_file():
                path.unlink()
        else:
            atomic_replace_bytes(path, base64.b64decode(info["original"]))
    # A force-killed atomic write can leave its hidden staging file in the
    # newly created board directory. Only our namespaced temporary source
    # files belonging to entries in this verified journal are disposable.
    # Remove them before dropping the journal so --remove stays repeatable.
    for name in state:
        path = target / name
        prefix = f".{path.name}.desk-overlay-"
        if path.parent.is_dir():
            for staged in path.parent.iterdir():
                if staged.name.startswith(prefix) and (
                    staged.is_file() or staged.is_symlink()
                ):
                    staged.unlink()
    marker.unlink()
    for name in BOARDS.values():
        board = target / name
        if board.is_dir() and not any(board.iterdir()):
            board.rmdir()


def apply(target: Path, board: str = "cores3") -> None:
    if board not in BOARDS:
        raise ValueError(f"Unknown board: {board}")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=target, text=True).strip()
    if head != PIN:
        raise ValueError(f"Requires Xiaozhi commit {PIN}, found {head}")
    marker = checked_overlay_path(target, MARKER, regular_file=True)
    if marker.exists():
        state = read_overlay_journal(target, marker)
        if not any(name.startswith(BOARDS[board] + "/") for name in state):
            raise ValueError("A different board overlay is installed; use a separate build copy")
        for name, info in state.items():
            path = target / name
            if not path.is_file() or digest(path.read_bytes()) != info["sha256"]:
                raise ValueError(
                    f"Overlay drift: {name}; preserve your changes before reinstalling"
                )
        recipe = overlay_recipe_digest(board)
        if any(info.get("recipe_sha256") != recipe for info in state.values()):
            raise ValueError(
                "Overlay recipe changed or journal predates recipe tracking; "
                "preserve local changes, use --remove, then reinstall"
            )
        if any("manifest_sha256" not in info for info in state.values()):
            raise ValueError(
                "Overlay journal predates manifest tracking; use --remove, then reinstall"
            )
        print("Overlay already applied, unchanged")
        return
    changed = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=target, text=True
    )
    if changed:
        raise ValueError("Target has tracked changes; use a clean build copy")
    if any(checked_overlay_path(target, name).exists() for name in BOARDS.values()):
        raise ValueError("Target board directory already exists")
    recipe = overlay_recipe_digest(board)
    files = planned_files(target, board)  # Validate every patch anchor before changing any source.
    if overlay_recipe_digest(board) != recipe:
        raise ValueError("Overlay recipe changed while planning; retry with stable sources")
    state = {}
    for name, data in files.items():
        path = checked_overlay_path(target, name, regular_file=True)
        state[name] = {
            "sha256": digest(data),
            "recipe_sha256": recipe,
            "original": base64.b64encode(path.read_bytes()).decode() if path.exists() else None,
        }
    # Journal FIRST, then atomically replace each file. If SIGKILL stops
    # this transaction, every published path is either its original bytes
    # or its complete overlay bytes, and --remove can recover using the
    # still-present marker. A marker written only after file replacements
    # would strand a force-killed build with no rollback information.
    manifest = overlay_journal_digest(state)
    for info in state.values():
        info["manifest_sha256"] = manifest
    atomic_replace_bytes(marker, (json.dumps(state, indent=2) + "\n").encode())
    attempted = []
    try:
        for name, data in files.items():
            attempted.append(name)
            atomic_replace_bytes(target / name, data)
    except BaseException:
        # Ordinary Python exceptions also roll back immediately. If disk
        # failure prevents one restore, KEEP the journal for a later --remove.
        rollback_failed = False
        for name in reversed(attempted):
            original = state[name]["original"]
            path = target / name
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_replace_bytes(path, base64.b64decode(original))
            except BaseException:
                rollback_failed = True
        if not rollback_failed:
            marker.unlink(missing_ok=True)
            for board_name in BOARDS.values():
                directory = target / board_name
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
        raise
    print(f"Installed {len(files)} overlay files into {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream", type=Path, help="Read-only local pinned upstream clone (for --output)"
    )
    parser.add_argument("--output", type=Path, help="New disposable build clone to create")
    parser.add_argument("--target", type=Path, help="Existing clean pinned build clone")
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--board", choices=BOARDS, default="cores3", help="Board adapter to install; use separate build copies")
    args = parser.parse_args()
    if args.output:
        if args.target or not args.upstream or args.remove:
            parser.error("--output requires --upstream and cannot combine with --target/--remove")
        if args.output.exists():
            parser.error("--output must not exist; use --target to check an installed overlay")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--no-hardlinks",
                str(args.upstream.resolve()),
                str(args.output.resolve()),
            ],
            check=True,
        )
        subprocess.run(["git", "checkout", "--detach", PIN], cwd=args.output, check=True)
        target = args.output
    elif args.target:
        target = args.target
    else:
        parser.error("Specify --output with --upstream, or --target")
    if args.remove:
        remove(target.resolve())
    else:
        apply(target.resolve(), args.board)


if __name__ == "__main__":
    main()
