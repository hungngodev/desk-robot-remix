"""Run core safety suites in fresh pytest processes with reproducible file orders."""

import os
import random
import shlex
import subprocess
import sys
from pathlib import Path

CORE = (
    "test_control.py",
    "test_b015_motion_authority.py",
    "test_stop_transport_failure.py",
    "test_runtime_voice_priority.py",
    "test_fleet.py",
)
SEED = 1461


def suite_orders(code: Path) -> tuple[tuple[str, list[str]], ...]:
    tests = code / "tests"
    memory = sorted(tests.glob("test_memory_*.py"))
    files = [tests / name for name in CORE] + memory
    if not memory or not all(path.is_file() for path in files):
        raise ValueError("Missing core safety or memory suites")
    baseline = [path.relative_to(code).as_posix() for path in sorted(files)]
    shuffled = baseline.copy()
    random.Random(SEED).shuffle(shuffled)
    return ("baseline", baseline), ("reverse", baseline[::-1]), (f"seed={SEED}", shuffled)


def verify(code: Path) -> int:
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    failed = False
    for label, files in suite_orders(code):
        command = [sys.executable, "-m", "pytest", "-q", "-ra", "-o", "addopts=", *files]
        print(f"{label}: {shlex.join(command)}", flush=True)
        result = subprocess.run(command, cwd=code, env=env, check=False)
        print(f"{label}: pytest exit {result.returncode}", flush=True)
        failed |= result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(verify(Path(__file__).resolve().parents[1]))
