"""Check the order harness with real pytest processes and synthetic suites."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_safety_suite_order.py"
CORE = (
    "test_control.py",
    "test_b015_motion_authority.py",
    "test_stop_transport_failure.py",
    "test_runtime_voice_priority.py",
    "test_fleet.py",
)


def _run_probe(tmp_path, *, failure_mode=None):
    script = tmp_path / "scripts" / SCRIPT.name
    script.parent.mkdir()
    script.write_bytes(SCRIPT.read_bytes())
    tests = tmp_path / "tests"
    tests.mkdir()
    files = sorted((*CORE, "test_memory_a.py", "test_memory_z.py"))
    for name in files:
        assertion = ""
        if name == CORE[0]:
            if failure_mode == "all":
                assertion = "    assert False\n"
            elif failure_mode == "first":
                assertion = (
                    "    entries = Path('execution.log').read_text().splitlines()\n"
                    f"    assert sum(line.split()[1] == {name!r} for line in entries) > 1\n"
                )
        (tests / name).write_text(
            "import os\n"
            "from pathlib import Path\n\n"
            "def test_probe():\n"
            "    with Path('execution.log').open('a') as stream:\n"
            f"        stream.write(str(os.getpid()) + ' ' + {name!r} + '\\n')\n"
            f"{assertion}"
        )
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTEST_ADDOPTS"] = "-k impossible_selection"
    result = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=45,
    )
    observed = [line.split() for line in (tmp_path / "execution.log").read_text().splitlines()]
    return result, files, observed


def _assert_execution_orders(files, observed):
    seeded = [
        "test_memory_z.py", "test_control.py", "test_memory_a.py", "test_fleet.py",
        "test_stop_transport_failure.py", "test_runtime_voice_priority.py",
        "test_b015_motion_authority.py",
    ]
    assert [name for _, name in observed] == files + files[::-1] + seeded
    count = len(files)
    process_ids = []
    for start in range(0, 3 * count, count):
        ids = {pid for pid, _ in observed[start:start + count]}
        assert len(ids) == 1
        process_ids.extend(ids)
    assert len(set(process_ids)) == 3


def test_safety_order_harness_runs_all_suites_in_three_orders(tmp_path):
    result, files, observed = _run_probe(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    _assert_execution_orders(files, observed)


@pytest.mark.parametrize("failure_mode,expected_codes", [
    ("all", [1, 1, 1]),
    ("first", [1, 0, 0]),
])
def test_safety_order_harness_does_not_mask_failed_permutations(
    tmp_path, failure_mode, expected_codes,
):
    result, files, observed = _run_probe(tmp_path, failure_mode=failure_mode)
    assert result.returncode == 1, result.stdout + result.stderr
    _assert_execution_orders(files, observed)
    assert [line for line in result.stdout.splitlines() if ": pytest exit " in line] == [
        f"{label}: pytest exit {code}"
        for label, code in zip(("baseline", "reverse", "seed=1461"), expected_codes, strict=True)
    ]
