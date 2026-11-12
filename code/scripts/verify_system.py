"""Run real source verification stages and emit an honest, local JSON receipt.

Unlike a GitHub PR badge, this command records actual subprocess exit codes.
It cannot certify a charger, printed assembly or live five robot acoustics.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODE = ROOT / "code"


def steps(suite: str, build: Path) -> list[tuple[str, list[str], Path, int]]:
    if suite not in ("python", "body", "wroom", "sense", "all"):
        raise ValueError("Unknown verification suite")
    jobs: list[tuple[str, list[str], Path, int]] = []
    if suite in ("python", "all"):
        jobs += [
            ("python-tests", [sys.executable, "-m", "pytest", "-q", "-ra",
                              "tests", "firmware/head/tests"], CODE, 900),
            ("python-lint", [sys.executable, "-m", "ruff", "check",
                             "laptop/src", "laptop/server/overlay",
                             "laptop/server", "tests", "scripts"], CODE, 180),
        ]
    if suite in ("body", "all"):
        jobs += [
            ("body-cmake", ["cmake", "-S", str(CODE / "firmware/body"),
                            "-B", str(build), "-DBODY_SANITIZERS=ON",
                            "-DCMAKE_BUILD_TYPE=Debug"], ROOT, 120),
            ("body-compile", ["cmake", "--build", str(build),
                              "--parallel", "2"], ROOT, 300),
            ("body-ctest", ["ctest", "--test-dir", str(build),
                            "--output-on-failure"], ROOT, 300),
        ]
    if suite in ("wroom", "all"):
        jobs += [
            (f"wroom-{env}", ["pio", "run", "-d",
                             str(CODE / "firmware/body"), "-e", env],
             ROOT, 900)
            for env in ("esp32_full", "esp32_stepper", "esp32dev")
        ]
    if suite in ("sense", "all"):
        jobs.append(
            ("sense-build", ["bash", str(CODE / "scripts/build_head.sh"),
                             "--board", "sense"], CODE, 2100)
        )
    return jobs


def run(name: str, argv: list[str], cwd: Path, timeout: int) -> dict:
    started = time.monotonic()
    result = {
        "name": name, "argv": argv, "cwd": str(cwd),
        "pass": False, "exit_code": None, "error": None,
        "elapsed_s": None, "output_tail": "",
    }
    try:
        response = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True,
            errors="replace", timeout=timeout, check=False,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        result["exit_code"] = response.returncode
        result["pass"] = response.returncode == 0
        result["output_tail"] = (response.stdout + "\n" + response.stderr)[-12000:]
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired) as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)[:300]
    result["elapsed_s"] = round(time.monotonic() - started, 2)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["python", "body", "wroom", "sense", "all"],
                        default="body")
    parser.add_argument("--report", type=Path,
                        default=Path("verification-result.json"))
    parser.add_argument("--build-dir", type=Path,
                        default=Path(tempfile.gettempdir()) / "desk-robot-body-verify")
    args = parser.parse_args()
    # A workspace or remote environment failing before pytest/cmake/Pio is
    # explicitly INCOMPLETE. Never manufacture a green CI result.
    records = []
    for name, argv, cwd, timeout in steps(args.suite, args.build_dir):
        record = run(name, argv, cwd, timeout)
        records.append(record)
        print(f"{name}: {'PASS' if record['pass'] else 'FAIL'} "
              f"(exit={record['exit_code']}, time={record['elapsed_s']}s)",
              flush=True)
        if not record["pass"]:
            print(record["output_tail"][-2000:] or record["error"], file=sys.stderr)
            break
    receipt = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "suite": args.suite, "stages": records,
        "source_suite_pass": bool(records) and len(records) == len(steps(
            args.suite, args.build_dir)) and all(r["pass"] for r in records),
        "physical_hardware_verified": False,
        "charging_verified": False,
        "print_fit_verified": False,
        "five_robot_acoustics_verified": False,
        "assembly_ready": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("Machine-readable verification: " + str(args.report))
    return 0 if receipt["source_suite_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
