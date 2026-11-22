"""Fast Mac CI must not be queued behind a long physical firmware build."""

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
            assert "tests/test_memory_duplicate_identity.py" in tests
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
        checkout = next(
            step for step in job["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["ref"] == (
            "${{ github.event.pull_request.head.sha || github.sha }}"
        )


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
    assert steps[compiled]["run"] == (
        "python3 -m compileall -q code/firmware/head/tests"
    )
