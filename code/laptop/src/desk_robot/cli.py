from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import shutil
import stat
from pathlib import Path

import httpx

from .config import load_settings, secret
from .conversation import conversation_turns
from .runtime import Runtime

ROOT = Path(__file__).resolve().parents[3]


def load_env(path: Path):
    """Read generated KEY=value secrets without executing shell content."""
    if path.is_file():
        for line in path.read_text().splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


def write_secrets(path: Path, settings, *, add_missing: bool = False) -> int:
    """Create credentials, or append new fleet identities without rotating any token."""
    names = {
        settings.coordinator_token_env,
        settings.tools_token_env,
        settings.speech_bridge_token_env,
        *(r.token_env for r in settings.robots),
    }
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in names):
        raise ValueError("Credential environment names must be valid identifiers")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
    if not add_missing:
        flags |= os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "a+", encoding="utf-8") as out:
        if not stat.S_ISREG(os.fstat(out.fileno()).st_mode):
            raise ValueError("Credentials must be a regular file")
        os.fchmod(out.fileno(), 0o600)
        out.seek(0)
        content = out.read()
        existing = {}
        for line in content.splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                if name in names:
                    if name in existing or not value.strip():
                        raise ValueError(f"Repair the duplicate or empty credential {name} first")
                    existing[name] = value
        missing = sorted(names - existing.keys())
        if missing:
            if not content:
                out.write("# Private LAN credentials; keep out of version control.\n")
            elif not content.endswith("\n"):
                out.write("\n")
            out.writelines(f"{name}={secrets.token_urlsafe(32)}\n" for name in missing)
        return len(missing)


async def demo(settings):
    if settings.mode != "simulation":
        raise ValueError("Demo requires the simulation config; it never talks to physical heads")
    runtime = Runtime(settings)
    try:
        robot = settings.robots[0].id
        await runtime.coordinator.operator_arm(robot)
        job = runtime.coordinator.pickup(robot, "key")
        await runtime.coordinator.tasks[job.id]
        transcript = await runtime.conversation.run(
            [r.id for r in settings.robots[:5]], "Take turns describing the desk"
        )
        return {
            "mode": "simulation",
            "physical_acceptance_pass": False,
            "pickup": job.data(),
            "conversation": transcript,
        }
    finally:
        await runtime.close()


async def request(args, settings):
    headers = {"Authorization": f"Bearer {secret(settings.coordinator_token_env)}"}
    async with httpx.AsyncClient(base_url=args.url, headers=headers, timeout=310) as client:
        if args.action == "status":
            result = await client.get(f"/v1/robots/{args.robot}/status")
        elif args.action == "job":
            result = await client.get(f"/v1/jobs/{args.job}")
        elif args.action.startswith("pet-"):
            action = args.action.removeprefix("pet-")
            endpoint = f"/v1/pet/{args.robot}"
            if action == "status":
                result = await client.get(endpoint)
            elif action == "quiet":
                result = await client.post(endpoint + "/quiet", json={"quiet": not args.off})
            else:
                result = await client.post(endpoint + "/" + action)
        elif args.action == "chat":
            turns = conversation_turns(args.robots, args.turns)
            result = await client.post(
                "/v1/conversation",
                json={"robot_ids": args.robots, "topic": args.topic, "utterances": turns},
            )
        else:
            payload = (
                {"command": args.command}
                if args.action == "move"
                else {"target": args.target}
                if args.action == "pickup"
                else {}
            )
            result = await client.post(f"/v1/robots/{args.robot}/{args.action}", json=payload)
        result.raise_for_status()
        return result.json()


def main():
    p = argparse.ArgumentParser(description="Desk robot setup and supervised controls")
    p.add_argument("--config", type=Path, default=ROOT / "config/robots.example.toml")
    p.add_argument("--secrets", type=Path, default=ROOT / "config/local.env")
    p.add_argument("--url", default="http://127.0.0.1:8765")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("demo", help="Run simulated pickup and a bounded group conversation")
    sub.add_parser("doctor", help="Check local prerequisites; no robot commands")
    credentials = sub.add_parser("secrets", help="Create private tokens; never prints their values")
    credentials.add_argument(
        "--add-missing",
        action="store_true",
        help="Append missing fleet tokens; preserve existing ones",
    )
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    for action in ("status", "enable", "stop", "move", "pickup"):
        part = sub.add_parser(action)
        part.add_argument("robot")
        if action == "move":
            part.add_argument("command", help='One bounded command, e.g. "drive 15 15 100"')
        if action == "pickup":
            part.add_argument("target", choices=["key", "candy"])
    for action in ("pet-status", "pet-start", "pet-pause", "pet-quiet"):
        part = sub.add_parser(action, help="Control and inspect proactive camera behavior")
        part.add_argument("robot")
        if action == "pet-quiet":
            part.add_argument("--off", action="store_true", help="Allow unsolicited speech again")
    job = sub.add_parser("job")
    job.add_argument("job")
    chat = sub.add_parser("chat")
    chat.add_argument("robots", nargs="+")
    chat.add_argument("--topic", default="Say hello to each other")
    chat.add_argument("--turns", type=int, default=None, choices=range(1, 11))
    args = p.parse_args()
    settings = load_settings(args.config)
    try:
        if args.action == "secrets":
            count = write_secrets(args.secrets, settings, add_missing=args.add_missing)
            print(f"Added {count} private credentials at {args.secrets}; values hidden")
            return
        load_env(args.secrets)
        if args.action == "serve":
            import uvicorn

            from .api import create_app

            uvicorn.run(create_app(settings), host=args.host, port=args.port)
            return
        if args.action == "doctor":
            result = {
                "mode": settings.mode,
                "python_env": True,
                "ollama_installed": shutil.which("ollama") is not None,
                "ffmpeg_installed": shutil.which("ffmpeg") is not None,
                "physical_test_status": "not run",
                "credentials_present": all(
                    os.environ.get(n)
                    for n in (settings.coordinator_token_env, settings.tools_token_env)
                ),
                "robots": [
                    {
                        "id": r.id,
                        "motion_enabled": r.motion_enabled,
                        "calibration_file_present": bool(r.calibration and r.calibration.is_file()),
                    }
                    for r in settings.robots
                ],
            }
        elif args.action == "demo":
            result = asyncio.run(demo(settings))
        else:
            result = asyncio.run(request(args, settings))
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        p.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
