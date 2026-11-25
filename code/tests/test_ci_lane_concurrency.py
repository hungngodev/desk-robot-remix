"""Fast Mac CI must not be queued behind a long physical firmware build."""

import shlex
import subprocess
from pathlib import Path

import yaml


def test_host_verification_uses_independent_bounded_job_lanes():
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2]
         / ".github/workflows/host-verification.yml").read_text()
    )
    assert "concurrency" not in workflow
    jobs = workflow["jobs"]
    expected = {
        "mac-fast", "python-and-head-host", "body-platformio", "body-host", "sense-idf",
    }
    assert expected <= jobs.keys()
    for lane in expected:
        job = jobs[lane]
        concurrent = job["concurrency"]
        assert concurrent["cancel-in-progress"] is False
        # First attempts still share one bounded PR queue; an explicit
        # run_attempt > 1 can verify an exact SHA despite ongoing pushes.
        assert "github.run_attempt > 1 && github.run_id" in concurrent["group"]
        assert concurrent["group"] == (
            "host-verification-" + lane + "-"
            + "${{ github.run_attempt > 1 && github.run_id || github.event.pull_request.number || github.ref }}"
        )
        assert "Verify exact source commit under test" in (
            str(job["steps"])
        )
        if lane == "mac-fast":
            tests = str(job["steps"])
            assert "tests/test_native_omni_xiaozhi.py" in tests
            assert "tests/test_voice_memory_reuse.py" in tests
            assert "tests/test_runtime_voice_priority.py" in tests
            assert "tests/test_control.py::test_hardware_fleet_allows_only_one_moving_pet_until_acknowledged_stop" in tests
            assert "tests/test_control.py::test_fleet_motion_owner_latches_failed_stop_until_explicit_recovery" in tests
            assert "tests/test_stop_transport_failure.py::StopTransportFailureTests::test_cooperative_job_cancellation_preserves_failed_physical_stop" in tests
            assert "tests/test_stop_transport_failure.py::StopTransportFailureTests::test_terminal_stop_halts_body_but_short_pulse_preserves_arm" in tests
            assert "tests/test_memory_*.py" in tests
            assert "tests/test_conversation_*.py" in tests
            assert "tests/test_core_memory_mutation_race.py" in tests
            assert "tests/test_vision_worker.py::test_scene_comparator_unhashable_model_kind_is_rejected_without_crash" in tests
            assert "tests/test_multimodal.py::test_unhashable_multimodal_cues_are_rejected_without_mutation" in tests
            # These new Mac source regressions must actually run in the
            # independent lane, not only exist in a frequently canceled
            # long full-Python CI job.
            assert "tests/test_grasp_feedback.py" in tests
            for native_voice_test in (
                "test_native_kokoro_voice_is_bound_to_current_pets_without_config_bleed",
                "test_native_voice_refuses_missing_or_malformed_operator_mapping",
                "test_native_kokoro_voice_fails_closed_for_unmapped_provider",
                "test_native_voice_mapping_export_matches_fleet_and_rejects_duplicates",
                "test_pinned_upstream_connection_initializes_per_device_native_tts",
                "test_actual_pinned_xiaozhi_tts_initializer_selects_each_registered_voice",
            ):
                assert f"tests/test_server_bridge.py::{native_voice_test}" in tests
            steps = job["steps"]
            restore = next(
                index for index, step in enumerate(steps)
                if step.get("name") == "Restore pinned Xiaozhi server fixture"
            )
            verify = next(
                index for index, step in enumerate(steps)
                if step.get("name") == "Verify bounded Mac voice, memory and fleet ownership"
            )
            assert restore < verify
            pinned = "d9c2e8c5d92627b670dec57d72a07a4226a410a3"
            assert pinned in steps[restore]["run"]
            assert "test \"$(git -C upstream/xiaozhi-esp32-server rev-parse HEAD)\"" in steps[restore]["run"]
        checkout = next(
            step for step in job["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["ref"] == (
            "${{ github.event.pull_request.head.sha || github.sha }}"
        )
        steps = job["steps"]
        assert steps[0] == checkout
        assert steps[1]["name"] == "Verify exact source commit under test"
        assert steps[2] == jobs["python-and-head-host"]["steps"][2]
        assert steps[2]["name"] == "Prevent partial repository trees"
        assert steps[2]["shell"] == "bash"



def test_sense_python_test_syntax_checked_before_expensive_setup():
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2]
         / ".github/workflows/host-verification.yml").read_text()
    )
    steps = workflow["jobs"]["python-and-head-host"]["steps"]
    compiled = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "Compile head test Python before expensive toolchain setup"
    )
    dependencies = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "Install Python and locked dependencies"
    )
    assert compiled < dependencies
    expected = [
        "laptop/src", "laptop/server/overlay", "laptop/server/*.py", "tests",
        "scripts", "firmware/head/*.py", "firmware/head/tests",
    ]
    assert steps[compiled]["working-directory"] == "code"
    assert steps[compiled]["run"].split() == ["python3", "-m", "compileall", "-q", *expected]
    lint = next(step for step in steps if step.get("name") == "Python lint")
    assert lint["working-directory"] == "code"
    assert lint["run"].split() == ["uv", "run", "--no-sync", "ruff", "check", *expected]


def test_tree_guard_rejects_missing_worktree_and_partial_index(tmp_path):
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2]
         / ".github/workflows/host-verification.yml").read_text()
    )
    guard = next(
        step["run"] for step in workflow["jobs"]["python-and-head-host"]["steps"]
        if step.get("name") == "Prevent partial repository trees"
    )
    counts = {
        "code/laptop/src": 53, "code/laptop/server": 7,
        "code/tests": 223, "code/scripts": 36,
        "code/firmware/head": 67, "code/firmware/body": 82,
        "code/firmware/room_station": 19, "code/firmware/dock": 2,
        "docs": 215, "agents": 245,
    }
    sentinels = (
        ".agent3d/fixture", ".github/fixture", ".gitignore", "AGENTS.md",
        "LICENSE", "README.md", "THIRD_PARTY_NOTICES.md",
        "code/firmware/body/include/BodyPins.h",
        "code/firmware/head/sense/config.h", "docs/hardware/full-feature-plan.json",
        "docs/records/verification.md", "code/laptop/src/desk_robot/handling.py",
    )
    for name in sentinels:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    for scope, count in counts.items():
        folder = tmp_path / scope
        folder.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            (folder / f"fixture-{index}").touch()
    unusual = tmp_path / "code/scripts/line\nbreak"
    unusual.touch()

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    def verify():
        return subprocess.run(
            ["bash", "-e", "-c", guard], cwd=tmp_path, capture_output=True, text=True,
        )

    git("init", "-q")
    git("add", ".")
    assert verify().returncode == 0
    for scope in ("code/firmware/room_station", "code/firmware/dock"):
        git("rm", "-r", "--cached", "-f", scope)
        partial = verify()
        assert partial.returncode != 0
        assert f"{scope} has only 0 tracked files" in partial.stdout
        git("add", scope)
    notice = tmp_path / "THIRD_PARTY_NOTICES.md"
    notice.unlink()
    git("rm", "--cached", "-f", "THIRD_PARTY_NOTICES.md")
    assert verify().returncode != 0
    notice.touch()
    git("add", "THIRD_PARTY_NOTICES.md")
    unusual.unlink()
    missing = verify()
    assert missing.returncode != 0
    assert "Missing tracked worktree path" in missing.stdout
    unusual.touch()
    git("rm", "-r", "--cached", "-f", "code/firmware/head")
    git("add", "code/firmware/head/sense/config.h")
    partial = verify()
    assert partial.returncode != 0
    assert "code/firmware/head has only 1 tracked files" in partial.stdout


def test_fast_lane_collects_private_memory_conversation_and_tool_fences():
    code = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load(
        (code.parent / ".github/workflows/host-verification.yml").read_text()
    )
    steps = workflow["jobs"]["mac-fast"]["steps"]
    command = next(
        step["run"] for step in steps
        if step.get("name") == "Verify bounded Mac voice, memory and fleet ownership"
    )
    # Resolve the actual unquoted shell globs, not substrings in step comments.
    args = shlex.split(command.replace(chr(92) + "\n", ""))
    assert args[:4] == ["uv", "run", "--no-sync", "pytest"]
    selected = set()
    for arg in args[4:]:
        if arg.startswith("tests/") and "::" not in arg:
            selected.update(code.glob(arg))
    required = set(code.glob("tests/test_memory_*.py"))
    required.update(code.glob("tests/test_conversation_*.py"))
    required.update(code / "tests" / name for name in (
        "test_api_motion_lifecycle.py",
        "test_episode_memory_mutation_race.py",
        "test_native_startup_memory_fence.py",
        "test_native_omni_consent_grant.py",
        "test_native_spoken_grant.py",
        "test_native_transcript_consent_grant.py",
        "test_tool_receipt_bridge_signature.py",
        "test_tool_receipt_operator_scope.py",
    ))
    assert required <= selected, sorted(str(p.relative_to(code)) for p in required - selected)
