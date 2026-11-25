"""Execute pinned upstream PowerSaveTimer and startup hint host regressions."""
from __future__ import annotations

import io
import shutil
import unittest
from pathlib import Path

import pytest

CODE = Path(__file__).resolve().parents[3]
UPSTREAM = CODE / "upstream/xiaozhi-esp32"
UPSTREAM_TESTS = UPSTREAM / "scripts/tests"
SENSE_CC = CODE / "firmware/head/sense/desk_robot_sense.cc"
WORKFLOW = CODE.parent / ".github/workflows/host-verification.yml"


def _run_upstream_unittest(pattern: str) -> unittest.TestResult:
    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(UPSTREAM_TESTS),
        pattern=pattern,
        top_level_dir=str(UPSTREAM_TESTS),
    )
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = runner.run(suite)
    assert result.testsRun >= 1, f"Expected at least 1 test for {pattern}: {stream.getvalue()}"
    assert result.wasSuccessful(), stream.getvalue()
    return result


def test_pinned_upstream_power_save_timer_and_startup_hint_pass():
    if not UPSTREAM_TESTS.is_dir():
        pytest.skip("Restore pinned upstream Xiaozhi firmware fixture to run these suites")
    if shutil.which("c++") is None:
        pytest.skip("requires a host C++ compiler")
    # Match macOS AppleClang SDK search path when CPLUS_INCLUDE_PATH is unset on CI/Linux it is a no-op.
    assert (UPSTREAM / "main/boards/common/power_save_timer.cc").is_file()
    assert (UPSTREAM / "main/application.cc").is_file()
    power_result = _run_upstream_unittest("test_power_save_timer.py")
    hint_result = _run_upstream_unittest("test_startup_wake_word_hint.py")
    ogg_result = _run_upstream_unittest("test_ogg_demuxer.py")
    assert power_result.testsRun >= 1
    assert hint_result.testsRun >= 1
    assert ogg_result.testsRun >= 1


def test_sense_board_retains_wake_word_disabled_and_no_unqualified_sleep():
    sense_src = SENSE_CC.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "PowerSaveTimer" not in sense_src
    assert "--wake-word disabled" in workflow
