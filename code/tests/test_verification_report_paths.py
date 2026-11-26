"""Verification receipts must stay in the explicitly selected directory."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "desk_robot_verify_report_paths", ROOT / "code/scripts/verify_system.py"
)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


@pytest.fixture
def report_runner(monkeypatch, tmp_path):
    stage = ("test-stage", ["true"], tmp_path, 1)
    monkeypatch.setattr(verify, "steps", lambda suite, build: [stage])
    monkeypatch.setattr(verify, "source_snapshot", lambda: {
        "sha": "a" * 40, "tracked_clean": True,
        "root_tree_intact": True, "error": None,
    })

    def run_report(report, before_write=lambda: None):
        def run_stage(*args):
            before_write()
            return {
                "name": "test-stage", "pass": True, "exit_code": 0,
                "elapsed_s": 0.01, "output_tail": "", "error": None,
            }

        monkeypatch.setattr(verify, "run", run_stage)
        monkeypatch.setattr(verify.sys, "argv", [
            "verify_system.py", "--suite", "body", "--report", str(report),
        ])
        return verify.main()

    return run_report


@pytest.mark.parametrize("nested", [False, True])
def test_report_rejects_redirected_parent(tmp_path, report_runner, nested):
    target = tmp_path / "unselected"
    target.mkdir()
    parent = tmp_path / "reports"
    parent.symlink_to(target, target_is_directory=True)
    report = parent / "child" / "receipt.json" if nested else parent / "receipt.json"
    with pytest.raises(SystemExit) as error:
        report_runner(report)
    assert error.value.code == 1
    assert list(target.iterdir()) == []


def test_report_rejects_dangling_parent(tmp_path, report_runner):
    target = tmp_path / "unselected"
    parent = tmp_path / "reports"
    parent.symlink_to(target, target_is_directory=True)
    with pytest.raises(SystemExit) as error:
        report_runner(parent / "child" / "receipt.json")
    assert error.value.code == 1
    assert not target.exists()


def test_report_rechecks_parent_after_stages(tmp_path, report_runner):
    target = tmp_path / "unselected"
    target.mkdir()
    parent = tmp_path / "reports"
    parent.mkdir()

    def change_parent():
        parent.rmdir()
        parent.symlink_to(target, target_is_directory=True)

    with pytest.raises(SystemExit) as error:
        report_runner(parent / "receipt.json", change_parent)
    assert error.value.code == 1
    assert list(target.iterdir()) == []


def test_report_creates_real_nested_directories(tmp_path, report_runner):
    report = tmp_path / "reports" / "body" / "receipt.json"
    assert report_runner(report) == 0
    receipt = json.loads(report.read_text(encoding="utf-8"))
    assert receipt["source_suite_pass"] is True
    assert receipt["physical_hardware_verified"] is False
    assert receipt["assembly_ready"] is False


def test_report_refuses_parent_traversal(tmp_path, report_runner):
    parent = tmp_path / "reports"
    parent.mkdir()
    with pytest.raises(SystemExit) as error:
        report_runner(parent / ".." / "receipt.json")
    assert error.value.code == 1
    assert not (tmp_path / "receipt.json").exists()
