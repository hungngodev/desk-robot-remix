from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HEAD = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("overlay", HEAD / "install_overlay.py")
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)
UPSTREAM = Path(os.environ.get("DESK_ROBOT_UPSTREAM", HEAD.parents[1] / "upstream/xiaozhi-esp32"))


def native_cpp_env() -> dict[str, str]:
    """Use Apple's actual SDK libc++ includes for the C++ harness on macOS.

    Never override a developer's explicit include path or mutate the shell.
    On non-Apple runners use the compiler's normal header discovery.
    """
    env = dict(os.environ)
    if sys.platform != "darwin" or env.get("CPLUS_INCLUDE_PATH"):
        return env
    xcrun = shutil.which("xcrun")
    if not xcrun:
        return env
    try:
        sdk = subprocess.run(
            [xcrun, "--show-sdk-path"], capture_output=True, text=True,
            check=False,
        )
    except OSError:
        return env
    if sdk.returncode == 0 and sdk.stdout.strip():
        headers = Path(sdk.stdout.strip()) / "usr/include/c++/v1"
        if headers.is_dir():
            env["CPLUS_INCLUDE_PATH"] = str(headers)
    return env


class ProtocolTests(unittest.TestCase):
    def test_native_cpp_env_preserves_user_configuration(self):
        with patch.object(sys, "platform", "darwin"), patch.dict(
            os.environ, {"CPLUS_INCLUDE_PATH": "/already/configured"}
        ):
            with patch.object(shutil, "which") as lookup:
                self.assertEqual(
                    native_cpp_env()["CPLUS_INCLUDE_PATH"],
                    "/already/configured",
                )
                lookup.assert_not_called()

    def test_native_cpp_env_resolves_macos_sdk_only_when_needed(self):
        with patch.object(sys, "platform", "darwin"), patch.dict(
            os.environ, {"CPLUS_INCLUDE_PATH": ""}
        ), patch.object(shutil, "which", return_value="/usr/bin/xcrun"), patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="/fake/MacOSX.sdk\n",
            ),
        ) as probe, patch.object(Path, "is_dir", return_value=True):
            env = native_cpp_env()
            self.assertEqual(
                env["CPLUS_INCLUDE_PATH"],
                "/fake/MacOSX.sdk/usr/include/c++/v1",
            )
            probe.assert_called_once()

    def test_native_protocol_and_ack_regressions(self):
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler, "A native C++20 compiler is required")
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "protocol-test"
            subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(HEAD / "overlay"), str(HEAD / "tests/protocol_test.cc"), "-o", str(exe)], check=True, env=native_cpp_env())
            subprocess.run([str(exe)], check=True)


class BuildSelectionTests(unittest.TestCase):
    def test_build_script_selects_distinct_board_copy_and_private_settings(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            script = root / "scripts/build_head.sh"
            script.parent.mkdir()
            shutil.copy(HEAD.parents[1] / "scripts/build_head.sh", script)
            (root / "firmware/head").mkdir(parents=True)
            shutil.copy(HEAD / "dependencies.lock", root / "firmware/head/dependencies.lock")
            for name in ("xiaozhi", "xiaozhi-modular"):
                build_script = root / "firmware/head/build" / name / "scripts/build.py"
                build_script.parent.mkdir(parents=True)
                build_script.touch()
            python = root / ".tools/sdk-bootstrap/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text(f"#!{sys.executable}\nimport json, os, sys\nopen(os.environ['TRACE_PATH'], 'w').write(json.dumps(sys.argv[1:]))\n")
            python.chmod(0o755)
            export = root / ".tools/esp-idf/export.sh"
            export.parent.mkdir(parents=True)
            export.write_text(":\n")
            trace = root / "args.json"
            env = dict(os.environ, TRACE_PATH=str(trace))
            subprocess.run(["bash", str(script)], env=env, check=True)
            args = json.loads(trace.read_text())
            self.assertEqual(args[0], "firmware/head/build/xiaozhi/scripts/build.py")
            self.assertIn("desk-robot/desk-robot-core-s3", args)
            self.assertIn("disabled", args)
            subprocess.run(["bash", str(script), "--board", "modular", "--private", "--skip-merge"], env=env, check=True)
            args = json.loads(trace.read_text())
            self.assertEqual(args[0], "firmware/head/build/xiaozhi-modular/scripts/build.py")
            self.assertIn("desk-robot/desk-robot-modular-s3", args)
            self.assertIn("config.private.json", args)
            self.assertIn("--skip-merge", args)
            self.assertNotIn("disabled", args)
            invalid = subprocess.run(["bash", str(script), "--board", "wrong"], env=env, capture_output=True)
            self.assertEqual(invalid.returncode, 2)
            lock = root / "firmware/head/build/xiaozhi-modular/dependencies.lock"
            lock.write_text("changed dependency lock\n")
            invalid = subprocess.run(["bash", str(script), "--board", "modular"], env=env, capture_output=True)
            self.assertEqual(invalid.returncode, 1)
            self.assertIn(b"dependency lock differs", invalid.stderr)

    def test_modular_snapshot_freshness_and_failures(self):
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler, "A native C++23 compiler is required")
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "snapshot-test"
            subprocess.run([compiler, "-std=c++23", "-Wall", "-Wextra", "-Werror", "-I", str(HEAD), str(HEAD / "tests/snapshot_test.cc"), "-o", str(exe)], check=True, env=native_cpp_env())
            subprocess.run([str(exe)], check=True)

class OverlayPathTests(unittest.TestCase):
    """Exercise the installer transaction without requiring an upstream clone."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "checkout"
        self.root.mkdir()
        self.external = Path(temp.name) / "external"
        self.external.mkdir()
        self.board = self.root / overlay.BOARD
        self.board.parent.parent.mkdir(parents=True)
        self.plan = {f"{overlay.BOARD}/config.json": b"{}"}
        self.recipe_root = Path(temp.name) / "recipe"
        (self.recipe_root / "overlay").mkdir(parents=True)
        (self.recipe_root / "install_overlay.py").write_bytes(b"installer")
        (self.recipe_root / "BOARD_README.md").write_bytes(b"board readme")
        self.driver = self.recipe_root / "overlay/driver.cc"
        self.driver.write_bytes(b"driver v1")
        recipe_root = patch.object(overlay, "HERE", self.recipe_root)
        recipe_root.start()
        self.addCleanup(recipe_root.stop)
        git = patch.object(
            overlay.subprocess, "check_output",
            side_effect=lambda args, **kwargs: overlay.PIN if "rev-parse" in args else "",
        )
        git.start()
        self.addCleanup(git.stop)
        planner = patch.object(overlay, "planned_files", return_value=self.plan)
        planner.start()
        self.addCleanup(planner.stop)

    def assert_install_refused(self):
        with self.assertRaisesRegex(ValueError, "symlink"):
            overlay.apply(self.root)
        self.assertFalse((self.root / overlay.MARKER).is_file())
        self.assertEqual(list(self.external.iterdir()), [])

    def test_untracked_board_parent_symlink(self):
        self.board.parent.symlink_to(self.external, target_is_directory=True)
        self.assert_install_refused()
        self.assertTrue(self.board.parent.is_symlink())

    def test_dangling_board_symlink(self):
        self.board.parent.mkdir()
        self.board.symlink_to(self.external / "missing", target_is_directory=True)
        self.assert_install_refused()
        self.assertTrue(self.board.is_symlink())

    def test_dangling_marker_symlink(self):
        marker = self.root / overlay.MARKER
        marker.symlink_to(self.external / "missing")
        self.assert_install_refused()
        with self.assertRaisesRegex(ValueError, "symlink"):
            overlay.remove(self.root)
        self.assertTrue(marker.is_symlink())

    def test_planned_file_symlink(self):
        path = self.root / "main/foreign.txt"
        path.symlink_to(self.external / "missing")
        self.plan["main/foreign.txt"] = b"replacement"
        self.assert_install_refused()
        self.assertTrue(path.is_symlink())

    def test_clean_install_reapply_remove(self):
        overlay.apply(self.root)
        marker = self.root / overlay.MARKER
        before = marker.read_bytes()
        overlay.apply(self.root)
        self.assertEqual(marker.read_bytes(), before)
        self.assertEqual((self.board / "config.json").read_bytes(), b"{}")
        overlay.remove(self.root)
        self.assertFalse(marker.exists())
        self.assertFalse(self.board.exists())

    def test_recovery_rejects_symlink_even_with_matching_bytes(self):
        overlay.apply(self.root)
        path = self.board / "config.json"
        other = self.root / "local.json"
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "path escapes pinned checkout.*symlink"):
            overlay.remove(self.root)
        self.assertTrue(path.is_symlink())
        self.assertTrue((self.root / overlay.MARKER).is_file())
        self.assertEqual(other.read_bytes(), b"{}")

    def test_removal_preflights_other_board_paths(self):
        overlay.apply(self.root)
        other = self.root / overlay.BOARDS["sense"]
        other.symlink_to(self.external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            overlay.remove(self.root)
        self.assertTrue((self.board / "config.json").is_file())
        self.assertTrue((self.root / overlay.MARKER).is_file())
        self.assertTrue(other.is_symlink())

    def test_reapply_refuses_stale_recipe_without_changing_installed_files(self):
        overlay.apply(self.root)
        marker = self.root / overlay.MARKER
        original_marker = marker.read_bytes()
        self.driver.write_bytes(b"driver v2")
        self.plan[f"{overlay.BOARD}/config.json"] = b'{"version": 2}'
        with self.assertRaisesRegex(ValueError, "recipe changed.*--remove"):
            overlay.apply(self.root)
        self.assertEqual(marker.read_bytes(), original_marker)
        self.assertEqual((self.board / "config.json").read_bytes(), b"{}")
        overlay.remove(self.root)
        overlay.apply(self.root)
        self.assertEqual((self.board / "config.json").read_bytes(), b'{"version": 2}')

    def test_legacy_journal_remains_recoverable_but_not_current(self):
        overlay.apply(self.root)
        marker = self.root / overlay.MARKER
        state = json.loads(marker.read_text())
        for info in state.values():
            del info["recipe_sha256"]
        marker.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "predates recipe tracking"):
            overlay.apply(self.root)
        overlay.remove(self.root)
        self.assertFalse(marker.exists())
        self.assertFalse(self.board.exists())

    def test_recipe_mutation_during_planning_refused_before_journal(self):
        def changing_plan(*args):
            self.driver.write_bytes(b"driver v2")
            return self.plan

        with patch.object(overlay, "planned_files", side_effect=changing_plan):
            with self.assertRaisesRegex(ValueError, "recipe changed while planning"):
                overlay.apply(self.root)
        self.assertFalse((self.root / overlay.MARKER).exists())
        self.assertFalse(self.board.exists())

    def test_recipe_digest_distinguishes_board_sources_and_shared_inputs(self):
        (self.recipe_root / "modular_snapshot.inc").write_bytes(b"snapshot")
        for board in ("modular", "sense", "waveshare"):
            folder = self.recipe_root / board
            folder.mkdir()
            (folder / "config.json").write_bytes(board.encode())
        before = {board: overlay.overlay_recipe_digest(board) for board in overlay.BOARDS}
        (self.recipe_root / "sense/config.json").write_bytes(b"sense v2")
        self.assertNotEqual(overlay.overlay_recipe_digest("sense"), before["sense"])
        for board in ("cores3", "modular", "waveshare"):
            self.assertEqual(overlay.overlay_recipe_digest(board), before[board])
        self.driver.write_bytes(b"driver v2")
        for board in overlay.BOARDS:
            self.assertNotEqual(overlay.overlay_recipe_digest(board), before[board])

    def test_malformed_recipe_digest_refused_before_removal(self):
        overlay.apply(self.root)
        marker = self.root / overlay.MARKER
        state = json.loads(marker.read_text())
        next(iter(state.values()))["recipe_sha256"] = "invalid"
        marker.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "Invalid head overlay journal recipe digest"):
            overlay.remove(self.root)
        self.assertTrue(marker.is_file())
        self.assertEqual((self.board / "config.json").read_bytes(), b"{}")


@unittest.skipUnless((UPSTREAM / "main/boards/common/esp_video.cc").is_file(), "Pinned upstream fixture unavailable")
class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        paths = ["main/Kconfig.projbuild", "main/CMakeLists.txt", "main/mcp_server.cc", "main/boards/common/camera.h", "main/boards/common/esp_video.h", "main/boards/common/esp_video.cc"]
        # Sense overlays urgent-stop and the pinned Xiaozhi I2S writer; no
        # shortcut synthetic codec is installed in the firmware clone.
        paths += [
            "main/application.cc", "main/application.h",
            "main/audio/audio_service.cc", "main/audio/audio_service.h",
            "main/audio/audio_codec.cc", "main/audio/audio_codec.h",
            "main/audio/codecs/no_audio_codec.cc",
            "main/protocols/protocol.cc", "main/protocols/protocol.h",
            "main/protocols/websocket_protocol.cc",
            "main/protocols/websocket_protocol.h",
        ]
        paths += ["main/boards/common/esp32_camera.h", "main/boards/common/esp32_camera.cc"]
        paths += [p.relative_to(UPSTREAM).as_posix() for p in (UPSTREAM / "main/boards/m5stack/core-s3").iterdir() if p.is_file()]
        self.original = {}
        for name in paths:
            data = (UPSTREAM / name).read_bytes()
            self.original[name] = data
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        self.git = patch.object(overlay.subprocess, "check_output", side_effect=lambda args, **kwargs: overlay.PIN if "rev-parse" in args else "")
        self.git.start()

    def tearDown(self):
        self.git.stop()
        self.temp.cleanup()

    def test_unique_board_and_shared_camera_lock(self):
        overlay.apply(self.root)
        config = json.loads((self.root / overlay.BOARD / "config.json").read_text())
        self.assertEqual(config["type"], "desk-robot-core-s3")
        source = (self.root / overlay.BOARD / "desk_robot_core_s3.cc").read_text()
        self.assertEqual(source.count("DECLARE_BOARD("), 1)
        self.assertIn("DECLARE_BOARD(DeskRobotCoreS3Board)", source)
        self.assertLess(source.index("WifiBoard::StartNetwork();"), source.index("robot_bridge.Start();"))
        self.assertEqual((self.root / overlay.BOARD / "config.h").read_bytes(), self.original["main/boards/m5stack/core-s3/config.h"])
        mcp = (self.root / "main/mcp_server.cc").read_text()
        lock = mcp.index("camera_lock(camera->AccessMutex())")
        self.assertLess(lock, mcp.index("camera->Capture()"))
        self.assertLess(lock, mcp.index("camera->Explain(question)"))
        for name, original in self.original.items():
            if "m5stack/core-s3" in name:
                self.assertEqual((self.root / name).read_bytes(), original)

    def test_install_idempotent_remove_exactly_restores_sources(self):
        overlay.apply(self.root)
        snapshot = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        overlay.apply(self.root)
        self.assertEqual(snapshot, {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        overlay.remove(self.root)
        for name, data in self.original.items():
            self.assertEqual((self.root / name).read_bytes(), data)
        self.assertFalse((self.root / overlay.BOARD).exists())
        self.assertFalse((self.root / overlay.MARKER).exists())

    def test_drift_is_preserved(self):
        overlay.apply(self.root)
        file = self.root / overlay.BOARD / "robot_bridge.cc"
        file.write_text(file.read_text() + "\n// local modification\n")
        with self.assertRaisesRegex(ValueError, "drift"):
            overlay.apply(self.root)
        with self.assertRaisesRegex(ValueError, "changed"):
            overlay.remove(self.root)
        self.assertIn("local modification", file.read_text())

    def test_anchor_mismatch_makes_no_partial_changes(self):
        path = self.root / "main/mcp_server.cc"
        path.write_text(path.read_text().replace("                    if (!camera->Capture()) {", "                    if (false) {"))
        with self.assertRaisesRegex(ValueError, "anchor"):
            overlay.apply(self.root)
        self.assertFalse((self.root / overlay.BOARD).exists())
        self.assertFalse((self.root / overlay.MARKER).exists())

    def test_interrupted_overlay_write_has_no_success_marker(self):
        """An interrupted source patch must not be mistaken for an install."""
        atomic_write = overlay.atomic_replace_bytes
        attempts = 0

        def interrupted_write(path, data):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise OSError("simulated interrupted overlay write")
            return atomic_write(path, data)

        # Journal publication now uses atomic_replace_bytes, not
        # Path.write_bytes. Inject failure in the real transaction seam.
        with patch.object(overlay, "atomic_replace_bytes",
                          side_effect=interrupted_write):
            with self.assertRaisesRegex(OSError, "simulated interrupted"):
                overlay.apply(self.root)
        self.assertGreaterEqual(attempts, 2)
        self.assertFalse((self.root / overlay.MARKER).exists())
        self.assertFalse((self.root / (overlay.MARKER + ".tmp")).exists())
        self.assertFalse((self.root / overlay.BOARD).exists())
        for name, original in self.original.items():
            self.assertEqual((self.root / name).read_bytes(), original)

    def test_wrong_commit_refused(self):
        self.git.stop()
        with patch.object(overlay.subprocess, "check_output", return_value="wrong-commit"):
            with self.assertRaisesRegex(ValueError, "Requires Xiaozhi commit"):
                overlay.apply(self.root)
        self.git.start()

    def test_sense_installed_component_inventory_and_exact_rollback(self):
        """The selected build must receive every Sense and shared board file."""
        overlay.apply(self.root, "sense")
        board = self.root / overlay.BOARDS["sense"]
        expected = {
            path.name: path.read_bytes()
            for folder in (HEAD / "sense", HEAD / "overlay")
            for path in folder.iterdir()
            if path.is_file() and path.suffix in (".cc", ".h", ".hpp", ".json", ".md")
        }
        required = {
            "config.h", "config.json", "desk_robot_sense.cc",
            "sense_reference_codec.cc", "sense_reference_codec.h",
            "reference_timeline.h", "sense_pcm_window.h", "sense_speaker_activity.hpp",
            "face_eye_display.hpp", "face_eye_animator.hpp", "stackchan_behavior.hpp",
            "robot_bridge.cc", "robot_bridge.h", "robot_protocol.h", "real_touch_edges.h",
        }
        self.assertFalse(required - expected.keys(), "Missing required source component")
        installed = {path.name: path.read_bytes() for path in board.iterdir() if path.is_file()}
        self.assertEqual(installed, expected)
        for variant, path in overlay.BOARDS.items():
            if variant != "sense":
                self.assertFalse((self.root / path).exists())
        cmake = (self.root / "main/CMakeLists.txt").read_text()
        self.assertIn(
            'elseif(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3)\n'
            '    set(BOARD_DIR "desk-robot/desk-robot-sense-s3")', cmake,
        )
        self.assertIn(
            "if(CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3)\n"
            "    list(APPEND MAIN_PRIV_REQUIRES_EXTRA esp_http_server)", cmake,
        )
        kconfig = (self.root / "main/Kconfig.projbuild").read_text()
        self.assertIn("config BOARD_TYPE_DESK_ROBOT_SENSE_S3", kconfig)
        overlay.remove(self.root)
        self.assertFalse(board.exists())
        self.assertEqual(
            {path.relative_to(self.root).as_posix(): path.read_bytes()
             for path in self.root.rglob("*") if path.is_file()},
            self.original,
        )

    def test_sense_reuses_upstream_i2s_writer_with_finite_stop_bound(self):
        overlay.apply(self.root, "sense")
        codec_path = "main/audio/codecs/no_audio_codec.cc"
        source = (self.root / codec_path).read_text()
        original = self.original[codec_path].decode()
        self.assertIn("portMAX_DELAY", original)
        self.assertIn("data_if_mutex_", original)
        self.assertIn("#ifdef CONFIG_BOARD_TYPE_DESK_ROBOT_SENSE_S3", source)
        self.assertIn("pdMS_TO_TICKS(120)", source)
        self.assertIn("size_t bytes_written = 0", source)
        self.assertIn("const int safe_volume = std::clamp(output_volume_, 0, 100);", source)
        self.assertIn("pow(double(safe_volume) / 100.0, 2) * 65536", source)
        # Only the opt-in Sense build changes gain. Upstream remains byte exact.
        self.assertNotIn("safe_volume", original)
        self.assertIn("if (err != ESP_OK)", source)
        self.assertIn("bytes_written = 0;", source)
        self.assertIn("bytes_written > static_cast<size_t>(samples)", source)
        self.assertIn("bytes_written % sizeof(int32_t) != 0", source)
        self.assertIn("return static_cast<int>(bytes_written / sizeof(int32_t))", source)
        self.assertIn("#else", source)
        self.assertIn("portMAX_DELAY", source)
        self.assertNotIn("pdMS_TO_TICKS(120)", original)
        service = (self.root / "main/audio/audio_service.cc").read_text()
        service_header = (self.root / "main/audio/audio_service.h").read_text()
        codec_header = (self.root / "main/audio/audio_codec.h").read_text()
        codec_base = (self.root / "main/audio/audio_codec.cc").read_text()
        protocol_header = (self.root / "main/protocols/protocol.h").read_text()
        protocol_source = (self.root / "main/protocols/protocol.cc").read_text()
        websocket_header = (
            self.root / "main/protocols/websocket_protocol.h"
        ).read_text()
        websocket_source = (
            self.root / "main/protocols/websocket_protocol.cc"
        ).read_text()
        self.assertIn("virtual int OutputData", codec_header)
        self.assertIn("return Write(data.data(), data.size());", codec_base)
        self.assertIn("on_playback_committed", service_header)
        output = service.split("void AudioService::AudioOutputTask()", 1)[1].split(
            "void AudioService::OpusCodecTask()", 1
        )[0]
        # The contiguous-prefix guard replaces the old short-write-only latch.
        self.assertIn("DeskPlaybackPrefix desk_robot_prefix;", output)
        self.assertIn("task.playback_id, task.media_position_ms,", output)
        self.assertIn("task.desk_frame_duration_ms,", output)
        self.assertIn("!task.pcm.empty() &&", output)
        self.assertIn(
            "transmitted_frames == static_cast<int>(task.pcm.size())", output
        )
        self.assertLess(
            output.index("codec_->OutputData(task.pcm)"),
            output.index("desk_robot_prefix.Accept("),
        )
        self.assertLess(
            output.index("desk_robot_prefix.Accept("),
            output.index("callbacks_.on_playback_committed("),
        )
        self.assertIn("SendI2sProgress", protocol_header)
        self.assertIn('"type\\":\\"desk_robot_i2s_progress', protocol_source)
        self.assertIn('"committed_ms\\":', protocol_source)
        self.assertNotIn('"played_ms\\":', protocol_source)
        self.assertIn("desk_playback_id_", websocket_header)
        self.assertIn(".playback_id = playback_id", websocket_source)
        self.assertIn(".media_position_ms = media_position_ms", websocket_source)
        self.assertIn('strcmp(type->valuestring, "tts") == 0', websocket_source)
        self.assertIn("constexpr int initial_decoder_rate = 24000;", service)
        self.assertIn("esp_ae_rate_cvt_open(&cfg, &output_resampler_)", service)
        # Scope the assertion to Sense's STARTUP converter. The upstream
        # decoder also closes output_resampler_ in Destroy and rate changes,
        # which must not mask a missing startup close.
        startup = service.split("constexpr int initial_decoder_rate = 24000;", 1)[1]
        startup = startup.split("esp_opus_enc_config_t opus_enc_cfg", 1)[0]
        self.assertIn("esp_ae_rate_cvt_close(output_resampler_)", startup)
        self.assertLess(
            startup.index("esp_ae_rate_cvt_close(output_resampler_)"),
            startup.index("esp_ae_rate_cvt_open(&cfg, &output_resampler_)"),
        )
        self.assertIn("output_resampler_ = nullptr;", startup)
        self.assertIn("Sense speaker resampler unavailable: discarding mismatched PCM", service)
        self.assertIn("decoded = !task.pcm.empty();", service)
        decoder = service.split("void AudioService::SetDecodeSampleRate(", 1)[1]
        decoder = decoder.split("void AudioService::PushTaskToEncodeQueue(", 1)[0]
        # Invalid formats cannot close the current decoder. Failed opens
        # retain its handle; successful opens swap under decoder_mutex_.
        self.assertIn("Rejecting unsupported Sense Opus rate", decoder)
        self.assertIn("Rejecting unsupported Sense Opus frame duration", decoder)
        self.assertIn("void* proposed_decoder = nullptr;", decoder)
        self.assertIn("void* previous_decoder = opus_decoder_;", decoder)
        self.assertLess(
            decoder.index("Rejecting unsupported Sense Opus frame duration"),
            decoder.index("esp_opus_dec_open(&opus_dec_cfg"),
        )
        self.assertLess(
            decoder.index("esp_opus_dec_open(&opus_dec_cfg"),
            decoder.index("void* previous_decoder = opus_decoder_;"),
        )
        self.assertLess(
            decoder.index("if (proposed_decoder == nullptr)"),
            decoder.index("void* previous_decoder = opus_decoder_;"),
        )
        self.assertLess(
            decoder.index("void* previous_decoder = opus_decoder_;"),
            decoder.index("esp_opus_dec_close(previous_decoder)"),
        )
        app = (self.root / "main/application.cc").read_text()
        self.assertIn("urgent_flush", app)
        self.assertIn("audio_service_.ResetDecoder()", app)
        self.assertIn("GetAudioCodec()->EnableOutput(false)", app)
        # The original single Xiaozhi Opus owner discards buffered voice
        # packets before any further send when physical BOOT has muted PDM.
        header = (self.root / "main/application.h").read_text()
        self.assertIn("void SetSenseMicrophonePrivacyMuted(bool muted)", header)
        self.assertIn("std::atomic<bool> sense_microphone_privacy_muted_{false};", header)
        pending_send = app.split("if (bits & MAIN_EVENT_SEND_AUDIO)", 1)[1].split(
            "if (bits & MAIN_EVENT_WAKE_WORD_DETECTED)", 1
        )[0]
        self.assertIn("sense_microphone_privacy_muted_.load(", pending_send)
        self.assertIn("while (audio_service_.PopPacketFromSendQueue()) {}", pending_send)
        self.assertLess(
            pending_send.index("sense_microphone_privacy_muted_.load("),
            pending_send.index("protocol_->SendAudio("),
        )
        stop = app.split("void Application::HandleStopListeningEvent()", 1)[1].split(
            "void Application::HandleWakeWordDetectedEvent()", 1
        )[0]
        self.assertIn("sense_microphone_privacy_muted_.load(", stop)
        self.assertIn("protocol_->CloseAudioChannel();", stop)
        self.assertIn("audio_service_.ResetDecoder();", stop)
        self.assertIn("while (audio_service_.PopPacketFromSendQueue()) {}", stop)
        toggle = app.split("void Application::HandleToggleChatEvent()", 1)[1].split(
            "void Application::ContinueOpenAudioChannel(", 1
        )[0]
        self.assertIn("sense_microphone_privacy_muted_.load(", toggle)
        start = app.split("void Application::HandleStartListeningEvent()", 1)[1].split(
            "void Application::HandleStopListeningEvent()", 1
        )[0]
        self.assertIn("sense_microphone_privacy_muted_.load(", start)
        self.assertIn(
            "sense_microphone_privacy_muted_.load(",
            app.split("void Application::StartListeningAudio()", 1)[1].split(
                "void Application::ConfigureWakeWordForListening()", 1
            )[0],
        )
        # A pending network open must check again before enabling listening.
        network_open = app.split("void Application::ContinueOpenAudioChannel(", 1)[1].split(
            "void Application::HandleStartListeningEvent()", 1
        )[0]
        self.assertIn("BOOT privacy may have cancelled while OpenAudioChannel blocked",
                      network_open)
        self.assertIn("GetDeviceState() != kDeviceStateConnecting", network_open)
        self.assertIn("protocol_->CloseAudioChannel();", network_open)
        self.assertLess(network_open.index("protocol_->OpenAudioChannel()"),
                        network_open.index("BOOT privacy may have cancelled"))
        self.assertLess(network_open.index("BOOT privacy may have cancelled"),
                        network_open.rindex("SetListeningMode(mode);"))
        self.assertIn('SenseReferenceCodec', (
            self.root / overlay.BOARDS["sense"] / "desk_robot_sense.cc").read_text())
        # The source checkout remains exact and the patch is reversible.
        overlay.remove(self.root)
        self.assertEqual((self.root / codec_path).read_bytes(),
                         self.original[codec_path])

    def test_modular_variant_pins_camera_lock_and_independent_identity(self):
        overlay.apply(self.root, "modular")
        board = self.root / overlay.BOARDS["modular"]
        config = json.loads((board / "config.json").read_text())
        self.assertEqual(config["type"], "desk-robot-modular-s3")
        self.assertIn("CONFIG_SPIRAM_MODE_OCT=y", config["builds"][0]["sdkconfig_append"])
        self.assertIn("CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y", config["builds"][0]["sdkconfig_append"])
        self.assertIn("CONFIG_SCCB_HARDWARE_I2C_PORT0=y", config["builds"][0]["sdkconfig_append"])
        self.assertIn("CONFIG_SCCB_HARDWARE_I2C_PORT1=n", config["builds"][0]["sdkconfig_append"])
        self.assertIn("CONFIG_SCCB_HARDWARE_I2C_DRIVER_NEW=y", config["builds"][0]["sdkconfig_append"])
        self.assertFalse((self.root / overlay.BOARD).exists())
        import re
        header = (board / "config.h").read_text()
        pins = dict(re.findall(r"#define (\w+) GPIO_NUM_(\d+)\b", header))
        self.assertEqual(len(pins.values()), len(set(pins.values())), "Peripheral GPIO collision")
        self.assertFalse({19, 20, 35, 36, 37, 43, 44, 48} & {int(pin) for pin in pins.values()})
        self.assertEqual((pins["DISPLAY_SDA_PIN"], pins["DISPLAY_SCL_PIN"]), ("38", "39"))
        self.assertEqual((pins["ROBOT_UART_TX"], pins["ROBOT_UART_RX"]), ("2", "1"))
        self.assertIn("uart_set_pin(kUart, 2, 1,", (board / "robot_bridge.cc").read_text())
        self.assertIn('#error "Modular head requires camera SCCB on I2C0', header)
        self.assertIn("#define DISPLAY_I2C_PORT I2C_NUM_1", header)
        self.assertIn("#define CAMERA_SCCB_I2C_PORT I2C_NUM_0", header)
        source = (board / "desk_robot_modular_s3.cc").read_text()
        self.assertEqual(source.count("DECLARE_BOARD("), 1)
        self.assertIn("new Esp32Camera(config)", source)
        self.assertIn("new OledDisplay(", source)
        self.assertIn("NoAudioCodecSimplex", source)
        self.assertLess(source.index("WifiBoard::StartNetwork();"), source.index("robot_bridge.Start();"))
        camera = (self.root / "main/boards/common/esp32_camera.cc").read_text()
        self.assertIn("Esp32Camera::SnapshotJpeg()", camera)
        self.assertEqual(camera.count("camera_lock(AccessMutex())"), 6)
        mcp = (self.root / "main/mcp_server.cc").read_text()
        self.assertLess(mcp.index("camera_lock(camera->AccessMutex())"), mcp.index("camera->Capture()"))
        with self.assertRaisesRegex(ValueError, "different board"):
            overlay.apply(self.root, "cores3")
        overlay.apply(self.root, "modular")
        overlay.remove(self.root)
        for name, data in self.original.items():
            self.assertEqual((self.root / name).read_bytes(), data)
        self.assertFalse(board.exists())

    def test_modular_drift_and_bad_camera_anchor_are_not_overwritten(self):
        path = self.root / "main/boards/common/esp32_camera.cc"
        original = path.read_text()
        path.write_text(original.replace("bool Esp32Camera::Capture() {", "bool Esp32Camera::Capture() /* changed */ {"))
        with self.assertRaisesRegex(ValueError, "anchor"):
            overlay.apply(self.root, "modular")
        self.assertFalse((self.root / overlay.MARKER).exists())
        path.write_text(original)
        overlay.apply(self.root, "modular")
        path.write_text(path.read_text() + "\n// local change\n")
        with self.assertRaisesRegex(ValueError, "drift"):
            overlay.apply(self.root, "modular")
        with self.assertRaisesRegex(ValueError, "changed"):
            overlay.remove(self.root)
        self.assertIn("local change", path.read_text())

if __name__ == "__main__":
    unittest.main()
