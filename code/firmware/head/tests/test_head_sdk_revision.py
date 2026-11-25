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


@pytest.mark.parametrize("wrong_revision", [False, True])
def test_head_build_requires_locked_sdk_revision(tmp_path, wrong_revision):
    code = tmp_path / "code"
    scripts = code / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(CODE / "scripts/build_head.sh", scripts / "build_head.sh")
    build = code / "firmware/head/build/xiaozhi-sense/scripts"
    build.mkdir(parents=True)
    (build / "build.py").write_text('print("BUILD_RAN")\n')
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
    if wrong_revision:
        git(sdk, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "--allow-empty", "-qm", "different SDK")
    (code / "toolchain-lock.json").write_text(json.dumps({"esp_idf": {"commit": expected}}))
    python = tools / "sdk-bootstrap/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    result = subprocess.run(
        ["bash", str(scripts / "build_head.sh"), "--board", "sense"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if wrong_revision:
        assert result.returncode != 0
        assert "ESP-IDF revision" in result.stderr
        assert "SDK_EXPORTED" not in result.stdout
        assert "BUILD_RAN" not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert "SDK_EXPORTED" in result.stdout
        assert "BUILD_RAN" in result.stdout
