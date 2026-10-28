from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
from pathlib import Path

import httpx

from .config import load_settings, secret
from .runtime import Runtime

ROOT = Path(__file__).resolve().parents[3]


def load_env(path: Path):
    """Read generated KEY=value secrets without executing shell content."""
    if path.is_file():
        for line in path.read_text().splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


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
            [r.id for r in settings.robots[:2]], "Take turns describing the desk", 6
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
        elif args.action == "chat":
            result = await client.post(
                "/v1/conversation",
                json={"robot_ids": args.robots, "topic": args.topic, "utterances": args.turns},
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
    sub.add_parser("demo", help="Run simulated pickup and six conversation turns")
    sub.add_parser("doctor", help="Check local prerequisites; no robot commands")
    sub.add_parser("secrets", help="Create private tokens once; never prints their values")
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
    job = sub.add_parser("job")
    job.add_argument("job")
    chat = sub.add_parser("chat")
    chat.add_argument("robots", nargs=2)
    chat.add_argument("--topic", default="Say hello to each other")
    chat.add_argument("--turns", type=int, default=6, choices=range(1, 7))
    args = p.parse_args()
    settings = load_settings(args.config)
    try:
        if args.action == "secrets":
            names = {
                settings.coordinator_token_env,
                settings.tools_token_env,
                settings.speech_bridge_token_env,
                *(r.token_env for r in settings.robots),
            }
            args.secrets.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(args.secrets, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as out:
                out.write("# Private LAN credentials; keep out of version control.\n")
                out.writelines(f"{name}={secrets.token_urlsafe(32)}\n" for name in sorted(names))
            print(f"Created private credentials at {args.secrets}; values hidden")
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
