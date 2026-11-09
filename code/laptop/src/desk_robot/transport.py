from __future__ import annotations

import asyncio
import re
from typing import Protocol

import httpx

from .config import RobotConfig, secret


class HeadError(RuntimeError):
    """A failed request may already have actuated: never automatically retry it."""


class Head(Protocol):
    async def command(self, command: str) -> dict: ...
    async def status(self) -> dict: ...
    async def snapshot(self) -> bytes: ...
    async def emote(self, emotion: str) -> dict: ...


def validate_command(command: str) -> str:
    if (
        not isinstance(command, str)
        or len(command) > 95
        or not re.fullmatch(r"[a-z0-9 -]+", command)
    ):
        raise ValueError("Invalid command")
    tokens = command.split(" ")
    op = tokens[0]
    if op in {"ping", "status", "arm", "disarm", "stop", "keepalive"} and len(tokens) == 1:
        return op
    if op == "drive" and len(tokens) == 4:
        values = tokens[1:]
        if not all(re.fullmatch(r"-?[0-9]{1,3}", x) for x in values):
            raise ValueError("drive arguments must be integers")
        left, right, duration = map(int, values)
        if -40 <= left <= 40 and -40 <= right <= 40 and 1 <= duration <= 250:
            return op
    if op in {"lift", "grip"} and len(tokens) == 2 and tokens[1].isdigit():
        if 60 <= int(tokens[1]) <= 120:
            return op
    raise ValueError("Command exceeds conservative bounds")


def expected_ack(command: str) -> str:
    op = validate_command(command)
    args = command.split()[1:]
    if op == "drive":
        left, right, ms = map(int, args)
        return f"OK drive left={left} right={right} ms={ms}"
    if op in {"lift", "grip"}:
        return f"OK {op} angle={int(args[0])}"
    return f"OK {op}"


class HttpHead:
    def __init__(self, config: RobotConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client
        self.lock = asyncio.Lock()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = await self.client.request(
                method,
                self.config.head_url.rstrip("/") + path,
                headers={"Authorization": f"Bearer {secret(self.config.token_env)}"},
                timeout=httpx.Timeout(3, connect=1),
                **kwargs,
            )
            response.raise_for_status()
            return response
        except (httpx.HTTPError, ValueError) as exc:
            raise HeadError(f"{self.config.id}: head request failed; no retry: {exc}") from exc

    async def command(self, command: str) -> dict:
        expected = expected_ack(command)
        async with self.lock:
            response = await self._request("POST", "/api/command", json={"command": command})
            data = response.json()
            reply = data.get("reply", "")
            if not data.get("ok") or data.get("robot_id") != self.config.id or reply != expected:
                raise HeadError("Unmatched or failed command ACK; movement not retried")
            return data

    async def status(self) -> dict:
        async with self.lock:
            data = (await self._request("GET", "/api/status")).json()
            if data.get("robot_id") != self.config.id:
                raise HeadError("Status robot identity mismatch")
            return data

    async def emote(self, emotion: str) -> dict:
        if emotion not in {"neutral", "happy", "thinking", "surprised", "sad", "sleepy"}:
            raise ValueError("Unsupported robot expression")
        data = (await self._request("POST", "/api/emotion", json={"emotion": emotion})).json()
        if not data.get("ok") or data.get("robot_id") != self.config.id:
            raise HeadError("Unmatched emotion acknowledgement")
        return data

    async def snapshot(self) -> bytes:
        # Camera may take longer than a keepalive transaction; head itself serializes UART/camera.
        response = await self._request("GET", "/api/camera.jpg")
        if len(response.content) > 4_000_000 or not response.content.startswith(b"\xff\xd8"):
            raise HeadError("Camera did not return a bounded JPEG")
        return response.content
