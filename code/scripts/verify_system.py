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
    if suite not in ("python", "body", "wroom", "sense", "room", "dock", "all"):
        raise ValueError("Unknown verification suite")
    jobs: list[tuple[str, list[str], Path, int]] = []
    if suite in ("python", "all"):
        jobs += [
            ("python-tests", [sys.executable, "-m", "pytest", "-q", "-ra",
                              "tests", "firmware/head/tests"], CODE, 900),
            ("python-lint", [sys.executable, "-m", "ruff", "check",
                             "laptop/src", "laptop/server/overlay",
                             "laptop/server", "tests", "scripts",
                             # Match CI's explicitly pinned head overlay Python
                             # targets, without recursively linting vendor C++.
                             "firmware/head/install_overlay.py",
                             "firmware/head/private_config.py"], CODE, 180),
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
            for env in (
                "esp32_full", "esp32_full_pulse_reversed_lab",
                "esp32_full_interaction_lab", "esp32_full_haptic_lab",
                "esp32_dc_full", "esp32_dc_watchdog_lab",
                "esp32_dc_integrated_lab", "esp32_servo_center_bench",
                "esp32_stepper", "esp32dev", "esp32_vl53l0x_bench",
            )
        ]
    if suite in ("sense", "all"):
        jobs.append(
            ("sense-build", ["bash", str(CODE / "scripts/build_head.sh"),
                             "--board", "sense"], CODE, 2100)
        )
    if suite in ("room", "all"):
        jobs += [
            (f"room-{env}", ["pio", "run", "-d",
                             str(CODE / "firmware/room_station"), "-e", env],
             ROOT, 900)
            for env in ("feather_nrf52840_room_bench",
                        "feather_nrf52840_room_full")
        ]
    if suite in ("dock", "all"):
        jobs += [
            (f"dock-{num:02d}", ["pio", "run", "-d",
                                str(CODE / "firmware/dock"), "-e",
                                f"bench_nano_dock_{num:02d}"], ROOT, 600)
            for num in range(1, 6)
        ]
    return jobs


def required_upstream_fixture_errors() -> list[str]:
    """Validate pinned test fixtures without cloning or modifying a checkout.

    A fresh local clone must never turn missing test prerequisites into an
    ambiguous source regression. The user may restore the exact pinned
    sources with the existing scripts/restore_upstreams.py command.
    """
    lock = json.loads((CODE / "upstream-lock.json").read_text(encoding="utf-8"))
    sources = {
        source["name"]: source for source in lock["repositories"]
    }
    missing = []
    for name in ("xiaozhi-esp32", "xiaozhi-esp32-server"):
        source = sources.get(name)
        if not isinstance(source, dict):
            missing.append(f"{name}: absent from upstream lock")
            continue
        directory = CODE / source["path"]
        if not directory.is_dir():
            missing.append(f"{name}: pinned source directory absent")
            continue
        try:
            actual = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=directory, text=True,
                stderr=subprocess.DEVNULL, timeout=10,
            ).strip()
        except (OSError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired):
            actual = ""
        if actual != source["commit"]:
            missing.append(f"{name}: expected locked SHA {source['commit']}")
            continue
        try:
            modifications = subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=directory, text=True, stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired):
            missing.append(f"{name}: cannot inspect tracked fixture changes")
            continue
        if modifications.strip():
            missing.append(f"{name}: tracked fixture files differ from pinned commit")
    return missing


def run(name: str, argv: list[str], cwd: Path, timeout: int) -> dict:
    started = time.monotonic()
    result = {
        "name": name, "argv": argv, "cwd": str(cwd),
        "pass": False, "exit_code": None, "error": None,
        "elapsed_s": None, "output_tail": "",
    }
    if name == "python-tests":
        try:
            fixture_errors = required_upstream_fixture_errors()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            fixture_errors = ["upstream lock unreadable: " + str(exc)[:160]]
        if fixture_errors:
            result["error"] = (
                "INCOMPLETE: " + "; ".join(fixture_errors) +
                ". Restore exact pinned test fixtures with "
                "python scripts/restore_upstreams.py, then retry."
            )
            result["elapsed_s"] = round(time.monotonic() - started, 2)
            return result
    try:
        response = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True,
            errors="replace", timeout=timeout, check=False,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        result["exit_code"] = response.returncode
        result["pass"] = response.returncode == 0
        result["output_tail"] = (response.stdout + "\n" + response.stderr)[-12000:]
    except subprocess.TimeoutExpired as exc:
        # subprocess may supply partial output as BYTES even with text=True.
        # Keep bounded compiler/test context so timeouts are diagnosable.
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        result["output_tail"] = (stdout + "\n" + stderr)[-12000:]
        result["error"] = type(exc).__name__ + ": " + str(exc)[:300]
    except (FileNotFoundError, PermissionError) as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)[:300]
    result["elapsed_s"] = round(time.monotonic() - started, 2)
    return result


def source_snapshot() -> dict:
    """Identify the exact tracked checkout used by an executed verification.

    Pull request CI may check out a synthetic merge commit rather than the
    PR branch head. Record what actually ran, never infer a different SHA.
    """
    snapshot = {"sha": None, "tracked_clean": None,
                "root_tree_intact": False, "error": None}
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            timeout=10, stderr=subprocess.DEVNULL,
        ).strip()
        if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
            raise ValueError("Git did not return a full commit SHA")
        changes = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT, text=True, timeout=10, stderr=subprocess.DEVNULL,
        )
        snapshot["sha"] = sha
        snapshot["tracked_clean"] = not bool(changes.strip())
        tracked = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT, text=True, timeout=10,
            stderr=subprocess.DEVNULL,
        ).split("\0")
        if tracked and tracked[-1] == "":
            tracked.pop()
        # Git's index includes skip-worktree paths in sparse checkouts.
        # The full worktree must contain every tracked file, not merely 400
        # index entries and a handful of sentinels. Broken symlink entries
        # count as present Git objects; missing files and sparse directories
        # do not. NUL framing handles unusual Git filenames without ambiguity.
        tracked_present = all(
            (ROOT / name).exists() or (ROOT / name).is_symlink()
            for name in tracked
        )
        # Mirror CI's root sentinels and 400-file conservative floor.
        # A valid-looking commit can still refer to a truncated Git tree.
        directories = (".agent3d", ".github", "code", "docs")
        files = (".gitignore", "AGENTS.md", "LICENSE", "README.md",
                 "code/firmware/body/include/BodyPins.h",
                 "code/firmware/head/sense/config.h",
                 "code/laptop/src/desk_robot/handling.py",
                 "docs/hardware/full-feature-plan.json",
                 "docs/records/verification.md")
        snapshot["root_tree_intact"] = (
            len(tracked) >= 400
            and tracked_present
            and all((ROOT / name).is_dir() for name in directories)
            and all((ROOT / name).is_file() for name in files)
        )
    except (OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, ValueError) as exc:
        snapshot["error"] = type(exc).__name__ + ": " + str(exc)[:200]
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["python", "body", "wroom", "sense", "room", "dock", "all"],
                        default="body")
    parser.add_argument("--report", type=Path,
                        default=Path("verification-result.json"))
    parser.add_argument("--build-dir", type=Path,
                        default=Path(tempfile.gettempdir()) / "desk-robot-body-verify")
    args = parser.parse_args()
    # Verification receipts are immutable evidence, not scratch output.
    # Refuse even a dangling symlink before starting expensive checks.
    if args.report.exists() or args.report.is_symlink():
        parser.error("Verification report already exists; choose an unused path")
    checkout_before = source_snapshot()
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
    checkout_after = source_snapshot()
    clean_same_commit = (
        checkout_before["sha"] is not None
        and checkout_before == checkout_after
        and checkout_before["tracked_clean"] is True
        and checkout_before["root_tree_intact"] is True
    )
    receipt = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "checkout_before": checkout_before,
        "checkout_after": checkout_after,
        "same_commit_clean_checkout": clean_same_commit,
        "suite": args.suite, "stages": records,
        "source_suite_pass": bool(records) and len(records) == len(steps(
            args.suite, args.build_dir)) and all(r["pass"] for r in records),
        "physical_hardware_verified": False,
        # Seeed XIAO ESP32S3 Sense SD connector shares GPIO7/8/9 with
        # selected speaker and optional RGB. A firmware build cannot prove
        # J3 has been physically isolated and verified by continuity meter.
        "sense_sd_j3_isolation_verified": False,
        # Seeed requires an isolated external source at XIAO 5V/VBUS.
        # A USB flash test cannot certify safe simultaneous laptop/boost power.
        "sense_vbus_power_path_verified": False,
        "charging_verified": False,
        "print_fit_verified": False,
        "five_robot_acoustics_verified": False,
        # Model weights, firmware and source-level CAD reuse do not grant
        # commercial rights to SMARS CC BY-NC-SA chassis/forklift derivatives.
        "commercial_cad_rights_verified": False,
        "commercial_batch_release_ready": False,
        "assembly_ready": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive creation also closes the race after the initial check.
        with args.report.open("x", encoding="utf-8") as report_file:
            report_file.write(json.dumps(receipt, indent=2) + "\n")
    except FileExistsError as exc:
        raise ValueError(
            "Verification report already exists; choose an unused path"
        ) from exc
    print("Machine-readable verification: " + str(args.report))
    return 0 if receipt["source_suite_pass"] and clean_same_commit else 1


if __name__ == "__main__":
    raise SystemExit(main())
