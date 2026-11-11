"""Deliver real Xiaozhi server AEC/VAD barge events to Mac speech owners.

This uses the authenticated loopback server's real websocket observation path.
No microphone samples, camera images, commands, or motor permits pass here.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx


class VoiceEventListener:
    def __init__(
        self, client: httpx.AsyncClient, *, url: str, token: str,
        robot_ids: set[str], on_interrupt: Callable[[str, str], Awaitable[None]],
    ):
        if not robot_ids or len(token) < 24:
            raise ValueError("Known robot IDs and private speech token required")
        self.client, self.url, self.token = client, url.rstrip("/"), token
        self.robot_ids = frozenset(robot_ids)
        self.on_interrupt = on_interrupt
        self.cursor: int | None = None
        self.handled = 0
        self.last_error: str | None = None

    async def _fetch(self, bootstrap: bool = False) -> dict:
        query = {"after": str(self.cursor if self.cursor is not None else 0)}
        if bootstrap:
            query["bootstrap"] = "1"
        response = await self.client.get(
            self.url + "/events", params=query,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=2.0,
        )
        response.raise_for_status()
        data = response.json()
        if (not isinstance(data, dict) or type(data.get("cursor")) is not int
                or not 0 <= data["cursor"] <= 0x7fffffffffffffff
                or type(data.get("reset")) is not bool
                or type(data.get("lost")) is not bool
                or not isinstance(data.get("events"), list)
                or len(data["events"]) > 128):
            raise ValueError("Malformed or oversized voice event stream")
        return data

    async def poll(self) -> int:
        if self.cursor is None:
            data = await self._fetch(bootstrap=True)
            if data["events"]:
                raise ValueError("Bootstrapping must not replay stale audio events")
            self.cursor = data["cursor"]
            return 0
        data = await self._fetch()
        if data["reset"]:
            self.cursor = None
            return 0
        if data["cursor"] < self.cursor:
            raise ValueError("Voice event cursor rolled backward without a restart")
        if data["lost"]:
            # Any missed interruption could have left obsolete Mac TTS running.
            for robot_id in sorted(self.robot_ids):
                await self.on_interrupt(robot_id, "gap")
            self.cursor = data["cursor"]
            return 0
        current = self.cursor
        for event in data["events"]:
            if (not isinstance(event, dict)
                    or type(event.get("seq")) is not int
                    or event["seq"] != current + 1
                    or event["seq"] > data["cursor"]
                    or event.get("robot_id") not in self.robot_ids
                    or event.get("kind") not in ("normal", "group")
                    or event.get("source") != "xiaozhi_aec_vad"):
                raise ValueError("Invalid real voice source, identity or sequence")
            await self.on_interrupt(event["robot_id"], event["kind"])
            current = event["seq"]
            # Commit only after successful cancellation; failed callbacks replay.
            self.cursor = current
            self.handled += 1
        if self.cursor != data["cursor"]:
            raise ValueError("Voice server skipped sequence without marking a gap")
        self.last_error = None
        return len(data["events"])

    async def run(self) -> None:
        while True:
            try:
                await self.poll()
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
                self.last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
                await asyncio.sleep(1)
