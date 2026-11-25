"""Verification runner must never turn failed CI into a fake accepted robot."""
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "desk_robot_verify", ROOT / "code/scripts/verify_system.py"
)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def test_every_real_host_and_firmware_stage_is_in_canonical_runner(tmp_path):
    jobs = verify.steps("all", tmp_path)
    names = [name for name, *_ in jobs]
    assert names == [
        "python-tests", "python-lint", "body-cmake", "body-compile",
        "body-ctest", "wroom-esp32_full", "wroom-esp32_full_pulse_reversed_lab",
        "wroom-esp32_full_interaction_lab", "wroom-esp32_full_haptic_lab",
        "wroom-esp32_dc_full", "wroom-esp32_dc_watchdog_lab",
        "wroom-esp32_dc_integrated_lab",
        "wroom-esp32_servo_center_bench",
        "wroom-esp32_stepper", "wroom-esp32dev",
        "wroom-esp32_vl53l0x_bench", "sense-build",
        "room-feather_nrf52840_room_bench",
        "room-feather_nrf52840_room_full",
        "dock-01", "dock-02", "dock-03", "dock-04", "dock-05",
    ]
    assert verify.steps("body", tmp_path)[-1][0] == "body-ctest"
    assert [job[0] for job in verify.steps("room", tmp_path)] == [
        "room-feather_nrf52840_room_bench", "room-feather_nrf52840_room_full"
    ]
    assert [job[0] for job in verify.steps("dock", tmp_path)] == [
        "dock-01", "dock-02", "dock-03", "dock-04", "dock-05"
    ]
    assert len(verify.steps("all", tmp_path)) == 24
    with pytest.raises(ValueError):
        verify.steps("physical-accepted-by-a-badge", tmp_path)


def test_all_five_ci_jobs_check_the_reviewed_pr_head_not_synthetic_merge():
    """GitHub checkout defaults to refs/pull/N/merge without an explicit ref.

    Keep every executable lane on the exact SHA of the source under review;
    manual and push verification continue to use the event commit SHA.
    """
    workflow = (ROOT / ".github/workflows/host-verification.yml").read_text()
    requested = "ref: ${{ github.event.pull_request.head.sha || github.sha }}"
    expected = 'expected="${{ github.event.pull_request.head.sha || github.sha }}"'
    # The fifth lane runs fast Mac brain tests independently of the long
    # Sense firmware compile; it must bind to the reviewed PR head too.
    lanes = 5
    assert workflow.count("      - uses: actions/checkout@v4") == lanes
    assert workflow.count(requested) == lanes
    assert workflow.count(expected) == lanes
    assert workflow.count('actual="$(git -c safe.directory="$PWD" rev-parse HEAD)"') == lanes
    assert workflow.count("Verify exact source commit under test") == lanes
    assert "pull_request_target:" not in workflow


def test_local_lint_covers_same_head_python_sources_as_ci(tmp_path):
    """Source receipt must include every Python Sense overlay file CI lints."""
    jobs = dict((name, argv) for name, argv, _, _ in
                verify.steps("python", tmp_path))
    local_paths = set(jobs["python-lint"][4:])
    workflow = (ROOT / ".github/workflows/host-verification.yml").read_text()
    assert "ruff check laptop/src laptop/server/overlay " in workflow
    for name in ("install_overlay.py", "private_config.py"):
        target = "firmware/head/" + name
        assert target in local_paths
        assert (ROOT / "code" / target).is_file()
    assert "firmware/head/*.py" in workflow


def test_every_declared_platformio_environment_is_exercised(tmp_path):
    """New lab builds may not silently disappear from the release matrix."""
    stages = {name for name, *_ in verify.steps("all", tmp_path)}
    for directory, prefix in (
        ("body", "wroom-"),
        ("room_station", "room-"),
        ("dock", "dock-"),
    ):
        config = (ROOT / "code/firmware" / directory / "platformio.ini").read_text()
        environments = set(re.findall(r"^\[env:([^\]]+)\]$", config,
                                      flags=re.MULTILINE))
        assert environments, directory
        expected = {prefix + name for name in environments}
        if directory == "dock":
            expected = {"dock-" + name[-2:] for name in environments}
        assert {stage for stage in stages if stage.startswith(prefix)} == expected


def test_github_actions_also_compiles_all_body_and_room_envs():
    """The CI runner, not just the optional local script, must build every profile."""
    workflow = (ROOT / ".github/workflows/host-verification.yml").read_text()
    for directory in ("body", "room_station"):
        config = (ROOT / "code/firmware" / directory / "platformio.ini").read_text()
        environments = re.findall(r"^\[env:([^\]]+)\]$", config,
                                  flags=re.MULTILINE)
        assert environments, directory
        for name in environments:
            command = f"pio run -d code/firmware/{directory} -e {name}"
            assert command in workflow, f"Missing GitHub Actions build: {command}"
    # The five Nano dock variants are intentionally built by a single loop.
    assert "for id in 01 02 03 04 05; do" in workflow
    assert 'pio run -d code/firmware/dock -e "bench_nano_dock_$id"' in workflow


def test_python_suite_reports_missing_pinned_upstreams_before_pytest(
    monkeypatch, tmp_path,
):
    import json

    sources = [
        {
            "name": name, "path": f"upstream/{name}",
            "commit": letter * 40,
        }
        for name, letter in (
            ("xiaozhi-esp32", "a"),
            ("xiaozhi-esp32-server", "b"),
        )
    ]
    (tmp_path / "upstream-lock.json").write_text(json.dumps({
        "repositories": sources,
    }))
    monkeypatch.setattr(verify, "CODE", tmp_path)
    executed = []

    def should_not_run(*args, **kwargs):
        executed.append(args)
        raise AssertionError("Never launch pytest without its pinned sources")

    monkeypatch.setattr(verify.subprocess, "run", should_not_run)
    result = verify.run("python-tests", ["python", "-m", "pytest"],
                        tmp_path, 2)
    assert result["pass"] is False
    assert result["exit_code"] is None
    assert "INCOMPLETE" in result["error"]
    assert "scripts/restore_upstreams.py" in result["error"]
    assert "xiaozhi-esp32-server" in result["error"]
    assert executed == []


def test_python_suite_accepts_exact_pinned_upstream_commits(
    monkeypatch, tmp_path,
):
    import json

    commits = {"xiaozhi-esp32": "a" * 40,
               "xiaozhi-esp32-server": "b" * 40}
    (tmp_path / "upstream-lock.json").write_text(json.dumps({
        "repositories": [
            {"name": name, "path": "upstream/" + name, "commit": sha}
            for name, sha in commits.items()
        ],
    }))
    for name in commits:
        (tmp_path / "upstream" / name).mkdir(parents=True)
    monkeypatch.setattr(verify, "CODE", tmp_path)
    calls = []

    def pinned_git(args, **kwargs):
        if args == ["git", "status", "--porcelain", "--untracked-files=no"]:
            return ""  # Synthetic locked fixture has no tracked modifications.
        assert args == ["git", "rev-parse", "HEAD"]
        return commits[kwargs["cwd"].name] + "\n"

    def successful_pytest(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="1 passed",
                               stderr="")

    monkeypatch.setattr(verify.subprocess, "check_output", pinned_git)
    monkeypatch.setattr(verify.subprocess, "run", successful_pytest)
    result = verify.run("python-tests", ["python", "-m", "pytest"],
                        tmp_path, 2)
    assert result["pass"] is True
    assert result["exit_code"] == 0
    assert len(calls) == 1


def test_runner_returns_real_failures_and_does_not_retry_motion(monkeypatch, tmp_path):
    calls = []

    def failed(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=7, stdout="compiler failed",
                               stderr="test assertion failed")

    monkeypatch.setattr(verify.subprocess, "run", failed)
    result = verify.run("body-ctest", ["ctest", "--test-dir", str(tmp_path)],
                        tmp_path, 1)
    assert result["pass"] is False
    assert result["exit_code"] == 7
    assert "compiler failed" in result["output_tail"]
    assert len(calls) == 1


def test_missing_tool_returns_incomplete_not_success(monkeypatch, tmp_path):
    def missing(*args, **kwargs):
        raise FileNotFoundError("pio not installed")

    monkeypatch.setattr(verify.subprocess, "run", missing)
    result = verify.run("wroom-full", ["pio", "run"], tmp_path, 1)
    assert result["pass"] is False
    assert result["exit_code"] is None
    assert "FileNotFoundError" in result["error"]


def test_timeout_preserves_bounded_partial_compiler_logs(monkeypatch, tmp_path):
    def timed_out(*args, **kwargs):
        raise verify.subprocess.TimeoutExpired(
            cmd=["cmake", "--build", str(tmp_path)], timeout=2,
            output=b"compiler: validating pins..." + bytes([10]) + b"a" * 20000,
            stderr=b"fatal: module failed" + bytes([10, 255]),
        )

    monkeypatch.setattr(verify.subprocess, "run", timed_out)
    result = verify.run("body-compile", ["cmake", "--build", str(tmp_path)],
                        tmp_path, 2)
    assert result["pass"] is False and result["exit_code"] is None
    assert result["error"].startswith("TimeoutExpired")
    assert "fatal: module failed" in result["output_tail"]
    assert len(result["output_tail"]) <= 12000
    assert chr(0xFFFD) in result["output_tail"]  # invalid UTF8 decoded safely


def test_passing_source_checks_never_clear_commercial_or_physical_batch_gates(
    monkeypatch, tmp_path,
):
    import json

    stages = [("standalone", ["true"], tmp_path, 1)]
    monkeypatch.setattr(verify, "steps", lambda suite, build: stages)
    monkeypatch.setattr(verify, "source_snapshot", lambda: {
        "sha": "a" * 40, "tracked_clean": True,
        "root_tree_intact": True, "error": None,
    })
    monkeypatch.setattr(verify, "run", lambda *args: {
        "name": "standalone", "pass": True, "exit_code": 0,
        "elapsed_s": 0.1, "output_tail": "", "error": None,
    })
    report = tmp_path / "release-receipt.json"
    monkeypatch.setattr(verify.sys, "argv", [
        "verify_system.py", "--suite", "all", "--report", str(report),
    ])
    assert verify.main() == 0  # source program succeeded, NOT a product release
    receipt = json.loads(report.read_text())
    assert receipt["source_suite_pass"] is True
    assert receipt["commercial_cad_rights_verified"] is False
    assert receipt["commercial_batch_release_ready"] is False
    assert receipt["assembly_ready"] is False
    assert receipt["charging_verified"] is False
    assert receipt["sense_sd_j3_isolation_verified"] is False
    assert receipt["sense_vbus_power_path_verified"] is False
    assert receipt["print_fit_verified"] is False
    assert receipt["five_robot_acoustics_verified"] is False
    assert receipt["same_commit_clean_checkout"] is True
    assert receipt["checkout_before"]["sha"] == "a" * 40


@pytest.mark.parametrize("fault", ["changed_commit", "dirty_tree", "missing_git",
                                   "partial_tree"])
def test_successful_test_stages_do_not_certify_unpinned_checkout(
    monkeypatch, tmp_path, fault,
):
    stages = [("stage", ["true"], tmp_path, 1)]
    monkeypatch.setattr(verify, "steps", lambda suite, build: stages)
    monkeypatch.setattr(verify, "run", lambda *args: {
        "name": "stage", "pass": True, "exit_code": 0,
        "elapsed_s": 0.1, "output_tail": "", "error": None,
    })
    clean = {"sha": "a" * 40, "tracked_clean": True,
             "root_tree_intact": True, "error": None}
    if fault == "changed_commit":
        final = {**clean, "sha": "b" * 40}
    elif fault == "dirty_tree":
        final = {**clean, "tracked_clean": False}
    elif fault == "partial_tree":
        final = {**clean, "root_tree_intact": False}
    else:
        final = {"sha": None, "tracked_clean": None,
                 "root_tree_intact": False, "error": "git unavailable"}
    snapshots = iter((clean, final))
    monkeypatch.setattr(verify, "source_snapshot", lambda: next(snapshots))
    report = tmp_path / "pin-receipt.json"
    monkeypatch.setattr(verify.sys, "argv", [
        "verify_system.py", "--suite", "all", "--report", str(report),
    ])
    assert verify.main() == 1
    import json
    receipt = json.loads(report.read_text())
    assert receipt["source_suite_pass"] is True
    assert receipt["same_commit_clean_checkout"] is False
    assert receipt["assembly_ready"] is False


def test_source_snapshot_rejects_unverified_or_dirty_git(monkeypatch):
    outputs = iter(("a" * 40, " M code/scripts/verify_system.py\\n", ""))
    monkeypatch.setattr(verify.subprocess, "check_output",
                        lambda *args, **kwargs: next(outputs))
    result = verify.source_snapshot()
    assert result["sha"] == "a" * 40
    assert result["tracked_clean"] is False
    assert result["root_tree_intact"] is False


def test_source_snapshot_rejects_sparse_checkout_with_missing_real_files(
    tmp_path, monkeypatch,
):
    """A clean Git index cannot hide an absent non-sentinel subtree."""
    import subprocess

    checkout = tmp_path / "sparse-reproduction"
    checkout.mkdir()
    tracked = (
        ".agent3d/agent.txt",
        ".github/workflows/host-verification.yml",
        ".gitignore",
        "AGENTS.md",
        "LICENSE",
        "README.md",
        "code/firmware/body/include/BodyPins.h",
        "code/firmware/head/sense/config.h",
        "code/laptop/src/desk_robot/handling.py",
        "docs/hardware/full-feature-plan.json",
        "docs/records/verification.md",
        "nested/only-non-sentinel-file.txt",
    )
    for name in tracked:
        file = checkout / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("tracked fixture\n", encoding="utf-8")
    # The old ls-files count passed with these still in the index even when
    # sparse checkout removed a whole unrelated subtree from the worktree.
    for index in range(410):
        file = checkout / "filler" / f"file-{index:03d}.txt"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("present\n", encoding="utf-8")

    def git(*args):
        subprocess.run(
            ["git", "-C", str(checkout), *args],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )

    git("init", "-q")
    git("config", "user.email", "robot-test@example.org")
    git("config", "user.name", "Robot Verification Fixture")
    git("add", "-A")
    git("commit", "-qm", "fixture with complete nested tree")
    monkeypatch.setattr(verify, "ROOT", checkout)
    complete = verify.source_snapshot()
    assert complete["tracked_clean"] is True
    assert complete["root_tree_intact"] is True

    git("sparse-checkout", "init", "--cone")
    git("sparse-checkout", "set", ".agent3d", ".github",
        "code", "docs", "filler")
    assert not (checkout / "nested" / "only-non-sentinel-file.txt").exists()
    sparse = verify.source_snapshot()
    assert sparse["sha"] == complete["sha"]
    assert sparse["tracked_clean"] is True  # Git legitimately skips that path.
    assert sparse["root_tree_intact"] is False


@pytest.mark.parametrize("kind", ("existing", "symlink", "dangling_symlink"))
def test_verification_report_never_overwrites_existing_evidence_or_source(
    monkeypatch, tmp_path, kind,
):
    protected = tmp_path / "source.py"
    protected.write_text("keep this source intact\\n", encoding="utf-8")
    report = tmp_path / "verification.json"
    if kind == "existing":
        report.write_text("older receipt\\n", encoding="utf-8")
    elif kind == "symlink":
        report.symlink_to(protected)
    else:
        report.symlink_to(tmp_path / "not-created.json")

    calls = []
    monkeypatch.setattr(verify, "run", lambda *args: calls.append(args))
    monkeypatch.setattr(verify.sys, "argv", [
        "verify_system.py", "--suite", "body", "--report", str(report),
    ])
    with pytest.raises(SystemExit) as error:
        verify.main()
    assert error.value.code == 2
    assert calls == []
    assert protected.read_text(encoding="utf-8") == "keep this source intact\\n"
    if kind == "existing":
        assert report.read_text(encoding="utf-8") == "older receipt\\n"
    else:
        assert report.is_symlink()


def test_verification_report_refuses_a_concurrent_creator(monkeypatch, tmp_path, capsys):
    report = tmp_path / "verification.json"
    stage = ("test-stage", ["true"], tmp_path, 1)
    monkeypatch.setattr(verify, "steps", lambda suite, build: [stage])
    monkeypatch.setattr(verify, "source_snapshot", lambda: {
        "sha": "a" * 40, "tracked_clean": True,
        "root_tree_intact": True, "error": None,
    })

    def competing_writer(*args):
        report.write_text("another writer's evidence\\n", encoding="utf-8")
        return {
            "name": "test-stage", "pass": True, "exit_code": 0,
            "elapsed_s": 0.01, "output_tail": "", "error": None,
        }

    monkeypatch.setattr(verify, "run", competing_writer)
    monkeypatch.setattr(verify.sys, "argv", [
        "verify_system.py", "--suite", "body", "--report", str(report),
    ])
    with pytest.raises(SystemExit) as error:
        verify.main()
    assert error.value.code == 2
    assert "already exists" in capsys.readouterr().err
    assert report.read_text(encoding="utf-8") == "another writer's evidence\\n"


def test_invalid_executable_is_failed_stage(tmp_path):
    tool = tmp_path / "not-a-tool"
    tool.write_text("not an executable format\n")
    tool.chmod(0o700)
    result = verify.run("body-compile", [str(tool)], tmp_path, 2)
    assert result["pass"] is False
    assert result["exit_code"] is None
    assert result["error"].startswith("OSError:")


def test_unusable_report_directory(monkeypatch, tmp_path, capsys):
    parent = tmp_path / "not-a-directory"
    parent.write_text("protected content\n")
    monkeypatch.setattr(verify, "steps", lambda suite, build: [
        ("stage", ["true"], tmp_path, 1),
    ])
    monkeypatch.setattr(verify, "source_snapshot", lambda: {
        "sha": "a" * 40, "tracked_clean": True,
        "root_tree_intact": True, "error": None,
    })
    monkeypatch.setattr(verify.sys, "argv", [
        "verify_system.py", "--report", str(parent / "report.json"),
    ])
    with pytest.raises(SystemExit) as error:
        verify.main()
    assert error.value.code == 1
    assert "Cannot create verification report directory" in capsys.readouterr().err
    assert parent.read_text() == "protected content\n"
