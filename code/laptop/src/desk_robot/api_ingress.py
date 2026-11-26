"""Bound and authenticate Mac API ingress before FastAPI parses JSON."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import secrets
from collections.abc import Callable

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import RobotConfig, Settings

MAX_REQUEST_BYTES = 64 * 1024
BODY_TIMEOUT_SECONDS = 5.0
MAX_JSON_DEPTH = 64


def require_configured_robot(settings: Settings, robot_id: str) -> RobotConfig:
    """Resolve an exact configured identity before touching runtime state."""
    try:
        return settings.robot(robot_id)
    except KeyError as exc:
        raise HTTPException(404, "Robot not found") from exc


def _safe_json_body(body: bytearray) -> bool:
    """Bound parsed values before routing; do not echo unsafe input."""
    try:
        value = json.loads(body)
        pending = [(value, 0)]
        while pending:
            value, depth = pending.pop()
            if isinstance(value, (dict, list)):
                if depth >= MAX_JSON_DEPTH:
                    return False
                if isinstance(value, dict):
                    for key in value:
                        key.encode("utf-8")
                    pending.extend((item, depth + 1) for item in value.values())
                else:
                    pending.extend((item, depth + 1) for item in value)
            elif isinstance(value, str):
                value.encode("utf-8")
            elif isinstance(value, float) and not math.isfinite(value):
                return False
    except json.JSONDecodeError:
        # Preserve FastAPI's existing syntax-error response.
        return True
    except (ValueError, RecursionError):
        return False
    return True


def token_matches(credential: str, token: str) -> bool:
    """Compare fixed-size digests, including when secret lengths differ."""
    return secrets.compare_digest(
        hashlib.sha256(credential.encode("utf-8")).digest(),
        hashlib.sha256(token.encode("utf-8")).digest(),
    )


def authorized_token(credential: str, operator: str, tool: str) -> bool:
    # Both comparisons must execute for either role.
    return token_matches(credential, operator) | token_matches(credential, tool)


class APIIngress:
    def __init__(self, app: ASGIApp, tokens: Callable[[], tuple[str, str]],
                 mode: str | None = None):
        self.app = app
        self.tokens = tokens
        self.mode = mode

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/v1/"):
            await self.app(scope, receive, send)
            return

        async def reject(status: int, detail: str) -> None:
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)

        headers: dict[bytes, list[bytes]] = {}
        for name, value in scope["headers"]:
            headers.setdefault(name.lower(), []).append(value)
        auth = headers.get(b"authorization", [])
        if len(auth) != 1 or not auth[0].isascii():
            await reject(401, "A valid private token is required")
            return
        scheme, _, credential = auth[0].decode("ascii").partition(" ")
        if (scheme.lower() != "bearer" or not credential
                or not authorized_token(credential, *self.tokens())):
            await reject(401, "A valid private token is required")
            return

        requested_mode = headers.get(b"x-desk-robot-mode")
        if requested_mode is not None and (
            self.mode not in ("simulation", "hardware")
            or requested_mode != [self.mode.encode("ascii")]
        ):
            await reject(409, "Request runtime mode does not match server")
            return

        for name, values in headers.items():
            if (name in {b"content-length", b"content-type", b"content-encoding"}
                    or name.startswith(b"x-desk-robot-tool-receipt")) and len(values) != 1:
                await reject(400, "Ambiguous request header")
                return
        length = headers.get(b"content-length", [None])[0]
        if length is not None:
            if not 1 <= len(length) <= 20 or not length.isdigit():
                await reject(400, "Invalid Content-Length")
                return
            if int(length) > MAX_REQUEST_BYTES:
                await reject(413, "Request body too large")
                return
        encoding = headers.get(b"content-encoding", [b"identity"])[0]
        if encoding.lower() != b"identity":
            await reject(415, "Unsupported Content-Encoding")
            return

        body = bytearray()
        try:
            async with asyncio.timeout(BODY_TIMEOUT_SECONDS):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(chunk) > MAX_REQUEST_BYTES - len(body):
                        await reject(413, "Request body too large")
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await reject(408, "Request body deadline exceeded")
            return
        if length is not None and int(length) != len(body):
            await reject(400, "Content-Length mismatch")
            return
        if body:
            media_type = headers.get(b"content-type", [b""])[0].lower().split(b";")
            if media_type[0].strip() != b"application/json" or any(
                parameter.strip() not in {b"charset=utf-8", b'charset="utf-8"'}
                for parameter in media_type[1:]
            ):
                await reject(415, "Expected application/json")
                return
            if not _safe_json_body(body):
                await reject(400, "Unsafe JSON input")
                return

        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
