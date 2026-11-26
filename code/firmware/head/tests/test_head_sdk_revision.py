"""Exercise the real build wrapper against a synthetic local SDK checkout."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CODE = Path(__file__).resolve().parents[3]


def git(cwd, *args):
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


@pytest.fixture
def head_build(tmp_path):
    code = tmp_path / "code"
    scripts = code / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(CODE / "scripts/build_head.sh", scripts / "build_head.sh")
    build = code / "firmware/head/build/xiaozhi-sense"
    (build / "scripts").mkdir(parents=True)
    (build / "scripts/build.py").write_text('print("BUILD_RAN")\n')
    (code / "firmware/head/dependencies.lock").write_text("locked\n")
    tools = tmp_path / ".tools"
    sdk = tools / "esp-idf"
    sdk.mkdir(parents=True)
    (sdk / "export.sh").write_text('echo SDK_EXPORTED\n')
    git(sdk, "init", "-q")
    git(sdk, "add", "export.sh")
    git(sdk, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "locked SDK")
    expected = git(sdk, "rev-parse", "HEAD")
    (code / "toolchain-lock.json").write_text(json.dumps({"esp_idf": {"commit": expected}}))
    python = tools / "sdk-bootstrap/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    return code, build, sdk


def run_build(code):
    return subprocess.run(
        ["bash", str(code / "scripts/build_head.sh"), "--board", "sense"],
        capture_output=True, text=True, timeout=10, check=False,
    )


def assert_rejected(result, diagnostic):
    assert result.returncode != 0
    assert diagnostic in result.stderr
    assert "SDK_EXPORTED" not in result.stdout
    assert "BUILD_RAN" not in result.stdout


@pytest.mark.parametrize(
    "case", ["wrong_revision", "missing_git", "invalid_json", "missing_commit"]
)
def test_head_build_requires_locked_sdk_revision(head_build, case):
    code, _, sdk = head_build
    if case == "wrong_revision":
        git(sdk, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "--allow-empty", "-qm", "different SDK")
    elif case == "missing_git":
        shutil.rmtree(sdk / ".git")
    elif case == "invalid_json":
        (code / "toolchain-lock.json").write_text("{")
    elif case == "missing_commit":
        (code / "toolchain-lock.json").write_text('{"esp_idf": {}}')
    assert_rejected(run_build(code), "ESP-IDF revision")


@pytest.mark.parametrize("existing_lock", [False, True])
def test_head_build_uses_pinned_component_lock(head_build, existing_lock):
    code, build, _ = head_build
    canonical = code / "firmware/head/dependencies.lock"
    local = build / "dependencies.lock"
    if existing_lock:
        shutil.copyfile(canonical, local)
    result = run_build(code)
    assert result.returncode == 0, result.stderr
    assert "SDK_EXPORTED" in result.stdout
    assert "BUILD_RAN" in result.stdout
    assert local.read_bytes() == canonical.read_bytes()


def test_head_build_rejects_changed_component_lock_without_overwriting(head_build):
    code, build, _ = head_build
    local = build / "dependencies.lock"
    local.write_text("different\n")
    assert_rejected(run_build(code), "Build dependency lock differs")
    assert local.read_text() == "different\n"
    assert (code / "firmware/head/dependencies.lock").read_text() == "locked\n"


@pytest.mark.parametrize("existing_lock", [False, True])
def test_head_build_rejects_missing_canonical_component_lock(head_build, existing_lock):
    code, build, _ = head_build
    local = build / "dependencies.lock"
    if existing_lock:
        local.write_text("locked\n")
    (code / "firmware/head/dependencies.lock").unlink()
    assert_rejected(run_build(code), "dependencies.lock")
    assert local.exists() == existing_lock
