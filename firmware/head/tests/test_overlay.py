from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HEAD = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("overlay", HEAD / "install_overlay.py")
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)
UPSTREAM = Path(os.environ.get("DESK_ROBOT_UPSTREAM", "/Users/hung/Documents/coding/desk-robot-remix/upstream/xiaozhi-esp32"))

class ProtocolTests(unittest.TestCase):
    def test_native_protocol_and_ack_regressions(self):
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler, "A native C++20 compiler is required")
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "protocol-test"
            subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(HEAD / "overlay"), str(HEAD / "tests/protocol_test.cc"), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

@unittest.skipUnless((UPSTREAM / "main/boards/common/esp_video.cc").is_file(), "Pinned upstream fixture unavailable")
class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        paths = ["main/Kconfig.projbuild", "main/CMakeLists.txt", "main/mcp_server.cc", "main/boards/common/camera.h", "main/boards/common/esp_video.h", "main/boards/common/esp_video.cc"]
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

    def test_wrong_commit_refused(self):
        self.git.stop()
        with patch.object(overlay.subprocess, "check_output", return_value="wrong-commit"):
            with self.assertRaisesRegex(ValueError, "Requires Xiaozhi commit"):
                overlay.apply(self.root)
        self.git.start()

if __name__ == "__main__":
    unittest.main()
