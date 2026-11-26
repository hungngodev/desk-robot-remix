"""Check the order harness with real pytest processes and synthetic suites."""

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_safety_suite_order.py"
CORE = (
    "test_control.py",
    "test_b015_motion_authority.py",
    "test_stop_transport_failure.py",
    "test_runtime_voice_priority.py",
    "test_fleet.py",
)


def _run_probe(tmp_path, *, fail=False):
    script = tmp_path / "scripts" / SCRIPT.name
    script.parent.mkdir()
    script.write_bytes(SCRIPT.read_bytes())
    tests = tmp_path / "tests"
    tests.mkdir()
    files = sorted((*CORE, "test_memory_a.py", "test_memory_z.py"))
    for name in files:
        assertion = "    assert False\n" if fail and name == CORE[0] else ""
        (tests / name).write_text(
            "from pathlib import Path\n\n"
            "def test_probe():\n"
            "    with Path('execution.log').open('a') as stream:\n"
            f"        stream.write({name!r} + '\\n')\n"
            f"{assertion}"
        )
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTEST_ADDOPTS"] = "-k impossible_selection"
    result = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=45,
    )
    observed = (tmp_path / "execution.log").read_text().splitlines()
    return result, files, observed


def test_safety_order_harness_runs_all_suites_in_three_orders(tmp_path):
    result, files, observed = _run_probe(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    count = len(files)
    assert observed[:count] == files
    assert observed[count:2 * count] == files[::-1]
    assert sorted(observed[2 * count:]) == files
    assert observed[2 * count:] not in (files, files[::-1])


def test_safety_order_harness_does_not_mask_failed_permutations(tmp_path):
    result, files, observed = _run_probe(tmp_path, fail=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert len(observed) == 3 * len(files)
    assert result.stdout.count("pytest exit 1") == 3
