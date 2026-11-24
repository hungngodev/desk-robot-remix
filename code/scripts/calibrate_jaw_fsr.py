"""Read actual jaw FSR via the Mac API and propose conservative raw ADC limits.

This never drives the jaw or asserts a measured force in newtons. Operator
performs a small safe manual three-phase measurement with no power motion.
The generated calibration candidate is always marked measured=false until
camera, safe servo linkage and force limits are independently accepted.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import math
import os
import re
import stat
import statistics
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from desk_robot.calibration import Calibration
from desk_robot.grasp_feedback import _fresh_jaw_sequence, force_observation

_ROBOT_ID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")


def _safe_aux_endpoint(base_url: str, robot: str) -> str:
    """Never send an operator bearer token to unencrypted remote origins."""
    if type(robot) is not str or not _ROBOT_ID.fullmatch(robot):
        raise ValueError("Require exact configured robot identity")
    if (type(base_url) is not str or base_url != base_url.strip()
            or any(ord(ch) < 32 for ch in base_url)):
        raise ValueError("Invalid jaw calibration API origin")
    try:
        parsed = urlsplit(base_url)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid jaw calibration API origin") from exc
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Invalid jaw calibration API origin")
    if parsed.scheme == "http":
        try:
            loopback = (parsed.hostname == "localhost"
                        or ipaddress.ip_address(parsed.hostname).is_loopback)
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("Bearer token requires loopback HTTP or HTTPS")
    return base_url.rstrip("/") + f"/v1/robots/{robot}/aux"



def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Refuse contradictory operator-entered calibration provenance."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated jaw calibration JSON field: " + key)
        result[key] = value
    return result


def _reject_nonfinite_json_constant(token: str) -> None:
    raise ValueError("Nonfinite jaw calibration JSON constant: " + token)


def load_source_calibration(path: Path) -> dict:
    """Load the builder's existing geometry without last-key-wins JSON."""
    source = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_strict_json_object,
        parse_constant=_reject_nonfinite_json_constant,
    )
    if not isinstance(source, dict):
        raise ValueError("Calibration must be JSON object")
    return source


def propose_force_limits(phases: dict[str, list[tuple[int, int]]]) -> dict:
    """Use real independent ADS1115 sample sequence numbers, never duplicate HTTP frames."""
    if set(phases) != {"free", "contact", "upper"}:
        raise ValueError("Expected free, light-contact and operator-approved upper samples")
    history = []
    medians = {}
    spans = {}
    for name in ("free", "contact", "upper"):
        rows = phases[name]
        if not isinstance(rows, list) or len(rows) < 5:
            raise ValueError(f"Need at least five distinct {name} samples")
        if any(
            not isinstance(row, tuple) or len(row) != 2
            or type(row[0]) is not int or type(row[1]) is not int
            or not -32768 <= row[0] <= 32767
            or row[0] in (-32768, 32767)  # clipped ADC is not force evidence
            or not 1 <= row[1] <= 0xffffffff for row in rows
        ):
            raise ValueError(f"Untrusted {name} ADC records")
        history.extend(seq for _adc, seq in rows)
        values = [value for value, _seq in rows]
        medians[name] = statistics.median(values)
        spans[name] = max(values) - min(values)
    # Both the body firmware and live gripper use a nonzero uint32 sequence.
    # It wraps from 0xffffffff to 1 without making a fresh frame stale.
    # Reuse the same half-range ordering as the live safety-critical grasp;
    # duplicate, backward and reset/replayed samples remain unacceptable.
    if any(not _fresh_jaw_sequence(new, old)
           for old, new in zip(history, history[1:], strict=False)):
        raise ValueError("FSR readings must come from distinct forward hardware conversions")
    base, touch, upper = (medians[name] for name in ("free", "contact", "upper"))
    sign = 1 if touch > base else -1
    light = (touch - base) * sign
    heavy = (upper - base) * sign
    noise = max(spans.values())
    if (not all(math.isfinite(x) for x in (light, heavy, noise))
            or light < max(100, 4 * noise)
            or heavy < light + max(100, 2 * noise)):
        raise ValueError("Unstable FSR or insufficient separation from unloaded baseline")
    threshold = int(max(50, min(light * 0.55, 20000)))
    # Place the recommended stop below the observed upper hand-applied sample,
    # but never call it a calibrated mechanical force safety ceiling.
    ceiling = int(min(30000, heavy * 0.80))
    if ceiling <= threshold + max(50, noise):
        raise ValueError("Contact threshold and operator upper level overlap")
    return {
        "grip_force_sign": sign,
        "grip_force_delta_raw": threshold,
        "grip_force_limit_raw": ceiling,
        "grip_step_deg": 4,
        "unloaded_median_raw": base,
        "light_contact_delta_raw": light,
        "upper_applied_delta_raw": heavy,
        "adc_noise_span_raw": noise,
        "newtons_measured": False,
        "physical_force_safety_qualified": False,
        "manual_review_required": True,
    }



def write_jaw_candidate(target: Path, payload: dict) -> None:
    """Publish an unapproved trial exclusively as private regular evidence.

    Walk directories by descriptors so a user-controlled alias cannot
    redirect a safety calibration into another location. Allow macOS /var
    root-owned aliases only when their root-owned parent is not writable.
    """
    if (".." in target.parts or not isinstance(payload, dict)
            or payload.get("measured") is not False):
        raise ValueError("Jaw candidate path or unreviewed provenance invalid")
    contents = json.dumps(payload, indent=2, allow_nan=False) + "\n"
    absolute = target.absolute()
    directory_fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for segment in absolute.parts[1:-1]:
            entry = os.stat(segment, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(entry.st_mode):
                directory = os.fstat(directory_fd)
                if (entry.st_uid != 0 or directory.st_uid != 0
                        or stat.S_IMODE(directory.st_mode) & 0o022):
                    raise ValueError("Unsafe jaw candidate parent alias")
            elif not stat.S_ISDIR(entry.st_mode):
                raise ValueError("Jaw candidate parent is not a directory")
            flags = os.O_RDONLY | os.O_DIRECTORY
            if not stat.S_ISLNK(entry.st_mode):
                flags |= os.O_NOFOLLOW
            next_fd = os.open(segment, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        directory = os.fstat(directory_fd)
        if (directory.st_uid != os.geteuid()
                or stat.S_IMODE(directory.st_mode) & 0o022):
            raise ValueError("Jaw candidate parent must be owned and not writable by peers")
        created = False
        try:
            fd = os.open(
                absolute.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=directory_fd,
            )
            created = True
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    fd = -1
                    output.write(contents)
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                if fd >= 0:
                    os.close(fd)
        except BaseException:
            if created:
                os.unlink(absolute.name, dir_fd=directory_fd)
            raise
    finally:
        os.close(directory_fd)


async def capture(
    client: httpx.AsyncClient, *, base_url: str, robot: str,
    token: str, count: int = 8, interval: float = 0.18,
    boot_state: dict | None = None,
) -> list[tuple[int, int]]:
    if not 5 <= count <= 40 or not 0.12 <= interval <= 2:
        raise ValueError("Invalid real ADC sampling cadence")
    endpoint = _safe_aux_endpoint(base_url, robot)
    samples = []
    seen = None
    for _ in range(count * 5):
        started = time.monotonic()
        response = await client.get(
            endpoint,
            headers={"Authorization": f"Bearer {token}"}, timeout=3.0,
        )
        response.raise_for_status()
        payload = response.json()
        # The live API normally enforces this identity itself. The raw
        # calibration capture must still reject a misrouted or cached
        # response before it enters a measured per-robot candidate.
        if not isinstance(payload, dict) or payload.get("robot_id") != robot:
            raise ValueError("Jaw calibration robot identity mismatch")
        adc, seq = force_observation(payload)
        if boot_state is not None:
            # The real WROOM reports one boot identity and acquisition age.
            # A reboot between unloaded, light and upper force trials cannot
            # be disguised as a uint32 ADC sequence rollover.
            force = payload["force"]
            boot = force.get("boot_id")
            age = force.get("jaw_age_ms")
            if (type(boot) is not int or not 1 <= boot <= 0xffffffff
                    or type(age) is not int or not 0 <= age < 500):
                raise ValueError("Physical jaw calibration requires WROOM boot and jaw age")
            if force.get("jaw_valid") is not True:
                raise ValueError("Physical jaw calibration requires independent jaw validity")
            if "boot_id" in boot_state and boot_state["boot_id"] != boot:
                raise ValueError("WROOM reboot invalidated jaw force calibration")
            if age + max(0, int((time.monotonic() - started) * 1000)) >= 500:
                raise ValueError("Stale jaw force calibration sample in transport")
            boot_state["boot_id"] = boot
        if seen is None or _fresh_jaw_sequence(seq, seen):
            samples.append((adc, seq))
            seen = seq
        if len(samples) == count:
            return samples
        await asyncio.sleep(interval)
    raise RuntimeError("Not enough independent fresh ADS1115 jaw conversions")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8008")
    parser.add_argument("--robot", default="robot-01")
    parser.add_argument("--token-env", default="DESK_ROBOT_OPERATOR_TOKEN")
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=8)
    args = parser.parse_args()
    _safe_aux_endpoint(args.url, args.robot)
    token = os.getenv(args.token_env, "")
    if len(token) < 24:
        raise ValueError("Private operator token required")
    if not args.calibration.is_file():
        raise ValueError("Existing measured camera calibration JSON required")
    source = load_source_calibration(args.calibration)
    step = source.get("grip_step_deg", 4)
    if type(step) is not int or not 1 <= step <= 4:
        raise ValueError("Existing grip_step_deg must be an integer from 1 to 4")
    # Validate the same geometry that the real grasp runtime loads. The
    # documented unmeasured example remains a valid starting point.
    existing = Calibration.model_validate(source)
    if existing.simulation_only:
        raise ValueError("Simulation-only geometry cannot calibrate a physical jaw")
    readings = {}
    boot_state = {}  # shared WROOM identity across all three manual phases
    async with httpx.AsyncClient() as client:
        for key, step in (
            ("free", "Release the jaw sensor: no object and no applied pressure"),
            ("contact", "Apply a gentle representative object contact by hand"),
            ("upper", "Apply a stronger but non-damaging pressure by hand"),
        ):
            input(step + ". Press Enter to record samples. ")
            readings[key] = await capture(
                client, base_url=args.url, robot=args.robot,
                token=token, count=args.samples, boot_state=boot_state,
            )
    proposed = propose_force_limits(readings)
    # A manual FSR trial does not measure servo increments.
    proposed["grip_step_deg"] = step
    # Never silently enable autonomous grasping based on raw ADC alone.
    source.update({
        key: proposed[key] for key in (
            "grip_force_sign", "grip_force_delta_raw",
            "grip_force_limit_raw", "grip_step_deg",
        )
    })
    source["measured"] = False
    Calibration.model_validate(source)
    target = args.calibration.with_name(args.calibration.stem + ".jaw_candidate.json")
    write_jaw_candidate(target, source)
    print(json.dumps(proposed, indent=2))
    print(f"Candidate written to {target}; physical approval still required")


if __name__ == "__main__":
    asyncio.run(main())
