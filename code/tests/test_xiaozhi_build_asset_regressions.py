"""Execute the pinned Xiaozhi build/asset suites from the normal host gate.

The generated Sense build is ignored by Git. Use the pristine upstream fixture
that host CI already restores, and isolate upstream build.py's chdir in a child
process rather than importing it into the project pytest process.
"""

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

UPSTREAM = Path(__file__).resolve().parents[1] / "upstream/xiaozhi-esp32"
PIN = "c435f99a88066029ec2dbd2d758c8cc9d051565b"


@pytest.fixture(scope="module")
def upstream() -> Path:
    if not (UPSTREAM / ".git").exists():
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail("CI must restore the pinned Xiaozhi firmware fixture")
        pytest.skip("Restore the pinned Xiaozhi firmware fixture to run these suites")
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=UPSTREAM, text=True, timeout=10
    ).strip()
    assert head == PIN, f"Expected Xiaozhi {PIN}, found {head}"
    return UPSTREAM


@pytest.mark.parametrize(
    ("suite", "timeout"),
    [
        ("test_spiffs_assets.py", 120),
        ("test_build_default_assets.py", 120),
        ("test_build.py", 1200),
    ],
)
def test_pinned_xiaozhi_build_asset_suite(upstream: Path, suite: str, timeout: int) -> None:
    if suite == "test_spiffs_assets.py":
        missing = [name for name in ("numpy", "PIL", "packaging")
                   if importlib.util.find_spec(name) is None]
        assert not missing, f"SPIFFS suite dependencies unavailable: {missing}"
    script = upstream / "scripts/tests" / suite
    assert script.is_file(), f"Missing pinned upstream regression suite: {script}"
    result = subprocess.run(
        [sys.executable, "-B", str(script), "-q"],
        cwd=upstream,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert re.search(r"Ran [1-9][0-9]* tests?\b", result.stderr), output
    assert "skipped=" not in result.stderr, output
