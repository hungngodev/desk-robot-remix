from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
from pathlib import Path

import httpx

from .config import RobotConfig, Settings, load_settings, read_private_env, secret
from .conversation import conversation_turns
from .runtime import Runtime
from .serial_device import require_local_serial_device

ROOT = Path(__file__).resolve().parents[3]


def load_env(path: Path) -> None:
    """Read generated KEY=value secrets without executing shell content."""
    for key, value in read_private_env(path).items():
        os.environ.setdefault(key, value)


def write_secrets(path: Path, settings: Settings, *, add_missing: bool = False) -> int:
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


def _configured_robot(settings: Settings, robot_id: str) -> RobotConfig:
    """Translate an operator lookup failure without changing the shared API."""
    try:
        return settings.robot(robot_id)
    except KeyError as exc:
        raise ValueError(
            "Unknown robot ID; check the configured IDs with desk-robot doctor"
        ) from exc


async def _inspect_body_and_model(
    http: httpx.AsyncClient, robot_id: str, robot: RobotConfig, selected_backend: str,
) -> dict[str, object]:
    status = await http.get(f"/v1/robots/{robot_id}/status", timeout=6)
    status.raise_for_status()
    body = status.json()
    if (not isinstance(body, dict) or body.get("robot_id") != robot_id
            or body.get("backend") != selected_backend
            or robot.motor_backend != selected_backend):
        raise ValueError("Real WROOM body or motor backend identity not confirmed")

    vision = await http.get(f"/v1/pet/{robot_id}/vision-status", timeout=6)
    vision.raise_for_status()
    model = vision.json()
    if not isinstance(model, dict) or model.get("robot_id") != robot_id:
        raise ValueError("Mac vision owner returned wrong robot identity")

    return model


async def _inspect_frame(http: httpx.AsyncClient, robot_id: str) -> tuple[int, int]:
    frame = await http.get(f"/v1/pet/{robot_id}/omni-frame", timeout=8)
    frame.raise_for_status()
    jpeg = frame.content
    headers = frame.headers
    if (headers.get("x-desk-robot-id") != robot_id
            or not headers.get("content-type", "").startswith("image/jpeg")
            or not 10 <= len(jpeg) <= 1_000_000
            or not jpeg.startswith(b"\xff\xd8")
            or not jpeg.endswith(b"\xff\xd9")):
        raise ValueError("Real live XIAO JPEG identity or format invalid")
    try:
        age = int(headers["x-desk-camera-age-ms"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Live XIAO frame age missing") from exc
    if not 0 <= age <= 1000:
        raise ValueError("Live XIAO frame expired")
    try:
        receipt = int(headers["x-desk-camera-receipt-us"])
        motion = int(headers["x-desk-frame-motion-ppm"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Real camera provenance metadata missing") from exc
    if receipt <= 0 or not 0 <= motion <= 1_000_000:
        raise ValueError("Real camera receipt or motion metadata invalid")

    return len(jpeg), age


async def _inspect_context(http: httpx.AsyncClient, robot_id: str) -> tuple[int, int]:
    context = await http.get(
        f"/v1/pet/{robot_id}/interaction-context", timeout=6
    )
    context.raise_for_status()
    evidence = context.json()
    timeline = evidence.get("current_interaction_timeline")
    if (evidence.get("robot_id") != robot_id
            or evidence.get("raw_media_included") is not False
            or evidence.get("persistent_memory_included") is not False
            or not isinstance(timeline, list)
            or not isinstance(evidence.get("model_context"), str)
            or len(evidence["model_context"]) > 400
            or evidence.get("model_context_untrusted_not_instructions")
                is not True):
        raise ValueError("Multimodal source context contract invalid")
    return len(timeline), len(evidence["model_context"])


async def _inspect_look(http: httpx.AsyncClient, robot_id: str) -> dict[str, object]:
    response = await http.post(
        f"/v1/pet/{robot_id}/look",
        json={"question": "What object is visible directly in front of me?"},
        timeout=23,
    )
    response.raise_for_status()
    seen = response.json()
    if (seen.get("robot_id") != robot_id
            or seen.get("source") != "authenticated_xiao_camera_and_local_vlm"
            or type(seen.get("frames_used")) is not int
            or seen["frames_used"] < 1
            or seen.get("motor_authorized") is not False
            or seen.get("charging_authorized") is not False):
        raise ValueError("Local VLM evidence or actuator boundary invalid")
    return {"live_tool_tested": True, "visual_answer": seen.get("answer", "")[:300]}


async def _inspect_media(
    http: httpx.AsyncClient, robot_id: str, robot: RobotConfig,
    selected_backend: str, *, look: bool,
) -> dict[str, object]:
    model = await _inspect_body_and_model(http, robot_id, robot, selected_backend)
    jpeg_bytes, age = await _inspect_frame(http, robot_id)
    context_events, context_chars = await _inspect_context(http, robot_id)
    result: dict[str, object] = {
        "robot_id": robot_id,
        "real_head_status_received": True,
        "xiao_jpeg_received": True,
        "xiao_jpeg_bytes": jpeg_bytes,
        "mac_frame_receipt_age_ms": age,
        "camera_model_configured": model.get("multimodal_model_configured") is True,
        "live_context_events": context_events,
        "live_context_chars": context_chars,
        "live_tool_tested": False,
        "motor_armed_or_charging_verified": False,
        "camera_exposure_timing_physically_verified": False,
    }
    if look:
        result.update(await _inspect_look(http, robot_id))
    return result


async def inspect_live_media(settings: Settings, robot_id: str, *, look: bool = False,
                             client: httpx.AsyncClient | None = None,
                             base_url: str = "http://127.0.0.1:8765") -> dict[str, object]:
    """Read-only end-to-end Mac/head/vision preflight, with NO actuator permit."""
    if settings.mode != "hardware" or not settings.voice_vision_tools_enabled:
        raise ValueError("Real XIAO camera preflight requires hardware vision consent")
    robot = _configured_robot(settings, robot_id)
    if not robot.device_id:
        raise ValueError("A configured real Xiaozhi head device ID is required")
    selected_backend = robot.motor_backend
    if selected_backend not in ("stepper_28byj48", "dc_pwm_guarded"):
        raise ValueError("Live WROOM diagnosis requires a verified motor backend")

    if client is not None:
        return await _inspect_media(client, robot_id, robot, selected_backend, look=look)
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {secret(settings.tools_token_env)}"},
        # The authenticated local Mac endpoint must ignore ambient proxies.
        trust_env=False,
        timeout=8,
    ) as http:
        return await _inspect_media(http, robot_id, robot, selected_backend, look=look)


async def demo(settings: Settings) -> dict[str, object]:
    if settings.mode != "simulation":
        raise ValueError("Demo requires the simulation config; it never talks to physical heads")
    runtime = await Runtime.create(settings)
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


async def _request_live_read(
    client: httpx.AsyncClient, args: argparse.Namespace, settings: Settings,
) -> httpx.Response:
    if settings.mode != "hardware":
        raise ValueError("Live camera tools require a physical XIAO head")
    _configured_robot(settings, args.robot)  # Validate configured robot identity.
    if args.action in ("look", "situation") and not settings.voice_vision_tools_enabled:
        raise ValueError("Live vision consent is disabled in local configuration")
    if args.action == "look":
        question = args.question.strip()
        if not 3 <= len(question) <= 280:
            raise ValueError("Visual question must have 3 to 280 characters")
        result = await client.post(
            f"/v1/pet/{args.robot}/look",
            json={"question": question}, timeout=23,
        )
    elif args.action == "situation":
        result = await client.get(
            f"/v1/pet/{args.robot}/interaction-context", timeout=8,
        )
    elif args.action == "power":
        result = await client.get(
            f"/v1/pet/{args.robot}/power-status", timeout=8,
        )
    else:
        result = await client.get(
            f"/v1/pet/{args.robot}/vision-status", timeout=8,
        )
    return result


async def request(args: argparse.Namespace, settings: Settings) -> object:
    headers = {"Authorization": f"Bearer {secret(settings.coordinator_token_env)}"}
    # Explicit Mac API bearer credentials must not transit env HTTP proxies.
    async with httpx.AsyncClient(
        base_url=args.url, headers=headers, timeout=310, trust_env=False,
    ) as client:
        if settings.mode == "simulation":
            # The default URL is shared by both modes. Verify before any robot
            # request, then bind subsequent requests to simulation at ingress.
            health = await client.get("/v1/health", timeout=5)
            health.raise_for_status()
            state = health.json()
            if (not isinstance(state, dict) or state.get("mode") != "simulation"
                    or state.get("runtime_ready") is not True):
                raise ValueError("Simulation CLI requires a ready simulation server")
            client.headers["X-Desk-Robot-Mode"] = "simulation"
        if args.action == "status":
            result = await client.get(f"/v1/robots/{args.robot}/status")
        elif args.action == "job":
            result = await client.get(f"/v1/jobs/{args.job}")
        elif args.action in ("look", "situation", "vision", "power"):
            result = await _request_live_read(client, args, settings)
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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Desk robot setup and supervised controls")
    p.add_argument("--config", type=Path, default=ROOT / "config/robots.example.toml")
    p.add_argument("--secrets", type=Path,
                   help="Private credentials file (default: local.env beside --config)")
    p.add_argument("--url", default="http://127.0.0.1:8765")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("demo", help="Run simulated pickup and a bounded group conversation")
    doctor = sub.add_parser("doctor", help="Check local and optional live read-only prerequisites")
    doctor.add_argument("--live", action="store_true",
                        help="Verify real XIAO JPEG and Mac multimodal context")
    doctor.add_argument("--look", action="store_true",
                        help="Also invoke the read-only local vision tool")
    doctor.add_argument("--robot", default=None,
                        help="Physical robot ID, default first configured")
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
    for action in ("look", "situation", "vision", "power"):
        part = sub.add_parser(action, help=(
            "Ask the real XIAO camera and local vision model"
            if action == "look" else
            "Inspect recent private transient sensor, tool and voice context"
            if action == "situation" else
            "Read raw WROOM fuel gauge data, never verified charging"
            if action == "power" else
            "Read actual Mac camera and model diagnostics"
        ))
        part.add_argument("robot")
        if action == "look":
            part.add_argument("question")
    sub.add_parser("job").add_argument("job")
    chat = sub.add_parser("chat")
    chat.add_argument("robots", nargs="+")
    chat.add_argument("--topic", default="Say hello to each other")
    chat.add_argument("--turns", type=int, default=None, choices=range(1, 11))
    return p


def _doctor_room_station(settings: Settings) -> dict[str, str]:
    if not settings.room_station_enabled:
        return {"status": "disabled"}
    port = settings.room_station_port
    try:
        if port is None:
            raise ValueError("Room station port is not configured")
        require_local_serial_device(port)
    except ValueError:
        return {
            "status": "device_unavailable",
            "next_action": (
                "Connect the room station by USB and set room_station_port to its direct "
                "/dev/ device, or disable the optional station and rerun doctor."
            ),
        }
    return {"status": "device_present_not_verified"}


def _doctor_report(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    result: dict[str, object] = {
        "mode": settings.mode,
        "python_env": True,
        "ollama_installed": shutil.which("ollama") is not None,
        "ffmpeg_installed": shutil.which("ffmpeg") is not None,
        "physical_test_status": "not run",
        "room_station": _doctor_room_station(settings),
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
    if args.live or args.look:
        result["live_media"] = asyncio.run(inspect_live_media(
            settings, args.robot or settings.robots[0].id,
            look=args.look, base_url=args.url,
        ))
    return result


def _degraded_status(value: object, robot_id: str) -> bool:
    if not isinstance(value, dict) or value.get("robot_id") != robot_id:
        return False
    health = value.get("health")
    return isinstance(health, dict) and health.get("state") == "degraded"


def main() -> None:
    p = _build_parser()
    args = p.parse_args()
    try:
        settings = load_settings(args.config)
        if args.secrets is None:
            args.secrets = args.config.resolve().with_name("local.env")
        if args.action == "secrets":
            count = write_secrets(args.secrets, settings, add_missing=args.add_missing)
            print(f"Added {count} private credentials at {args.secrets}; values hidden")
            return
        load_env(args.secrets)
        if args.action == "serve":
            import uvicorn

            from .api import create_app

            # Bound request draining so a stuck API call cannot indefinitely
            # postpone lifespan cleanup and its independent WROOM STOP attempts.
            uvicorn.run(
                create_app(settings), host=args.host, port=args.port,
                timeout_graceful_shutdown=1,
            )
            return
        if args.action == "doctor":
            result = _doctor_report(args, settings)
        elif args.action == "demo":
            result = asyncio.run(demo(settings))
        else:
            result = asyncio.run(request(args, settings))
        print(json.dumps(result, indent=2))
        if args.action == "status" and _degraded_status(result, args.robot):
            p.exit(1)
    except httpx.HTTPStatusError as exc:
        if args.action == "status" and exc.response.status_code == 503:
            try:
                result = exc.response.json()
            except ValueError:
                result = None
            if _degraded_status(result, args.robot):
                print(json.dumps(result, indent=2))
                p.exit(1)
        p.exit(1, f"{exc}\n")
    except sqlite3.Error:
        p.exit(1, "Private memory database unavailable. Check memory_dir permissions, "
               "free space and database integrity; preserve existing memory files.\n")
    except (ValueError, OSError, httpx.HTTPError) as exc:
        p.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
