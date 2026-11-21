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
        assert concurrent["group"] == (
            "host-verification-" + lane + "-"
            + "${{ github.event.pull_request.number || github.ref }}"
        )
        assert "Verify exact source commit under test" in (
            str(job["steps"])
        )
        if lane == "mac-fast":
            tests = str(job["steps"])
            assert "tests/test_native_omni_xiaozhi.py" in tests
            assert "tests/test_voice_memory_reuse.py" in tests
        checkout = next(
            step for step in job["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["ref"] == (
            "${{ github.event.pull_request.head.sha || github.sha }}"
        )
